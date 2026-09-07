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
from ha_windows_bridge.communication.state_outbox import StateOutbox
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.core.commands import CommandError, CommandResult
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ComputerStateStore
from ha_windows_bridge.discovery import master_volume_topics, power_action_topic


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
    second_attempt = outbox.begin_attempt(second.key, second.token, 1)
    assert second_attempt is not None
    assert outbox.mark_failed(
        second_attempt.key,
        second_attempt.token,
        second_attempt.connection_generation,
    )
    assert {item.state for item in outbox.pending()} == {
        DeliveryState.ACCEPTED, DeliveryState.FAILED
    }
    outbox.replay()
    assert all(item.state == DeliveryState.ACCEPTED for item in outbox.pending())
    replayed_second = next(item for item in outbox.pending() if item.key == second.key)
    delivered_attempt = outbox.begin_attempt(
        replayed_second.key, replayed_second.token, 2
    )
    assert delivered_attempt is not None
    assert outbox.mark_delivered(
        delivered_attempt.key,
        delivered_attempt.token,
        delivered_attempt.connection_generation,
    )
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
    failed = [item for item in gateway.outbox.snapshot() if item.key.endswith(":command-1")]
    assert failed[0].state == DeliveryState.FAILED
    gateway._connection_changed(SimpleNamespace(data=SimpleNamespace(
        transport="mqtt", state="connected")))
    results = [ResultMessage.decode(payload) for topic, payload, _kw in transport.calls
               if topic == gateway.protocol.result_topic]
    assert len(results) == 2 and results[-1].status == "succeeded"
    assert not any(item.key.endswith(":command-1") for item in gateway.outbox.snapshot())


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
    transport.machine.stop()
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


def test_legacy_adapter_uses_new_ids_for_idempotent_entity_setters():
    config = AppConfig(control_master_volume=True)
    protocol = TopicProtocol(config, session="current", clock=lambda: 100)
    topic = master_volume_topics(config)[0]
    first = protocol.decode(topic, b"42")
    retry = protocol.decode(topic, b"42")
    assert first.id != retry.id
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


def test_p2_r2_late_ack_from_old_connection_cannot_ack_new_failed_attempt():
    outbox = MessageOutbox()
    accepted = outbox.accept("result", "v3/result", "payload", retain=False)
    old_attempt = outbox.begin_attempt("result", accepted.token, 1)
    assert old_attempt is not None

    outbox.replay(2)
    replayed = outbox.pending()[0]
    new_attempt = outbox.begin_attempt("result", replayed.token, 2)
    assert new_attempt is not None
    assert outbox.mark_failed(
        new_attempt.key, new_attempt.token, new_attempt.connection_generation
    )

    assert not outbox.mark_delivered(
        old_attempt.key, old_attempt.token, old_attempt.connection_generation
    )
    current = outbox.snapshot()[0]
    assert current.token == new_attempt.token
    assert current.state == DeliveryState.FAILED


def test_p2_r3_precedence_and_outbox_update_are_atomic():
    accepted_passed_precedence = threading.Event()
    terminal_started = threading.Event()
    release = threading.Event()
    errors = []

    class Transport:
        connected = False

        @staticmethod
        def publish(*_args, **_kwargs):
            return False

    gateway = MqttGateway(AppConfig(device_id="desktop"), SimpleNamespace(), EventBus())
    gateway.transport = Transport()
    original_accept = gateway.outbox.accept

    def barrier_accept(*args, **kwargs):
        payload = json.loads(args[2])
        if payload.get("status") == "accepted":
            accepted_passed_precedence.set()
            assert release.wait(1)
        return original_accept(*args, **kwargs)

    gateway.outbox.accept = barrier_accept

    def reply(result):
        try:
            gateway._reply(result)
        except Exception as exc:  # pragma: no cover - assertions expose failures
            errors.append(exc)

    accepted = threading.Thread(
        target=reply, args=(CommandResult("reverse-order", "accepted"),)
    )
    accepted.start()
    assert accepted_passed_precedence.wait(1)

    def terminal_reply():
        terminal_started.set()
        reply(CommandResult("reverse-order", "succeeded"))

    terminal = threading.Thread(target=terminal_reply)
    terminal.start()
    assert terminal_started.wait(1)
    release.set()
    accepted.join(1)
    terminal.join(1)
    assert not accepted.is_alive() and not terminal.is_alive() and not errors
    item = next(
        item for item in gateway.outbox.snapshot()
        if item.key.endswith(":reverse-order")
    )
    assert ResultMessage.decode(item.payload).status == "succeeded"
    assert gateway._result_status[(3, gateway.protocol.session, "reverse-order")] == "succeeded"


