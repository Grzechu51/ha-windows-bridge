from ha_windows_bridge.overlays.engine import NotificationEngine


def notification(identifier, **options):
    return {"title": identifier, "message": "Body", "data": {"id": identifier, **options}}


def test_queue_priority_parallel_and_update():
    engine = NotificationEngine(limit=2, queue_limit=2, clock=lambda: 100)
    assert engine.submit(notification("a")) == "shown"
    assert engine.submit(notification("b", display_mode="parallel")) == "shown"
    engine.submit(notification("normal"))
    engine.submit(notification("critical", priority="critical"))
    assert engine.submit(notification("low", priority="low")) == "queue_full"
    assert engine.submit({"message": "Changed", "data": {"id": "a", "action": "update"}}) == "updated"
    assert engine.visible["a"].options["title"] == "a"
    engine.remove("b")
    assert list(engine.visible) == ["a"]
    engine.remove("a")
    assert list(engine.visible) == ["critical"]


def test_hover_preserves_remaining_time_and_pinned_needs_no_clock():
    now = [0.0]
    engine = NotificationEngine(clock=lambda: now[0])
    engine.submit(notification("timed", pause_on_hover=True, duration=10))
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
    assert engine.submit(notification("missing", action="update")) == "not_found"
    engine.submit(notification("one"))
    engine.submit(notification("two"))
    engine.submit({"data": {"action": "clear"}})
    assert not engine.visible
    assert not engine.pending
