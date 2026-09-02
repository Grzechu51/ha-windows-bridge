from __future__ import annotations

import json
import logging

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
            {"id": 2, "type": "result", "success": True},
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
    assert socket.sent[2]["event_type"] == (
        "ha_windows_bridge_template_command_gaming_pc_123456"
    )
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
                        "data": {"channel": "security", "priority": "high"},
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

    assert received == [("Door", "Opened", {"channel": "security", "priority": "high"})]


def test_direct_bridge_receives_template_selection_and_publishes_catalog() -> None:
    received: list[tuple[str, str]] = []
    socket = FakeSocket(
        [
            {
                "id": 2,
                "type": "event",
                "event": {
                    "data": {"action": "select", "template_id": "powiadomienie"}
                },
            }
        ]
    )
    bridge = DirectHaBridge(
        direct_config(),
        logger=logging.getLogger(__name__),
        overlay_callback=lambda *_: None,
        template_callback=lambda action, template_id: (
            received.append((action, template_id)),
            bridge._stop_event.set(),  # noqa: SLF001
        ),
    )

    bridge._read_events(socket)  # noqa: SLF001
    bridge._socket = socket  # noqa: SLF001
    bridge.connected = True
    assert bridge.publish_overlay_templates()

    assert received == [("select", "powiadomienie")]
    assert socket.sent[-1]["type"] == "fire_event"
    assert socket.sent[-1]["event_type"] == "ha_windows_bridge_templates_gaming_pc_123456"
    assert socket.sent[-1]["event_data"]["selected"] == "powiadomienie"
