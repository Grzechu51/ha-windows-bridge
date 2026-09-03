from __future__ import annotations

import json
import logging
import ssl
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse, urlunparse

import websocket

from .config import AppConfig

MAX_MESSAGE_BYTES = 1024 * 1024


class DirectHaBridge:
    """Authenticated Home Assistant WebSocket channel for overlay events."""

    def __init__(
        self,
        config: AppConfig,
        *,
        logger: logging.Logger,
        overlay_callback: Callable[[str, str, dict[str, Any]], None],
        status_callback: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.overlay_callback = overlay_callback
        self.status_callback = status_callback or (lambda _text, _connected: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: websocket.WebSocket | None = None
        self.connected = False

    @staticmethod
    def websocket_url(url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/"))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        base_path = parsed.path.rstrip("/")
        return urlunparse((scheme, parsed.netloc, f"{base_path}/api/websocket", "", "", ""))

    def _ssl_options(self) -> dict[str, Any]:
        if self.config.home_assistant.verify_tls:
            return {}
        return {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}  # noqa: S501

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ha-direct-websocket",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        socket = self._socket
        if socket is not None:
            with suppress(OSError):
                socket.close()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._set_status("Połączenie bezpośrednie zatrzymane", False)

    def _set_status(self, text: str, connected: bool) -> None:
        self.connected = connected
        self.status_callback(text, connected)

    def _receive_json(self, socket: websocket.WebSocket) -> dict[str, Any]:
        raw = socket.recv()
        if not isinstance(raw, (str, bytes)):
            raise ConnectionError("Home Assistant returned an unsupported WebSocket frame")
        size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
        if size > MAX_MESSAGE_BYTES:
            raise ConnectionError("Home Assistant WebSocket message is too large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ConnectionError("Home Assistant returned an invalid WebSocket message")
        return value

    def _connect(self) -> websocket.WebSocket:
        socket = websocket.create_connection(
            self.websocket_url(self.config.home_assistant.url),
            timeout=12,
            sslopt=self._ssl_options(),
            enable_multithread=True,
        )
        hello = self._receive_json(socket)
        if hello.get("type") != "auth_required":
            socket.close()
            raise ConnectionError("Home Assistant did not request authentication")
        socket.send(
            json.dumps(
                {"type": "auth", "access_token": self.config.home_assistant.token},
                separators=(",", ":"),
            )
        )
        authenticated = self._receive_json(socket)
        if authenticated.get("type") != "auth_ok":
            socket.close()
            raise PermissionError("Home Assistant rejected the access token")
        socket.send(
            json.dumps(
                {
                    "id": 1,
                    "type": "subscribe_events",
                    "event_type": f"ha_windows_bridge_overlay_{self.config.device_id}",
                },
                separators=(",", ":"),
            )
        )
        subscribed = self._receive_json(socket)
        if subscribed.get("type") != "result" or not subscribed.get("success"):
            socket.close()
            raise ConnectionError("Home Assistant rejected the overlay subscription")
        socket.settimeout(30)
        return socket

    def _run(self) -> None:
        retry_seconds = 1
        while not self._stop_event.is_set():
            try:
                self._socket = self._connect()
                self._set_status("Połączono bezpośrednio z Home Assistant", True)
                retry_seconds = 1
                self._read_events(self._socket)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self.logger.warning("Bezpośrednie połączenie Home Assistant: %s", exc)
                    self._set_status("Brak bezpośredniego połączenia z Home Assistant", False)
            finally:
                if self._socket is not None:
                    with suppress(OSError):
                        self._socket.close()
                self._socket = None
            if self._stop_event.wait(retry_seconds):
                break
            retry_seconds = min(30, retry_seconds * 2)

    def _read_events(self, socket: websocket.WebSocket) -> None:
        while not self._stop_event.is_set():
            try:
                message = self._receive_json(socket)
            except websocket.WebSocketTimeoutException:
                socket.ping()
                continue
            if message.get("type") != "event" or message.get("id") != 1:
                continue
            event = message.get("event")
            data = event.get("data") if isinstance(event, dict) else None
            if not isinstance(data, dict):
                continue
            options = data.get("data")
            self.overlay_callback(
                str(data.get("title", ""))[:128],
                str(data.get("message", ""))[:2048],
                options if isinstance(options, dict) else {},
            )

    @classmethod
    def test_connection(cls, config: AppConfig) -> tuple[bool, str]:
        bridge = cls(config, logger=logging.getLogger(__name__), overlay_callback=lambda *_: None)
        try:
            socket = bridge._connect()
            socket.close()
            return True, "Połączenie bezpośrednie z Home Assistant działa."
        except Exception as exc:
            return False, f"Nie udało się połączyć bezpośrednio: {exc}"
