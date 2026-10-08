from __future__ import annotations

import copy
import time
from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QPushButton
from test_phase5_gui_ux import close_window
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.audio import AudioProviderSnapshot, AudioSessionSnapshot
from ha_windows_bridge.communication.state import ConnectionState, ConnectionStatus
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.core.state import ProviderSample, StateQuality
from ha_windows_bridge.ui.shell import PAGES, DesktopWindow, Page
from ha_windows_bridge.ui_components import AppCard


def test_simplified_pages_and_connection_test():
    qt = qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, control_master_volume=False)))
    try:
        window.show()
        qt.processEvents()
        assert PAGES == ("Przegląd", "Komputer", "Aplikacje", "Powiadomienia", "Ustawienia", "Diagnostyka")
        assert window.navigation.currentRow() == Page.OVERVIEW
        labels = [item.text() for item in window.findChildren(QLabel)]
        assert not any(text in labels for text in ("Zdrowie i świeżość", "Skonfigurowane funkcje", "Lokalny edytor", "Brak niezapisanych zmian"))
        overlay = window.pages.widget(Page.OVERLAYS)
        assert not overlay.findChildren(QPushButton)
        assert set(window._fields) & {"overlay_animation", "overlay_background_effect", "overlay_example_duration"} == set()
        window.connection_test.click()
        assert "Skonfiguruj" in window.connection_test_result.text()
        assert not window.status.isVisible()
    finally:
        close_window(window)


def test_export_refresh_keeps_scroll_even_when_report_changes(monkeypatch):
    qt = qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, control_master_volume=False)))
    try:
        window.navigation.setCurrentRow(Page.DIAGNOSTICS)
        window.show()
        qt.processEvents()
        report = copy.deepcopy(window.application.diagnostic_preview())
        report["padding"] = list(range(150))
        monkeypatch.setattr(window.application, "diagnostic_preview", lambda: report)
        window._refresh_status()
        scrollbar = window.diagnostic_preview.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        position = scrollbar.value()
        assert position > 0
        window._refresh_status()
        assert scrollbar.value() == position
        report["padding"][0] = 100
        window._refresh_status()
        assert scrollbar.value() == position
    finally:
        close_window(window)


def test_audio_refresh_retains_value_only_during_expected_poll_gap(monkeypatch):
    qt_app()
    config = AppConfig(auto_connect=False, control_master_volume=False, apps=[AudioAppConfig("Discord.exe", "Discord", "discord", True)])
    window = DesktopWindow(runtime(config))
    try:
        now = time.monotonic()
        sample = ProviderSample("audio", SimpleNamespace(applications=[SimpleNamespace(
            process_name="Discord.exe", executable_path="", volume=0.42, muted=False,
        )]), time.time(), now - 4, StateQuality.STALE, "freshness_deadline_exceeded")
        monkeypatch.setattr(window.application, "computer_snapshot", lambda: SimpleNamespace(provider=lambda _: sample))
        window._update_applications_from_state()
        assert window._cards[0].slider.value() == 42
        assert window._cards[0].slider.isEnabled()
        sample = replace(sample, quality=StateQuality.ERROR, detail="read_timeout")
        window._update_applications_from_state()
        assert not window._cards[0].slider.isEnabled()
        sample = replace(sample, quality=StateQuality.STALE, detail="freshness_deadline_exceeded", observed_monotonic=now - 60)
        window._update_applications_from_state()
        assert not window._cards[0].slider.isEnabled()
    finally:
        close_window(window)


def test_discord_upgrade_icon_resolution_preserves_authorized_launch_path(tmp_path, monkeypatch):
    qt_app()
    installed = tmp_path / "Discord" / "app-2.0" / "Discord.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"icon-test")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    original = str(tmp_path / "Discord" / "app-1.0" / "Discord.exe")
    card = AppCard(AudioAppConfig("Discord.exe", "Discord", "discord", True, executable_path=original, allow_remote_start=True))
    try:
        assert card._icon_path == str(installed)
        assert card.config.executable_path == original
        assert not card.avatar.pixmap().isNull()
        card.set_executable_icon("", update_config=False)
        assert not card.avatar.pixmap().isNull()
        assert card.config.executable_path == original
    finally:
        card.deleteLater()


def test_footer_connection_dot_and_no_feature_values():
    qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, control_master_volume=False, mqtt=MqttConfig(host="broker"))))
    try:
        window.application.computer_state.observe_provider("cpu_ram", SimpleNamespace(cpu_percent=23.5, ram_percent=47.0), generation=window.application._generation)
        assert not window.pages.widget(Page.COMPUTER).findChildren(QLabel, "dataLabel")
        for state, expected, color in (
            (ConnectionState.STOPPED, "Brak połączenia", "#899297"),
            (ConnectionState.CONNECTED, "Połączono", "#43c982"),
            (ConnectionState.AUTH_ERROR, "Awaria", "#e06c75"),
        ):
            window._connection_states["mqtt"] = ConnectionStatus("mqtt", state)
            window._refresh_status()
            assert window.connection_indicator.text() == "●"
            assert window.connection_indicator.toolTip().startswith(expected)
            assert color in window.connection_indicator.styleSheet()
    finally:
        close_window(window)


def test_volume_cards_are_on_applications_and_refresh_preserves_draft(monkeypatch):
    qt = qt_app()
    window = DesktopWindow(runtime(AppConfig(auto_connect=False, control_master_volume=True, control_active_app=True)))
    try:
        window.navigation.setCurrentRow(Page.APPLICATIONS)
        window.show()
        sample = AudioProviderSnapshot(active_process="Spotify.exe", sessions=(("spotify.exe", AudioSessionSnapshot(.35, False)),))
        window.application.computer_state.observe_audio_provider(sample, (.62, False), generation=window.application._generation)
        window._refresh_master_audio()
        qt.processEvents()
        assert window.pages.widget(Page.APPLICATIONS).isAncestorOf(window.master_audio)
        assert window.pages.widget(Page.APPLICATIONS).isAncestorOf(window.active_audio)
        assert not window.pages.widget(Page.COMPUTER).isAncestorOf(window.master_audio)
        assert window.master_audio.percent_label.text() == "62%"
        assert window.active_audio.percent_label.text() == "35%"
        assert window.active_audio.description_label.text() == "Spotify.exe"
        assert window.active_audio.slider.isEnabled()
        calls = []
        monkeypatch.setattr(window.application, "command", lambda *args: calls.append(args))
        window.active_audio.volume_requested.emit(48)
        assert calls == [("audio.active.volume", {"value": .48})]
        window.active_audio.enabled_switch.setChecked(False)
        before = copy.deepcopy(window.draft)
        window._refresh_master_audio()
        assert window.draft == before and not window.draft.control_active_app
        assert not window.active_audio.enabled_switch.isChecked()
        window._discard()
        assert window.active_audio.enabled_switch.isChecked()
        assert window.draft.control_active_app
    finally:
        close_window(window)


def test_known_application_icons_without_executable_paths():
    qt_app()
    for name in ("chrome.exe", "Spotify.exe", "Discord.exe"):
        card = AppCard(AudioAppConfig(name, name, name.replace(".", "_"), False))
        try:
            assert not card.avatar.pixmap().isNull()
            assert not card.config.executable_path
        finally:
            card.deleteLater()
