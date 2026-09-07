from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import websocket

from ha_windows_bridge.communication.home_assistant import HomeAssistantTransport, websocket_url
from ha_windows_bridge.communication.mqtt import MqttTransport
from ha_windows_bridge.communication.state import ConnectionState
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.core.commands import CommandResult
from ha_windows_bridge.core.events import EventBus


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = False

    def recv(self):
        return json.dumps(next(self.messages))

    def send(self, value):
        self.sent.append(json.loads(value))

    def settimeout(self, _timeout):
        pass

    def close(self, **kwargs):
        self.closed = True


def ha_transport(socket, receive=lambda value: None):
    config = AppConfig(home_assistant=HomeAssistantConfig(enabled=True, url="https://ha.local/base", token="private"))
    return HomeAssistantTransport(config, EventBus(), receive, socket_factory=lambda *args, **kwargs: socket)


def handshake():
    return [{"type": "auth_required"}, {"type": "auth_ok"},
            {"type": "result", "id": 1, "success": True, "result": {"protocol": 3}}]


def test_ha_authenticates_with_scoped_api_and_acks_without_event_bus():
    socket = Socket(handshake())
    transport = ha_transport(socket)
    transport._epoch = transport.machine.begin()
    connection, subscription = transport._connect()
    assert connection is socket and subscription == 1
    assert socket.sent[0] == {"type": "auth", "access_token": "private"}
    assert socket.sent[1]["type"] == "ha_windows_bridge/connect"
    assert socket.sent[1]["protocol"] == 3
    assert socket.sent[1]["session"] == transport.protocol.session
    transport.machine.connected(transport._epoch)
    transport.acknowledge(CommandResult("id", "succeeded"))
    assert socket.sent[-1]["type"] == "ha_windows_bridge/result"
    assert socket.sent[-1]["result"]["version"] == 3
    assert transport.stop() and socket.closed


def test_p2_r1_direct_writer_preserves_id_allocation_wire_order_without_owner_lock():
    entered = threading.Event()
    release = threading.Event()
    owner_lock_free = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    errors = []

    class BarrierSocket:
        def __init__(self):
            self.sent = []

        def send(self, raw):
            value = json.loads(raw)
            if value["id"] == 2:
                entered.set()
                assert release.wait(1)
            self.sent.append(value)

        def close(self, **_kwargs):
            pass

    socket = BarrierSocket()
    transport = ha_transport(socket)
    transport._socket = socket
    transport._sequence = 1

    def send_result():
        try:
            transport._send({"type": "ha_windows_bridge/result"})
        except Exception as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)

    def send_heartbeat():
        second_started.set()
        try:
            transport._send({"type": "ha_windows_bridge/heartbeat"})
        except Exception as exc:  # pragma: no cover - assertion reports thread failures
            errors.append(exc)
        finally:
            second_done.set()

    first = threading.Thread(target=send_result)
    first.start()
    assert entered.wait(1)

    def inspect_owner():
        with transport._lock:
            owner_lock_free.set()

    inspector = threading.Thread(target=inspect_owner)
    inspector.start()
    assert owner_lock_free.wait(1)
    second = threading.Thread(target=send_heartbeat)
    second.start()
    assert second_started.wait(1)
    assert not second_done.is_set()
    release.set()
    first.join(1)
    second.join(1)
    inspector.join(1)
    assert not errors
    assert [item["id"] for item in socket.sent] == [2, 3]
    transport.stop()


def test_p2_r10_old_direct_endpoint_invalid_format_is_permanent_mismatch():
    events = EventBus()
    incompatible = threading.Event()
    events.subscribe(
        "connection.changed",
        lambda event: incompatible.set()
        if event.data.state == ConnectionState.CONFIGURATION_ERROR
        else None,
    )
    socket = Socket(
        handshake()[:2]
        + [{"type": "result", "id": 1, "success": False,
            "error": {"code": "invalid_format", "message": "old schema"}}]
    )
    calls = []
    transport = HomeAssistantTransport(
        AppConfig(
            home_assistant=HomeAssistantConfig(
                enabled=True, url="https://ha.local", token="private"
            )
        ),
        events,
        lambda _value: None,
        socket_factory=lambda *_args, **_kwargs: calls.append(True) or socket,
    )
    transport.start()
    assert incompatible.wait(1)
    assert transport.machine.status.error == "protocol_mismatch"
    assert len(calls) == 1
    assert transport.stop()


