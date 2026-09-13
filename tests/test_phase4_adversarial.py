"""Independent adversarial contract tests for the Phase 4 overlay subsystem."""

from __future__ import annotations

from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import (
    DeliveryDisposition,
    LifecycleReason,
    NotificationCommand,
)


def payload(identifier: str, **data):
    return {"title": data.pop("title", "Original title"), "message": data.pop("message", "Original body"), "data": {"id": identifier, **data}}


def test_typed_command_distinguishes_omission_from_explicit_empty_patch():
    omitted = NotificationCommand.parse({"data": {"action": "update", "id": "card", "progress": 42}}, source="mqtt", command_id="cmd-1")
    explicit = NotificationCommand.parse({"title": "", "message": "", "data": {"action": "update", "id": "card"}}, source="direct", command_id="cmd-2")
    assert "title" not in omitted.provided and "message" not in omitted.provided
    assert {"title", "message"} <= explicit.provided
    assert omitted.policy.source == "mqtt" and omitted.command_id == "cmd-1"


def test_patch_unknown_retiring_and_omitted_fields():
    engine = NotificationEngine(clock=lambda: 0.0)
    missing = engine.submit({"data": {"action": "update", "id": "missing", "progress": 7}})
    assert (missing.disposition, missing.reason) == (DeliveryDisposition.REJECTED, LifecycleReason.NOT_FOUND)
    first = engine.submit(payload("card", pinned=True, pause_on_hover=True, progress=1))
    patched = engine.submit({"data": {"action": "update", "id": "card", "progress": 80}})
    item = engine.visible["card"]
    assert (item.options["title"], item.options["message"], item.options["pinned"], item.options["progress"]) == ("Original title", "Original body", True, 80)
    assert engine.begin_retire("card", patched.token)
    late = engine.submit({"message": "too late", "data": {"action": "update", "id": "card"}})
    assert (late.disposition, late.reason) == (DeliveryDisposition.REJECTED, LifecycleReason.NOT_FOUND)
    assert engine.retiring["card"].options["message"] == "Original body"
    assert first.token == patched.token


def test_no_display_success_before_matching_host_callback():
    engine = NotificationEngine()
    admitted = engine.submit(payload("card"))
    assert (admitted.disposition, admitted.reason) == (DeliveryDisposition.ACCEPTED, LifecycleReason.QUEUED)
    assert engine.mark_displayed("card", admitted.token).disposition is DeliveryDisposition.DISPLAYED


def test_replacement_and_shutdown_reject_stale_callbacks():
    engine = NotificationEngine()
    first = engine.submit(payload("same", message="first"))
    second = engine.submit(payload("same", message="second"))
    assert engine.mark_displayed("same", first.token).disposition is DeliveryDisposition.REJECTED
    assert engine.visible["same"].options["message"] == "second"
    assert engine.mark_displayed("same", second.token).disposition is DeliveryDisposition.DISPLAYED
    engine.shutdown()
    assert engine.mark_displayed("same", second.token).disposition is DeliveryDisposition.REJECTED
    assert not engine.visible and not engine.pending and not engine.retiring
    assert engine.submit(payload("later")).reason is LifecycleReason.STOPPING


def test_hover_expiry_and_pinned_patch_preserve_clock():
    now = [0.0]
    engine = NotificationEngine(clock=lambda: now[0])
    admitted = engine.submit(payload("timed", duration=10, pause_on_hover=True))
    engine.mark_displayed("timed", admitted.token)
    now[0] = 4
    engine.pause("timed", True)
    now[0] = 100
    engine.tick()
    assert "timed" in engine.visible
    engine.submit({"data": {"action": "update", "id": "timed", "progress": 55}})
    assert engine.visible["timed"].remaining == 6
    engine.pause("timed", False)
    now[0] = 106
    engine.tick()
    assert "timed" not in engine.visible
    engine.submit(payload("pinned", pinned=True, duration=2))
    now[0] = 1000
    engine.tick()
    assert "pinned" in engine.visible
    engine.submit({"data": {"action": "update", "id": "pinned", "progress": 9}})
    assert engine.visible["pinned"].deadline is None


def test_retiring_capacity_and_queue_age_are_bounded_without_sleep():
    now = [0.0]
    engine = NotificationEngine(limit=1, queue_limit=2, queue_max_age=5, clock=lambda: now[0])
    shown = engine.submit(payload("visible", pinned=True))
    assert engine.begin_retire("visible", shown.token)
    queued = engine.submit(payload("waiting"))
    assert queued.reason is LifecycleReason.QUEUED and "waiting" not in engine.visible
    now[0] = 6
    engine.tick()
    assert not engine.pending
    assert engine.finish_retire("visible", shown.token) and not engine.visible


def test_overload_rejects_low_priority_without_evicting_accepted_work():
    engine = NotificationEngine(limit=1, queue_limit=2)
    engine.submit(payload("visible", pinned=True))
    normal = engine.submit(payload("normal"))
    critical = engine.submit(payload("critical", priority="critical"))
    low = engine.submit(payload("low", priority="low"))
    assert normal.disposition is DeliveryDisposition.ACCEPTED
    assert critical.disposition is DeliveryDisposition.ACCEPTED
    assert (low.disposition, low.reason) == (DeliveryDisposition.REJECTED, LifecycleReason.QUEUE_FULL)
    assert [item.id for item in engine.pending] == ["critical", "normal"]
