"""Deterministic regression coverage for the Phase 4 overlay host and engine."""

from __future__ import annotations

import threading

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from test_v2_application import runtime
from test_v2_desktop import qt_app

import ha_windows_bridge.overlays.service as service_module
from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.core.events import Event
from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.monitors import screen_id
from ha_windows_bridge.overlays.positioning import PlacementEngine, Rect
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.ui.motion import MotionSystem


def payload(identifier, **options):
    return {"title": options.pop("title", "Title"), "message": "Body",
            "data": {"id": identifier, **options}}


def test_patch_restores_hover_deadline_clears_title_and_preserves_media_anchor():
    now = [10.0]
    engine = NotificationEngine(clock=lambda: now[0])
    admitted = engine.submit(payload(
        "card", duration=10, pause_on_hover=True, layout="media",
        media_position=20, media_duration=100, media_playing=True,
    ))
    engine.mark_displayed("card", admitted.token)
    now[0] = 14
    assert engine.pause("card", True, admitted.token)
    anchor = engine.visible["card"].media_updated_at

    patched = engine.submit({
        "title": "",
        "data": {"id": "card", "action": "update", "pause_on_hover": False},
    })
    item = engine.visible["card"]
    assert item.options["title"] == ""
    assert item.media_updated_at == anchor
    assert item.remaining is None and item.deadline == 20
    assert engine.media_position("card") == 24
    assert patched.token == admitted.token


def test_stale_tokens_cannot_dismiss_or_hover_replacement_atomically():
    now = [0.0]
    engine = NotificationEngine(clock=lambda: now[0])
    first = engine.submit(payload("same", duration=10, pause_on_hover=True))
    engine.mark_displayed("same", first.token)
    second = engine.submit(payload("same", duration=10, pause_on_hover=True))

    assert not engine.pause("same", True, first.token)
    assert not engine.remove("same", first.token)
    assert engine.visible["same"].token == second.token
    assert engine.visible["same"].deadline is None


def test_same_id_waits_for_retiring_generation_before_promotion():
    engine = NotificationEngine(limit=3)
    first = engine.submit(payload("same"))
    assert engine.begin_retire("same", first.token)
    engine.submit(payload("other", display_mode="parallel"))
    second = engine.submit(payload(
        "same", title="replacement", display_mode="parallel"
    ))
    assert set(engine.visible) == {"other"}
    assert engine.pending[0].token == second.token
    assert engine.finish_retire("same", first.token)
    assert engine.visible["same"].token == second.token


def test_presentation_state_is_atomic_and_rejects_stale_generation():
    now = [10.0]
    engine = NotificationEngine(clock=lambda: now[0])
    first = engine.submit(payload(
        "frame", duration=10, layout="media", media_position=2,
        media_duration=20, media_playing=True,
    ))
    engine.mark_displayed("frame", first.token)
    now[0] = 12.0
    assert engine.presentation_state("frame", first.token) == (0.8, 20, 4.0)

    second = engine.submit(payload("frame", duration=5))
    assert engine.presentation_state("frame", first.token) is None
    assert engine.presentation_state("frame", second.token) is not None


def test_presentation_frame_serializes_concurrent_replacement_without_sleep():
    frame_entered = threading.Event()
    release_frame = threading.Event()
    replacement_attempted = threading.Event()
    replacement_finished = threading.Event()

    def clock():
        if threading.current_thread().name == "frame-reader":
            frame_entered.set()
            assert release_frame.wait(1)
        return 10.0

    engine = NotificationEngine(clock=clock)
    first = engine.submit(payload("concurrent"))

    reader = threading.Thread(
        name="frame-reader",
        target=lambda: engine.presentation_state("concurrent", first.token),
    )

    def replace():
        replacement_attempted.set()
        engine.submit(payload("concurrent", title="new"))
        replacement_finished.set()

    writer = threading.Thread(name="replacement-writer", target=replace)
    reader.start()
    assert frame_entered.wait(1)
    writer.start()
    assert replacement_attempted.wait(1)
    assert not replacement_finished.is_set()
    release_frame.set()
    reader.join(1)
    writer.join(1)
    assert not reader.is_alive() and not writer.is_alive()
    assert replacement_finished.is_set()
    assert engine.presentation_state("concurrent", first.token) is None


