from __future__ import annotations

import json
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.audio import AudioApplication
from ha_windows_bridge.config import AppConfig, AudioAppConfig
from ha_windows_bridge.core.events import Event
from ha_windows_bridge.overlays.examples import media_example
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.ui.shell import DesktopWindow, Page
from ha_windows_bridge.ui_components import ToggleSwitch
from ha_windows_bridge.windows.resources import ProcessResources


def test_ha_manifest_has_hassfest_key_order():
    manifest = json.loads((Path(__file__).parents[1] / "custom_components/ha_windows_bridge/manifest.json").read_text(encoding="utf-8"))
    assert list(manifest)[:2] == ["domain", "name"]
    assert list(manifest)[2:] == sorted(list(manifest)[2:])


def test_toggle_mouse_focus_has_no_second_outline_but_keyboard_keeps_focus():
    qt = qt_app()
    toggle = ToggleSwitch()
    toggle.show()
    try:
        QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
        qt.processEvents()
        assert toggle.isChecked()
        assert not toggle._focus_visible
        qt.sendEvent(toggle, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        assert toggle._focus_visible
    finally:
        toggle.close()
        toggle.deleteLater()


def test_media_background_is_painted_and_bars_are_thin(tmp_path):
    qt = qt_app()
    example = media_example()
    window = NotificationWindow(validated_request(example["title"], example["message"], example["data"]))
    try:
        window.show()
        qt.processEvents()
        assert not window._media_image.isNull()
        assert window.source.text() == "PC Media Player"
        assert window.media_time.text() == "1:05 / 3:42"
        assert window.progress.height() == 3
        assert window.lifetime.height() == 2
        assert window.progress.value() == 29
        frame = window.grab().toImage()
        ratio = window.devicePixelRatioF()
        assert frame.pixelColor(int(window.width() / 2 * ratio), int(5 * ratio)).alpha() > 220
        assert frame.pixelColor(0, 0).alpha() < 50
        assert frame.save(str(tmp_path / "media-card.png"))
        window.set_media_position(75, 222)
        assert window.media_time.text() == "1:15 / 3:42"
        window.update_notification(validated_request("Title", "Message", {"layout": "compact", "show_lifetime": True}))
        qt.processEvents()
        assert window._media_image.isNull()
        assert window.height() < 140
    finally:
        window.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_application_discovery_preserves_permissions_icons_and_alignment(tmp_path):
    qt = qt_app()
    config = AppConfig(auto_connect=False, apps=[AudioAppConfig("chrome.exe", "Chrome", "chrome", True)])
    application = runtime(config)
    application.audio = SimpleNamespace(list_audio_applications=lambda **_: [])
    window = DesktopWindow(application)
    application.request_inventory = lambda _kind: False
    try:
        window.resize(820, 620)
        window.show()
        window.navigation.setCurrentRow(Page.APPLICATIONS)
        qt.processEvents()
        window._update_applications([AudioApplication("chrome.exe", "Chrome", sys.executable, .42, False),
                                     AudioApplication("player.exe", "Player", "", .6, True)])
        qt.processEvents()
        assert len(window._cards) == 2
        card, detected = window._cards
        assert card.config.executable_path == sys.executable
        assert not card.avatar.pixmap().isNull()
        assert card.percent_label.text() == "42%"
        assert not detected.enabled_switch.isChecked()
        assert not detected.config.allow_remote_start
        assert not detected.config.allow_remote_close
        window._event(Event("audio.snapshot", {}))
        assert card.percent_label.text() == "42%"
        centers = [widget.geometry().center().y() for widget in
                   (card.slider, card.percent_label, card.mute_button, card.enabled_switch, card.more_button)]
        assert max(centers) - min(centers) <= 1
        assert window.pages.widget(Page.APPLICATIONS).horizontalScrollBar().maximum() == 0
        assert window.grab().save(str(tmp_path / "applications.png"))
        window._update_applications([AudioApplication("PLAYER.EXE", "Player", "", .7, False)])
        assert len(window._cards) == 2
        assert not card.slider.isEnabled()  # its audio session disappeared
        window.navigation.setCurrentRow(Page.DIAGNOSTICS)
        qt.processEvents()
        window._event(Event("resources.updated", {"cpu_percent": 1.2, "memory_mib": 85.3, "threads": 8}))
        assert "CPU: 1.2%" in window.resource_usage.text()
        assert window._page_timer.isActive()
        window.hide()
        assert not window._page_timer.isActive()
        assert "minimize_to_tray" not in window._toggles
        assert window.theme.accessibleName() == "Motyw"
        assert all("Ty decydujesz" not in label.text() for label in window.findChildren(QLabel))
    finally:
        window._force_close = True
        window.close()
        assert application.shutdown()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_resource_cpu_is_machine_normalized_and_sampling_is_cached():
    now, total = [10.0], [1.0]
    process = SimpleNamespace(oneshot=nullcontext, cpu_times=lambda: SimpleNamespace(user=total[0], system=0),
                              memory_info=lambda: SimpleNamespace(rss=64 * 1024**2), num_threads=lambda: 7)
    meter = ProcessResources(process, clock=lambda: now[0], cpu_count=4)
    assert meter.sample() == {"cpu_percent": None, "memory_mib": 64.0, "threads": 7}
    total[0] = 2
    now[0] = 10.5
    assert meter.sample()["cpu_percent"] is None
    now[0] = 12
    assert meter.sample()["cpu_percent"] == 12.5


def test_inventory_coalesces_requests_and_works_without_mqtt():
    app = runtime(AppConfig(auto_connect=False))
    entered, release, received = threading.Event(), threading.Event(), threading.Event()
    def scan(**_kwargs):
        entered.set()
        assert release.wait(2)
        return [AudioApplication("a.exe", "A")]
    app.audio = SimpleNamespace(list_audio_applications=scan)
    app.events.subscribe("inventory.applications", lambda event: received.set())
    try:
        assert app.request_inventory("applications")
        assert entered.wait(2)
        assert not app.request_inventory("applications")
        release.set()
        assert received.wait(2)
    finally:
        release.set()
        assert app.shutdown()
