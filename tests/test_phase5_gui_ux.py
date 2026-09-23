from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from shiboken6 import isValid
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.communication.state import ConnectionState, ConnectionStatus
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.core.commands import CommandResult
from ha_windows_bridge.core.state import ServiceState
from ha_windows_bridge.ui.shell import PAGES, DesktopWindow, Page
from ha_windows_bridge.ui.theme import style_for_theme, tokens_for_theme
from ha_windows_bridge.ui_components import ToggleSwitch


def close_window(window: DesktopWindow) -> None:
    application = window.application
    window._force_close = True
    window.close()
    window.deleteLater()
    assert application.shutdown()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_phase5_compact_populated_pages_have_no_horizontal_scrollbar():
    qt = qt_app()
    config = AppConfig(
        mqtt=MqttConfig(host="broker.local", username="operator", base_topic="desk/pc"),
        apps=[AudioAppConfig("long-application-name.exe", "A long configured application", "long_app", True)],
        auto_connect=False,
        control_master_volume=False,
        publish_cpu_stats=True,
        publish_ram_stats=True,
        publish_activity=True,
        overlay_enabled=True,
    )
    window = DesktopWindow(runtime(config))
    try:
        window.resize(700, 520)
        window.show()
        qt.processEvents()
        for page in range(len(PAGES)):
            window.navigation.setCurrentRow(page)
            qt.processEvents()
            assert window.pages.widget(page).horizontalScrollBar().maximum() == 0
    finally:
        close_window(window)


@pytest.mark.parametrize("factor", ["1", "1.25", "1.5", "2"])
def test_phase5_scale_matrix_keeps_compact_onboarding_within_view(tmp_path, factor):
    script = r'''
import sys
sys.path.insert(0, "tests")
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from test_v2_application import runtime
from test_v2_desktop import qt_app
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.ui.shell import DesktopWindow
qt = qt_app()
application = runtime(AppConfig(mqtt=MqttConfig(host="broker.local"), auto_connect=False, control_master_volume=False))
window = DesktopWindow(application)
window.resize(700, 520)
window.show()
qt.processEvents()
assert window.pages.widget(0).horizontalScrollBar().maximum() == 0
assert window.grab().save(sys.argv[1])
window._force_close = True
window.close()
window.deleteLater()
assert application.shutdown()
QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
'''
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=factor)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / f"scale-{factor}.png")],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_phase5_language_and_theme_are_local_draft_and_discardable():
    qt = qt_app()
    application = runtime(AppConfig(mqtt=MqttConfig(host="broker"), auto_connect=False, control_master_volume=False))
    previews = []
    application.events.subscribe("ui.theme_preview", lambda event: previews.append(copy.deepcopy(event.data)))
    window = DesktopWindow(application)
    try:
        window.language.setCurrentIndex(window.language.findData("en"))
        window.theme.setCurrentIndex(window.theme.findData("light"))
        qt.processEvents()
        assert window.navigation.item(Page.OVERVIEW).text() == "Overview"
        assert window.draft.language == "en" and window.draft.theme == "light"
        assert window.dirty_status.text() == "Unsaved changes"
        assert previews and previews[-1].theme == "light"
        assert application.config.language == "pl" and application.config.theme == "dark"
        window._discard()
        qt.processEvents()
        assert window.navigation.item(Page.OVERVIEW).text() == "Przegląd"
        assert window.draft == window.applied == application.config
    finally:
        close_window(window)


def test_phase5_runtime_snapshots_do_not_dirty_configuration():
    qt = qt_app()
    application = runtime(AppConfig(mqtt=MqttConfig(host="broker"), auto_connect=False, control_master_volume=False))
    window = DesktopWindow(application)
    try:
        window.resize(700, 520)
        window.show()
        window.navigation.setCurrentRow(Page.COMPUTER)
        qt.processEvents()
        before = copy.deepcopy(window.draft)
        application.computer_state.observe_provider(
            "cpu_ram", SimpleNamespace(cpu_percent=23.5, ram_percent=47.0),
            generation=application.computer_snapshot().generation,
        )
        qt.processEvents()
        assert window.draft == before == window.applied
        assert "23.5%" in window.feature_values["publish_cpu_stats"].text()
        assert not window.save.isEnabled()
    finally:
        close_window(window)


