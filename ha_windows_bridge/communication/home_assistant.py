"""HA WebSocket transport and explicit overlay gateway; no presentation imports."""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from contextlib import suppress
from urllib.parse import urlparse, urlunparse

import websocket

from ..core.commands import Command, CommandError
from .state import Backoff, ConnectionMachine, ConnectionState


def websocket_url(url: str) -> str:
    parsed = urlparse(url.strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid Home Assistant URL")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid Home Assistant port")
    return urlunparse(("wss" if parsed.scheme == "https" else "ws", parsed.netloc,
                      parsed.path.rstrip("/") + "/api/websocket", "", "", ""))


class HomeAssistantConnectionError(ConnectionError):
    def __init__(self, code, *, authentication=False, configuration=False):
        super().__init__(code)
        self.code = code
        self.authentication = authentication
        self.configuration = configuration


def response_error(response):
    """Keep actionable codes, never mistake a configured-device error for a bad token."""
    error = response.get("error")
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    if code == "unauthorized":
        return HomeAssistantConnectionError("unauthorized", authentication=True)
    if code == "unknown_command":
        return HomeAssistantConnectionError("integration_missing", configuration=True)
    if code in ("bridge_not_configured", "popup_unavailable", "protocol_mismatch"):
        return HomeAssistantConnectionError(code, configuration=True)
    if code in ("bridge_busy", "bridge_not_ready"):
        return HomeAssistantConnectionError(code)
    # Recognise the explicit errors sent by alpha.1–3 without logging remote text.
    if code == "home_assistant_error":
        if error.get("message") == "Configure this Direct Windows Bridge in Home Assistant first":
            return HomeAssistantConnectionError("bridge_not_configured", configuration=True)
        if error.get("message") == "Windows Bridge is already connected or unloading":
            return HomeAssistantConnectionError("bridge_busy")
    return HomeAssistantConnectionError("server_error")


class HomeAssistantTransport:
    def __init__(self, config, events, receive, *, socket_factory=None):
        self.config, self.receive = config, receive
        self.machine = ConnectionMachine("home_assistant", events)
        self.log = logging.getLogger("bridge.ha")
        self._socket_factory = socket_factory or websocket.create_connection
        self._socket = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._sequence = 0
        self._epoch = 0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("HA transport still running")
        self._stop.clear()
        self._epoch = self.machine.begin()
        self._thread = threading.Thread(target=self._run, name="ha-transport", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.machine.stop()
        self._close_socket()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=4)
        return self._thread is None or not self._thread.is_alive()

    def _close_socket(self):
        with self._lock:
            connection, self._socket = self._socket, None
        if connection:
            with suppress(Exception):
                connection.close(timeout=0.2)

    def _read(self, connection):
        raw = connection.recv()
        if not isinstance(raw, (str, bytes)) or len(raw) > 1024 * 1024:
            raise ConnectionError("Invalid HA frame")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise ConnectionError("Invalid HA JSON") from exc
        if not isinstance(data, dict):
            raise ConnectionError("Invalid HA response")
        return data

    def _send(self, payload, *, numbered=True):
        with self._lock:
            if self._stop.is_set() or self._socket is None:
                raise ConnectionError("HA disconnected")
            if numbered:
                self._sequence += 1
                payload = {**payload, "id": self._sequence}
            self._socket.send(json.dumps(payload, separators=(",", ":"), allow_nan=False))
            return self._sequence

    def _connect(self):
        settings = self.config.home_assistant
        options = {} if settings.verify_tls else {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}  # noqa: S501
        connection = self._socket_factory(websocket_url(settings.url), timeout=3,
                                          sslopt=options, enable_multithread=True)
        with self._lock:
            self._socket = connection
            self._sequence = 0
        try:
            if self._stop.is_set():
                raise ConnectionAbortedError()
            if self._read(connection).get("type") != "auth_required":
                raise ConnectionError("HA authentication handshake")
            self._send({"type": "auth", "access_token": settings.token}, numbered=False)
            auth = self._read(connection).get("type")
            if auth == "auth_invalid":
                raise HomeAssistantConnectionError("authentication", authentication=True)
            if auth != "auth_ok":
                raise ConnectionError("HA authentication handshake")
            subscription = self._send({"type": "ha_windows_bridge/connect", "device_id": self.config.device_id})
            response = self._read(connection)
            if response.get("type") != "result" or response.get("id") != subscription:
                raise ConnectionError("Invalid HA subscription response")
            if not response.get("success"):
                raise response_error(response)
            result = response.get("result")
            if isinstance(result, dict) and result.get("protocol") != 2:
                raise HomeAssistantConnectionError("protocol_mismatch", configuration=True)
            connection.settimeout(1)
            return connection, subscription
        except BaseException:
            self._close_socket()
            raise

    def _run(self):
        while not self._stop.is_set():
            try:
                connection, subscription = self._connect()
                if not self.machine.connected(self._epoch):
                    break
                self._read_events(connection, subscription)
            except HomeAssistantConnectionError as exc:
                self.machine.failed(self._epoch, exc.code, authentication=exc.authentication,
                                    configuration=exc.configuration)
            except Exception:
                if not self._stop.is_set():
                    self.machine.failed(self._epoch, "network")
                    self.log.warning("Home Assistant connection unavailable")
            finally:
                self._close_socket()
            if self.machine.status.state in {ConnectionState.AUTH_ERROR, ConnectionState.CONFIGURATION_ERROR}:
                break
            if self._stop.wait(Backoff().delay(self.machine.status.attempt)):
                break
            if not self.machine.retry(self._epoch):
                break

    def _read_events(self, connection, subscription):
        last_heartbeat = time.monotonic()
        pending = None
        deadline = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if pending is not None and now >= deadline:
                raise ConnectionError("HA heartbeat timeout")
            if pending is None and now - last_heartbeat >= 30:
                pending = self._send({"type": "ha_windows_bridge/heartbeat", "device_id": self.config.device_id})
                deadline = now + 10
            try:
                message = self._read(connection)
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("type") == "result" and message.get("id") == pending:
                if not message.get("success"):
                    error = response_error(message)
                    # Reloading an HA entry replaces its runtime/lease. Reconnect
                    # and re-check permissions instead of getting stuck forever.
                    if error.code == "unauthorized":
                        raise HomeAssistantConnectionError("session_expired")
                    raise error
                pending = None
                last_heartbeat = time.monotonic()
            if message.get("type") == "event" and message.get("id") == subscription:
                value = message.get("event")
                if isinstance(value, dict):
                    self.receive(value)

    def acknowledge(self, result):
        if self.machine.status.state != ConnectionState.CONNECTED or result.status in {"accepted", "pending"}:
            return
        try:
            self._send({"type": "ha_windows_bridge/result", "device_id": self.config.device_id,
                        "result": json.loads(result.encode())})
        except Exception:
            self.log.warning("HA command result could not be delivered")


class HomeAssistantGateway:
    def __init__(self, config, router, events):
        self.router = router
        self.transport = HomeAssistantTransport(config, events, self.receive)

    def start(self):
        self.transport.start()

    def stop(self):
        return self.transport.stop()

    def receive(self, value):
        try:
            command = Command.parse(json.dumps(value, allow_nan=False).encode())
            if command.kind != "overlay.show":
                raise CommandError("direct_scope")
        except (CommandError, ValueError, RecursionError):
            self.transport.log.warning("Direct overlay command rejected")
            return
        result = self.router.submit(command, self.transport.acknowledge)
        if result.status != "accepted":
            self.transport.acknowledge(result)
