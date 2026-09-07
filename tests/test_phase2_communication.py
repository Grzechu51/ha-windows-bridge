from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest

from ha_windows_bridge.application.commands import CommandRouter
from ha_windows_bridge.application.protocol_projection import ProtocolStateProjection
from ha_windows_bridge.communication.gateway import MqttGateway
from ha_windows_bridge.communication.home_assistant import HomeAssistantTransport
from ha_windows_bridge.communication.message_outbox import DeliveryState, MessageOutbox
from ha_windows_bridge.communication.mqtt import MqttTransport
from ha_windows_bridge.communication.protocol import TopicProtocol
from ha_windows_bridge.communication.publishing import StatePublisher
from ha_windows_bridge.communication.schema import CommandMessage, ResultMessage, SnapshotMessage
from ha_windows_bridge.communication.state import ConnectionState
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.core.commands import CommandError, CommandResult
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ComputerStateStore
from ha_windows_bridge.discovery import master_volume_topics


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class _TcpMqttBroker:
    """Small real-socket MQTT 3.1.1 broker used only for reconnect contracts."""

    def __init__(self, port=0):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", port))
        self.port = self._listener.getsockname()[1]
        self._listener.listen()
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._clients = []
        self.published = []
        self.connections = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        with suppress(OSError):
            self._listener.close()
        for connection in tuple(self._clients):
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                connection.close()
        self._thread.join(2)

    @staticmethod
    def _read_exact(connection, count):
        value = b""
        while len(value) < count:
            block = connection.recv(count - len(value))
            if not block:
                raise ConnectionError("closed")
            value += block
        return value

    @classmethod
    def _packet(cls, connection):
        first = cls._read_exact(connection, 1)[0]
        remaining, multiplier = 0, 1
        while True:
            encoded = cls._read_exact(connection, 1)[0]
            remaining += (encoded & 127) * multiplier
            if not encoded & 128:
                break
            multiplier *= 128
        return first, cls._read_exact(connection, remaining)

    def _run(self):
        while not self._stop.is_set():
            try:
                connection, _address = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            self.connections += 1
            self._clients.append(connection)
            connection.settimeout(0.1)
            try:
                self._serve(connection)
            finally:
                with suppress(OSError):
                    connection.close()
                with suppress(ValueError):
                    self._clients.remove(connection)

    def _serve(self, connection):
        while not self._stop.is_set():
            try:
                first, body = self._packet(connection)
            except TimeoutError:
                continue
            except (ConnectionError, OSError):
                return
            packet_type = first >> 4
            if packet_type == 1:  # CONNECT
                connection.sendall(b"\x20\x02\x00\x00")
            elif packet_type == 8:  # SUBSCRIBE
                identifier = body[:2]
                count, offset = 0, 2
                while offset < len(body):
                    size = int.from_bytes(body[offset:offset + 2])
                    offset += 2 + size + 1
                    count += 1
                connection.sendall(b"\x90" + bytes([2 + count]) + identifier + b"\x01" * count)
            elif packet_type == 3:  # PUBLISH
                topic_size = int.from_bytes(body[:2])
                topic = body[2:2 + topic_size].decode()
                offset = 2 + topic_size
                qos = (first >> 1) & 3
                identifier = body[offset:offset + 2] if qos else b""
                if qos:
                    offset += 2
                self.published.append((topic, body[offset:]))
                if qos:
                    connection.sendall(b"\x40\x02" + identifier)
            elif packet_type == 12:  # PINGREQ
                connection.sendall(b"\xd0\x00")
            elif packet_type == 14:  # DISCONNECT
                return