def test_phase5_overlay_editor_uses_single_phase4_command_path():
    qt_app()
    application = runtime(AppConfig(mqtt=MqttConfig(host="broker"), auto_connect=False, control_master_volume=False, overlay_enabled=True))
    calls = []
    application.command = lambda kind, arguments, target="": calls.append((kind, arguments, target)) or CommandResult("local", "accepted")
    window = DesktopWindow(application)
    try:
        window._preview_overlay()
        window._update_overlay()
        window._remove_overlay()
        window._clear_overlays()
        assert [call[0] for call in calls] == ["overlay.show"] * 4
        assert [call[1]["data"]["action"] for call in calls] == ["show", "update", "remove", "clear"]
        assert calls[0][1]["data"]["duration"] == application.config.overlay_example_duration
    finally:
        close_window(window)


def test_phase5_diagnostic_export_is_exact_preview_and_private(tmp_path, monkeypatch):
    qt_app()
    config = AppConfig(mqtt=MqttConfig(host="private.example", username="private-user", password="private-password"), auto_connect=False, control_master_volume=False)
    config.home_assistant.token = "private-token"
    application = runtime(config)
    application.log.warning("window=Private title path=C:/Users/private/app.exe payload=private-payload")
    window = DesktopWindow(application)
    destination = tmp_path / "diagnostics.json"
    try:
        window._refresh_status()
        shown = window.diagnostic_preview.toPlainText()
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_args, **_kwargs: (str(destination), "JSON (*.json)")))
        window._diagnostics()
        exported = destination.read_text(encoding="utf-8")
        assert exported == shown
        json.loads(exported)
        for private in ("private.example", "private-user", "private-password", "private-token", "Private title", "C:/Users", "private-payload"):
            assert private not in exported
    finally:
        close_window(window)


@pytest.mark.parametrize("failure", ["startup_read", "stop"])
def test_phase5_apply_terminal_failure_preserves_original_preflight_boundaries(monkeypatch, failure):
    application = runtime()
    terminal = []
    calls = []
    application.events.subscribe("configuration.apply_finished", lambda event: terminal.append(event.data))
    monkeypatch.setattr(application, "_schedule", lambda action: application._run_operation(action) or True)
    monkeypatch.setattr(application, "_build_services", lambda: calls.append("build"))
    monkeypatch.setattr(application, "_start", lambda: calls.append("start"))
    application.store.save = lambda _config: calls.append("save")
    if failure == "startup_read":
        application.startup.is_enabled = lambda: (_ for _ in ()).throw(OSError("registry read"))
        monkeypatch.setattr(application, "_stop", lambda: calls.append("stop"))
    else:
        application.startup.is_enabled = lambda: False
        monkeypatch.setattr(application, "_stop", lambda: calls.append("stop") or (_ for _ in ()).throw(RuntimeError("still stopping")))
    try:
        request_id = application.request_configuration_apply(copy.deepcopy(application.config))
        assert request_id
        assert terminal == [{"request_id": request_id, "ok": False, "code": "OSError" if failure == "startup_read" else "RuntimeError"}]
        assert calls == ([] if failure == "startup_read" else ["stop"])
    finally:
        assert application.shutdown()


@pytest.fixture
def phase5_window():
    qt_app()
    config = AppConfig(mqtt=MqttConfig(host="broker"), auto_connect=False, control_master_volume=False)
    window = DesktopWindow(runtime(config))
    yield window
    close_window(window)


@pytest.fixture
def phase5_overlay_window():
    qt_app()
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        auto_connect=False,
        control_master_volume=False,
        overlay_enabled=True,
    )
    window = DesktopWindow(runtime(config))
    yield window
    close_window(window)


@pytest.mark.parametrize("mutation", ["import", "reset", "disk"])
def test_phase5_non_field_draft_mutations_enable_apply(phase5_window, monkeypatch, mutation):
    window = phase5_window
    if mutation == "import":
        changed = copy.deepcopy(window.draft)
        changed.mqtt.host = "new-broker"
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: ("fixture.json", ""))
        monkeypatch.setattr("ha_windows_bridge.ui.shell.ConfigurationStore.import_settings", lambda _: changed)
        window._import_settings()
    elif mutation == "reset":
        monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
        window._reset_settings()
    else:
        def choose(dialog):
            dialog.findChild(QListWidget).item(0).setCheckState(Qt.CheckState.Checked)
            return QDialog.DialogCode.Accepted
        monkeypatch.setattr(QDialog, "exec", choose)
        window._select_inventory("disks", [SimpleNamespace(mountpoint="Z:/", total_gb=100)])
    assert window.draft != window.applied
    assert window.save.isEnabled() and window.discard.isEnabled()