def test_reduced_motion_finishes_enter_once_and_disposes_exit(monkeypatch):
    app = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: True))
    app.setProperty("bridgePopupAnimation", "slide")
    app.setProperty("bridgePopupAnimationDuration", 700)
    window = NotificationWindow(validated_request("Title", "Body", {"id": "motion"}), token=7)
    displayed = QSignalSpy(window.displayed)
    window.place(QPoint(8, 8), appearing=True)
    window.reduce_motion()
    app.processEvents()
    assert displayed.count() == 1
    assert window.pos() == QPoint(8, 8) and window.windowOpacity() == 1

    window.retire()
    window.reduce_motion()
    assert window._closed
    app.processEvents()
    assert displayed.count() == 1


def test_stale_static_callback_after_dispose_is_silent(monkeypatch):
    app = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: False))
    window = NotificationWindow(validated_request("Title", "Body", {"id": "static"}), token=9)
    displayed = QSignalSpy(window.displayed)
    window.place(QPoint(), appearing=True)
    window.dispose()
    app.processEvents()
    assert displayed.count() == 0


def test_close_button_click_emits_id_and_generation():
    app = qt_app()
    window = NotificationWindow(validated_request(
        "Title", "Body", {"id": "close", "show_close_button": True}
    ), token=13)
    dismissed = QSignalSpy(window.dismissed)
    try:
        window.show()
        app.processEvents()
        QTest.mouseClick(window.close_button, Qt.MouseButton.LeftButton)
        assert dismissed.count() == 1
        assert list(dismissed.at(0)) == ["close", 13]
    finally:
        window.dispose()


def test_invalid_oversized_corrupt_and_url_images_use_empty_fallback():
    qt_app()
    images = (
        "data:image/png;base64,%%%",
        "data:image/png;base64," + "A" * (768 * 1024),
        "data:image/png;base64,bm90LWFuLWltYWdl",
        "https://example.invalid/private.png",
    )
    for index, image in enumerate(images):
        window = NotificationWindow(validated_request(
            "Media", "Body", {"id": f"image-{index}", "layout": "media", "image": image}
        ))
        try:
            assert window._media_image.isNull()
        finally:
            window.dispose()