class _DirectWebSocketServer:
    """Real-socket WebSocket handshake used to exercise Direct reconnect ownership."""

    def __init__(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self._listener.listen()
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._clients = []
        self.connections = 0
        self.connect_messages = []
        self.second_ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        with suppress(OSError):
            self._listener.close()
        for connection in tuple(self._clients):
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                connection.close()
        self._thread.join(2)

    @staticmethod
    def _read_exact(connection, count):
        value = b""
        while len(value) < count:
            block = connection.recv(count - len(value))
            if not block:
                raise ConnectionError("closed")
            value += block
        return value

    @classmethod
    def _receive(cls, connection):
        first, second = cls._read_exact(connection, 2)
        length = second & 127
        if length == 126:
            length = int.from_bytes(cls._read_exact(connection, 2))
        elif length == 127:
            length = int.from_bytes(cls._read_exact(connection, 8))
        mask = cls._read_exact(connection, 4) if second & 128 else b""
        payload = cls._read_exact(connection, length)
        if mask:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if first & 15 == 8:
            raise ConnectionError("close")
        return json.loads(payload)

    @staticmethod
    def _send(connection, value):
        payload = json.dumps(value, separators=(",", ":")).encode()
        if len(payload) < 126:
            header = bytes((0x81, len(payload)))
        else:
            header = b"\x81\x7e" + len(payload).to_bytes(2)
        connection.sendall(header + payload)

    def _run(self):
        while not self._stop.is_set():
            try:
                connection, _address = self._listener.accept()
            except (TimeoutError, OSError):
                continue
            self.connections += 1
            self._clients.append(connection)
            connection.settimeout(0.1)
            try:
                self._serve(connection, disconnect=self.connections == 1)
            finally:
                with suppress(OSError):
                    connection.close()
                with suppress(ValueError):
                    self._clients.remove(connection)

    def _serve(self, connection, *, disconnect):
        request = b""
        while b"\r\n\r\n" not in request:
            request += connection.recv(4096)
        headers = {}
        for line in request.decode().split("\r\n")[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        accept = base64.b64encode(hashlib.sha1(
            (headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                            "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept +
                            "\r\n\r\n").encode())
        self._send(connection, {"type": "auth_required"})
        assert self._receive(connection)["type"] == "auth"
        self._send(connection, {"type": "auth_ok"})
        message = self._receive(connection)
        self.connect_messages.append(message)
        self._send(connection, {"type": "result", "id": message["id"], "success": True,
                                "result": {"protocol": 3}})
        if disconnect:
            return
        self.second_ready.set()
        while not self._stop.is_set():
            try:
                message = self._receive(connection)
            except TimeoutError:
                continue
            except (ConnectionError, OSError):
                return
            if message.get("type") == "ha_windows_bridge/heartbeat":
                self._send(connection, {"type": "result", "id": message["id"], "success": True})


def test_duplicate_command_id_executes_once_and_stale_session_is_rejected():
    now = 100.0
    config = AppConfig(device_id="desktop", control_master_volume=True)
    protocol = TopicProtocol(config, session="current-session", clock=lambda: now)
    message = CommandMessage("command-1", protocol.session, config.device_id,
                             "audio.master.volume", "", {"value": 0.42}, now, 10_000)
    command = protocol.decode(protocol.command_topic, message.encode().encode())
    duplicate = protocol.decode(protocol.command_topic, message.encode().encode())
    stale = CommandMessage("command-2", "old-session", config.device_id,
                           message.kind, "", message.arguments, now, 10_000)
    with pytest.raises(CommandError, match="stale_session"):
        protocol.decode(protocol.command_topic, stale.encode().encode())

    router = CommandRouter(clock=lambda: now)
    executed, finished = [], threading.Event()
    router.register(message.kind, lambda item: executed.append(item.id) or {})
    try:
        assert router.submit(command, lambda _result: finished.set()).status == "accepted"
        second = router.submit(duplicate, lambda _result: None)
        assert second.status in {"pending", "succeeded"}
        assert finished.wait(1)
        assert executed == ["command-1"]
    finally:
        assert router.stop()


def test_command_ttl_uses_monotonic_countdown_after_wall_clock_validation():
    wall = [100.0]
    monotonic = [10.0]
    config = AppConfig(device_id="desktop", control_master_volume=True)
    protocol = TopicProtocol(
        config,
        session="current-session",
        clock=lambda: wall[0],
        monotonic_clock=lambda: monotonic[0],
    )
    message = CommandMessage(
        "command-clock",
        protocol.session,
        config.device_id,
        "audio.master.volume",
        "",
        {"value": 0.42},
        wall[0],
        10_000,
    )
    command = protocol.decode(protocol.command_topic, message.encode().encode())
    wall[0] = 10_000.0  # Simulate a wall-clock correction after ingress validation.
    monotonic[0] = 11.0
    router = CommandRouter(
        clock=lambda: wall[0], monotonic_clock=lambda: monotonic[0]
    )
    completed = threading.Event()
    router.register(message.kind, lambda _command: {})
    try:
        assert router.submit(command, lambda _result: completed.set()).status == "accepted"
        assert completed.wait(1)
    finally:
        assert router.stop()


def test_latest_protocol_snapshot_survives_failed_publish_and_broker_restart():
    events = EventBus()
    state = ComputerStateStore(events, wall_clock=lambda: 100, monotonic_clock=lambda: 10)
    state.begin_generation(1)

    class Transport:
        connected = False

        def __init__(self):
            self.sent = []

        def publish(self, topic, payload, **kwargs):
            if not self.connected:
                return False
            self.sent.append((topic, payload, kwargs))
            return True

    transport = Transport()
    publisher = StatePublisher(transport, events, generation=1)
    protocol = TopicProtocol(AppConfig(device_id="desktop"), session="session-a")
    projection = ProtocolStateProjection(state, publisher, events, protocol, 1)
    projection.start()
    try:
        state.observe_master_audio(0.2, False, generation=1)
        state.observe_master_audio(0.8, True, generation=1)
        assert not transport.sent
        transport.connected = True
        assert publisher.replay()
        snapshots = [SnapshotMessage.decode(payload) for topic, payload, _kw in transport.sent
                     if topic == protocol.snapshot_topic]
        assert len(snapshots) == 1
        assert snapshots[0].revision == state.snapshot().revision
        assert snapshots[0].state["master_audio"] == {
            "volume": 0.8, "muted": True, "observed_at": 100.0
        }
    finally:
        projection.stop()


def test_protocol_outbox_is_bounded_and_tracks_accepted_delivered_failed():
    outbox = MessageOutbox(capacity=2)
    first = outbox.accept("snapshot", "v3/snapshot", "one", retain=True,
                          replace_latest=True)
    second = outbox.accept("result:1", "v3/result", "two", retain=False)
    assert first and second
    assert outbox.accept("result:2", "v3/result", "three", retain=False) is None
    replacement = outbox.accept("snapshot", "v3/snapshot", "latest", retain=True,
                                replace_latest=True)
    assert replacement and replacement.token != first.token
    assert outbox.mark_failed(second.key, second.token)
    assert {item.state for item in outbox.pending()} == {
        DeliveryState.ACCEPTED, DeliveryState.FAILED
    }
    outbox.replay()
    assert all(item.state == DeliveryState.ACCEPTED for item in outbox.pending())
    assert outbox.mark_delivered(second.key, second.token)
    outbox.discard_delivered()
    assert [item.key for item in outbox.snapshot()] == ["snapshot"]
    outbox.close()
    assert outbox.accept("x", "x", "x", retain=False) is None


def test_state_delivery_waits_for_puback_and_ignores_stale_callback():
    class AckTransport:
        supports_delivery_ack = True
        connected = True

        def __init__(self):
            self.callbacks = []

        def publish(self, _topic, _payload, *, on_delivery, **_kwargs):
            self.callbacks.append(on_delivery)
            return True

    transport = AckTransport()
    publisher = StatePublisher(transport, EventBus())
    assert publisher.publish_observation("v3/snapshot", "one")
    assert publisher.outbox.is_dirty("v3/snapshot")
    publisher.flush()
    assert len(transport.callbacks) == 1  # One in-flight send until its PUBACK/failure.
    first = transport.callbacks.pop()
    publisher.request_replay()
    first(True)
    assert publisher.outbox.is_dirty("v3/snapshot")
    publisher.flush()
    transport.callbacks.pop()(True)
    assert not publisher.outbox.is_dirty("v3/snapshot")
    assert publisher.outbox.delivered()


def test_failed_result_publish_is_replayed_after_reconnect_with_puback():
    gateway = MqttGateway(AppConfig(device_id="desktop"), SimpleNamespace(), EventBus())

    class AckTransport:
        connected = True

        def __init__(self):
            self.calls = []
            self.fail_first_result = True

        def publish(self, topic, payload, *, on_delivery=None, **kwargs):
            self.calls.append((topic, payload, kwargs))
            if topic.endswith("/result") and self.fail_first_result:
                self.fail_first_result = False
                return False
            if on_delivery:
                on_delivery(True)
            return True

    transport = AckTransport()
    gateway.transport = transport
    gateway._reply(CommandResult("command-1", "succeeded"))
    failed = [item for item in gateway.outbox.snapshot() if item.key == "result:command-1"]
    assert failed[0].state == DeliveryState.FAILED
    gateway._connection_changed(SimpleNamespace(data=SimpleNamespace(
        transport="mqtt", state="connected")))
    results = [ResultMessage.decode(payload) for topic, payload, _kw in transport.calls
               if topic == gateway.protocol.result_topic]
    assert len(results) == 2 and results[-1].status == "succeeded"
    assert not any(item.key == "result:command-1" for item in gateway.outbox.snapshot())


class _MqttClient:
    def __init__(self):
        self.next_mid = 1
        self.queued = None
        self.inflight = None
        self.published = []

    def max_queued_messages_set(self, value):
        self.queued = value

    def max_inflight_messages_set(self, value):
        self.inflight = value

    def will_set(self, *args, **kwargs):
        pass

    def subscribe(self, topic, qos):
        mid, self.next_mid = self.next_mid, self.next_mid + 1
        return 0, mid

    def publish(self, topic, payload, **kwargs):
        mid, self.next_mid = self.next_mid, self.next_mid + 1
        self.published.append((topic, payload, kwargs, mid))
        return SimpleNamespace(rc=0, mid=mid)

    def disconnect(self):
        pass


def test_mqtt_waits_for_all_subacks_and_distinguishes_puback_delivery():
    client = _MqttClient()
    transport = MqttTransport(MqttConfig(base_topic="desktop"), "desktop", EventBus(),
                              lambda *_args: None, {"one", "two"},
                              client_factory=lambda *_args, **_kwargs: client)
    transport._epoch = transport.machine.begin()
    transport._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
    assert transport.machine.status.state == ConnectionState.CONNECTING
    mids = set(transport._pending_subacks)
    first = mids.pop()
    transport._on_subscribe(client, None, first, [SimpleNamespace(is_failure=False)], None)
    assert transport.machine.status.state == ConnectionState.CONNECTING
    transport._on_subscribe(client, None, mids.pop(), [SimpleNamespace(is_failure=False)], None)
    assert transport.machine.status.state == ConnectionState.CONNECTED
    delivered = []
    assert transport.publish("desktop/v3/snapshot", "{}", on_delivery=delivered.append)
    assert delivered == []
    mid = client.published[-1][3]
    transport._on_publish(client, None, mid, None, None)
    assert delivered == [True]
    assert client.queued == 256 and client.inflight == 20
    assert transport.stop()


def test_shutdown_interrupts_mqtt_reconnect_wait_without_another_attempt():
    client = _MqttClient()
    client.connect = lambda *_args: (_ for _ in ()).throw(OSError("offline"))
    client.loop = lambda **_kwargs: 0
    transport = MqttTransport(MqttConfig(host="offline.invalid"), "desktop", EventBus(),
                              lambda *_args: None, set(),
                              client_factory=lambda *_args, **_kwargs: client)
    attempts = 0

    def connect(*_args):
        nonlocal attempts
        attempts += 1
        raise OSError("offline")

    client.connect = connect
    transport.start()
    deadline = time.monotonic() + 1
    while attempts == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert attempts == 1
    assert transport.stop()
    time.sleep(0.02)
    assert attempts == 1
    assert transport.machine.status.state == ConnectionState.STOPPED


def test_legacy_adapter_is_transition_only_and_deduplicates_replayed_entity_frame():
    config = AppConfig(control_master_volume=True)
    protocol = TopicProtocol(config, session="current", clock=lambda: 100)
    topic = master_volume_topics(config)[0]
    first = protocol.decode(topic, b"42")
    retry = protocol.decode(topic, b"42")
    assert first.id == retry.id
    assert first.session == "legacy-v2" and first.arguments == {"value": 0.42}
    legacy = json.dumps({"version": 2, "id": "old-command", "kind": "audio.master.volume",
                         "target": "", "arguments": {"value": 0.5},
                         "issued_at": 100, "ttl_ms": 10_000}).encode()
    assert protocol.decode(protocol.legacy_command_topic, legacy).id == "old-command"
    with pytest.raises(CommandError, match="retained_command"):
        protocol.decode(topic, b"42", retained=True)


def test_real_mqtt_socket_broker_restart_replays_only_latest_snapshot():
    first_broker = _TcpMqttBroker()
    first_broker.start()
    events = EventBus()
    transport = MqttTransport(
        MqttConfig(host="127.0.0.1", port=first_broker.port, base_topic="desktop"),
        "desktop",
        events,
        lambda *_args: None,
        {"desktop/v3/command"},
    )
    publisher = StatePublisher(transport, events)

    def connection_changed(event):
        if event.data.transport == "mqtt" and event.data.state == "connected":
            publisher.request_replay()
            publisher.flush()

    unsubscribe = events.subscribe("connection.changed", connection_changed)
    second_broker = None
    try:
        transport.start()
        assert _wait_for(
            lambda: transport.machine.status.state == ConnectionState.CONNECTED
        )
        assert publisher.publish_observation("desktop/v3/snapshot", "one")
        assert _wait_for(lambda: not publisher.outbox.is_dirty("desktop/v3/snapshot"))

        first_broker.stop()
        assert _wait_for(lambda: transport.machine.status.state == ConnectionState.RETRY_WAIT)
        assert publisher.publish_observation("desktop/v3/snapshot", "two")
        assert publisher.publish_observation("desktop/v3/snapshot", "three")

        second_broker = _TcpMqttBroker(first_broker.port)
        second_broker.start()
        assert _wait_for(lambda: transport.connected)
        assert _wait_for(lambda: not publisher.outbox.is_dirty("desktop/v3/snapshot"))
        snapshots = [payload for topic, payload in second_broker.published
                     if topic == "desktop/v3/snapshot"]
        assert snapshots == [b"three"]
        assert first_broker.connections == 1 and second_broker.connections == 1
    finally:
        unsubscribe()
        transport.stop()
        if second_broker is not None:
            second_broker.stop()
        else:
            first_broker.stop()


def test_real_direct_websocket_reconnect_keeps_session_and_shutdown_stops_retry():
    server = _DirectWebSocketServer()
    server.start()
    config = AppConfig(
        device_id="desktop",
        overlay_enabled=True,
        home_assistant=HomeAssistantConfig(
            enabled=True,
            url=f"http://127.0.0.1:{server.port}",
            token="test-token",
        ),
    )
    transport = HomeAssistantTransport(config, EventBus(), lambda _value: None)
    try:
        transport.start()
        assert server.second_ready.wait(5)
        assert _wait_for(
            lambda: transport.machine.status.state == ConnectionState.CONNECTED
        )
        assert server.connections == 2
        assert [item["protocol"] for item in server.connect_messages] == [3, 3]
        assert len({item["session"] for item in server.connect_messages}) == 1
        assert all(any(capability["name"] == "overlay.show"
                       and "direct" in capability["transports"]
                       for capability in item["capabilities"])
                   for item in server.connect_messages)
        assert transport.stop()
        connections = server.connections
        time.sleep(0.05)
        assert server.connections == connections
        assert transport.machine.status.state == ConnectionState.STOPPED
    finally:
        transport.stop()
        server.stop()