def test_phase5_pending_apply_rejects_late_inventory(phase5_window, monkeypatch):
    window = phase5_window
    monkeypatch.setattr(window.application, "request_configuration_apply", lambda _: "pending-1")
    window._fields["mqtt.host"].setText("new-broker")
    window._save()
    before = copy.deepcopy(window.draft)
    window.application.events.emit("inventory.applications", [
        SimpleNamespace(process_name="new.exe", display_name="New", executable_path="", volume=None, muted=None)
    ])
    QApplication.processEvents()
    assert window.draft == before
    assert not any(card.config.process_name == "new.exe" for card in window._cards)


def test_phase5_diagnostic_export_freezes_before_file_dialog(phase5_window, monkeypatch, tmp_path):
    window = phase5_window
    before = window.diagnostic_preview.toPlainText()
    destination = tmp_path / "report.json"
    def choose(*_):
        window.application.set_notifications_quiet(True)
        QApplication.processEvents()
        return str(destination), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    window._diagnostics()
    assert destination.read_text(encoding="utf-8") == before


def test_phase5_computer_navigation_refreshes_sample_and_age(phase5_window):
    window = phase5_window
    window.show()
    window.navigation.setCurrentRow(Page.OVERVIEW)
    QApplication.processEvents()
    window.application.computer_state.observe_provider(
        "cpu_ram", SimpleNamespace(cpu_percent=23.5, ram_percent=47),
        generation=window.application.computer_snapshot().generation,
    )
    window.navigation.setCurrentRow(Page.COMPUTER)
    QApplication.processEvents()
    assert "23.5%" in window.feature_values["publish_cpu_stats"].text()
    assert "cpu_ram" in window.feature_values["publish_cpu_stats"].text()


def test_phase5_language_keeps_dynamic_values_and_translates_combo(phase5_window):
    window = phase5_window
    window.application.computer_state.observe_provider(
        "cpu_ram", SimpleNamespace(cpu_percent=23.5, ram_percent=47),
        generation=window.application.computer_snapshot().generation,
    )
    window._refresh_computer_state()
    window.language.setCurrentIndex(window.language.findData("en"))
    assert "23.5%" in window.feature_values["publish_cpu_stats"].text()
    assert window.dirty_status.text() == "Unsaved changes"
    assert window.theme.itemText(0) == "Dark"
    assert window.channel.itemText(0).startswith("MQTT")


def test_phase5_monitor_refresh_keeps_editor_identity(phase5_window):
    window = phase5_window
    window.draft.overlay_monitor_id = "screen-A"
    window._refresh_overlay_monitors(["1: screen-A", "2: screen-B"])
    window.overlay_monitor.setCurrentIndex(1)
    window._refresh_overlay_monitors(["1: screen-B", "2: screen-A"])
    assert window._overlay_arguments("show")["data"]["monitor_id"] == "screen-B"


def test_phase5_onboarding_lifecycle_is_correlated(phase5_window):
    window = phase5_window
    window.application.config.overlay_enabled = True
    window.application.command = lambda *_: CommandResult("local-1", "accepted")
    window._preview_overlay()
    window.application.events.emit("overlay.lifecycle", {
        "notification_id": window._last_overlay_id, "command_id": "remote",
        "disposition": "failed", "reason": "remote",
    })
    QApplication.processEvents()
    assert "accepted" in window.onboarding_result.text()
    window.application.events.emit("overlay.lifecycle", {
        "notification_id": window._last_overlay_id, "command_id": "local-1",
        "disposition": "displayed", "reason": "",
    })
    QApplication.processEvents()
    assert "displayed" in window.onboarding_result.text()
    assert window.onboarding_result.text() == window.overlay_result.text()


def test_phase5_stopped_sensor_status_and_activation(phase5_window):
    window = phase5_window
    window._refresh_status()
    assert "Sensory: zatrzymane" in window.diagnostic_status.text()
    window.hide()
    window.application.events.emit("windows.activate_requested")
    QApplication.processEvents()
    assert window.isVisible()