def test_p2_r4_legacy_setter_sequence_and_explicit_id_retry():
    config = AppConfig(control_master_volume=True, allow_power_actions=True)
    protocol = TopicProtocol(config, clock=lambda: 100, monotonic_clock=lambda: 10)
    topic = master_volume_topics(config)[0]
    commands = [protocol.decode(topic, value) for value in (b"20", b"80", b"20")]
    assert [item.arguments["value"] for item in commands] == [0.2, 0.8, 0.2]
    assert len({item.id for item in commands}) == 3
    with pytest.raises(CommandError, match="legacy_command_id_required"):
        protocol.decode(power_action_topic(config, "restart"), b"PRESS")

    payload = json.dumps(
        {
            "version": 2,
            "id": "explicit-retry",
            "kind": "audio.master.volume",
            "target": "",
            "arguments": {"value": 0.5},
            "issued_at": 100,
            "ttl_ms": 10_000,
        }
    ).encode()
    router = CommandRouter(clock=lambda: 100, monotonic_clock=lambda: 10)
    executions = []
    done = threading.Event()

    def execute(command):
        executions.append(command.arguments["value"])
        if len(executions) == 3:
            done.set()
        return {}

    router.register("audio.master.volume", execute)
    try:
        for command in commands:
            assert router.submit(command, lambda _result: None).status == "accepted"
        assert done.wait(1)
        assert executions == [0.2, 0.8, 0.2]

        first = protocol.decode(protocol.legacy_command_topic, payload)
        retry = protocol.decode(protocol.legacy_command_topic, payload)
        assert first.id == retry.id == "explicit-retry"
        retried = threading.Event()
        assert router.submit(first, lambda _result: retried.set()).status == "accepted"
        assert retried.wait(1)
        assert router.submit(retry, lambda _result: None).status == "succeeded"
        assert executions == [0.2, 0.8, 0.2, 0.5]
    finally:
        assert router.stop()


def test_p2_r5_v2_command_execution_returns_v2_result_topic():
    config = AppConfig(device_id="desktop", control_master_volume=True)
    events = EventBus()
    router = CommandRouter()
    terminal = threading.Event()

    class Transport:
        connected = True

        def __init__(self):
            self.frames = []

        def publish(self, topic, payload, *, on_delivery=None, **_kwargs):
            decoded = json.loads(payload)
            self.frames.append((topic, decoded))
            if decoded.get("status") == "succeeded":
                terminal.set()
            if on_delivery:
                on_delivery(True)
            return True

    gateway = MqttGateway(config, router, events)
    gateway.transport = Transport()
    router.register("audio.master.volume", lambda _command: {"applied": True})
    payload = json.dumps(
        {
            "version": 2,
            "id": "legacy-command",
            "kind": "audio.master.volume",
            "target": "",
            "arguments": {"value": 0.5},
            "issued_at": time.time(),
            "ttl_ms": 10_000,
        }
    ).encode()
    try:
        gateway.receive(gateway.protocol.legacy_command_topic, payload)
        assert terminal.wait(1)
        topic, result = gateway.transport.frames[-1]
        assert topic == gateway.protocol.legacy_result_topic
        assert result == {
            "version": 2,
            "id": "legacy-command",
            "status": "succeeded",
            "code": "",
            "data": {"applied": True},
        }
    finally:
        assert router.stop()


def test_p2_r6_state_outbox_retries_after_missing_ack_deadline():
    clock = [0.0]
    outbox = StateOutbox(monotonic_clock=lambda: clock[0], ack_timeout=5)
    callbacks = []
    assert outbox.observe("snapshot", "one")
    assert not outbox.flush_confirmed(
        lambda _item, callback: callbacks.append(callback) or True
    )
    clock[0] = 6
    assert not outbox.flush_confirmed(
        lambda _item, callback: callbacks.append(callback) or True
    )
    assert len(callbacks) == 2
    callbacks[0](True)
    assert outbox.is_dirty("snapshot")
    callbacks[1](True)
    assert not outbox.is_dirty("snapshot")


