"""Bounded and complete overlay delivery lifecycle tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.communication.gateway import MqttGateway
from ha_windows_bridge.communication.home_assistant import HomeAssistantTransport
from ha_windows_bridge.communication.schema import ResultMessage
from ha_windows_bridge.communication.state import ConnectionState
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig
from ha_windows_bridge.core.commands import CommandResult
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import (
    DeliveryDisposition,
    LifecycleReason,
    NotificationCommand,
)


def command(identifier, command_id="cmd-1", **data):
    return NotificationCommand.parse(
        {"title": "Title", "message": "Body", "data": {"id": identifier, **data}},
        source="mqtt", command_id=command_id, session="session-1", device_id="device-1",
    )


def lifecycle(engine):
    return [(item.disposition, item.reason, item.command_id)
            for item in engine.drain_lifecycle()]


def test_admission_display_and_user_close_are_distinct_and_exactly_once():
    engine = NotificationEngine()
    admitted = engine.submit(command("card"))
    assert lifecycle(engine) == [
        (DeliveryDisposition.ACCEPTED, LifecycleReason.QUEUED, "cmd-1")
    ]
    engine.mark_displayed("card", admitted.token)
    engine.mark_displayed("card", admitted.token)
    assert lifecycle(engine) == [
        (DeliveryDisposition.DISPLAYED, LifecycleReason.DISPLAYED, "cmd-1")
    ]
    assert engine.remove("card", admitted.token)
    assert lifecycle(engine) == [
        (DeliveryDisposition.CLOSED, LifecycleReason.USER, "cmd-1")
    ]


def test_replacement_drops_old_generation_before_accepting_new_one():
    engine = NotificationEngine()
    first = engine.submit(command("same", "old"))
    engine.drain_lifecycle()
    second = engine.submit(command("same", "new", title="replacement"))
    assert second.token != first.token
    assert lifecycle(engine) == [
        (DeliveryDisposition.DROPPED, LifecycleReason.REPLACED, "old"),
        (DeliveryDisposition.ACCEPTED, LifecycleReason.REPLACED, "new"),
    ]


def test_patch_is_a_revision_of_same_card_and_does_not_emit_replaced_terminal():
    now = [0.0]
    engine = NotificationEngine(clock=lambda: now[0])
    shown = engine.submit(command("same", "show", duration=2))
    engine.mark_displayed("same", shown.token)
    engine.drain_lifecycle()
    patched = NotificationCommand.parse(
        {"data": {"id": "same", "action": "update", "progress": 50}},
        source="mqtt", command_id="patch", session="session-1", device_id="device-1",
    )
    result = engine.submit(patched)
    assert result.reason is LifecycleReason.UPDATED
    assert engine.visible["same"].token == shown.token
    assert lifecycle(engine) == [
        (DeliveryDisposition.ACCEPTED, LifecycleReason.UPDATED, "patch")
    ]
    now[0] = 2
    engine.tick()
    assert lifecycle(engine) == [
        (DeliveryDisposition.CLOSED, LifecycleReason.EXPIRED, "show")
    ]


def test_queue_rejection_and_expiry_have_unambiguous_results():
    now = [0.0]
    engine = NotificationEngine(
        limit=1, queue_limit=1, queue_max_age=2, clock=lambda: now[0]
    )
    engine.submit(command("visible", "visible", pinned=True))
    engine.submit(command("waiting", "waiting"))
    rejected = engine.submit(command("overflow", "overflow", priority="low"))
    assert (rejected.disposition, rejected.reason) == (
        DeliveryDisposition.REJECTED, LifecycleReason.QUEUE_FULL,
    )
    records = engine.drain_lifecycle()
    assert any(item.command_id == "overflow" and item.disposition is DeliveryDisposition.REJECTED
               for item in records)
    now[0] = 3
    engine.tick()
    assert lifecycle(engine) == [
        (DeliveryDisposition.DROPPED, LifecycleReason.NO_SPACE, "waiting")
    ]


def test_shutdown_emits_terminal_before_fencing_stale_generation():
    engine = NotificationEngine()
    visible = engine.submit(command("visible", "visible"))
    engine.mark_displayed("visible", visible.token)
    engine.submit(command("pending", "pending"))
    engine.drain_lifecycle()
    engine.shutdown()
    assert lifecycle(engine) == [
        (DeliveryDisposition.CLOSED, LifecycleReason.STOPPING, "visible"),
        (DeliveryDisposition.DROPPED, LifecycleReason.STOPPING, "pending"),
    ]
    assert engine.mark_displayed("visible", visible.token).reason is LifecycleReason.NOT_FOUND


def test_lifecycle_backlog_reserves_future_events_and_stays_bounded_under_flood():
    engine = NotificationEngine(lifecycle_limit=12)
    accepted = 0
    for index in range(100):
        result = engine.submit(command("same", f"cmd-{index}"))
        accepted += result.accepted
    assert accepted < 100
    assert len(engine._lifecycle) + sum(engine._lifecycle_reserved.values()) <= 12
    assert engine.submit(command("other", "last")).reason is LifecycleReason.QUEUE_FULL


def test_rejection_flood_cannot_consume_reserved_display_and_terminal_slots():
    engine = NotificationEngine(lifecycle_limit=6)
    admitted = engine.submit(command("kept", "kept"))
    for index in range(100):
        engine.submit(command(f"rejected-{index}", f"reject-{index}"))
    assert len(engine._lifecycle) + sum(engine._lifecycle_reserved.values()) <= 6
    engine.mark_displayed("kept", admitted.token)
    engine.remove("kept", admitted.token)
    assert len(engine._lifecycle) <= 6
    records = engine.drain_lifecycle()
    assert any(item.disposition is DeliveryDisposition.DISPLAYED for item in records)
    assert any(item.disposition is DeliveryDisposition.CLOSED for item in records)


def test_public_local_event_is_whitelisted_and_excludes_internal_route_and_token():
    emitted = []

    class Events:
        def emit(self, topic, data):
            emitted.append((topic, data))

    app = object.__new__(Application)
    app.events = Events()
    engine = NotificationEngine()
    admitted = engine.submit(command("card"))
    result = engine.drain_lifecycle()[0]
    assert result.token == admitted.token and result.transport == "mqtt"
    app.publish_notification_lifecycle(result)
    assert emitted[0] == ("overlay.lifecycle", {
        "notification_id": "card", "disposition": "accepted",
        "reason": "queued", "command_id": "cmd-1",
    })
    assert "token" not in emitted[0][1] and "source" not in emitted[0][1]
    routed = emitted[1][1]
    assert routed["payload"] == emitted[0][1]
    assert "token" not in routed and "source" not in routed


class RecordingTransport:
    connected = True

    def __init__(self):
        self.frames = []

    def publish(self, topic, payload, *, on_delivery=None, **_kwargs):
        self.frames.append((topic, payload))
        if on_delivery:
            on_delivery(True)
        return True


def envelope(protocol, *, transport="mqtt", session=None):
    return SimpleNamespace(data={
        "transport": transport,
        "session": session or protocol.session,
        "device_id": protocol.device_id,
        "payload": {
            "notification_id": "card",
            "disposition": "displayed",
            "reason": "displayed",
            "command_id": "cmd-1",
        },
    })


def test_mqtt_lifecycle_reuses_result_topic_without_overwriting_command_result():
    gateway = MqttGateway(AppConfig(device_id="device-1"), SimpleNamespace(), EventBus())
    gateway.transport = RecordingTransport()
    gateway._reply(CommandResult("cmd-1", "succeeded", data={"delivery": "accepted"}))
    original_status = dict(gateway._result_status)
    gateway._lifecycle(envelope(gateway.protocol))
    messages = [ResultMessage.decode(raw) for topic, raw in gateway.transport.frames
                if topic == gateway.protocol.result_topic]
    assert [message.code for message in messages] == ["", "notification_lifecycle"]
    assert messages[1].data == {
        "notification_id": "card", "disposition": "displayed",
        "reason": "displayed", "command_id": "cmd-1",
    }
    assert gateway._result_status == original_status
    gateway._lifecycle(envelope(gateway.protocol, session="stale-session"))
    assert len(gateway.transport.frames) == 2


def test_direct_lifecycle_reuses_result_endpoint_and_is_session_fenced():
    config = AppConfig(
        device_id="device-1",
        home_assistant=HomeAssistantConfig(
            enabled=True, url="https://ha.local", token="secret"
        ),
    )
    transport = HomeAssistantTransport(config, EventBus(), lambda _value: None)

    class Socket:
        def __init__(self):
            self.sent = []
            self.read = False

        def send(self, raw):
            self.sent.append(json.loads(raw))

        def recv(self):
            self.read = True
            transport._stop.set()
            return "{}"

    socket = Socket()
    transport._socket = socket
    transport._epoch = transport.machine.begin()
    assert transport.machine.connected(transport._epoch)
    assert transport.machine.status.state is ConnectionState.CONNECTED
    public = envelope(transport.protocol, transport="direct").data["payload"]
    assert transport.lifecycle(public)
    assert not socket.sent
    transport._read_events(socket, 999)
    assert socket.read
    frame = socket.sent[-1]
    assert frame["type"] == "ha_windows_bridge/result"
    assert frame["result"]["code"] == "notification_lifecycle"
    assert frame["result"]["data"] == public
    assert not ({"token", "source", "generation", "content", "url", "image"}
                & frame["result"]["data"].keys())
    transport.stop()


def test_mqtt_lifecycle_flood_does_not_consume_command_result_capacity():
    gateway = MqttGateway(AppConfig(device_id="device-1"), SimpleNamespace(), EventBus())

    class OfflineTransport(RecordingTransport):
        connected = False

        def publish(self, *_args, **_kwargs):
            return False

    gateway.transport = OfflineTransport()
    for index in range(300):
        event = envelope(gateway.protocol)
        event.data["payload"] = {
            **event.data["payload"],
            "notification_id": f"card-{index}",
            "command_id": f"cmd-{index}",
        }
        gateway._lifecycle(event)
    assert len(gateway.lifecycle_outbox.snapshot()) == 256
    gateway._reply(CommandResult("ordinary", "succeeded"))
    assert any(item.key.endswith(":ordinary") for item in gateway.outbox.snapshot())
    assert not any(item.key.endswith(":ordinary")
                   for item in gateway.lifecycle_outbox.snapshot())