def test_phase5_local_app_commands_use_applied_identity_and_result(phase5_window):
    window = phase5_window
    app = AudioAppConfig("demo.exe", "Demo", "applied_slug", True, executable_path="C:/Demo/demo.exe",
                         allow_remote_start=True, allow_remote_close=True)
    window.applied.apps = [copy.deepcopy(app)]
    window.draft.apps = [copy.deepcopy(app)]
    window._refresh_fields()
    card = window._cards[0]
    card.config.slug = "draft_slug"
    calls = []
    window.application.command = lambda kind, args, target="": calls.append((kind, args, target)) or CommandResult(str(len(calls)), "accepted")
    window._local_app_command(card, "application.start")
    window._local_app_command(card, "application.close")
    assert calls == [("application.start", {}, "applied_slug"), ("application.close", {}, "applied_slug")]
    window.application.events.emit("command.result", CommandResult("2", "failed", "protected_process"))
    QApplication.processEvents()
    assert "protected_process" in card.local_result.text()


def test_phase5_connection_test_waits_for_all_channels_and_ignores_stopped(phase5_window, monkeypatch):
    window = phase5_window
    window.applied.home_assistant.enabled = True
    window.applied.overlay_enabled = True
    window.draft = copy.deepcopy(window.applied)
    window._refresh_fields()
    monkeypatch.setattr(window.application, "start", lambda: True)
    window._test_connection()
    assert window._connection_test_pending
    for transport, state in [
        ("mqtt", ConnectionState.STOPPED),
        ("irrelevant", ConnectionState.CONNECTED),
        ("mqtt", ConnectionState.CONNECTING),
        ("mqtt", ConnectionState.CONNECTED),
    ]:
        window.application.events.emit("connection.changed", ConnectionStatus(transport, state))
        QApplication.processEvents()
        assert window._connection_test_pending
    window.application.events.emit("connection.changed", ConnectionStatus("home_assistant", ConnectionState.CONNECTED))
    QApplication.processEvents()
    assert not window._connection_test_pending
    assert "MQTT" in window.connection_test_result.text()
    assert "Home Assistant" in window.connection_test_result.text()


def test_phase5_computer_capabilities_show_values_not_app_counts(phase5_window):
    from ha_windows_bridge.audio import (
        AudioOutputDevice,
        AudioProviderSnapshot,
        AudioSessionSnapshot,
        MicrophoneSnapshot,
    )
    window = phase5_window
    value = AudioProviderSnapshot(
        master=AudioSessionSnapshot(.4, False), balance=.2,
        microphone=MicrophoneSnapshot(.6, True, False),
        outputs=(AudioOutputDevice("id", "Speakers", True),),
    )
    assert "40%" in window._feature_value("control_master_volume", value)
    assert "0.20" in window._feature_value("control_channel_balance", value)
    assert "60%" in window._feature_value("control_microphone", value)
    assert "Speakers" in window._feature_value("control_audio_output", value)
    assert "aplikacje audio" not in window._feature_value("audio_enhancements_enabled", value)


def test_phase5_log_filter_is_bounded_and_recovery_navigation(phase5_window):
    window = phase5_window
    for index in range(220):
        window.application.log.info("entry %s", index)
    window.log_filter.setText("entry 219")
    assert "entry 219" in window.logs.toPlainText()
    assert "entry 0" not in window.logs.toPlainText()
    window.navigation.setCurrentRow(Page.OVERVIEW)
    buttons = window.pages.widget(Page.OVERVIEW).findChildren(QPushButton)
    next(button for button in buttons if button.text() == "Otwórz diagnostykę").click()
    assert window.navigation.currentRow() == Page.DIAGNOSTICS


def test_phase5_badge_text_contrast_ignores_unsafe_system_accent():
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear, strict=True))
    for mode in ("dark", "light"):
        tokens = tokens_for_theme(mode, "#0078d4")
        a, b = sorted((luminance(tokens.text), luminance(tokens.selection)))
        assert (b + .05) / (a + .05) >= 4.5
        assert f"QLabel#statusBadge {{ color: {tokens.text};" in style_for_theme("", mode, "#0078d4")


