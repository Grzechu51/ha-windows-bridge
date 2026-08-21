from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QFileDialog, QLabel, QToolTip

from ha_windows_bridge.audio import AudioApplication
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.gui import MainWindow
from ha_windows_bridge.ui_components import AppCard, HelpButton


class FakeStore:
    config_path = Path("C:/Temp/HAWindowsBridge/config.json")
    data_dir = Path("C:/Temp/HAWindowsBridge")

    def save(self, _config) -> None:
        return None


class FakeStartup:
    def set_enabled(self, _enabled: bool) -> None:
        return None


def make_window(config: AppConfig | None = None) -> MainWindow:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        config or AppConfig(),
        FakeStore(),
        FakeStartup(),
        logging.getLogger(f"gui-test-{id(app)}-{id(config)}"),
    )
    app.processEvents()
    return window


def close_window(window: MainWindow) -> None:
    window._force_close = True
    window.tray.hide()
    window.close()


def test_gui_defaults_and_minimum_size() -> None:
    window = make_window()
    try:
        assert window.minimumWidth() >= 980
        assert "Integracja Windows" in window.title_bar.subtitle.text()
        assert window.pages.count() == 5
        assert len(window.nav_buttons) == 5
        assert all("Uruchamianie" not in button.text() for button in window.nav_buttons)
        assert window.master_volume_card is not None
        assert window.pages.widget(window.APPLICATIONS_PAGE).isAncestorOf(window.control_active_row)
        assert window.pages.widget(window.SETTINGS_PAGE).isAncestorOf(window.start_with_windows_row)
        assert window.pages.widget(window.SETTINGS_PAGE).isAncestorOf(window.status_card)
        assert window.start_with_windows_row.switch.isChecked()
        assert window.start_minimized_row.switch.isChecked()
        assert window.minimize_to_tray_row.switch.isChecked()
        assert window.auto_connect_row.switch.isChecked()
        assert window.pages.widget(window.FEATURES_PAGE).isAncestorOf(window.publish_activity_row)
        assert window.pages.widget(window.FEATURES_PAGE).isAncestorOf(window.media_player_row)
        assert not window.control_active_row.switch.isChecked()
        assert window.publish_initial_row.switch.isChecked()
        assert not window.publish_activity_row.switch.isChecked()
        assert not window.publish_idle_row.switch.isChecked()
        assert not window.publish_session_lock_row.switch.isChecked()
        assert not window.publish_system_stats_row.switch.isChecked()
        assert not window.publish_gpu_stats_row.switch.isChecked()
        assert not window.media_player_row.switch.isChecked()
        assert window.master_volume_card.enabled_switch.isChecked()
        assert not window.microphone_card.enabled_switch.isChecked()
        assert not window.audio_output_card.enabled_switch.isChecked()
        assert window.idle_threshold.value() == 300
        assert window.publish_initial_row.parentWidget().layout().spacing() == 12
        assert window.language_combo.parentWidget().parentWidget().layout().spacing() == 12
        assert window.resource_label.text().startswith("CPU ")
        assert window.port.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.keepalive.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.idle_threshold.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.poll_interval.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert not window.windowIcon().isNull()
        assert not window.uninstall_button.isEnabled()
        labels = [label.text() for label in window.findChildren(QLabel)]
        assert "Zaznacz opcje do zintegrowania z Home Assistant." not in labels
        assert "Dodatkowe dane z Windows." in labels
        assert "Wybierz programy, którymi chcesz sterować z Home Assistant." in labels
        assert not any(text.startswith("Każda włączona aplikacja") for text in labels)
    finally:
        close_window(window)


def test_detected_audio_application_is_added_unchecked() -> None:
    window = make_window()
    try:
        window._merge_audio_apps([AudioApplication("NewPlayer.exe", "New Player")])
        card = next(card for card in window.app_cards if card.config.process_name == "NewPlayer.exe")
        assert card.enabled_switch.isChecked() is False
        assert card.to_config().display_name == "New Player"
        assert card.more_button.menu() is None
        assert card.remote_start_action.isChecked() is False
        assert card.remote_close_action.isChecked() is False
    finally:
        close_window(window)


