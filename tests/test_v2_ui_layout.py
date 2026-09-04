from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.ui.shell import DesktopWindow
from ha_windows_bridge.ui.theme import style_for_theme


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_all_pages_fit_minimum_width_and_port_ignores_wheel(theme):
    qt = qt_app()
    qt.setProperty("bridgeTheme", theme)
    qt.setStyleSheet(style_for_theme("", theme))
    application = runtime(AppConfig(auto_connect=False, control_master_volume=False))
    window = DesktopWindow(application)
    try:
        window.resize(820, 620)
        window.show()
        for index in range(7):
            window.navigation.setCurrentRow(index)
            qt.processEvents()
            page = window.pages.widget(index)
            assert page.horizontalScrollBar().maximum() == 0, (theme, index)
        window.navigation.setCurrentRow(1)
        port = window._fields["mqtt.port"]
        before = port.value()
        wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        qt.sendEvent(port, wheel)
        assert port.value() == before
    finally:
        window._force_close = True
        window.close()
        assert application.shutdown()
        window.deleteLater()
        qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("layout", ["compact", "standard", "status", "badge", "media", "camera"])
def test_notification_grid_centers_icon_and_does_not_overlap_text(layout):
    qt = qt_app()
    options = validated_request("Home Assistant", "Wiadomość testowa", {"layout": layout, "icon": "mdi:home-assistant", "show_lifetime": True, "progress": 40})
    window = NotificationWindow(options)
    try:
        window.show()
        qt.processEvents()
        assert not window.icon.pixmap().isNull()
        assert window.rect().contains(window.message.geometry())
        assert not window.icon.geometry().intersects(window.message.geometry())
        if layout != "badge":
            assert not window.title.geometry().intersects(window.message.geometry())
            assert window.lifetime.isVisible()
        else:
            assert abs(window.icon.geometry().center().y() - window.message.geometry().center().y()) <= 1
    finally:
        window.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