@pytest.mark.parametrize("messages", [[], [{"type": "auth_required"}], [{"type": "auth_required"}, {"type": "auth_invalid"}], handshake()[:2] + [{"id": 1, "success": False}]])
def test_ha_failed_handshake_closes_socket(messages):
    socket = Socket(messages)
    transport = ha_transport(socket)
    with pytest.raises((StopIteration, ConnectionError)):
        transport._connect()
    assert socket.closed and transport._socket is None


def test_ha_stop_during_connect_cannot_subscribe():
    socket = Socket([])
    transport = ha_transport(socket)
    def factory(*args, **kwargs):
        transport._stop.set()
        return socket
    transport._socket_factory = factory
    with pytest.raises(ConnectionAbortedError):
        transport._connect()
    assert socket.closed and not socket.sent


def test_ha_heartbeat_timeout_is_bounded_without_waiting_wall_clock(monkeypatch):
    socket = Socket(handshake())
    transport = ha_transport(socket)
    transport._connect()
    clock = iter([0, 31, 42])
    monkeypatch.setattr("ha_windows_bridge.communication.home_assistant.time.monotonic", lambda: next(clock))
    def timeout():
        raise websocket.WebSocketTimeoutException()
    socket.recv = timeout
    with pytest.raises(ConnectionError, match="heartbeat timeout"):
        transport._read_events(socket, 1)
    assert socket.sent[-1]["type"] == "ha_windows_bridge/heartbeat"
    transport.stop()


def test_ha_delivers_only_subscription_events():
    socket = Socket(handshake() + [{"type": "event", "id": 7, "event": {"wrong": True}}, {"type": "event", "id": 1, "event": {"version": 3}}])
    values = []
    transport = ha_transport(socket)
    transport.receive = lambda value: (values.append(value), transport._stop.set())
    transport._connect()
    transport._read_events(socket, 1)
    assert values == [{"version": 3}]
    transport.stop()


@pytest.mark.parametrize("url", ["ftp://ha.local", "http://user:secret@ha.local", "https://", "https://ha.local?token=secret", "https://ha.local:99999"])
def test_ha_rejects_invalid_and_secret_bearing_urls(url):
    with pytest.raises(ValueError):
        websocket_url(url)


def test_mqtt_transport_copies_and_bounds_frames_and_keeps_auth_failure():
    client = Mock()
    receive = Mock()
    transport = MqttTransport(MqttConfig(base_topic="pc"), "pc", EventBus(), receive, {"pc/command"}, client_factory=lambda *args, **kwargs: client)
    transport._epoch = transport.machine.begin()
    transport._on_connect(client, None, None, SimpleNamespace(is_failure=True, value=135), None)
    transport._on_disconnect(client, None, None, None, None)
    assert transport.machine.status.state == ConnectionState.AUTH_ERROR
    transport._on_message(client, None, SimpleNamespace(topic="unknown", payload=b"x", retain=False))
    transport._on_message(client, None, SimpleNamespace(topic="pc/command", payload=b"x" * (768 * 1024 + 1), retain=False))
    receive.assert_not_called()
    payload = bytearray(b"test")
    transport._on_message(client, None, SimpleNamespace(topic="pc/command", payload=payload, retain=True))
    payload[0] = 0
    receive.assert_called_once_with("pc/command", b"test", True)
    assert transport.stop()
    transport._on_message(client, None, SimpleNamespace(topic="pc/command", payload=b"after", retain=False))
    assert receive.call_count == 1