def test_p2_r6_missing_suback_and_puback_trigger_controlled_retry():
    sub_clock = [0.0]
    sub_client = _MqttClient()
    sub_transport = MqttTransport(
        MqttConfig(base_topic="desktop"),
        "desktop",
        EventBus(),
        lambda *_args: None,
        {"command"},
        client_factory=lambda *_args, **_kwargs: sub_client,
        monotonic_clock=lambda: sub_clock[0],
        ack_timeout=5,
    )
    sub_transport._epoch = sub_transport.machine.begin()
    sub_transport._on_connect(
        sub_client, None, None, SimpleNamespace(is_failure=False), None
    )
    sub_clock[0] = 6
    assert sub_transport._expire_ack_deadlines()
    assert sub_transport.machine.status.error == "suback_timeout"

    pub_clock = [0.0]
    pub_client = _MqttClient()
    pub_transport = MqttTransport(
        MqttConfig(base_topic="desktop"),
        "desktop",
        EventBus(),
        lambda *_args: None,
        set(),
        client_factory=lambda *_args, **_kwargs: pub_client,
        monotonic_clock=lambda: pub_clock[0],
        ack_timeout=5,
    )
    pub_transport._epoch = pub_transport.machine.begin()
    pub_transport._on_connect(
        pub_client, None, None, SimpleNamespace(is_failure=False), None
    )
    publisher = StatePublisher(pub_transport, EventBus())
    assert publisher.publish_observation("desktop/v3/snapshot", "latest")
    pub_clock[0] = 6
    assert pub_transport._expire_ack_deadlines()
    assert pub_transport.machine.status.error == "puback_timeout"
    assert publisher.outbox.is_dirty("desktop/v3/snapshot")


def test_p2_r7_active_connection_retries_transient_result_publish():
    delivered = threading.Event()

    class Transport:
        connected = True

        def __init__(self):
            self.calls = 0

        def start(self):
            pass

        def stop(self):
            return True

        def publish(self, topic, _payload, *, on_delivery=None, **_kwargs):
            if not topic.endswith("/result"):
                return True
            self.calls += 1
            if self.calls == 1:
                return False
            on_delivery(True)
            delivered.set()
            return True

    gateway = MqttGateway(
        AppConfig(device_id="desktop"),
        SimpleNamespace(),
        EventBus(),
        protocol_retry_delay=lambda _attempt: 0,
    )
    gateway.transport = Transport()
    gateway.start()
    try:
        gateway._reply(CommandResult("retry-active", "succeeded"))
        assert delivered.wait(1)
        assert gateway.transport.calls == 2
        assert not any(item.key.endswith(":retry-active") for item in gateway.outbox.snapshot())
    finally:
        assert gateway.stop()


def test_p2_r7_retry_does_not_republish_another_message_waiting_for_ack():
    callbacks = {}
    calls = []

    class Transport:
        connected = True

        @staticmethod
        def publish(_topic, payload, *, on_delivery=None, **_kwargs):
            identifier = ResultMessage.decode(payload).id
            calls.append(identifier)
            if identifier == "message-a":
                callbacks[identifier] = on_delivery
                return True
            if calls.count(identifier) == 1:
                return False
            on_delivery(True)
            return True

    gateway = MqttGateway(AppConfig(device_id="desktop"), SimpleNamespace(), EventBus())
    gateway.transport = Transport()
    gateway._reply(CommandResult("message-a", "succeeded"))
    gateway._reply(CommandResult("message-b", "succeeded"))
    assert calls == ["message-a", "message-b"]
    assert next(
        item for item in gateway.outbox.snapshot() if item.key.endswith(":message-a")
    ).state == DeliveryState.INFLIGHT

    gateway._flush_protocol()
    assert calls == ["message-a", "message-b", "message-b"]
    callbacks["message-a"](True)
    assert not any(item.key.endswith(":message-a") for item in gateway.outbox.snapshot())


def test_p2_r7_exhausted_terminal_result_is_retained_for_bounded_replay():
    class Transport:
        connected = True

        @staticmethod
        def publish(topic, _payload, **_kwargs):
            return not topic.endswith("/result")

    gateway = MqttGateway(AppConfig(device_id="desktop"), SimpleNamespace(), EventBus())
    gateway.transport = Transport()
    gateway._reply(CommandResult("bounded-result", "succeeded"))
    for _attempt in range(gateway._max_active_attempts - 1):
        gateway._flush_protocol()
    retained = next(
        item for item in gateway.outbox.snapshot()
        if item.key.endswith(":bounded-result")
    )
    assert retained.state == DeliveryState.EXHAUSTED
    assert ResultMessage.decode(retained.payload).status == "succeeded"
    assert not any(item.key == retained.key for item in gateway.outbox.pending())

    gateway.outbox.replay(2)
    replayed = next(item for item in gateway.outbox.pending() if item.key == retained.key)
    assert replayed.state == DeliveryState.ACCEPTED and replayed.attempts == 0

    bounded = MessageOutbox(capacity=1)
    old = bounded.accept("old", "v3/result", "old", retain=False)
    attempt = bounded.begin_attempt("old", old.token, 1)
    assert bounded.mark_failed("old", attempt.token, 1)
    assert bounded.mark_exhausted("old", attempt.token, 1)
    assert bounded.accept("new", "v3/result", "new", retain=False) is not None
    assert [item.key for item in bounded.snapshot()] == ["new"]


