from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.core.configuration import parse_settings, public_settings
from ha_windows_bridge.media import MediaSnapshot, _timeline_position, friendly_media_source
from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.examples import media_example
from ha_windows_bridge.overlays.glass import GlassRenderer, blur_scene
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.overlays.windows_media import windows_media_payload
from ha_windows_bridge.ui.motion import MotionSystem
from ha_windows_bridge.ui.shell import DesktopWindow, Page
from ha_windows_bridge.ui.theme import PALETTES, style_for_theme
from ha_windows_bridge.windows_effects import NativeBackdrop


def test_live_refresh_changes_pause_seek_and_track_without_restarting_lifetime():
    now = [100.]
    engine = NotificationEngine(clock=lambda: now[0])
    payload = windows_media_payload(MediaSnapshot(title="First", source_app="Player", state="playing", duration=200, position=20), controls=True)
    payload["data"].update(id="live", duration=12, pause_on_hover=True)
    engine.submit(payload)
    deadline = engine.visible["live"].deadline
    now[0] = 102
    assert engine.media_position("live") == 22
    paused = windows_media_payload(MediaSnapshot(title="First", source_app="Player", state="paused", duration=200, position=75), controls=True)
    engine.refresh_media(paused)
    now[0] = 105
    assert engine.media_position("live") == 75
    assert not engine.visible["live"].options["media_playing"]
    assert engine.visible["live"].deadline == deadline
    engine.pause("live", True)
    remaining = engine.visible["live"].remaining
    next_track = windows_media_payload(MediaSnapshot(title="Next", source_app="Player", state="playing", duration=100, position=3), controls=True)
    engine.refresh_media(next_track)
    assert engine.visible["live"].options["title"] == "Next"
    assert engine.visible["live"].remaining == remaining
    assert engine.visible["live"].deadline is None
    now[0] += 1
    assert engine.media_position("live") == 4


def test_windows_refresh_cannot_replace_home_assistant_media_or_regular_popup():
    engine = NotificationEngine()
    engine.submit({"title": "TV", "data": {"id": "remote", "layout": "media", "media_position": 8, "media_duration": 100}})
    assert not engine.refresh_media(windows_media_payload(MediaSnapshot(title="Windows")))
    assert engine.visible["remote"].options["title"] == "TV"


def test_timeline_advances_between_windows_updates_but_stops_when_paused():
    updated = datetime(2026, 9, 4, tzinfo=UTC)
    timeline = SimpleNamespace(position=timedelta(seconds=10), last_updated_time=updated)
    assert _timeline_position(timeline, "playing", 100, updated+timedelta(seconds=4)) == 14
    assert _timeline_position(timeline, "paused", 100, updated+timedelta(seconds=4)) == 10
    assert _timeline_position(timeline, "playing", 12, updated+timedelta(seconds=4)) == 12