def test_legacy_hawn_topic_is_migrated_in_the_form() -> None:
    config = AppConfig(
        device_name="Gaming PC",
        mqtt=MqttConfig(host="broker", base_topic="hawn/desktop_123"),
    )
    config.auto_connect = False
    window = make_window(config)
    try:
        assert window.base_topic.text() == "ha-windows-bridge/gaming_pc"
        assert window.current_config.mqtt.base_topic == "ha-windows-bridge/gaming_pc"
    finally:
        close_window(window)


def test_device_name_updates_only_an_automatic_base_topic() -> None:
    window = make_window(AppConfig(device_name="Gaming PC"))
    try:
        window.device_name.textEdited.emit("Studio PC")
        assert window.base_topic.text() == "ha-windows-bridge/studio_pc"
        window.base_topic.textEdited.emit("my/custom/topic")
        window.base_topic.setText("my/custom/topic")
        window.device_name.textEdited.emit("Office PC")
        assert window.base_topic.text() == "my/custom/topic"
    finally:
        close_window(window)


def test_transparent_icon_margins_are_trimmed_before_scaling() -> None:
    QApplication.instance() or QApplication([])
    pixmap = QPixmap(100, 100)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.fillRect(46, 46, 8, 8, QColor("#5865f2"))
    painter.end()

    trimmed = AppCard._trim_transparent(pixmap)

    assert trimmed.width() < 20
    assert trimmed.height() < 20


def test_language_can_switch_without_rebuilding_the_window() -> None:
    window = make_window(AppConfig(language="en"))
    try:
        assert window.title_bar.subtitle.text().startswith("Windows integration")
        assert "Applications" in window.nav_buttons[1].text()
        assert window.language_combo.currentData() == "en"
        window.language_combo.setCurrentIndex(window.language_combo.findData("pl"))
        QApplication.processEvents()
        assert "Aplikacje" in window.nav_buttons[1].text()
    finally:
        close_window(window)


def test_disabled_app_stays_visibly_inactive_with_live_audio_session() -> None:
    window = make_window()
    try:
        card = window.app_cards[0]
        card.set_volume(0.5)
        card.set_muted(False)
        assert not card.enabled_switch.isChecked()
        assert not card.slider.isEnabled()
        assert not card.mute_button.isEnabled()
        card.enabled_switch.setChecked(True)
        QApplication.processEvents()
        assert card.slider.isEnabled()
        assert card.mute_button.isEnabled()
        assert window.microphone_card.slider.width() == window.master_volume_card.slider.width()
        assert window.audio_cards_layout.spacing() == 12
        assert window.cards_layout.spacing() == 12
    finally:
        close_window(window)


def test_remote_start_prompts_for_executable_when_path_is_unknown(monkeypatch, tmp_path) -> None:
    QApplication.instance() or QApplication([])
    executable = tmp_path / "Player.exe"
    executable.write_bytes(b"")
    card = AppCard(AudioAppConfig("Player.exe", "Player", "player", False))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(executable), "Programy Windows (*.exe)"),
    )

    assert card.remote_start_action.isEnabled()
    card.remote_start_action.setChecked(True)

    assert card.remote_start_action.isChecked()
    assert card.to_config().allow_remote_start is True
    assert card.to_config().executable_path == str(executable)


def test_save_button_shows_temporary_confirmation() -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), auto_connect=False)
    window = make_window(config)
    try:
        assert window.save_and_apply()
        assert window.save_button.text() == "✓ Zapisano"
        assert window.save_button.property("saved") is True
        window._reset_save_button()
        assert window.save_button.text() == "Zapisz i zastosuj"
    finally:
        close_window(window)


def test_help_button_shows_explanation_on_demand(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda *args: shown.append(args[1]))
    button = HelpButton("Pełne objaśnienie opcji")

    button.show_help()

    assert shown == ["Pełne objaśnienie opcji"]


def test_resource_indicator_matches_total_cpu_and_private_memory() -> None:
    class Process:
        @staticmethod
        def cpu_percent(interval=None):
            return 24.0

        @staticmethod
        def memory_full_info():
            return SimpleNamespace(uss=64 * 1024 * 1024)

    window = make_window()
    try:
        window._self_process = Process()
        window._cpu_count = 12
        window._refresh_resource_usage()

        assert window.resource_bar.value() == 2
        assert window.resource_label.text() == "CPU 2,0% · RAM 64 MB"
        assert window.resource_bar.width() == 34
    finally:
        close_window(window)