def test_p2_r8_shutdown_preserves_lwt_when_offline_cannot_enter_full_window():
    client = _MqttClient()
    client.disconnect_calls = 0
    client.socket_closes = 0
    client.disconnect = lambda: setattr(
        client, "disconnect_calls", client.disconnect_calls + 1
    )
    client._sock_close = lambda: setattr(
        client, "socket_closes", client.socket_closes + 1
    )
    transport = MqttTransport(
        MqttConfig(base_topic="desktop"),
        "desktop",
        EventBus(),
        lambda *_args: None,
        set(),
        client_factory=lambda *_args, **_kwargs: client,
        shutdown_timeout=0.01,
    )
    transport._epoch = transport.machine.begin()
    assert transport.machine.connected(transport._epoch)
    for index in range(transport._ack_capacity):
        assert transport.publish(
            f"state/{index}", "value", on_delivery=lambda _success: None
        )
    assert not transport.stop()
    assert client.disconnect_calls == 0
    assert client.socket_closes == 1
    assert transport.machine.status.state == ConnectionState.STOPPED


def test_p2_r8_ack_timeout_during_offline_wait_never_sends_disconnect():
    clock = [0.0]
    offline_enqueued = threading.Event()
    client = _MqttClient()
    client.disconnect_calls = 0
    client.socket_closes = 0
    client.disconnect = lambda: setattr(
        client, "disconnect_calls", client.disconnect_calls + 1
    )
    client._sock_close = lambda: setattr(
        client, "socket_closes", client.socket_closes + 1
    )
    original_publish = client.publish

    def publish(topic, payload, **kwargs):
        info = original_publish(topic, payload, **kwargs)
        if topic == "desktop/status" and payload == "offline":
            offline_enqueued.set()
        return info

    client.publish = publish
    transport = MqttTransport(
        MqttConfig(base_topic="desktop"),
        "desktop",
        EventBus(),
        lambda *_args: None,
        set(),
        client_factory=lambda *_args, **_kwargs: client,
        monotonic_clock=lambda: clock[0],
        ack_timeout=5,
        shutdown_timeout=1,
    )
    transport._epoch = transport.machine.begin()
    assert transport.machine.connected(transport._epoch)
    for index in range(20):
        assert transport.publish(
            f"state/{index}", "value", on_delivery=lambda _success: None
        )
    clock[0] = 4
    outcome = []
    stopping = threading.Thread(target=lambda: outcome.append(transport.stop()))
    stopping.start()
    assert offline_enqueued.wait(1)
    assert transport._shutdown.is_set()
    clock[0] = 6
    assert transport._expire_ack_deadlines()
    stopping.join(1)
    assert not stopping.is_alive()
    assert outcome == [False]
    assert client.disconnect_calls == 0
    assert client.socket_closes >= 1
    assert transport.machine.status.state == ConnectionState.STOPPED


def test_p2_r9_ha_birth_resync_is_jittered_coalesced_and_cancelled_on_stop():
    events = EventBus()
    inventory = []
    events.subscribe("inventory.requested", inventory.append)
    scheduled = []

    def schedule(delay, callback):
        item = {"delay": delay, "callback": callback, "cancelled": False}
        scheduled.append(item)

        def cancel():
            item["cancelled"] = True

        return cancel

    class Transport:
        connected = True

        def __init__(self):
            self.topics = []

        @staticmethod
        def stop():
            return True

        def publish(self, topic, _payload, *, on_delivery=None, **_kwargs):
            self.topics.append(topic)
            if on_delivery:
                on_delivery(True)
            return True

    gateway = MqttGateway(
        AppConfig(device_id="desktop"),
        SimpleNamespace(),
        events,
        resync_delay=lambda: 0.25,
        resync_scheduler=schedule,
    )
    transport = Transport()
    gateway.transport = transport
    gateway.publisher.transport = transport
    assert gateway.publisher.publish_observation(
        gateway.protocol.snapshot_topic, "latest-snapshot"
    )
    gateway._flush_protocol()
    transport.topics.clear()

    for _ in range(3):
        gateway.receive(gateway.protocol.birth_topic, b"online")
    assert len(scheduled) == 1 and scheduled[0]["delay"] == 0.25
    assert not inventory and not transport.topics

    scheduled[0]["callback"]()
    assert len(inventory) == 1
    assert transport.topics.count(gateway.protocol.capabilities_topic) == 1
    assert transport.topics.count(gateway.protocol.snapshot_topic) == 1

    transport.topics.clear()
    gateway.receive(gateway.protocol.birth_topic, b"online")
    assert len(scheduled) == 2
    assert gateway.stop()
    assert scheduled[1]["cancelled"]
    scheduled[1]["callback"]()
    assert len(inventory) == 1 and not transport.topics
