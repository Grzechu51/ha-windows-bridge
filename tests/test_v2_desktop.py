from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from test_phase1_core import FakeGateway, wait_until
from test_phase1_core import application as phase1_application
from test_v2_application import runtime

from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.discovery import master_volume_topics
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.ui.control_style import BridgeProxyStyle
from ha_windows_bridge.ui.shell import PAGES, DesktopWindow
from ha_windows_bridge.ui.theme import style_for_theme


def qt_app():
    app = QApplication.instance() or QApplication([])
    for filename in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename))
    app.setFont(QFont("Segoe UI", 10))
    if not app.property("testFontsLoaded"):
        app.setStyle(BridgeProxyStyle(app.style()))
        app.setProperty("testFontsLoaded", True)
    app.setStyleSheet(style_for_theme("", "dark"))
    return app


def test_new_shell_uses_application_and_has_independent_status_pages(tmp_path):
    qt = qt_app()
    application = runtime(AppConfig(auto_connect=False, control_master_volume=False))
    window = DesktopWindow(application)
    try:
        window.resize(1000, 760)
        window.show()
        qt.processEvents()
        assert window.pages.count() == 6
        assert not hasattr(window, "bridge")
        assert not hasattr(window, "direct_bridge")
        for page in range(len(PAGES)):
            window.navigation.setCurrentRow(page)
            qt.processEvents()
            assert window.pages.currentIndex() == page
            assert window.grab().save(str(tmp_path / f"v2-page-{page}.png"))
        window.navigation.setCurrentRow(0)
        artifact = os.environ.get("BRIDGE_LAYOUT_ARTIFACTS")
        if artifact:
            folder = Path(artifact)
            folder.mkdir(parents=True, exist_ok=True)
            assert window.grab().save(str(folder / "v2-dashboard.png"))
    finally:
        window._force_close = True
        window.close()
        window.deleteLater()
        assert application.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_new_overlay_badges_are_content_sized_spaced_and_cleaned():
    qt = qt_app()
    application = runtime(AppConfig(auto_connect=False, control_master_volume=False))
    overlays = OverlayService(application)
    try:
        overlays.example("badges")
        qt.processEvents()
        assert len(overlays.windows) == 3
        windows = sorted(overlays.windows.values(), key=lambda window: window.x())
        assert all(window.width() <= 200 for window in windows)
        assert windows[1].x() - windows[0].geometry().right() >= 10
        assert windows[2].x() - windows[1].geometry().right() >= 10
        assert any(window.message.text() == "88%" for window in windows)
        assert sum(not window.icon.pixmap().isNull() for window in windows) == 2
        overlays.engine.submit({"data": {"action": "clear"}})
        overlays._sync()
        assert not overlays.timer.isActive()
        assert not overlays.windows
    finally:
        overlays.close()
        assert application.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_master_audio_gui_windows_and_ha_use_one_computer_state():
    qt = qt_app()
    FakeGateway.instances.clear()
    application = phase1_application()
    window = DesktopWindow(application)
    try:
        assert application.start()
        assert wait_until(lambda: application.computer_snapshot().master_audio is not None)
        qt.processEvents()
        window._refresh_master_audio()
        assert window.master_audio.slider.value() == 20
        assert window.master_audio.slider.isEnabled()

        window.master_audio.volume_requested.emit(61)
        window.master_audio.mute_requested.emit(True)
        assert wait_until(
            lambda: application.computer_snapshot().master_audio.volume == .61
            and application.computer_snapshot().master_audio.muted
        )
        qt.processEvents()
        window._refresh_master_audio()
        assert window.master_audio.percent_label.text() == "61%"
        assert window.master_audio.mute_button.isChecked()
        topic = master_volume_topics(application.config)[1]
        assert any(
            sent_topic == topic and payload == "61"
            for sent_topic, payload, _kwargs in FakeGateway.instances[-1].transport.sent
        )
    finally:
        window._force_close = True
        window.close()
        window.deleteLater()
        assert application.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