@pytest.mark.parametrize(("source", "expected"), [
    (r"SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "Spotify"),
    (r"C:\\Program Files\\Google\\Chrome\\chrome.exe", "Chrome"),
    ("MSEdge.exe", "Microsoft Edge"),
    ("vlc.exe", "VLC"),
    ("Contoso.Player_123!Player", "Player"),
])
def test_media_source_is_a_short_application_name(source, expected):
    assert friendly_media_source(source) == expected


def test_media_controls_are_larger_aligned_and_refresh_does_not_decode_artwork(tmp_path):
    qt = qt_app()
    example = media_example()
    example["data"].update(media_live=True, media_controls=True)
    options = validated_request(example["title"], example["message"], example["data"])
    window = NotificationWindow(options)
    try:
        window.show()
        qt.processEvents()
        assert window.source.x() == window.title.x() == window.message.x() == window.media_controls.x() == window.media_time.x()
        assert all(button.size() == QSize(48, 48) for button in window._media_buttons)
        assert window.progress.maximumWidth() <= 280
        assert window.progress.maximumWidth() < window.width()
        assert "border-radius: 2px" in window.progress.styleSheet()
        centers = [button.geometry().center().y() for button in window._media_buttons]
        assert max(centers)-min(centers) <= 1
        assert not window.lifetime.isVisible()
        cache_key = window._media_image.cacheKey()
        geometry = window.geometry()
        paused = {**options, "media_playing": False, "media_position": 90., "progress": 41}
        window.update_notification(paused)
        assert window._media_buttons[1].accessibleName() == "Odtwórz"
        assert window.media_time.text() == "1:30 / 3:42"
        assert window._media_image.cacheKey() == cache_key
        assert window.geometry() == geometry
        assert window.grab().save(str(tmp_path / "media-player.png"))
        window.update_notification({**paused, "media_position": 150., "progress": 68})
        assert window.media_time.text() == "2:30 / 3:42"
        assert window._media_image.cacheKey() == cache_key
        window.update_notification({**paused, "media_duration": 0., "progress": None})
        assert not window.progress.isVisible() and not window.media_time.isVisible()
        window.update_notification(paused)
        assert window.progress.isVisible() and window.media_time.isVisible()
    finally:
        window.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_media_card_keeps_one_size_for_different_artwork_and_long_titles():
    qt = qt_app()

    def artwork(width, height, colour):
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(QColor(colour))
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "PNG")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")

    example = media_example()
    window = NotificationWindow(validated_request(example["title"], example["message"], example["data"]))
    try:
        expected = QSize(520, 214)
        widths = set()
        title_was_elided = False
        for size, title in (((180, 180), "Krótki tytuł"),
                            ((520, 160), "Bardzo długi tytuł utworu, który wcześniej powiększał całe okno odtwarzacza"),
                            ((160, 520), "Inny utwór")):
            options = validated_request(title, "Długi wykonawca i nazwa albumu, które również muszą pozostać w swoim sektorze", {
                **example["data"], "image": artwork(*size, "#c86638"),
            })
            window.update_notification(options)
            window.show()
            qt.processEvents()
            assert window.size() == expected
            widths.add((window.title.maximumWidth(), window.message.maximumWidth(), window.progress.maximumWidth()))
            title_was_elided = title_was_elided or bool(window.title.toolTip())
        assert len(widths) == 1
        assert title_was_elided
    finally:
        window.dispose()


@pytest.mark.parametrize("animation", ["none", "slide", "fade", "reveal"])
def test_animation_preferences_roundtrip_and_controls_fit(animation):
    qt = qt_app()
    config = AppConfig(auto_connect=False, overlay_animation=animation, overlay_animation_duration=380, overlay_example_duration=20, overlay_background_effect="liquid")
    restored = parse_settings(public_settings(config))
    assert restored.overlay_animation == animation and restored.overlay_animation_duration == 380
    assert restored.overlay_example_duration == 20 and restored.overlay_background_effect == "liquid"
    app = runtime(config)
    window = DesktopWindow(app)
    try:
        window.resize(820, 740)
        window.navigation.setCurrentRow(Page.OVERLAYS)
        window.show()
        qt.processEvents()
        window._collect()
        assert window.draft.overlay_animation == animation
        assert window.draft.overlay_background_effect == "liquid"
        assert window.pages.widget(Page.OVERLAYS).horizontalScrollBar().maximum() == 0
    finally:
        window._force_close = True
        window.close()
        assert app.shutdown()
        window.deleteLater()


def test_dark_theme_has_no_inner_rounded_holes_and_is_darker():
    assert QColor(PALETTES["dark"].canvas).lightness() < 32
    assert QColor(PALETTES["dark"].surface).lightness() < 43
    style = style_for_theme("", "dark")
    assert "border-radius: 0px" in style


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_shell_removes_development_labels_and_fluent_edge_marks(theme, tmp_path):
    qt = qt_app()
    qt.setStyleSheet(style_for_theme("", theme))
    app = runtime(AppConfig(auto_connect=False))
    window = DesktopWindow(app)
    try:
        assert window.windowTitle() == "HA Windows Bridge"
        sidebar = window.findChild(QFrame, "sidebar")
        texts = {label.text() for label in sidebar.findChildren(QLabel)}
        assert "HA Windows Bridge" not in texts
        assert not any("wersja rozwojowa" in text for text in texts)
        style = qt.styleSheet()
        assert "border-left: 3px" not in style
        assert "border-bottom: 1px solid" not in style
        window.application.config.mqtt.host = "broker.local"
        window._connection_states["mqtt"] = SimpleNamespace(state="connected", error="")
        window._refresh_status()
        assert "#43c982" in window.summary.text() and "●" in window.summary.text()
        window.resize(1000, 760)
        window.show()
        qt.processEvents()
        assert window.grab().save(str(tmp_path / f"overview-clean-{theme}.png"))
    finally:
        window._force_close = True
        window.close()
        assert app.shutdown()


