from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QToolTip
from test_phase5_gui_ux import close_window
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.ui.motion import MotionSystem
from ha_windows_bridge.ui.shell import DesktopWindow, Page
from ha_windows_bridge.ui.theme import PALETTES


def test_all_volume_cards_have_matching_slider_columns_and_heights():
    qt = qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, apps=[
        AudioAppConfig("chrome.exe", "Chrome", "chrome", True),
    ])))
    try:
        window.resize(1040, 760)
        window.active_audio.description_label.setText("Spotify.exe")
        window.navigation.setCurrentRow(Page.APPLICATIONS)
        window.show()
        qt.processEvents()
        cards = [window.master_audio, window.active_audio, window._cards[0]]
        positions = [card.slider.mapTo(window, QPoint()).x() for card in cards]
        assert len(set(positions)) == 1
        assert len({card.slider.width() for card in cards}) == 1
        assert len({card.height() for card in cards}) == 1
        assert len({card.slider.height() for card in cards}) == 1
        assert not window._cards[0].local_result.isVisible()
    finally:
        close_window(window)


def test_connection_tooltip_uses_normal_text_font_and_color():
    qt = qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, mqtt=MqttConfig(host="broker"))))
    try:
        window.show()
        window._refresh_status()
        qt.processEvents()
        dot = window.connection_indicator
        QToolTip.showText(dot.mapToGlobal(QPoint(0, 0)), dot.toolTip(), dot)
        qt.processEvents()
        tooltip = next(widget for widget in qt.topLevelWidgets() if widget.metaObject().className() == "QTipLabel")
        assert tooltip.font().family() == "Segoe UI"
        assert tooltip.font().pointSize() == 10
        assert tooltip.palette().color(QPalette.ColorRole.WindowText).name() == PALETTES["dark"].text
        assert not any(label.text() == "Stan runtime" for label in window.findChildren(QLabel))
        assert not hasattr(window, "diagnostic_status")
    finally:
        QToolTip.hideText()
        close_window(window)


def test_animation_preserves_surface_alpha(monkeypatch):
    qt = qt_app()
    monkeypatch.setattr(MotionSystem, "enabled", staticmethod(lambda: True))
    qt.setProperty("bridgePopupAnimation", "slide")
    qt.setProperty("bridgePopupAnimationDuration", 1000)
    window = NotificationWindow(validated_request("Title", "Text", {"opacity": .35}))
    try:
        window.show()
        qt.processEvents()
        point = QPoint(30, window.height() - 9)
        before = window.grab().toImage().pixelColor(point).alpha()
        assert 50 < before < 140
        window.place(QPoint(50, 50), appearing=True)
        qt.processEvents()
        window._animation.setCurrentTime(500)
        during = window.grab().toImage().pixelColor(point).alpha()
        assert abs(before - during) <= 2
        window._animation.setCurrentTime(1000)
        after = window.grab().toImage().pixelColor(point).alpha()
        assert abs(before - after) <= 2
    finally:
        window.dispose()
        qt.setProperty("bridgePopupAnimationDuration", 220)


def test_reveal_has_rounded_corners_at_partial_width():
    qt_app()
    window = NotificationWindow(validated_request("Title", "Text", {}))
    try:
        region = window._reveal_region(.5, 1)
        bounds = region.boundingRect()
        assert not region.contains(bounds.topLeft())
        assert not region.contains(bounds.topRight())
        assert region.contains(bounds.center())
        assert region.contains(QPoint(bounds.left() + 14, bounds.top()))
    finally:
        window.dispose()


def test_media_timeline_is_adjacent_to_transport_controls():
    qt = qt_app()
    window = NotificationWindow(validated_request("Track", "Artist", {
        "layout": "media", "media_controls": True,
        "media_duration": 200, "media_position": 20, "show_lifetime": True,
    }))
    try:
        window.show()
        qt.processEvents()
        gap = window.media_time.y() - window.media_controls.geometry().bottom() - 1
        assert 0 <= gap <= 10
        for widget in (window.media_controls, window.media_time, window.progress, window.lifetime):
            assert window.rect().contains(widget.geometry())
        assert window.media_time.x() == window.title.x() == window.progress.x()
    finally:
        window.dispose()


@pytest.mark.parametrize("layout", ["auto", "badge", "media"])
def test_lifetime_bar_is_available_for_each_timed_layout(layout):
    qt = qt_app()
    window = NotificationWindow(validated_request("Title", "Text", {"layout": layout, "show_lifetime": True}))
    try:
        window.show()
        qt.processEvents()
        assert window.lifetime.isVisible()
        window.update_notification(validated_request("Title", "Text", {"layout": layout, "show_lifetime": True, "pinned": True}))
        assert window.lifetime.isHidden()
    finally:
        window.dispose()


def test_layout_editor_offers_distinct_layouts_and_visible_lifetime_switch():
    root = Path(__file__).parents[1] / "custom_components" / "ha_windows_bridge"
    services = yaml.safe_load((root / "services.yaml").read_text(encoding="utf-8"))
    fields = services["show_overlay"]["fields"]
    assert fields["content"]["fields"]["layout"]["selector"]["select"]["options"] == ["auto", "badge", "media"]
    assert fields["timing"]["collapsed"] is False
    assert fields["timing"]["fields"]["show_lifetime"]["selector"] == {"boolean": None}
    for path in (root / "strings.json", root / "translations" / "en.json", root / "translations" / "pl.json"):
        strings = json.loads(path.read_text(encoding="utf-8"))
        assert set(strings["selector"]["overlay_layout"]["options"]) == {"auto", "badge", "media"}
    for legacy in ("compact", "standard", "status", "camera"):
        options = validated_request("Title", "Text", {"layout": legacy})
        assert options["layout"] == "default"
        assert options["camera"] is (legacy == "camera")
    assert validated_request("Title", "Text", {"layout": "auto", "media_duration": 100})["layout"] == "media"