def test_phase5_recovery_required_remains_in_footer_and_overview(phase5_window, monkeypatch):
    window = phase5_window
    application = window.application
    writes = []
    def save(config):
        writes.append(config)
        if len(writes) == 2:
            raise OSError("rollback disk failure")
    application.store.save = save
    application.startup.set_enabled = lambda _: (_ for _ in ()).throw(OSError("registry failure"))
    monkeypatch.setattr(application, "_schedule", lambda action: application._run_operation(action) or True)
    window._fields["mqtt.host"].setText("new-broker")
    window._save()
    QApplication.processEvents()
    assert window._pending_apply is None
    assert window.draft.mqtt.host == "new-broker"
    assert "odzyskanie" in window.status.text()
    assert "odzyskanie" in window.last_error.text()
    window.language.setCurrentIndex(window.language.findData("en"))
    assert "manual configuration recovery" in window.status.text()
    assert "manual configuration recovery" in window.last_error.text()


def test_phase5_apply_progress_is_correlated_to_pending_request(phase5_window, monkeypatch):
    window = phase5_window
    monkeypatch.setattr(window.application, "request_configuration_apply", lambda _: "pending-1")
    window._fields["mqtt.host"].setText("new-broker")
    window._save()
    before = window.status.text()
    window.application.events.emit("configuration.apply_progress", {"request_id": "other", "stage": "rollback"})
    QApplication.processEvents()
    assert window.status.text() == before
    window.application.events.emit("configuration.apply_progress", {"request_id": "pending-1", "stage": "rollback"})
    QApplication.processEvents()
    assert "Cofanie" in window.status.text()



@pytest.mark.parametrize("change", ["theme", "host"])
def test_phase5_current_connection_runs_against_applied_config_with_dirty_draft(
    phase5_window, monkeypatch, change,
):
    window = phase5_window
    calls = []
    monkeypatch.setattr(window.application, "start", lambda: calls.append("start") or True)
    if change == "theme":
        window.theme.setCurrentIndex(window.theme.findData("light"))
    else:
        window._fields["mqtt.host"].setText("new-broker")
    assert window.draft != window.applied

    window._test_connection()

    assert calls == ["start"]
    assert window._connection_test_pending
    if change == "host":
        assert "zastosowanego serwera" in window.connection_test_result.text()


def test_phase5_english_feature_descriptions_and_accessibility_are_complete(phase5_window):
    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))

    labels = [label.text() for label in window.findChildren(QLabel)]
    assert not any("Bieżąca wartość" in label for label in labels)
    assert not any("Publikuj" in label for label in labels)
    assert window._toggles["publish_cpu_stats"].accessibleName().startswith("Share:")
    assert window.feature_values["publish_cpu_stats"].accessibleName().startswith("Feature status:")
    assert "Udostępniaj" not in window._toggles["publish_cpu_stats"].accessibleName()


def test_phase5_english_live_overlay_resource_and_update_results(phase5_window, monkeypatch):
    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))
    window.application.config.overlay_enabled = True
    monkeypatch.setattr(
        window.application,
        "command",
        lambda *_args, **_kwargs: CommandResult("local", "accepted"),
    )

    window._preview_overlay()
    assert "awaiting presentation" in window.onboarding_result.text()
    assert "oczekuje" not in window.onboarding_result.text()

    window.application.events.emit(
        "resources.updated",
        {"cpu_percent": 1.0, "memory_mib": 30.0, "threads": 5},
    )
    window.application.events.emit(
        "updates.checked",
        SimpleNamespace(error=False, available=True, latest_version="9.9.9"),
    )
    QApplication.processEvents()

    assert "Threads: 5" in window.resource_usage.text()
    assert "Wątki" not in window.resource_usage.text()
    assert window.status.text() == "Version 9.9.9 is available."