def test_lock_suspend_and_fullscreen_policy_emit_controlled_terminal_reasons():
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    overlays = OverlayService(app)
    records = []
    unsubscribe = app.events.subscribe("overlay.lifecycle", lambda event: records.append(event.data))
    try:
        locked = overlays.engine.submit({"data": {"id": "locked"}})
        overlays.engine.mark_displayed("locked", locked.token)
        overlays._publish_lifecycle()
        overlays._policy_event(Event("windows.locked", True))
        overlays._event(Event("windows.locked", True))
        assert any(item["reason"] == "locked" and item["disposition"] == "closed"
                   for item in records)

        overlays._policy_event(Event("windows.locked", False))
        suspended = overlays.engine.submit({"data": {"id": "suspended"}})
        overlays.engine.mark_displayed("suspended", suspended.token)
        overlays._publish_lifecycle()
        overlays._policy_event(Event("windows.power_changed", "suspend"))
        overlays._event(Event("windows.power_changed", "suspend"))
        assert any(item["reason"] == "suspended" for item in records)

        overlays._policy_event(Event("windows.power_changed", "resume"))
        app._system_view.context_snapshot = lambda: type("Context", (), {
            "locked": False, "fullscreen": True,
        })()
        overlays.engine.submit({"data": {"id": "fullscreen"}})
        overlays._sync()
        assert any(item["reason"] == "fullscreen" for item in records)
    finally:
        unsubscribe()
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_context_change_rechecks_fullscreen_for_stable_pinned_card():
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    context = type("Context", (), {"locked": False, "fullscreen": False})()
    app._system_view.context_snapshot = lambda: context
    overlays = OverlayService(app)
    records = []
    unsubscribe = app.events.subscribe(
        "overlay.lifecycle", lambda event: records.append(event.data)
    )
    try:
        admitted = overlays.engine.submit(payload("pinned", pinned=True))
        overlays._sync()
        overlays.engine.mark_displayed("pinned", admitted.token)
        overlays._publish_lifecycle()
        assert "pinned" in overlays.engine.visible
        assert not overlays.timer.isActive()

        context.fullscreen = True
        overlays._event(Event("computer_state.changed", context))
        assert "pinned" not in overlays.engine.visible
        assert any(item["notification_id"] == "pinned"
                   and item["reason"] == "fullscreen" for item in records)
    finally:
        unsubscribe()
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_no_screens_stages_then_drops_without_false_display(monkeypatch):
    qt = qt_app()
    now = [0.0]
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    overlays = OverlayService(app)
    overlays.engine.clock = lambda: now[0]
    overlays.engine.queue_max_age = 2.0
    records = []
    unsubscribe = app.events.subscribe(
        "overlay.lifecycle", lambda event: records.append(event.data)
    )
    facade = type("NoScreens", (), {
        "screens": staticmethod(lambda: []),
        "primaryScreen": staticmethod(lambda: None),
    })
    monkeypatch.setattr(service_module, "QGuiApplication", facade)
    try:
        overlays.engine.submit(payload("waiting"))
        overlays._sync()
        assert not overlays.engine.visible
        assert [item.id for item in overlays.engine.pending] == ["waiting"]
        assert not any(item["disposition"] == "displayed" for item in records)

        now[0] = 2.0
        overlays._tick()
        assert not overlays.engine.pending
        assert any(item["notification_id"] == "waiting"
                   and item["disposition"] == "dropped"
                   and item["reason"] == "no_space" for item in records)
    finally:
        unsubscribe()
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_local_card_binds_actual_monitor_then_reports_removal(monkeypatch):
    qt = qt_app()
    app = runtime(AppConfig(
        auto_connect=False, overlay_enabled=True, reduced_motion=True,
    ))
    overlays = OverlayService(app)
    records = []
    unsubscribe = app.events.subscribe(
        "overlay.lifecycle", lambda event: records.append(event.data)
    )
    try:
        admitted = overlays.engine.submit(payload("local"))
        overlays._sync()
        actual_id = screen_id(overlays._screens[0])
        item = overlays.engine.snapshot()[0]["local"]
        assert item.token == admitted.token
        assert item.options["monitor_id"] == actual_id

        facade = type("NoScreens", (), {
            "screens": staticmethod(lambda: []),
            "primaryScreen": staticmethod(lambda: None),
        })
        monkeypatch.setattr(service_module, "QGuiApplication", facade)
        overlays._screens_changed()
        assert any(item["notification_id"] == "local"
                   and item["reason"] == "display_removed" for item in records)
    finally:
        unsubscribe()
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_placement_remove_interleave_is_token_fenced_and_does_not_raise(monkeypatch):
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    overlays = OverlayService(app)
    try:
        overlays.engine.submit(payload("race"))

        def remove_during_place(_self, _area, _cards):
            overlays.engine.remove("race")
            return {}

        monkeypatch.setattr(PlacementEngine, "place", remove_during_place)
        overlays._sync()
        assert "race" not in overlays.engine.visible
        assert "race" not in overlays.windows
        assert "race" in overlays.engine.retiring
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt.processEvents()
        assert "race" not in overlays.engine.retiring
    finally:
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_stale_placement_cannot_defer_replacement_generation(monkeypatch):
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    overlays = OverlayService(app)
    replacement = []
    try:
        first = overlays.engine.submit(payload("race"))

        def replace_during_place(_self, _area, _cards):
            replacement.append(overlays.engine.submit(payload("race", title="new")))
            return {"race": Rect(10, 10, 100, 100)}

        monkeypatch.setattr(PlacementEngine, "place", replace_during_place)
        overlays._sync()
        current = overlays.engine.visible["race"]
        assert current.token == replacement[0].token
        assert current.token != first.token
        assert not overlays.engine.pending
        assert "race" not in overlays.windows
        assert len(overlays._retiring) == 1
        assert "race" not in overlays.engine.retiring
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt.processEvents()
        assert not overlays._retiring
        assert "race" not in overlays.engine.retiring
        assert overlays.engine.visible["race"].token == replacement[0].token
    finally:
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_no_screen_snapshot_remove_interleave_is_a_noop(monkeypatch):
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=True))
    overlays = OverlayService(app)
    called = [False]
    try:
        overlays.engine.submit(payload("race"))

        def screens():
            if not called[0]:
                called[0] = True
                overlays.engine.remove("race")
            return []

        facade = type("NoScreens", (), {
            "screens": staticmethod(screens),
            "primaryScreen": staticmethod(lambda: None),
        })
        monkeypatch.setattr(service_module, "QGuiApplication", facade)
        overlays._sync()
        assert "race" not in overlays.engine.visible
        assert "race" not in overlays.engine.pending
    finally:
        overlays.close()
        assert app.shutdown()
        qt.processEvents()
