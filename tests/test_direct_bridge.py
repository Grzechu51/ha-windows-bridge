from __future__ import annotations

import json
import logging

import pytest
import websocket

from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.direct_bridge import DirectHaBridge


class FakeSocket:
    def __init__(self, messages: list[dict]):
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[dict] = []
        self.closed = False

    def recv(self):
        return self.messages.pop(0)

    def send(self, value: str):
        self.sent.append(json.loads(value))

    def settimeout(self, _timeout: int):
        return None

    def close(self):
        self.closed = True


def direct_config() -> AppConfig:
    return AppConfig(
        device_id="gaming_pc_123456",
        mqtt=MqttConfig(),
        home_assistant=HomeAssistantConfig(
            enabled=True,
            url="https://ha.local:8123/base/",
            token="secret",
        ),
    )


def test_direct_bridge_authenticates_and_subscribes(monkeypatch) -> None:
    socket = FakeSocket(
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
        ]
    )
    monkeypatch.setattr("websocket.create_connection", lambda *_args, **_kwargs: socket)
    bridge = DirectHaBridge(
        direct_config(), logger=logging.getLogger(__name__), overlay_callback=lambda *_: None
    )

    connected = bridge._connect()  # noqa: SLF001

    assert connected is socket
    assert socket.sent[0] == {"type": "auth", "access_token": "secret"}
    assert socket.sent[1]["event_type"] == "ha_windows_bridge_overlay_gaming_pc_123456"
    assert len(socket.sent) == 2
    assert DirectHaBridge.websocket_url("https://ha.local:8123/base/") == (
        "wss://ha.local:8123/base/api/websocket"
    )


def test_direct_bridge_delivers_overlay_event() -> None:
    received: list[tuple[str, str, dict]] = []
    socket = FakeSocket(
        [
            {
                "id": 1,
                "type": "event",
                "event": {
                    "data": {
                        "title": "Door",
                        "message": "Opened",
                        "data": {"priority": "high"},
                    }
                },
            }
        ]
    )
    bridge = DirectHaBridge(
        direct_config(),
        logger=logging.getLogger(__name__),
        overlay_callback=lambda title, message, data: (
            received.append((title, message, data)),
            bridge._stop_event.set(),  # noqa: SLF001
        ),
    )

    bridge._read_events(socket)  # noqa: SLF001

    assert received == [("Door", "Opened", {"priority": "high"})]


@pytest.mark.parametrize("messages", [[], [{"type": "auth_required"}],
    [{"type": "auth_required"}, {"type": "auth_ok"}],
    [{"type": "auth_required"}, {"type": "auth_ok"}, {"type": "result", "id": 2, "success": True}]])
def test_handshake_failure_always_closes_socket(monkeypatch, messages):
    socket = FakeSocket(messages)
    monkeypatch.setattr("websocket.create_connection", lambda *_args, **_kwargs: socket)
    bridge = DirectHaBridge(direct_config(), logger=logging.getLogger(__name__), overlay_callback=lambda *_: None)
    with pytest.raises((IndexError, ConnectionError)):
        bridge._connect()
    assert socket.closed
    assert bridge._socket is None


def test_stop_during_handshake_does_not_subscribe(monkeypatch):
    socket = FakeSocket([])
    bridge = DirectHaBridge(direct_config(), logger=logging.getLogger(__name__), overlay_callback=lambda *_: None)
    def connect(*_args, **_kwargs):
        bridge._stop_event.set()
        return socket
    monkeypatch.setattr("websocket.create_connection", connect)
    with pytest.raises(ConnectionAbortedError):
        bridge._connect()
    assert socket.closed
    assert not socket.sent


def test_missing_heartbeat_response_causes_reconnect():
    socket = FakeSocket([])
    def timeout():
        raise websocket.WebSocketTimeoutException()
    socket.recv = timeout
    bridge = DirectHaBridge(direct_config(), logger=logging.getLogger(__name__), overlay_callback=lambda *_: None)
    with pytest.raises(ConnectionError, match="heartbeat"):
        bridge._read_events(socket)
    assert socket.sent == [{"id": 2, "type": "ping"}]


def test_heartbeat_pong_restores_idle_timeout():
    socket = FakeSocket([])
    bridge = DirectHaBridge(direct_config(), logger=logging.getLogger(__name__), overlay_callback=lambda *_: None)
    calls = []
    socket.settimeout = calls.append
    replies = iter([None, {"type": "pong", "id": 2}, {"type": "result"}])
    def receive():
        reply = next(replies)
        if reply is None:
            raise websocket.WebSocketTimeoutException()
        if reply["type"] == "result":
            bridge._stop_event.set()
        return json.dumps(reply)
    socket.recv = receive
    bridge._read_events(socket)
    assert calls == [10, 30]


@pytest.mark.parametrize("url", ["ftp://ha.local", "https://user:pass@ha.local", "https://", "https://ha.local?token=secret"])
def test_invalid_or_credential_bearing_url_is_rejected(url):
    with pytest.raises(ValueError):
        DirectHaBridge.websocket_url(url)