def test_blur_uses_one_rounded_composited_surface_without_native_layer(monkeypatch):
    qt = qt_app()
    qt.setProperty("bridgePopupAnimation", "slide")
    options = validated_request("Tytuł", "Treść", {"background_effect": "blur"})
    window = NotificationWindow(options)
    applied = []
    rounded = []
    window._backdrop.apply_blur = lambda hwnd: applied.append(hwnd) or True
    monkeypatch.setattr(NativeBackdrop, "apply_rounded_region", lambda hwnd, radius=14: rounded.append((hwnd, radius)) or True)
    try:
        assert not applied
        window.place(QPoint(0, 0), appearing=True)
        assert not applied
        assert window.mask().contains(window.rect().center())
        assert not window.mask().contains(QPoint(0, 0))
        QTest.qWait(25)
        qt.processEvents()
        assert not applied
        assert window._backdrop.backend == "none"
        assert rounded and all(radius == 14 for _hwnd, radius in rounded)
    finally:
        window.dispose()


def test_glass_is_ready_before_first_animated_frame(monkeypatch):
    qt = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: True))
    qt.setProperty("bridgePopupAnimation", "slide")
    qt.setProperty("bridgePopupAnimationDuration", 700)
    window = NotificationWindow(validated_request("Tytuł", "Treść", {"background_effect": "blur"}))
    renderer = GlassRenderer({"staged": window}, logging.getLogger("test.glass"))
    try:
        target = QPoint(20, 20)
        window.stage(target, qt.primaryScreen())
        assert window._awaiting_glass and not window.isVisible()
        screen = window.screen()
        region = window.geometry().translated(-screen.geometry().topLeft())
        key = ("staged", int(window.winId()), region.x(), region.y(), region.width(), region.height(), screen.name())
        background = QImage(320, 240, QImage.Format.Format_RGBA8888)
        background.fill(QColor("#38506b"))
        renderer._accept((0, [(key, background)], [key]), 5)
        assert window.isVisible() and not window._awaiting_glass
        assert not window._glass_image.isNull()
        assert not window._intro_snapshot.isNull()
        assert window.mask().contains(window.rect().center())
        assert not window.mask().contains(QPoint(0, 0))
        QTest.qWait(10)
        assert window._animation.state().name == "Running"
        assert window.windowOpacity() == 1
        assert not window.mask().contains(QPoint(0, 0))
    finally:
        renderer.close()
        window.dispose()
        qt.setProperty("bridgePopupAnimationDuration", 220)


def test_service_stages_a_new_glass_popup_before_showing_it(monkeypatch):
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False))
    overlays = OverlayService(app)
    try:
        monkeypatch.setattr(overlays.glass, "can_prime", lambda: True)
        monkeypatch.setattr(overlays.glass, "sync", lambda: None)
        overlays.engine.submit({"title": "Szkło", "message": "Gotowe przed animacją", "data": {
            "id": "prime-first-frame", "background_effect": "liquid",
        }})
        overlays._sync()
        window = overlays.windows["prime-first-frame"]
        assert window._awaiting_glass
        assert not window.isVisible()
        assert window._target == window.pos()
    finally:
        overlays.close()
        assert app.shutdown()
        qt.processEvents()


