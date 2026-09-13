from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import DeliveryDisposition, LifecycleReason


def notification(identifier, **options):
    return {"title": identifier, "message": "Body", "data": {"id": identifier, **options}}


def test_queue_priority_parallel_and_update():
    engine = NotificationEngine(limit=2, queue_limit=2, clock=lambda: 100)
    first = engine.submit(notification("a"))
    second = engine.submit(notification("b", display_mode="parallel"))
    assert first.disposition is DeliveryDisposition.ACCEPTED
    assert second.disposition is DeliveryDisposition.ACCEPTED
    engine.submit(notification("normal"))
    engine.submit(notification("critical", priority="critical"))
    assert engine.submit(notification("low", priority="low")).reason is LifecycleReason.QUEUE_FULL
    assert engine.submit({"message": "Changed", "data": {"id": "a", "action": "update"}}).reason is LifecycleReason.UPDATED
    assert engine.visible["a"].options["title"] == "a"
    engine.remove("b")
    assert list(engine.visible) == ["a"]
    assert engine.finish_retire("b", second.token)
    engine.remove("a")
    patched_token = engine.retiring["a"].token
    assert engine.finish_retire("a", patched_token)
    assert list(engine.visible) == ["critical"]


def test_hover_preserves_remaining_time_and_pinned_needs_no_clock():
    now = [0.0]
    engine = NotificationEngine(clock=lambda: now[0])
    admitted = engine.submit(notification("timed", pause_on_hover=True, duration=10))
    engine.mark_displayed("timed", admitted.token)
    now[0] = 4
    engine.pause("timed", True)
    assert not engine.needs_clock
    now[0] = 50
    engine.tick()
    assert engine.lifetime("timed") == .6
    engine.pause("timed", False)
    now[0] = 56
    engine.tick()
    assert not engine.visible
    engine.submit(notification("pinned", pinned=True))
    assert not engine.needs_clock


def test_clear_cancels_pending_and_unknown_update_creates_nothing():
    engine = NotificationEngine()
    assert engine.submit(notification("missing", action="update")).reason is LifecycleReason.NOT_FOUND
    engine.submit(notification("one"))
    engine.submit(notification("two"))
    engine.submit({"data": {"action": "clear"}})
    assert not engine.visible
    assert not engine.pending