def test_phase5_english_dialogs_and_inventory_actions_are_localized(phase5_window, monkeypatch):
    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))
    file_dialogs = []

    def open_file(_parent, title, _directory, file_filter):
        file_dialogs.append(("open", title, file_filter))
        return "", ""

    def save_file(_parent, title, _default, file_filter):
        file_dialogs.append(("save", title, file_filter))
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_file)
    questions = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message: questions.append((title, message))
        or QMessageBox.StandardButton.No,
    )
    inventory = []

    def reject_inventory(dialog):
        buttons = dialog.findChild(QDialogButtonBox)
        inventory.append(
            (
                dialog.windowTitle(),
                buttons.button(QDialogButtonBox.StandardButton.Ok).text(),
                buttons.button(QDialogButtonBox.StandardButton.Cancel).text(),
            )
        )
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", reject_inventory)

    window._add_app()
    window._import_settings()
    window._export_settings()
    window._diagnostics()
    window._reset_settings()
    window._select_inventory("devices", [])
    window._fields["mqtt.host"].setText("dirty-broker")
    window._request_exit()

    assert ("open", "Choose application", "Applications (*.exe)") in file_dialogs
    assert ("open", "Import settings 2.0", "JSON (*.json)") in file_dialogs
    assert ("save", "Export settings", "JSON (*.json)") in file_dialogs
    assert ("save", "Diagnostic report", "JSON (*.json)") in file_dialogs
    assert ("Default settings", "Restore default settings? Connection details will be retained.") in questions
    assert ("Unsaved changes", "Exit and discard unsaved changes?") in questions
    assert inventory == [("Choose devices", "Choose", "Cancel")]


def test_phase5_quiet_overlay_terminal_result_reaches_both_surfaces(phase5_overlay_window):
    window = phase5_overlay_window
    window.application.set_notifications_quiet(True)

    window._preview_overlay()
    for _ in range(30):
        QTest.qWait(10)
        QApplication.processEvents()
        if "notifications_quiet" in window.onboarding_result.text():
            break

    assert "notifications_quiet" in window.onboarding_result.text()
    assert "notifications_quiet" in window.overlay_result.text()
    assert "accepted" not in window.overlay_result.text()


@pytest.mark.parametrize(
    ("invoke", "action"),
    [
        ("_update_overlay", "update"),
        ("_remove_overlay", "remove"),
        ("_clear_overlays", "clear"),
    ],
)
def test_phase5_real_router_terminal_overlay_actions_are_correlated(
    phase5_overlay_window, invoke, action,
):
    window = phase5_overlay_window
    remote = CommandResult("unrelated-remote", "failed", "remote_failure")

    getattr(window, invoke)()
    pending_id = window._local_overlay_pending_id
    assert pending_id
    window.application.events.emit("command.result", remote)
    QApplication.processEvents()
    assert "remote_failure" not in window.overlay_result.text()

    for _ in range(40):
        QTest.qWait(10)
        QApplication.processEvents()
        if window._local_overlay_pending_id is None:
            break

    shown = window.overlay_result.text()
    assert shown.startswith(f"{action}: ")
    assert "awaiting result" not in shown
    assert "oczekuje na wynik" not in shown
    assert any(status in shown for status in ("succeeded", "failed", "rejected", "cancelled"))
    assert shown == window.onboarding_result.text()


def test_phase5_initial_light_style_recolours_navigation_icons(phase5_window):
    window = phase5_window
    qt = QApplication.instance()
    tokens = tokens_for_theme("light")
    qt.setProperty("bridgeTheme", "light")
    qt.setProperty("bridgeAccent", tokens.accent)
    qt.setProperty("bridgeAccentText", tokens.accent_text)
    qt.setProperty("bridgeIcon", tokens.text)
    qt.setProperty("bridgeFocus", tokens.text)
    qt.setStyleSheet(style_for_theme("", "light"))
    window.show()
    QApplication.processEvents()

    icon = window.navigation.item(1).icon().pixmap(24, 24).toImage()
    colors = [
        icon.pixelColor(x, y)
        for x in range(24)
        for y in range(24)
        if icon.pixelColor(x, y).alpha() > 240
    ]
    assert colors
    assert all(color.red() < 100 and color.green() < 100 and color.blue() < 100 for color in colors)