def test_liquid_glass_has_a_distinct_surface_from_regular_blur():
    qt = qt_app()
    background = QImage(320, 240, QImage.Format.Format_RGBA8888)
    for x in range(background.width()):
        background.fill(QColor("#24374e")) if x == 0 else None
        for y in range(background.height()):
            background.setPixelColor(x, y, QColor(30 + x // 3, 45 + y // 5, 80 + x // 5))
    frames = []
    windows = []
    try:
        for effect in ("blur", "liquid"):
            window = NotificationWindow(validated_request("Szkło", "Podgląd", {"background_effect": effect}))
            windows.append(window)
            window.set_glass_image(background)
            window.show()
            qt.processEvents()
            frames.append(window.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888))
        assert frames[0].size() == frames[1].size()
        assert bytes(frames[0].constBits()) != bytes(frames[1].constBits())
    finally:
        for window in windows:
            window.dispose()


def test_fade_animates_a_complete_flattened_popup_frame(monkeypatch, tmp_path):
    qt = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: True))
    qt.setProperty("bridgePopupAnimation", "fade")
    qt.setProperty("bridgePopupAnimationDuration", 700)
    options = validated_request("Tytuł", "Treść", {"background_effect": "blur"})
    window = NotificationWindow(options)
    try:
        window.place(QPoint(0, 0), appearing=True)
        assert not window._intro_snapshot.isNull()
        assert window.title.isHidden() and window.message.isHidden()
        qt.processEvents()
        window._animation.setCurrentTime(350)
        assert window.grab().save(str(tmp_path / "fade-mid-frame.png"))
        window._animation.setCurrentTime(700)
        qt.processEvents()
        assert window._intro_snapshot.isNull()
        assert window.title.isVisible() and window.message.isVisible()
    finally:
        window.dispose()
        qt.setProperty("bridgePopupAnimation", "slide")
        qt.setProperty("bridgePopupAnimationDuration", 220)


@pytest.mark.parametrize("animation", ["slide", "fade", "reveal", "none"])
def test_live_refresh_preserves_animation_and_stops_polling_when_dismissed(animation, monkeypatch):
    qt = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: True))
    app = runtime(AppConfig(auto_connect=False, overlay_animation=animation, overlay_animation_duration=700))
    overlays = OverlayService(app)
    try:
        payload = windows_media_payload(MediaSnapshot(title="Song", source_app="Player", state="playing", duration=200, position=10))
        payload["data"]["id"] = "live-animation"
        overlays.engine.submit(payload)
        overlays._sync()
        window = overlays.windows["live-animation"]
        transition = window._animation
        qt.processEvents()
        assert overlays.media_timer.isActive()
        if animation == "none":
            assert transition is None
        else:
            assert transition.duration() == 700
            transition.setCurrentTime(180)
        payload["data"].update(media_playing=False, media_position=60)
        overlays.engine.refresh_media(payload)
        overlays._sync()
        assert window._animation is transition
        assert window.media_time.text() == "1:00 / 3:20"
        if transition:
            transition.setCurrentTime(700)
            assert window.mask().contains(window.rect().center())
            assert not window.mask().contains(QPoint(0, 0))
            assert window.windowOpacity() == 1
        overlays._dismiss("live-animation")
        assert not overlays.media_timer.isActive()
        if animation != "none":
            assert window._animation.duration() == 700
        assert not overlays.glass.timer.isActive()
    finally:
        overlays.close()
        assert app.shutdown()
        qt.setProperty("bridgePopupAnimation", "slide")
        qt.setProperty("bridgePopupAnimationDuration", 220)
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_glass_blurs_and_bounds_pixels_and_uses_a_different_surface(tmp_path):
    qt = qt_app()
    image = QImage(640, 300, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#203a70"))
    for x in range(320,640):
        for y in range(300):
            image.setPixelColor(x,y,QColor("#efa343"))
    blurred, digest = blur_scene(image)
    assert blurred.width() <= 320 and blurred.height() <= 240
    center = blurred.pixelColor(blurred.width()//2,blurred.height()//2)
    assert center != QColor("#203a70") and center != QColor("#efa343")
    assert digest == blur_scene(image)[1]
    options = validated_request("Liquid Glass", "Rozmyte tło", {"background_effect":"liquid", "preset":"success"})
    window = NotificationWindow(options)
    try:
        window.set_glass_image(blurred)
        window.place(QPoint(0,0), appearing=True)
        qt.processEvents()
        assert window.grab().save(str(tmp_path / "liquid-glass.png"))
    finally:
        window.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
