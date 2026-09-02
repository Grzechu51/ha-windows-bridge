from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
    QToolTip,
)

from ha_windows_bridge.audio import AudioApplication
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.gui import MainWindow, MdiIconDialog
from ha_windows_bridge.overlay import OverlayCard, OverlayManager
from ha_windows_bridge.system_monitor import PnpDevice
from ha_windows_bridge.ui_components import AppCard, HelpButton, LabeledToggle


def wait_for_qt_condition(
    predicate: Callable[[], bool], timeout_ms: int = 2_000, interval_ms: int = 20
) -> bool:
    attempts = max(1, (timeout_ms + interval_ms - 1) // interval_ms)
    for _ in range(attempts):
        if predicate():
            return True
        QTest.qWait(interval_ms)
    return predicate()


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
        assert window.feature_tabs.widget(2).isAncestorOf(window.media_player_row)
        assert not window.feature_tabs.widget(0).isAncestorOf(window.media_player_row)
        assert not window.control_active_row.switch.isChecked()
        assert window.publish_initial_row.switch.isChecked()
        assert not window.publish_activity_row.switch.isChecked()
        assert not window.publish_idle_row.switch.isChecked()
        assert not window.publish_session_lock_row.switch.isChecked()
        assert not window.publish_ram_stats_row.switch.isChecked()
        assert not window.publish_cpu_stats_row.switch.isChecked()
        assert not window.publish_gpu_stats_row.switch.isChecked()
        assert not window.media_player_row.switch.isChecked()
        assert window.master_volume_card.enabled_switch.isChecked()
        assert not window.microphone_card.enabled_switch.isChecked()
        assert not window.audio_output_card.enabled_switch.isChecked()
        assert window.idle_threshold.value() == 300
        assert window.publish_initial_row.parentWidget().layout().spacing() == 12
        assert window.language_combo.parentWidget().parentWidget().layout().spacing() == 12
        assert window.theme_combo.currentData() == "dark"
        assert window.resource_label.text().startswith("CPU ")
        assert window.port.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.keepalive.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.idle_threshold.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert window.poll_interval.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        assert not window.windowIcon().isNull()
        assert not window.uninstall_button.isEnabled()
        labels = [label.text() for label in window.findChildren(QLabel)]
        assert "Kod źródłowy i licencja" not in labels
        assert "Podgląd aktualizowany na żywo." not in labels
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
        card = next(
            card for card in window.app_cards if card.config.process_name == "NewPlayer.exe"
        )
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


def test_theme_can_switch_without_rebuilding_the_window() -> None:
    app = QApplication.instance() or QApplication([])
    changes: list[str] = []
    window = MainWindow(
        AppConfig(theme="light"),
        FakeStore(),
        FakeStartup(),
        logging.getLogger("gui-theme-test"),
        theme_changed=changes.append,
    )
    try:
        assert window.theme_combo.currentData() == "light"
        assert changes[-1] == "light"
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
        app.processEvents()
        assert changes[-1] == "dark"
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


def test_compact_settings_and_remote_features_are_localized() -> None:
    window = make_window(AppConfig(language="en", theme="light"))
    try:
        assert window.title_bar.status_dot.isHidden()
        assert window.title_bar.status_label.isHidden()
        assert window.language_combo.width() == 112
        assert window.theme_combo.width() == 112
        assert window.poll_interval.width() == 96
        assert not window.power_actions_row.switch.isChecked()
        assert not window.windows_notifications_row.switch.isChecked()
        assert window.pages.widget(window.FEATURES_PAGE).isAncestorOf(window.power_actions_row)
        assert window.power_actions_row.title_label.text() == "Safe system actions"
        assert window.windows_notifications_row.title_label.text() == "Windows notifications"
        assert window.mqtt_cleanup_button.text() == "Clean MQTT data"
        assert window.uninstall_button.text() == "Uninstall application"
    finally:
        close_window(window)


def test_audio_page_contains_only_current_audio_features() -> None:
    config = AppConfig(audio_enhancements_enabled=True)
    window = make_window(config)
    try:
        assert window.audio_enhancements_row.switch.isChecked()
        assert window.channel_balance_row.isEnabled()
        assert window.publish_audio_sessions_row.isEnabled()
        assert not hasattr(window, "audio_profiles_row")
        assert not hasattr(window, "audio_profiles_list")
    finally:
        close_window(window)


def test_overlay_defaults_and_device_filters_are_user_facing() -> None:
    config = AppConfig(overlay_enabled=True)
    window = make_window(config)
    try:
        saved = window._config_from_form()
        assert saved.overlay_monitor == 0
        assert not hasattr(saved, "overlay_show_close_button")
        assert not hasattr(window, "overlay_opacity")
        assert window.device_filter_combo.count() == 3
        assert window.device_filter_combo.itemText(1) == "Aktywne"

        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        assert manager.handle_message(
            "Don't encode this",
            "Plain <text>",
            {
                "id": "test",
                "preset": "warning",
                "pinned": True,
                "show_close_button": False,
                "close_on_click": True,
            },
        )
        QApplication.processEvents()
        assert manager._title.text() == "Don't encode this"
        assert manager._label.text() == "Plain <text>"
        assert "rgba(242, 184, 75, 165)" in manager._window.styleSheet()
        assert manager._icon.isHidden()
        assert manager._close_button.isHidden()
        QTest.mouseClick(manager._label, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert manager._current is None
    finally:
        close_window(window)


def test_overlay_renders_a_selected_home_assistant_mdi_icon() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        assert manager.handle_message(
            "Music", "Playing", {"id": "mdi", "icon": "mdi:music", "pinned": True}
        )
        QApplication.processEvents()

        assert not manager._icon.isHidden()
        assert manager._icon.pixmap() is not None
        assert not manager._icon.pixmap().isNull()
    finally:
        close_window(window)


def test_overlay_automatic_size_shrinks_after_manual_height() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        assert manager.handle_message(
            "Compact",
            "Short message",
            {
                "id": "compact",
                "size_mode": "manual",
                "width": 400,
                "height": 240,
                "pinned": True,
            },
        )
        QApplication.processEvents()
        assert manager._card.height() == 240

        assert manager.handle_message(
            "Compact",
            "Short message",
            {"action": "update", "id": "compact", "size_mode": "auto"},
        )
        QApplication.processEvents()
        assert 72 <= manager._card.height() < 120
        assert manager._window.height() == manager._card.height()
    finally:
        close_window(window)


def test_compact_overlay_aligns_short_message_with_title() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        manager._animations_allowed = False
        assert manager.handle_message(
            "Home Assistant",
            "Drzwi wejściowe zostały zamknięte.",
            {
                "id": "short-message",
                "icon": "mdi:door-closed",
                "layout": "compact",
                "pinned": True,
            },
        )
        QApplication.processEvents()

        assert manager._current["_resolved_layout"] == "compact"
        assert manager._label.contentsMargins().left() == 44
        assert manager._card.height() < 120
    finally:
        close_window(window)


def test_parallel_status_overlays_are_visible_updated_and_removed_side_by_side() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        manager._animations_allowed = False
        for message_id, title, value, progress in (
            ("battery", "Bateria", "78%", 78),
            ("cpu", "Procesor", "24%", 24),
            ("memory", "Pamięć RAM", "61%", 61),
        ):
            assert manager.handle_message(
                title,
                value,
                {
                    "id": message_id,
                    "display_mode": "parallel",
                    "layout": "status",
                    "channel": "system",
                    "progress": progress,
                    "pinned": True,
                },
            )
        QApplication.processEvents()

        children = list(manager._parallel_cards.values())
        assert len(children) == 3
        assert all(child._current["_resolved_layout"] == "status" for child in children)
        assert all(child._window.isVisible() for child in children)
        assert all(child._card.width() <= 220 for child in children)
        assert all(child._card.height() <= 72 for child in children)
        assert [child._window.x() for child in children] == sorted(
            (child._window.x() for child in children), reverse=True
        )
        assert len({child._window.y() for child in children}) == 1

        assert manager.handle_message(
            "Aktualizacja",
            "System działa prawidłowo.",
            {"id": "regular", "channel": "general", "pinned": True},
        )
        QApplication.processEvents()
        parallel_bottom = max(
            child._card.mapToGlobal(QPoint(0, 0)).y() + child._card.height()
            for child in children
        )
        regular_top = manager._card.mapToGlobal(QPoint(0, 0)).y()
        assert regular_top >= parallel_bottom + 10

        cpu = manager._parallel_cards["cpu"]
        assert manager.handle_message(
            "", "42%", {"action": "update", "id": "cpu", "progress": 42}
        )
        QApplication.processEvents()
        assert cpu._label.text() == "42%"
        assert cpu._progress.value() == 42

        assert manager.handle_message("", "", {"action": "remove", "id": "cpu"})
        QApplication.processEvents()
        assert "cpu" not in manager._parallel_cards
        assert manager.handle_message("", "", {"action": "clear", "channel": "system"})
        QApplication.processEvents()
        assert not manager._parallel_cards
    finally:
        close_window(window)


def test_parallel_status_animation_preserves_the_visual_gap_on_first_show() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        manager._animations_allowed = True
        assert manager.show_test_pattern("parallel")

        def visible_gaps() -> list[int]:
            cards = sorted(
                (
                    QRect(child._card.mapToGlobal(QPoint(0, 0)), child._card.size())
                    for child in manager._parallel_cards.values()
                ),
                key=QRect.left,
            )
            return [cards[index + 1].left() - cards[index].right() - 1 for index in range(2)]

        QTest.qWait(120)
        assert all(gap >= 10 for gap in visible_gaps())
        QTest.qWait(520)
        assert all(gap >= 10 for gap in visible_gaps())
        assert all(child._lifetime_progress.isHidden() for child in manager._parallel_cards.values())
    finally:
        close_window(window)


def test_indicator_strip_renders_small_icon_value_and_image_badges() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        manager._animations_allowed = False
        assert manager.show_test_pattern("badges")
        QApplication.processEvents()

        badges = list(manager._parallel_cards.values())
        assert len(badges) == 4
        assert all(child._current["_resolved_layout"] == "badge" for child in badges)
        assert all(child._card.width() <= 180 for child in badges)
        assert all(child._card.height() <= 44 for child in badges)
        assert all(child._progress.isHidden() for child in badges)
        assert all(child._lifetime_progress.isHidden() for child in badges)
        assert manager._parallel_cards["local-test-badge-battery"]._title.text() == "88%"
        battery = manager._parallel_cards["local-test-badge-battery"]
        battery_center = battery._card.rect().center().y()
        icon_center = (
            battery._icon.mapTo(battery._card, QPoint(0, 0)).y()
            + battery._icon.height() // 2
        )
        title_center = (
            battery._title.mapTo(battery._card, QPoint(0, 0)).y()
            + battery._title.height() // 2
        )
        assert abs(icon_center - battery_center) <= 1
        assert abs(title_center - battery_center) <= 1
        light = manager._parallel_cards["local-test-badge-light"]
        assert light._title.isHidden()
        assert not light._icon.isHidden()
        assert "border: 1px solid transparent" in light._window.styleSheet()
        assert "background: transparent; border: 1px solid rgba" in light._window.styleSheet()
        assert ", 0); border-radius" in light._window.styleSheet()

        artwork = QPixmap(32, 32)
        artwork.fill(QColor("#7a4ea3"))
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert artwork.save(buffer, "PNG")
        buffer.close()
        image = "data:image/png;base64," + bytes(encoded.toBase64()).decode("ascii")
        assert manager.handle_message(
            "",
            "",
            {
                "action": "update",
                "id": "local-test-badge-person",
                "image": image,
            },
        )
        QApplication.processEvents()
        person = manager._parallel_cards["local-test-badge-person"]
        assert person._image.isHidden()
        assert person._icon.pixmap() is not None
        assert not person._icon.pixmap().isNull()
    finally:
        close_window(window)


def test_overlay_designer_previews_and_persists_a_local_template() -> None:
    window = make_window(
        AppConfig(
            mqtt=MqttConfig(host="broker"),
            overlay_enabled=True,
            auto_connect=False,
        )
    )
    try:
        window.overlay_template_title.setText("Live title")
        window.overlay_template_message.setPlainText("Live message")
        window.overlay_template_effect.setCurrentIndex(
            window.overlay_template_effect.findData("liquid")
        )
        window.overlay_template_opacity.setValue(35)
        QTest.qWait(380)

        assert window.overlay_preview_manager is not None
        assert window.overlay_preview_manager._current["title"] == "Live title"
        assert window.overlay_preview_manager._current["message"] == "Live message"
        assert window.overlay_preview_manager._current["opacity"] == 0.35
        assert window.overlay_template_opacity_slider.value() == 35
        assert window.overlay_preview_manager._lifetime_progress.isVisible()
        assert window.overlay_template_icon.currentText().startswith("mdi:")
        assert isinstance(window.overlay_template_pinned, LabeledToggle)
        assert isinstance(window.overlay_template_live, LabeledToggle)
        assert window.overlay_template_live.isChecked()
        initial_pinned = window.overlay_template_pinned.isChecked()
        QTest.mouseClick(
            window.overlay_template_pinned,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                window.overlay_template_pinned.width() - 4,
                window.overlay_template_pinned.height() // 2,
            ),
        )
        assert window.overlay_template_pinned.isChecked() is not initial_pinned
        slider = window.overlay_template_opacity_slider
        QTest.mouseClick(
            slider,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(slider.width() * 0.75), slider.height() // 2),
        )
        assert 73 <= window.overlay_template_opacity.value() <= 77
        ignored_wheels: list[bool] = []
        wheel = SimpleNamespace(ignore=lambda: ignored_wheels.append(True))
        window.overlay_template_opacity.wheelEvent(wheel)
        window.overlay_template_effect.wheelEvent(wheel)
        assert ignored_wheels == [True, True]
        assert 73 <= window.overlay_template_opacity.value() <= 77
        assert window.overlay_template_duration.buttonSymbols() == (
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        duration = window.overlay_template_duration.value()
        accepted_wheels: list[bool] = []
        guarded_wheel = SimpleNamespace(
            type=lambda: QEvent.Type.Wheel,
            angleDelta=lambda: QPoint(0, -120),
            accept=lambda: accepted_wheels.append(True),
        )
        assert window._settings_wheel_guard.eventFilter(
            window.overlay_template_duration, guarded_wheel
        )
        assert window.overlay_template_duration.value() == duration
        assert accepted_wheels == [True]

        window.overlay_template_live.setChecked(False)
        assert window.overlay_preview_manager is None

        window.overlay_template_name.setText("Widok testowy")
        window._save_overlay_template()

        assert window.current_config.overlay_templates[0].name == "Widok testowy"
        assert window.current_config.overlay_templates[0].title == "Live title"
        assert 0.73 <= window.current_config.overlay_templates[0].opacity <= 0.77
        assert window.current_config.selected_overlay_template_id == "powiadomienie"
    finally:
        close_window(window)


def test_mdi_picker_exposes_and_filters_the_complete_catalog() -> None:
    QApplication.instance() or QApplication([])
    dialog = MdiIconDialog("mdi:home-assistant")
    try:
        assert dialog.model.rowCount() > 7_000
        dialog.search.setText("battery")
        QApplication.processEvents()
        assert dialog.proxy.rowCount() > 10
        assert all(
            "battery" in str(dialog.proxy.index(row, 0).data()).casefold()
            for row in range(min(10, dialog.proxy.rowCount()))
        )
    finally:
        dialog.close()


def test_reset_defaults_preserves_connection_credentials(monkeypatch) -> None:
    config = AppConfig(
        device_name="Komputer testowy",
        device_id="desktop-test",
        mqtt=MqttConfig(host="broker.local", port=2883, username="ha", password="secret"),
        overlay_enabled=True,
        auto_connect=False,
        language="pl",
    )
    window = make_window(config)
    try:
        window.publish_cpu_stats_row.switch.setChecked(True)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(window, "start_bridge", lambda: None)

        window._reset_default_settings()

        assert window.current_config.device_name == "Komputer testowy"
        assert window.current_config.device_id == "desktop_test"
        assert window.current_config.mqtt.host == "broker.local"
        assert window.current_config.mqtt.port == 2883
        assert window.current_config.mqtt.username == "ha"
        assert window.current_config.mqtt.password == "secret"
        assert window.current_config.overlay_enabled is False
        assert window.current_config.publish_cpu_stats is False
    finally:
        close_window(window)


def test_direct_connection_device_id_can_be_copied() -> None:
    window = make_window()
    try:
        window._copy_device_id()
        assert QApplication.clipboard().text() == window.current_config.device_id
        assert window.copy_ha_device_id.text() == "Skopiowano"
    finally:
        close_window(window)


def test_media_overlay_uses_right_artwork_and_contrasting_palette() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        pixmap = QPixmap(40, 40)
        pixmap.fill(QColor("#256a4d"))
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert pixmap.save(buffer, "PNG")
        buffer.close()
        image = "data:image/png;base64," + bytes(encoded.toBase64()).decode("ascii")

        assert manager.handle_message(
            "Track",
            "Artist",
            {
                "id": "media-card",
                "layout": "media",
                "media_source": "PC Media Player",
                "image": image,
                "progress": 35,
                "pinned": True,
            },
        )
        QApplication.processEvents()

        assert manager._card._media_background is not None
        assert manager._cover.isHidden()
        assert manager._image.isHidden()
        assert manager._card.width() >= 480
        assert manager._card.height() >= 180
        assert manager._title.text() == "PC Media Player"
        assert manager._media_title.text() == "Track"
        assert manager._label.text() == "Artist"
        surface = manager._card._media_surface
        _, primary, secondary = manager._media_palette(pixmap)
        assert manager._contrast_ratio(primary, surface) >= 4.8
        assert manager._contrast_ratio(secondary, surface) >= 3.6
        assert "QLabel#overlayMediaTitle" in manager._window.styleSheet()

        square_rect = manager._card._right_artwork_rect(QSize(480, 180), QSize(400, 400))
        wide_rect = manager._card._right_artwork_rect(QSize(480, 180), QSize(1600, 900))
        assert square_rect == QRect(300, 0, 180, 180)
        assert wide_rect == QRect(160, 0, 320, 180)
    finally:
        close_window(window)


def test_media_background_blends_smoothly_into_complete_artwork() -> None:
    app = QApplication.instance() or QApplication([])
    card = OverlayCard()
    try:
        card.setFixedSize(480, 180)
        artwork = QPixmap(400, 400)
        artwork.fill(QColor("#205fe0"))
        card.set_media_background(artwork, QColor("#7d1f24"), 1.0)
        card.show()
        app.processEvents()

        rendered = card.grab().toImage()
        samples = [rendered.pixelColor(x, 90) for x in range(280, 451, 10)]
        channel_steps = [
            max(
                abs(current.red() - previous.red()),
                abs(current.green() - previous.green()),
                abs(current.blue() - previous.blue()),
            )
            for previous, current in zip(samples, samples[1:], strict=False)
        ]
        assert max(channel_steps) < 48
        assert rendered.pixelColor(300, 90).red() > 115
        assert rendered.pixelColor(450, 90).blue() > 200
    finally:
        card.close()


def test_gaussian_blur_softens_a_sharp_background_edge() -> None:
    app = QApplication.instance() or QApplication([])
    source = QPixmap(80, 40)
    source.fill(Qt.GlobalColor.black)
    painter = QPainter(source)
    painter.fillRect(QRect(40, 0, 40, 40), Qt.GlobalColor.white)
    painter.end()

    image = OverlayManager._blur_pixmap(source, 12).toImage()
    boundary = image.pixelColor(40, 20).red()
    assert 70 < boundary < 210
    assert image.pixelColor(28, 20).red() < boundary
    assert image.pixelColor(52, 20).red() > boundary
    app.processEvents()


def test_background_modes_and_media_do_not_leave_stale_layers(monkeypatch) -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True

        def capture(opacity: float, effect: str) -> bool:
            captured = QPixmap(manager._card.size())
            captured.fill(QColor("#557799"))
            manager._card.set_glass_background(captured, opacity, effect)
            return True

        monkeypatch.setattr(manager, "_capture_glass_background", capture)
        assert manager.handle_message(
            "Modes",
            "Test",
            {"id": "modes", "pinned": True, "background_effect": "blur"},
        )
        assert manager._card._glass_background is not None
        assert manager._card._glass_effect == "blur"

        assert manager.handle_message(
            "Modes",
            "Test",
            {
                "action": "update",
                "id": "modes",
                "background_effect": "liquid",
                "opacity": 0.83,
            },
        )
        assert manager._card._glass_effect == "liquid"
        assert manager._card._glass_opacity == 0.83

        artwork = QPixmap(40, 40)
        artwork.fill(QColor("#8f2430"))
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert artwork.save(buffer, "PNG")
        buffer.close()
        image = "data:image/png;base64," + bytes(encoded.toBase64()).decode("ascii")
        assert manager.handle_message(
            "Track",
            "Artist",
            {
                "action": "update",
                "id": "modes",
                "layout": "media",
                "image": image,
                "background_effect": "liquid",
            },
        )
        assert manager._card._media_background is not None
        assert manager._card._glass_background is None
        assert manager._card._glass_effect == "none"

        assert manager.handle_message(
            "Modes",
            "Test",
            {
                "action": "update",
                "id": "modes",
                "layout": "default",
                "image": "",
                "background_effect": "none",
            },
        )
        assert manager._card._media_background is None
        assert manager._card._glass_background is None
    finally:
        close_window(window)


def test_overlay_visible_card_is_flush_with_right_screen_edge() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        assert manager.handle_message("Edge", "Aligned", {"id": "edge", "pinned": True})
        QApplication.processEvents()

        area = QApplication.screens()[0].availableGeometry()
        card_right = manager._card.mapToGlobal(
            QPoint(manager._card.width() - 1, 0)
        ).x()
        assert card_right == area.right()

        assert manager.handle_message(
            "Edge",
            "Offset",
            {"action": "update", "id": "edge", "edge_offset": 24},
        )
        QApplication.processEvents()
        card_top_left = manager._card.mapToGlobal(QPoint(0, 0))
        assert card_top_left.x() + manager._card.width() - 1 == area.right() - 24
        assert card_top_left.y() == area.top() + 24
    finally:
        close_window(window)


def test_glass_backgrounds_refresh_and_liquid_falls_back(monkeypatch) -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        manager._liquid_compatible = True
        captures = 0
        effects: list[str] = []

        def capture(opacity: float, effect: str) -> bool:
            nonlocal captures
            captures += 1
            effects.append(effect)
            background = QPixmap(manager._card.size())
            background.fill(QColor("#203040"))
            manager._card.set_glass_background(background, opacity, effect)
            return True

        monkeypatch.setattr(manager, "_capture_glass_background", capture)
        assert manager.handle_message(
            "Glass",
            "Live background",
            {
                "id": "glass-live",
                "pinned": True,
                "background_effect": "liquid",
            },
        )
        initial_captures = captures
        assert wait_for_qt_condition(
            lambda: captures >= initial_captures + 2,
            timeout_ms=1_200,
        )
        assert manager._glass_timer.isActive()

        monkeypatch.setattr(manager, "_capture_glass_background", lambda *_args: False)
        manager._refresh_glass_background()
        manager._refresh_glass_background()
        assert manager._current["_effective_background_effect"] == "blur"
        assert manager._glass_timer.isActive()

        monkeypatch.setattr(manager, "_capture_glass_background", capture)
        captures_before_blur = captures
        QTest.qWait(350)
        assert captures > captures_before_blur
        assert effects[-1] == "blur"
    finally:
        close_window(window)


def test_standard_blur_refreshes_for_timed_messages(monkeypatch) -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        captures = 0

        def capture(opacity: float, effect: str) -> bool:
            nonlocal captures
            captures += 1
            background = QPixmap(manager._card.size())
            background.fill(QColor("#405060"))
            manager._card.set_glass_background(background, opacity, effect)
            return True

        monkeypatch.setattr(manager, "_capture_glass_background", capture)
        assert manager.handle_message(
            "Blur",
            "Live background",
            {"id": "blur-live", "duration": 2, "background_effect": "blur"},
        )
        initial_captures = captures
        # Qt's offscreen event dispatcher can coalesce timer wakes under load.  A full
        # second still verifies repeated refreshes without making the test scheduler-
        # dependent.
        QTest.qWait(1_050)
        assert captures >= initial_captures + 2
        assert manager._glass_timer.isActive()
    finally:
        close_window(window)


def test_liquid_glass_adapts_text_to_backdrop_luminance() -> None:
    window = make_window(AppConfig(overlay_enabled=True))
    try:
        manager = window.overlay_manager
        assert manager is not None
        manager.allow_fullscreen = True
        assert manager.handle_message("Readable", "Text", {"id": "contrast", "pinned": True})

        backdrop = QPixmap(manager._card.size())
        backdrop.fill(Qt.GlobalColor.white)
        manager._apply_adaptive_legibility(backdrop)
        assert manager._glass_text_mode == "dark"
        assert "#11191c" in manager._title.styleSheet()
        assert manager._card._text_scrim.alpha() > 0

        backdrop.fill(Qt.GlobalColor.black)
        manager._apply_adaptive_legibility(backdrop)
        assert manager._glass_text_mode == "light"
        assert "#f7fbfa" in manager._title.styleSheet()
    finally:
        close_window(window)


def test_overlay_animates_show_resize_and_hide_when_system_allows_it() -> None:
    QApplication.instance() or QApplication([])
    manager = OverlayManager()
    manager.allow_fullscreen = True
    manager._animations_allowed = True
    try:
        assert manager.handle_message(
            "Animation",
            "Initial",
            {
                "id": "animation",
                "pinned": True,
                "size_mode": "manual",
                "width": 420,
                "height": 180,
            },
        )
        assert manager._animation is not None
        assert manager._animation.duration() == 760
        assert manager._animation_offset_x == 14
        assert manager._animation_offset_y > 0
        assert manager._card.width() < round(420 * 0.7)
        assert manager._window.windowOpacity() == 1.0
        assert wait_for_qt_condition(lambda: manager._animation is None)
        assert manager._card.size() == QSize(420, 180)
        assert manager._window.windowOpacity() == 1.0

        assert manager.handle_message(
            "Animation",
            "Short",
            {"action": "update", "id": "animation", "size_mode": "auto"},
        )
        assert manager._animation is not None
        assert manager._animation.duration() == 500
        assert wait_for_qt_condition(lambda: manager._animation is None)
        assert manager._card.height() < 120

        manager.hide(show_next=False)
        assert manager._animation is not None
        assert manager._animation.duration() == 620
        start_width = manager._card.width()
        assert wait_for_qt_condition(
            lambda: manager._window.isVisible()
            and 0.0 < manager._window.windowOpacity() < 1.0
            and manager._card.width() < start_width,
            timeout_ms=450,
        )
        assert wait_for_qt_condition(manager._window.isHidden)
    finally:
        manager.close()


def test_device_filter_separates_active_and_inactive_devices() -> None:
    window = make_window()
    try:
        window._apply_scanned_devices(
            [
                PnpDevice("ACTIVE", "Connected headset", "AudioEndpoint", True),
                PnpDevice("INACTIVE", "Disconnected headset", "AudioEndpoint", False),
            ]
        )
        assert window.devices_list.count() == 2

        window.device_filter_combo.setCurrentIndex(window.device_filter_combo.findData("active"))
        QApplication.processEvents()
        assert not window.devices_list.item(0).isHidden()
        assert window.devices_list.item(1).isHidden()

        window.device_filter_combo.setCurrentIndex(window.device_filter_combo.findData("inactive"))
        QApplication.processEvents()
        assert window.devices_list.item(0).isHidden()
        assert not window.devices_list.item(1).isHidden()
    finally:
        close_window(window)