def test_phase5_toggle_keyboard_focus_uses_contrast_safe_theme_text():
    qt = qt_app()
    tokens = tokens_for_theme("light")
    qt.setProperty("bridgeTheme", "light")
    qt.setProperty("bridgeAccent", "#ffffff")
    qt.setProperty("bridgeAccentText", "#ffffff")
    qt.setProperty("bridgeFocus", tokens.text)
    host = QDialog()
    layout = QVBoxLayout(host)
    before = QPushButton("Before")
    switch = ToggleSwitch()
    layout.addWidget(before)
    layout.addWidget(switch)
    host.show()
    host.activateWindow()
    switch.setFocus()
    QApplication.processEvents()
    QApplication.sendEvent(
        switch,
        QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason),
    )
    QApplication.processEvents()
    try:
        assert switch.hasFocus()
        assert switch._focus_visible
        image = switch.grab().toImage()
        perimeter = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
            if x < 3 or y < 3 or x >= image.width() - 3 or y >= image.height() - 3
        ]
        assert any(color.alpha() > 200 and max(color.red(), color.green(), color.blue()) < 100 for color in perimeter)
    finally:
        host.close()
        host.deleteLater()


def test_phase5_sensor_lifecycle_and_app_identity_survive_language_roundtrip(phase5_window):
    window = phase5_window
    application = window.application
    window.language.setCurrentIndex(window.language.findData("en"))
    for state, paused, expected in [
        (ServiceState.RUNNING, False, "running"),
        (ServiceState.RUNNING, True, "paused"),
        (ServiceState.ERROR, False, "error"),
        (ServiceState.STOPPED, True, "stopped"),
    ]:
        application.states.set("provider_cpu_ram", state)
        application.pause_sensors(paused)
        window._refresh_status()
        assert f"Sensors: {expected}" in window.diagnostic_status.text()
        assert window.tray_sensors.text() == f"Sensors: {expected}"

    window.applied.apps = [AudioAppConfig("identity.exe", "Start", "stable_id", True)]
    window.draft = copy.deepcopy(window.applied)
    window._refresh_fields()
    window._cards[0].name_label.setText("User edited name")
    window.language.setCurrentIndex(window.language.findData("pl"))
    window.language.setCurrentIndex(window.language.findData("en"))
    assert window._cards[0].name_label.text() == "User edited name"
    assert window._cards[0].config.slug == "stable_id"


def test_phase5_real_computer_shapes_retain_values_across_failure(phase5_window, monkeypatch):
    from ha_windows_bridge.application.providers import DeviceSnapshot, StorageSnapshot
    from ha_windows_bridge.audio import (
        AudioOutputDevice,
        AudioProviderSnapshot,
        AudioSessionSnapshot,
        MicrophoneSnapshot,
    )
    from ha_windows_bridge.config import TrackedDeviceConfig
    from ha_windows_bridge.core.state import StateQuality
    from ha_windows_bridge.system_monitor import DiskVolume, PnpDevice, SystemMetrics

    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))
    store = window.application.computer_state
    generation = window.application.computer_snapshot().generation
    window.draft.disk_mounts = ["Z:/"]
    window.draft.tracked_devices = [TrackedDeviceConfig("dev-1", "Keyboard", "HID")]
    samples = [
        ("cpu_ram", SystemMetrics(23.5, 47.0, 100)),
        ("storage", StorageSnapshot((DiskVolume("Z:/", "Z", "NTFS", 100.0, 25.0, 75.0),))),
        ("pnp", DeviceSnapshot((PnpDevice("dev-1", "Keyboard", "HID", False),))),
        (
            "audio",
            AudioProviderSnapshot(
                master=AudioSessionSnapshot(0.4, True),
                balance=0.2,
                microphone=MicrophoneSnapshot(0.6, False, True),
                outputs=(AudioOutputDevice("out", "Speakers", True),),
            ),
        ),
    ]
    for source, value in samples:
        store.observe_provider(source, value, generation=generation, observed_at=100.0)
    monkeypatch.setattr("ha_windows_bridge.ui.shell.time.time", lambda: 110.0)
    window._refresh_computer_state()

    assert "10 s ago" in window.feature_values["publish_cpu_stats"].text()
    assert "Z:/: 25% used, 75.0 GB free" in window.feature_values["publish_disk_stats"].text()
    assert "Keyboard: absent" in window.feature_values["publish_devices"].text()
    assert "40%" in window.feature_values["control_master_volume"].text()
    assert "0.20" in window.feature_values["control_channel_balance"].text()
    assert "Speakers (default)" in window.feature_values["control_audio_output"].text()

    store.fail_provider(
        "cpu_ram",
        StateQuality.ERROR,
        "read_failed",
        generation=generation,
    )
    monkeypatch.setattr("ha_windows_bridge.ui.shell.time.time", lambda: 115.0)
    window._refresh_computer_state()
    shown = window.feature_values["publish_cpu_stats"].text()
    assert all(value in shown for value in ("error", "read_failed", "23.5%", "15 s ago"))



def _application_card_language_state(card):
    return (
        card.local_result.text(),
        card.local_start_action.text(),
        card.local_close_action.text(),
        card.local_result.accessibleName(),
    )


def test_phase5_added_and_discovered_cards_follow_language_and_preserve_identity(
    phase5_window, monkeypatch,
):
    from ha_windows_bridge.audio import AudioApplication

    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args: ("C:/User Apps/new.exe", ""),
    )

    window._add_app()
    added = window._cards[-1]
    window._update_applications(
        [AudioApplication("observed.exe", "Observed User Name", "C:/Observed/app.exe")],
        discover=True,
    )
    discovered = window._cards[-1]

    expected_en = (
        "No local command yet.",
        "Start locally",
        "Close locally",
        "Local application command result",
    )
    assert _application_card_language_state(added) == expected_en
    assert _application_card_language_state(discovered) == expected_en
    identities = [
        (card.config.process_name, card.config.display_name, card.config.slug)
        for card in (added, discovered)
    ]

    window.language.setCurrentIndex(window.language.findData("pl"))
    assert _application_card_language_state(added) == (
        "Brak lokalnego polecenia.",
        "Uruchom lokalnie",
        "Zamknij lokalnie",
        "Wynik lokalnego polecenia aplikacji",
    )
    window.language.setCurrentIndex(window.language.findData("en"))

    assert _application_card_language_state(added) == expected_en
    assert _application_card_language_state(discovered) == expected_en
    assert [
        (card.config.process_name, card.config.display_name, card.config.slug)
        for card in (added, discovered)
    ] == identities
    window._update_dirty()
    added_draft = next(app for app in window.draft.apps if app.process_name == "new.exe")
    assert Path(added_draft.executable_path) == Path("C:/User Apps/new.exe")
    assert window.save.isEnabled()


def test_phase5_application_edit_dialog_accepts_localized_values_without_identity_loss(
    phase5_window, monkeypatch,
):
    window = phase5_window
    window.language.setCurrentIndex(window.language.findData("en"))
    config = AudioAppConfig("old.exe", "Original Name", "stable", True)
    window.draft.apps.append(config)
    window._add_card(config)
    card = window._cards[-1]
    dialogs = []

    def get_text(_parent, title, prompt, **kwargs):
        dialogs.append((title, prompt, kwargs["text"]))
        return ("Renamed by user", True) if len(dialogs) == 1 else ("stable_user", True)

    monkeypatch.setattr(QInputDialog, "getText", get_text)
    card.edit()

    assert dialogs == [
        ("Application name", "Friendly name:", "Original Name"),
        ("Topic identifier", "MQTT identifier:", "stable"),
    ]
    assert card.config.process_name == "old.exe"
    assert card.config.display_name == "Renamed by user"
    assert card.config.slug == "stable_user"
    assert card.name_label.text() == "Renamed by user"
    edited_draft = next(app for app in window.draft.apps if app.process_name == "old.exe")
    assert edited_draft.display_name == "Renamed by user"
    assert edited_draft.slug == "stable_user"
    assert window.save.isEnabled()

    window.language.setCurrentIndex(window.language.findData("pl"))
    window.language.setCurrentIndex(window.language.findData("en"))
    assert card.name_label.text() == "Renamed by user"
    assert card.config.slug == "stable_user"
    assert card.local_start_action.text() == "Start locally"


def test_phase5_queued_icon_refresh_is_safe_after_window_disposal(monkeypatch):
    qt_app()
    application = runtime(
        AppConfig(
            mqtt=MqttConfig(host="broker"),
            auto_connect=False,
            control_master_volume=False,
        )
    )
    window = DesktopWindow(application)
    errors = []
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda error_type, value, _traceback: errors.append(
            (error_type.__name__, str(value))
        ),
    )
    try:
        QApplication.sendEvent(window, QEvent(QEvent.Type.StyleChange))
        window._force_close = True
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()
        assert not errors
    finally:
        if isValid(window):
            close_window(window)
        else:
            assert application.shutdown()
