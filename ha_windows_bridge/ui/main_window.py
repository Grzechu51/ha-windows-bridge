from __future__ import annotations

import copy
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import psutil
from PySide6.QtCore import (
    QObject,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..audio import AudioApplication, AudioOutputDevice, WindowsAudioService
from ..config import (
    AppConfig,
    AudioAppConfig,
    HomeAssistantConfig,
    MqttConfig,
    SettingsStore,
    TrackedDeviceConfig,
    slugify,
)
from ..data_exchange import (
    build_diagnostic_report,
    export_configuration,
    import_configuration,
    save_diagnostic_report,
)
from ..direct_bridge import DirectHaBridge
from ..discovery import all_possible_mqtt_topics
from ..i18n import LocalizedFormatter, set_active_language, translate
from ..mqtt_bridge import MqttBridge
from ..mqtt_cleanup import MqttCleanupResult, cleanup_application_mqtt_data
from ..overlay import OverlayManager
from ..runtime.worker import SerialWorker
from ..startup import WindowsStartupManager
from ..system_monitor import DiskVolume, PnpDevice, WindowsSystemMonitor
from ..ui_components import (
    AppCard,
    HelpButton,
    NavButton,
    TitleBar,
)
from ..updater import GitHubUpdateChecker, UpdateInfo
from ..windows_effects import DesktopDuplicationCapture
from .inputs import SettingsWheelGuard
from .motion import MotionSystem
from .navigation import PageStack
from .pages import applications, connection, examples, features, logs, settings


class UiSignals(QObject):
    status = Signal(str, bool)
    log_line = Signal(str)
    audio_apps = Signal(object)
    app_metadata = Signal(object)
    audio_outputs = Signal(object)
    volume_snapshot = Signal(object)
    connection_test = Signal(bool, str)
    cleanup_finished = Signal(object)
    windows_notification = Signal(str, str)
    update_checked = Signal(object)
    devices_scanned = Signal(object)
    overlay_requested = Signal(str, str, object)


class QtLogHandler(logging.Handler):
    def __init__(self, signals: UiSignals):
        super().__init__()
        self.signals = signals

    def emit(self, record: logging.LogRecord) -> None:
        self.signals.log_line.emit(self.format(record))




class MainWindow(QMainWindow):
    CONNECTION_PAGE = 0
    APPLICATIONS_PAGE = 1
    FEATURES_PAGE = 2
    LOGS_PAGE = 3
    SETTINGS_PAGE = 4

    def __init__(
        self,
        config: AppConfig,
        store: SettingsStore,
        startup: WindowsStartupManager,
        logger: logging.Logger,
        theme_changed: Callable[[str], None] | None = None,
        launch_minimized: bool = False,
    ):
        super().__init__()
        original_config = copy.deepcopy(config)
        loaded_config = copy.deepcopy(config)
        legacy_base_topic = loaded_config.mqtt.base_topic.startswith("hawn/")
        if legacy_base_topic:
            loaded_config.mqtt.base_topic = (
                f"ha-windows-bridge/{slugify(loaded_config.device_name, 'windows_pc')}"
            )
        suggested_topic = f"ha-windows-bridge/{slugify(loaded_config.device_name, 'windows_pc')}"
        self._base_topic_is_automatic = (
            legacy_base_topic or loaded_config.mqtt.base_topic == suggested_topic
        )
        self.current_config = loaded_config
        self.store = store
        self.startup = startup
        self.logger = logger
        self._audio_worker = SerialWorker("ui-audio-commands", logger)
        self._theme_changed_callback = theme_changed
        self.pending_uninstaller: Path | None = None
        self._uninstaller_path = self._find_uninstaller()
        self._known_mqtt_topics: set[str] = set()
        if hasattr(self.store, "load_mqtt_topic_history"):
            self._known_mqtt_topics.update(self.store.load_mqtt_topic_history())
        self._remember_mqtt_topics(original_config, loaded_config)
        self.audio = WindowsAudioService()
        self.system_monitor = WindowsSystemMonitor()
        self._overlay_desktop_capture = DesktopDuplicationCapture()
        self.overlay_manager: OverlayManager | None = None
        self.overlay_preview_manager: OverlayManager | None = None
        self.bridge: MqttBridge | None = None
        self.direct_bridge: DirectHaBridge | None = None
        self.signals = UiSignals()
        self.app_cards: list[AppCard] = []
        self._force_close = False
        self._tray_notice_shown = False
        self._volume_refresh_running = False
        self._present_device_ids: set[str] = set()
        self._last_status_text = "Zatrzymano"
        self._cleanup_then_uninstall = False
        self._latest_release_url = ""
        self.update_checker = GitHubUpdateChecker()
        self._language = "pl"
        self._sidebar_expanded = True
        self._self_process = psutil.Process()
        self._cpu_count = max(1, psutil.cpu_count(logical=True) or 1)
        self._self_process.cpu_percent(interval=None)

        self.setWindowTitle("HA Windows Bridge")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(800, 600)
        self.resize(1120, 760)
        self.setWindowIcon(self._create_icon())

        self._build_ui()
        self._settings_wheel_guard = SettingsWheelGuard(self)
        for editor in self.findChildren(QAbstractSpinBox):
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self._settings_wheel_guard)
        self.save_feedback_timer = QTimer(self)
        self.save_feedback_timer.setSingleShot(True)
        self.save_feedback_timer.timeout.connect(self._reset_save_button)
        self._build_tray()
        self._connect_signals()
        self._load_config(self.current_config)
        self._install_log_handler()
        self._refresh_log_secrets(self.current_config)

        self.volume_timer = QTimer(self)
        self.volume_timer.setInterval(1000)
        self.volume_timer.timeout.connect(self._refresh_card_volumes)
        self.volume_timer.start()
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(1000)
        self.runtime_timer.timeout.connect(self._refresh_runtime_status)
        self.runtime_timer.start()
        self.resource_timer = QTimer(self)
        self.resource_timer.setInterval(3000)
        self.resource_timer.timeout.connect(self._refresh_resource_usage)
        self.resource_timer.start()
        self._refresh_resource_usage()
        QTimer.singleShot(120, self._refresh_existing_app_metadata)
        QTimer.singleShot(180, self._refresh_card_volumes)
        QTimer.singleShot(220, self._refresh_audio_outputs)
        QTimer.singleShot(5000, self._automatic_update_check)

        if self.current_config.auto_connect and not self.current_config.validation_errors():
            QTimer.singleShot(180, self.start_bridge)
        if launch_minimized:
            QTimer.singleShot(0, self.hide)

    def _build_ui(self) -> None:
        transparent_root = QWidget()
        root_layout = QVBoxLayout(transparent_root)
        root_layout.setContentsMargins(3, 3, 3, 3)
        root_layout.setSpacing(0)

        self.window_frame = QFrame()
        self.window_frame.setObjectName("windowFrame")
        frame_layout = QVBoxLayout(self.window_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        root_layout.addWidget(self.window_frame)
        self.setCentralWidget(transparent_root)

        self.title_bar = TitleBar()
        frame_layout.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar)
        self.pages = PageStack()
        self.pages.setObjectName("pageStack")
        self.pages.currentChanged.connect(self._sync_navigation)
        self.pages.addWidget(self._connection_page())
        self.pages.addWidget(self._applications_page())
        self.pages.addWidget(self._features_page())
        self.pages.addWidget(self._logs_page())
        self.pages.addWidget(self._settings_page())
        body.addWidget(self.pages, 1)
        frame_layout.addLayout(body, 1)

        frame_layout.addWidget(self._build_footer())

    def _remove_settings_wheel_guard(self) -> None:
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self._settings_wheel_guard)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(9, 17, 9, 12)
        layout.setSpacing(7)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        entries = (
            ("⇄", "Połączenie"),
            ("▦", "Aplikacje"),
            ("✦", "Funkcje"),
            ("◷", "Logi"),
            ("⚙", "Ustawienia"),
        )
        self.nav_buttons: list[NavButton] = []
        for index, (icon, label) in enumerate(entries):
            button = NavButton(icon, label)
            button.clicked.connect(lambda _checked=False, page=index: self._switch_page(page))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch()
        return sidebar

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(72)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 14, 0)
        layout.setSpacing(0)

        self.sidebar_footer = QFrame()
        self.sidebar_footer.setObjectName("sidebarFooter")
        self.sidebar_footer.setFixedWidth(190)
        left = QVBoxLayout(self.sidebar_footer)
        left.setContentsMargins(20, 7, 8, 7)
        left.setSpacing(2)
        version = QLabel(f"v{__version__}")
        version.setObjectName("versionLabel")
        status_row = QHBoxLayout()
        self.footer_status_dot = QLabel("●")
        self.footer_status_dot.setObjectName("footerStatusDot")
        self.footer_status_label = QLabel("Zatrzymano")
        self.footer_status_label.setObjectName("footerStatusLabel")
        status_row.addWidget(self.footer_status_dot)
        status_row.addWidget(self.footer_status_label)
        status_row.addStretch()
        left.addWidget(version)
        left.addLayout(status_row)

        resource_layout = QHBoxLayout()
        resource_layout.setSpacing(6)
        self.resource_bar = QProgressBar()
        self.resource_bar.setObjectName("resourceBar")
        self.resource_bar.setRange(0, 100)
        self.resource_bar.setTextVisible(False)
        self.resource_bar.setFixedSize(34, 4)
        resource_layout.addWidget(self.resource_bar)
        self.resource_label = QLabel("CPU 0,0% · 0 MB")
        self.resource_label.setObjectName("resourceLabel")
        resource_layout.addWidget(self.resource_label)
        resource_layout.addStretch()
        resource_help = (
            "Bieżące użycie CPU i pamięci przez HA Windows Bridge. "
            "Odczyt jest odświeżany co 3 sekundy."
        )
        self.resource_bar.setToolTip(resource_help)
        self.resource_label.setToolTip(resource_help)
        left.addLayout(resource_layout)
        layout.addWidget(self.sidebar_footer)
        layout.addStretch()

        self.start_button = QPushButton("Uruchom usługę")
        self.start_button.setObjectName("secondaryButton")
        self.save_button = QPushButton("Zapisz i zastosuj")
        self.save_button.setObjectName("primaryButton")
        layout.addWidget(self.start_button)
        layout.addSpacing(12)
        layout.addWidget(self.save_button)
        layout.addSpacing(8)
        size_grip = QSizeGrip(self.window_frame)
        size_grip.setFixedSize(16, 16)
        layout.addWidget(size_grip, 0, Qt.AlignmentFlag.AlignBottom)
        return footer

    @staticmethod
    def _page_header(title: str, subtitle: str) -> tuple[QWidget, QHBoxLayout]:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        text.addWidget(title_label)
        text.addWidget(subtitle_label)
        layout.addLayout(text, 1)
        return header, layout

    @staticmethod
    def _help_button(tooltip: str) -> HelpButton:
        return HelpButton(tooltip)

    @staticmethod
    def _scroll_page(content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _connection_page(self) -> QWidget:
        return connection.build_page(self)

    def _applications_page(self) -> QWidget:
        return applications.build_page(self)

    def _features_page(self) -> QWidget:
        return features.build_page(self)

    def _build_overlay_examples(self) -> QFrame:
        return examples.build_page(self)

    def _logs_page(self) -> QWidget:
        return logs.build_page(self)

    def _settings_page(self) -> QWidget:
        return settings.build_page(self)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        self.tray_status = QAction("● Zatrzymano", menu)
        self.tray_status.setEnabled(False)
        open_action = menu.addAction("Otwórz")
        settings_action = menu.addAction("Ustawienia")
        self.tray_toggle = menu.addAction("Uruchom usługę")
        reconnect_action = menu.addAction("Połącz ponownie")
        menu.addSeparator()
        example_action = menu.addAction("Pokaż przykład nakładki")
        hide_example_action = menu.addAction("Zamknij przykład nakładki")
        menu.addSeparator()
        quit_action = menu.addAction("Zakończ")
        menu.insertAction(open_action, self.tray_status)
        open_action.triggered.connect(self._show_window)
        settings_action.triggered.connect(lambda: (self._switch_page(self.SETTINGS_PAGE), self._show_window()))
        example_action.triggered.connect(self._show_overlay_example)
        hide_example_action.triggered.connect(self._close_overlay_example)
        self.tray_toggle.triggered.connect(self._toggle_bridge)
        reconnect_action.triggered.connect(self.restart_bridge)
        quit_action.triggered.connect(self.quit_application)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _connect_signals(self) -> None:
        self.signals.status.connect(self._set_status)
        self.signals.log_line.connect(self.logs.appendPlainText)
        self.signals.audio_apps.connect(self._merge_audio_apps)
        self.signals.app_metadata.connect(self._apply_existing_app_metadata)
        self.signals.audio_outputs.connect(self._apply_audio_outputs)
        self.signals.volume_snapshot.connect(self._apply_volume_snapshot)
        self.signals.connection_test.connect(self._show_test_result)
        self.signals.cleanup_finished.connect(self._mqtt_cleanup_finished)
        self.signals.windows_notification.connect(self._show_windows_notification)
        self.signals.update_checked.connect(self._update_check_finished)
        self.signals.devices_scanned.connect(self._apply_scanned_devices)
        self.signals.overlay_requested.connect(self._show_overlay_message)
        self.title_bar.menu_clicked.connect(self._toggle_sidebar)
        self.show_password.toggled.connect(
            lambda checked: self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        self.show_ha_token.toggled.connect(
            lambda checked: self.ha_token.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        self.direct_enabled.toggled.connect(self._apply_direct_state)
        self.copy_ha_device_id.clicked.connect(self._copy_device_id)
        for editor in (self.host, self.username, self.password, self.ha_url, self.ha_token):
            editor.textChanged.connect(self._clear_test_result)
        self.ha_url.textChanged.connect(self._refresh_direct_connection_badge)
        self.ha_token.textChanged.connect(self._refresh_direct_connection_badge)
        for editor in (self.port, self.keepalive):
            editor.valueChanged.connect(self._clear_test_result)
        self.tls.toggled.connect(self._clear_test_result)
        self.ha_verify_tls.toggled.connect(self._clear_test_result)
        self.device_name.textEdited.connect(self._update_automatic_base_topic)
        self.base_topic.textEdited.connect(self._mark_base_topic_as_custom)
        self.scan_apps_button.clicked.connect(self.scan_audio_apps)
        self.add_exe_button.clicked.connect(self.add_executable)
        self.master_volume_card.volume_requested.connect(self._set_master_volume)
        self.master_volume_card.mute_requested.connect(self._set_master_mute)
        self.microphone_card.volume_requested.connect(self._set_microphone_volume)
        self.microphone_card.mute_requested.connect(self._set_microphone_mute)
        self.audio_output_card.output_requested.connect(self._set_audio_output)
        self.audio_output_card.refresh_requested.connect(self._refresh_audio_outputs)
        self.publish_idle_row.switch.toggled.connect(self.idle_threshold.setEnabled)
        self.publish_disk_stats_row.switch.toggled.connect(self._apply_disk_state)
        self.scan_disks_button.clicked.connect(self.scan_disk_volumes)
        self.audio_enhancements_row.switch.toggled.connect(self._apply_audio_state)
        self.publish_devices_row.switch.toggled.connect(self._apply_devices_state)
        self.device_filter_combo.currentIndexChanged.connect(self._apply_device_filter)
        self.overlay_enabled_row.switch.toggled.connect(self._apply_overlay_state)
        self.overlay_example_button.clicked.connect(self._show_overlay_example)
        self.scan_devices_button.clicked.connect(self.scan_devices)
        self.test_button.clicked.connect(self.test_mqtt_connection)
        self.discovery_button.clicked.connect(self._republish_discovery)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.reduced_motion_row.switch.toggled.connect(self._motion_changed)
        self.save_button.clicked.connect(self.save_and_apply)
        self.start_button.clicked.connect(self._toggle_bridge)
        self.reset_defaults_button.clicked.connect(self._reset_default_settings)
        self.uninstall_button.clicked.connect(self._uninstall_application)
        self.mqtt_cleanup_button.clicked.connect(self._cleanup_mqtt_only)
        self.import_button.clicked.connect(self._import_configuration)
        self.export_button.clicked.connect(self._export_configuration)
        self.diagnostics_button.clicked.connect(self._save_diagnostics)
        self.check_update_button.clicked.connect(self._check_for_updates)
        self.open_update_button.clicked.connect(self._open_latest_release)

    def _language_changed(self, _index: int) -> None:
        self._apply_language(str(self.language_combo.currentData() or "pl"))

    def _theme_changed(self, _index: int) -> None:
        if self._theme_changed_callback:
            self._theme_changed_callback(str(self.theme_combo.currentData() or "dark"))
        for button in self.nav_buttons:
            button.refresh_icon()

    def _motion_changed(self, enabled: bool) -> None:
        QApplication.instance().setProperty("bridgeReducedMotion", enabled)
        if enabled:
            self.pages._clear_transition()
        for manager in (self.overlay_manager, self.overlay_preview_manager):
            if manager is not None:
                manager.set_motion_enabled(MotionSystem.enabled())

    def _apply_language(self, language: str) -> None:
        self._language = language if language in {"pl", "en"} else "pl"
        set_active_language(self._language)
        for button in self.nav_buttons:
            button.set_language(self._language)
        self.theme_combo.setItemText(0, "Dark" if self._language == "en" else "Ciemny")
        self.theme_combo.setItemText(1, "Light" if self._language == "en" else "Jasny")
        device_filters = {
            "all": ("All", "Wszystkie"),
            "active": ("Active", "Aktywne"),
            "inactive": ("Inactive", "Nieaktywne"),
        }
        for index in range(self.device_filter_combo.count()):
            english, polish = device_filters[str(self.device_filter_combo.itemData(index))]
            self.device_filter_combo.setItemText(
                index, english if self._language == "en" else polish
            )
        for index in range(self.devices_list.count()):
            self._update_device_item_text(self.devices_list.item(index))
        tab_names = (
            ("General", "Ogólne"),
            ("System and disks", "System i dyski"),
            ("Audio", "Audio"),
            ("Devices", "Urządzenia"),
            ("Overlay", "Nakładka"),
        )
        for index, (english, polish) in enumerate(tab_names):
            self.feature_tabs.setTabText(index, english if self._language == "en" else polish)
        for index, (_name, label) in enumerate(OverlayManager.test_pattern_names()):
            self.overlay_example_combo.setItemText(index, self._t(label))
        self._translate_widget_tree(self, self._language)
        self.status_card.set_language(self._language)
        connected = bool(
            (self.bridge and self.bridge.connected)
            or (self.direct_bridge and self.direct_bridge.connected)
        )
        displayed = "Połączono" if connected else self._last_status_text
        self.title_bar.status_label.setText(self._t(displayed))
        self.footer_status_label.setText(self._t(displayed))

    @staticmethod
    def _translate_widget_tree(root: QWidget, language: str) -> None:
        for widget in root.findChildren(QWidget):
            if isinstance(widget, NavButton):
                continue
            if isinstance(widget, (QLabel, QAbstractButton)):
                widget.setText(translate(widget.text(), language))
            if isinstance(widget, QLineEdit) and widget.placeholderText():
                widget.setPlaceholderText(translate(widget.placeholderText(), language))
            if widget.toolTip():
                widget.setToolTip(translate(widget.toolTip(), language))
        for action in root.findChildren(QAction):
            action.setText(translate(action.text(), language))
            if action.toolTip():
                action.setToolTip(translate(action.toolTip(), language))

    def _t(self, text: str) -> str:
        return translate(text, self._language)

    def _republish_discovery(self) -> None:
        if not self.bridge or not self.bridge.connected:
            self._show_test_result(False, self._t("Najpierw uruchom połączenie MQTT."))
            return
        count = self.bridge.publish_discovery()
        message = self._t(
            "Przekazano ponownie {count} encji do integracji HA Windows Bridge."
        ).format(count=count)
        self._show_test_result(True, message)
        self.logger.info(
            "Przekazano ponownie %s encji do integracji HA Windows Bridge",
            count,
        )

    def _install_log_handler(self) -> None:
        handler = QtLogHandler(self.signals)
        handler.setFormatter(
            LocalizedFormatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S")
        )
        self.logger.addHandler(handler)
        self._qt_log_handler = handler

    def _refresh_log_secrets(self, config: AppConfig) -> None:
        for handler in self.logger.handlers:
            if isinstance(handler.formatter, LocalizedFormatter):
                handler.formatter.add_secrets(config.mqtt.password, config.home_assistant.token)

    def _sync_navigation(self, index: int) -> None:
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == self.APPLICATIONS_PAGE and hasattr(self, "volume_timer"):
            self._refresh_card_volumes()

    def _toggle_sidebar(self) -> None:
        self._sidebar_expanded = not self._sidebar_expanded
        self._update_navigation_width()

    def _update_navigation_width(self) -> None:
        compact = self.width() < 1000 or not self._sidebar_expanded
        self.sidebar.setFixedWidth(64 if compact else 190)
        self.sidebar_footer.setVisible(True)
        for button in self.nav_buttons:
            button.set_compact(compact)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "sidebar_footer"):
            self._update_navigation_width()

    def _load_config(self, config: AppConfig) -> None:
        self.reduced_motion_row.switch.setChecked(config.reduced_motion)
        self._motion_changed(config.reduced_motion)
        self.device_name.setText(config.device_name)
        self.base_topic.setText(config.mqtt.base_topic)
        self.host.setText(config.mqtt.host)
        self.port.setValue(config.mqtt.port)
        self.username.setText(config.mqtt.username)
        self.password.setText(config.mqtt.password)
        self.direct_enabled.setChecked(config.home_assistant.enabled)
        self.ha_url.setText(config.home_assistant.url)
        self.ha_token.setText(config.home_assistant.token)
        self.ha_verify_tls.setChecked(config.home_assistant.verify_tls)
        self.tls.setChecked(config.mqtt.tls)
        self.discovery_prefix.setText(config.mqtt.discovery_prefix)
        self.keepalive.setValue(config.mqtt.keepalive)
        self.start_with_windows_row.switch.setChecked(config.start_with_windows)
        self.start_minimized_row.switch.setChecked(config.start_minimized)
        self.minimize_to_tray_row.switch.setChecked(config.minimize_to_tray)
        self.auto_connect_row.switch.setChecked(config.auto_connect)
        self.control_active_row.switch.setChecked(config.control_active_app)
        self.publish_initial_row.switch.setChecked(config.publish_initial_state)
        self.poll_interval.setValue(config.poll_interval)
        self.publish_activity_row.switch.setChecked(config.publish_activity)
        self.publish_idle_row.switch.setChecked(config.publish_idle)
        self.idle_threshold.setValue(config.idle_threshold)
        self.publish_session_lock_row.switch.setChecked(config.publish_session_lock)
        self.publish_ram_stats_row.switch.setChecked(config.publish_ram_stats)
        self.publish_cpu_stats_row.switch.setChecked(config.publish_cpu_stats)
        self.publish_gpu_stats_row.switch.setChecked(config.publish_gpu_stats)
        self.publish_windows_health_row.switch.setChecked(config.publish_windows_health)
        self.publish_disk_stats_row.switch.setChecked(config.publish_disk_stats)
        self._load_disk_volumes(config.disk_mounts)
        if config.publish_disk_stats and not config.disk_mounts:
            config.disk_mounts = self._selected_disk_mounts()
        self.audio_enhancements_row.switch.setChecked(config.audio_enhancements_enabled)
        self.channel_balance_row.switch.setChecked(config.control_channel_balance)
        self.publish_audio_sessions_row.switch.setChecked(config.publish_audio_sessions)
        self.publish_devices_row.switch.setChecked(config.publish_devices)
        self._load_tracked_devices(config.tracked_devices)
        self.overlay_enabled_row.switch.setChecked(config.overlay_enabled)
        self.overlay_fullscreen_row.switch.setChecked(config.overlay_allow_fullscreen)
        self.overlay_monitor_combo.setCurrentIndex(
            max(0, min(self.overlay_monitor_combo.count() - 1, config.overlay_monitor))
        )
        self.media_player_row.switch.setChecked(config.media_player_enabled)
        self.power_actions_row.switch.setChecked(config.allow_power_actions)
        self.windows_notifications_row.switch.setChecked(config.enable_windows_notifications)
        self.auto_update_row.switch.setChecked(config.auto_check_updates)
        self.master_volume_card.set_feature_enabled(config.control_master_volume)
        self.microphone_card.set_feature_enabled(config.control_microphone)
        self.audio_output_card.set_feature_enabled(config.control_audio_output)
        self.idle_threshold.setEnabled(config.publish_idle)
        self._apply_audio_state(config.audio_enhancements_enabled)
        self._apply_disk_state(config.publish_disk_stats)
        self._apply_overlay_state(config.overlay_enabled)
        self._apply_direct_state(config.home_assistant.enabled)
        self._apply_devices_state(config.publish_devices)
        language_index = self.language_combo.findData(config.language)
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(max(0, language_index))
        theme_index = self.theme_combo.findData(config.theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        self.theme_combo.blockSignals(False)
        if self._theme_changed_callback:
            self._theme_changed_callback(config.theme)
        self.language_combo.blockSignals(False)
        for card in list(self.app_cards):
            self._remove_app_card(card)
        for app_config in config.apps:
            self._add_app_card(app_config)
        self._update_empty_state()
        self._configure_overlay(config)
        self._apply_language(config.language)
        if config.publish_devices:
            QTimer.singleShot(300, self.scan_devices)

    def _config_from_form(self) -> AppConfig:
        return AppConfig(
            device_name=self.device_name.text(),
            device_id=self.current_config.device_id,
            mqtt=MqttConfig(
                host=self.host.text().strip(),
                port=self.port.value(),
                username=self.username.text().strip(),
                password=self.password.text(),
                keepalive=self.keepalive.value(),
                tls=self.tls.isChecked(),
                base_topic=self.base_topic.text(),
                discovery_prefix=self.discovery_prefix.text(),
            ),
            home_assistant=HomeAssistantConfig(
                enabled=self.direct_enabled.isChecked(),
                url=self.ha_url.text().strip(),
                token=self.ha_token.text(),
                verify_tls=self.ha_verify_tls.isChecked(),
            ),
            apps=[card.to_config() for card in self.app_cards],
            start_with_windows=self.start_with_windows_row.switch.isChecked(),
            start_minimized=self.start_minimized_row.switch.isChecked(),
            minimize_to_tray=self.minimize_to_tray_row.switch.isChecked(),
            auto_connect=self.auto_connect_row.switch.isChecked(),
            language=str(self.language_combo.currentData() or "pl"),
            control_master_volume=self.master_volume_card.enabled_switch.isChecked(),
            control_active_app=self.control_active_row.switch.isChecked(),
            publish_initial_state=self.publish_initial_row.switch.isChecked(),
            poll_interval=self.poll_interval.value(),
            theme=str(self.theme_combo.currentData() or "dark"),
            reduced_motion=self.reduced_motion_row.switch.isChecked(),
            publish_activity=self.publish_activity_row.switch.isChecked(),
            publish_idle=self.publish_idle_row.switch.isChecked(),
            idle_threshold=self.idle_threshold.value(),
            publish_session_lock=self.publish_session_lock_row.switch.isChecked(),
            publish_ram_stats=self.publish_ram_stats_row.switch.isChecked(),
            publish_cpu_stats=self.publish_cpu_stats_row.switch.isChecked(),
            publish_gpu_stats=self.publish_gpu_stats_row.switch.isChecked(),
            control_microphone=self.microphone_card.enabled_switch.isChecked(),
            control_audio_output=self.audio_output_card.enabled_switch.isChecked(),
            media_player_enabled=self.media_player_row.switch.isChecked(),
            allow_power_actions=self.power_actions_row.switch.isChecked(),
            enable_windows_notifications=self.windows_notifications_row.switch.isChecked(),
            auto_check_updates=self.auto_update_row.switch.isChecked(),
            publish_windows_health=self.publish_windows_health_row.switch.isChecked(),
            publish_disk_stats=self.publish_disk_stats_row.switch.isChecked(),
            disk_mounts=self._selected_disk_mounts(),
            audio_enhancements_enabled=self.audio_enhancements_row.switch.isChecked(),
            control_channel_balance=self.channel_balance_row.switch.isChecked(),
            publish_audio_sessions=self.publish_audio_sessions_row.switch.isChecked(),
            publish_devices=self.publish_devices_row.switch.isChecked(),
            tracked_devices=self._tracked_devices_from_list(),
            overlay_enabled=self.overlay_enabled_row.switch.isChecked(),
            overlay_allow_fullscreen=self.overlay_fullscreen_row.switch.isChecked(),
            overlay_monitor=int(self.overlay_monitor_combo.currentData() or 0),
        )

    def save_and_apply(self) -> bool:
        try:
            new_config = self._config_from_form()
            self._refresh_log_secrets(new_config)
            errors = new_config.validation_errors()
            if errors:
                raise ValueError("\n".join(self._t(error) for error in errors))
            self._remember_mqtt_topics(self.current_config, new_config)
            if self.bridge or self.direct_bridge:
                self.stop_bridge()
            self.store.save(new_config)
            self.startup.set_enabled(new_config.start_with_windows)
            self.current_config = copy.deepcopy(new_config)
            self._configure_overlay(new_config)
            self.logger.info("Zapisano konfigurację")
            if new_config.auto_connect:
                self.start_bridge()
            else:
                self._set_status("Zapisano — usługa zatrzymana", False)
            self._show_save_confirmation()
            return True
        except Exception as exc:
            QMessageBox.warning(self, self._t("Nie można zapisać"), str(exc))
            self.logger.error("Nie można zapisać konfiguracji: %s", exc)
            return False

    def _show_save_confirmation(self) -> None:
        self.save_button.setProperty("saved", True)
        self.save_button.setText(self._t("✓ Zapisano"))
        self.save_button.style().unpolish(self.save_button)
        self.save_button.style().polish(self.save_button)
        self.save_feedback_timer.start(1800)

    def _reset_save_button(self) -> None:
        self.save_button.setProperty("saved", False)
        self.save_button.setText(self._t("Zapisz i zastosuj"))
        self.save_button.style().unpolish(self.save_button)
        self.save_button.style().polish(self.save_button)

    def start_bridge(self) -> None:
        if self.bridge is not None or self.direct_bridge is not None:
            return
        errors = self.current_config.validation_errors()
        if errors:
            self._set_status("Wymagana konfiguracja", False)
            self._switch_page(self.CONNECTION_PAGE)
            return
        try:
            overlay_monitors = [
                f"{index + 1}: {screen.name()} ({screen.size().width()}×{screen.size().height()})"
                for index, screen in enumerate(QApplication.screens())
            ]
            if self.current_config.mqtt.host:
                self.bridge = MqttBridge(
                    copy.deepcopy(self.current_config),
                    audio=self.audio,
                    logger=self.logger,
                    status_callback=lambda text, connected: self.signals.status.emit(
                        text, connected
                    ),
                    notification_callback=lambda title, message: self.signals.windows_notification.emit(
                        title, message
                    ),
                    overlay_callback=lambda title, message, data: self.signals.overlay_requested.emit(
                        title, message, data
                    ),
                    overlay_monitors=overlay_monitors,
                    system_monitor=self.system_monitor,
                )
                self.bridge.start()
            if self.current_config.home_assistant.enabled:
                self.direct_bridge = DirectHaBridge(
                    copy.deepcopy(self.current_config),
                    logger=self.logger,
                    status_callback=lambda text, connected: self.signals.status.emit(
                        text, connected
                    ),
                    overlay_callback=lambda title, message, data: self.signals.overlay_requested.emit(
                        title, message, data
                    ),
                )
                self.direct_bridge.start()
            self.start_button.setText(self._t("Zatrzymaj usługę"))
            self.tray_toggle.setText(self._t("Zatrzymaj usługę"))
        except Exception as exc:
            if self.bridge is not None:
                self.bridge.stop()
            self.bridge = None
            if self.direct_bridge is not None:
                self.direct_bridge.stop()
            self.direct_bridge = None
            self._set_status(f"Błąd: {exc}", False)
            self.logger.exception("Nie można uruchomić usługi")

    def stop_bridge(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        if self.direct_bridge:
            self.direct_bridge.stop()
            self.direct_bridge = None
        self.start_button.setText(self._t("Uruchom usługę"))
        self.tray_toggle.setText(self._t("Uruchom usługę"))
        self.discovery_button.setEnabled(False)
        self._refresh_runtime_status()

    def restart_bridge(self) -> None:
        self.stop_bridge()
        self.start_bridge()

    def _apply_audio_state(self, enabled: bool) -> None:
        for row in (
            self.channel_balance_row,
            self.publish_audio_sessions_row,
        ):
            row.setEnabled(enabled)

    def _apply_disk_state(self, enabled: bool) -> None:
        self.disk_volumes_list.setEnabled(enabled)
        self.scan_disks_button.setEnabled(enabled)

    def _load_disk_volumes(
        self, selected_mounts: list[str], select_all_if_empty: bool = True
    ) -> None:
        selected = {os.path.normcase(os.path.normpath(mount)) for mount in selected_mounts if mount}
        self.disk_volumes_list.clear()
        for volume in self.system_monitor.list_disk_volumes():
            self._add_disk_volume_item(volume, selected, select_all_if_empty)

    def _add_disk_volume_item(
        self,
        volume: DiskVolume,
        selected: set[str],
        select_all_if_empty: bool,
    ) -> None:
        item = QListWidgetItem(
            f"{volume.mountpoint}  ·  {volume.file_system or self._t('System plików')}"
            f"  ·  {volume.total_gb:.1f} GiB"
        )
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        key = os.path.normcase(os.path.normpath(volume.mountpoint))
        item.setCheckState(
            Qt.CheckState.Checked
            if key in selected or (not selected and select_all_if_empty)
            else Qt.CheckState.Unchecked
        )
        item.setData(Qt.ItemDataRole.UserRole, volume.mountpoint)
        item.setToolTip(volume.device)
        self.disk_volumes_list.addItem(item)

    def _selected_disk_mounts(self) -> list[str]:
        return [
            str(self.disk_volumes_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.disk_volumes_list.count())
            if self.disk_volumes_list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def scan_disk_volumes(self) -> None:
        selected = self._selected_disk_mounts()
        self._load_disk_volumes(selected, select_all_if_empty=False)

    def _apply_overlay_state(self, enabled: bool) -> None:
        for widget in (
            self.overlay_fullscreen_row,
            self.overlay_monitor_combo,
            self.overlay_examples_card,
        ):
            widget.setEnabled(enabled)
        if not enabled and self.overlay_manager is not None:
            self.overlay_manager.close()
            self.overlay_manager = None
        if not enabled and self.overlay_preview_manager is not None:
            self.overlay_preview_manager.close()
            self.overlay_preview_manager = None

    def _show_overlay_example(self) -> None:
        if self.overlay_preview_manager is not None:
            self.overlay_preview_manager.close()
        self.overlay_preview_manager = OverlayManager(
            allow_fullscreen=True,
            default_monitor=int(self.overlay_monitor_combo.currentData() or 0),
            close_tooltip=self._t("Zamknij nakładkę"),
            desktop_capture=self._overlay_desktop_capture,
        )
        name = str(self.overlay_example_combo.currentData() or "compact")
        if not self.overlay_preview_manager.show_test_pattern(name):
            self.logger.warning("Nie udało się wyświetlić przykładowej nakładki")

    def _close_overlay_example(self) -> None:
        if self.overlay_preview_manager is not None:
            self.overlay_preview_manager.close()
            self.overlay_preview_manager = None

    def _apply_direct_state(self, enabled: bool) -> None:
        for widget in (self.ha_url, self.ha_token, self.show_ha_token, self.ha_verify_tls):
            widget.setEnabled(enabled)
        self._refresh_direct_connection_badge()

    def _copy_device_id(self) -> None:
        QApplication.clipboard().setText(self.ha_device_id.text())
        self.copy_ha_device_id.setText(self._t("Skopiowano"))
        QTimer.singleShot(
            1_500,
            lambda: self.copy_ha_device_id.setText(self._t("Kopiuj")),
        )

    def _refresh_direct_connection_badge(self) -> None:
        if not self.direct_enabled.isChecked():
            text, state = "Wyłączone", "off"
        elif self.direct_bridge is not None and self.direct_bridge.connected:
            text, state = "Połączono", "connected"
        elif self.ha_url.text().strip() and self.ha_token.text():
            text, state = "Gotowe", "ready"
        else:
            text, state = "Uzupełnij dane", "warning"
        self.direct_connection_badge.setText(self._t(text))
        self.direct_connection_badge.setProperty("connectionState", state)
        self.direct_connection_badge.style().unpolish(self.direct_connection_badge)
        self.direct_connection_badge.style().polish(self.direct_connection_badge)

    def _configure_overlay(self, config: AppConfig) -> None:
        if self.overlay_manager is not None:
            self.overlay_manager.close()
            self.overlay_manager = None
        if config.overlay_enabled:
            self.overlay_manager = OverlayManager(
                allow_fullscreen=config.overlay_allow_fullscreen,
                default_monitor=config.overlay_monitor,
                close_tooltip=self._t("Zamknij nakładkę"),
                desktop_capture=self._overlay_desktop_capture,
            )

    def _show_overlay_message(self, title: str, message: str, data: dict) -> None:
        if self.overlay_manager is None:
            return
        if not self.overlay_manager.handle_message(title, message, dict(data)):
            self.logger.info("Pominięto nakładkę podczas działania aplikacji pełnoekranowej")

    def _load_tracked_devices(self, devices: list[TrackedDeviceConfig]) -> None:
        self.devices_list.clear()
        for device in devices:
            present = (
                device.instance_id.casefold() in self._present_device_ids
                if self._present_device_ids
                else None
            )
            self._add_device_item(device, present)
        self._apply_device_filter()

    def _add_device_item(self, device: TrackedDeviceConfig, present: bool | None = None) -> None:
        item = QListWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if device.enabled else Qt.CheckState.Unchecked)
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "instance_id": device.instance_id,
                "display_name": device.display_name,
                "category": device.category,
                "slug": device.slug,
                "present": present,
            },
        )
        item.setToolTip(device.instance_id)
        self._update_device_item_text(item)
        self.devices_list.addItem(item)

    def _update_device_item_text(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        present = data.get("present")
        state = (
            self._t("Aktywne")
            if present is True
            else self._t("Nieaktywne")
            if present is False
            else self._t("Stan nieznany")
        )
        item.setText(f"{data.get('display_name', '')}  ·  {data.get('category', '')}  ·  {state}")

    def _apply_devices_state(self, enabled: bool) -> None:
        self.devices_list.setEnabled(enabled)
        self.device_filter_combo.setEnabled(enabled)
        self.scan_devices_button.setEnabled(enabled)

    def _apply_device_filter(self, *_args: object) -> None:
        selected = str(self.device_filter_combo.currentData() or "all")
        for index in range(self.devices_list.count()):
            item = self.devices_list.item(index)
            present = (item.data(Qt.ItemDataRole.UserRole) or {}).get("present")
            item.setHidden(
                (selected == "active" and present is not True)
                or (selected == "inactive" and present is not False)
            )

    def _tracked_devices_from_list(self) -> list[TrackedDeviceConfig]:
        devices: list[TrackedDeviceConfig] = []
        for index in range(self.devices_list.count()):
            item = self.devices_list.item(index)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            devices.append(
                TrackedDeviceConfig(
                    instance_id=str(data.get("instance_id", "")),
                    display_name=str(data.get("display_name", "")),
                    category=str(data.get("category", "Device")),
                    slug=str(data.get("slug", "")),
                    enabled=item.checkState() == Qt.CheckState.Checked,
                )
            )
        return devices

    def scan_devices(self) -> None:
        self.scan_devices_button.setEnabled(False)
        self.scan_devices_button.setText(self._t("Wyszukiwanie…"))

        def worker() -> None:
            self.signals.devices_scanned.emit(
                self.system_monitor.list_pnp_devices(include_disconnected=True)
            )

        threading.Thread(target=worker, name="device-scan", daemon=True).start()

    def _apply_scanned_devices(self, detected: list[PnpDevice]) -> None:
        self._present_device_ids = {
            device.instance_id.casefold() for device in detected if device.present
        }
        existing = {
            device.instance_id.casefold(): device for device in self._tracked_devices_from_list()
        }
        self.devices_list.clear()
        for device in detected:
            previous = existing.get(device.instance_id.casefold())
            self._add_device_item(
                TrackedDeviceConfig(
                    instance_id=device.instance_id,
                    display_name=device.display_name,
                    category=device.category,
                    slug=previous.slug if previous else "",
                    enabled=previous.enabled if previous else False,
                ),
                device.present,
            )
        self._apply_device_filter()
        self.scan_devices_button.setEnabled(self.publish_devices_row.switch.isChecked())
        self.scan_devices_button.setText(self._t("Odśwież listę"))

    def scan_audio_apps(self) -> None:
        self.scan_apps_button.setEnabled(False)
        self.scan_apps_button.setText(self._t("Wyszukiwanie…"))

        def worker() -> None:
            try:
                applications = self.audio.list_audio_applications()
                self.signals.audio_apps.emit(applications)
            except Exception:
                self.logger.exception("Nie można odczytać sesji audio")
                self.signals.audio_apps.emit([])

        threading.Thread(target=worker, name="audio-scan", daemon=True).start()

    def add_executable(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Wybierz aplikację", "", "Programy Windows (*.exe)"
        )
        if not file_name:
            return
        path = Path(file_name)
        self._merge_audio_apps([AudioApplication(path.name, path.stem, str(path))])

    def _merge_audio_apps(self, applications: list[AudioApplication]) -> None:
        existing = {card.config.process_name.lower() for card in self.app_cards}
        added = 0
        for application in applications:
            if application.process_name.lower() in existing:
                card = next(
                    card
                    for card in self.app_cards
                    if card.config.process_name.lower() == application.process_name.lower()
                )
                if application.executable_path:
                    card.set_executable_icon(application.executable_path)
                card.set_volume(application.volume)
                card.set_muted(application.muted)
                continue
            card = self._add_app_card(
                AudioAppConfig(
                    application.process_name,
                    application.display_name,
                    slugify(application.display_name),
                    False,
                    application.executable_path,
                )
            )
            card.set_volume(application.volume)
            card.set_muted(application.muted)
            existing.add(application.process_name.lower())
            added += 1
        self.scan_apps_button.setEnabled(True)
        self.scan_apps_button.setText(self._t("Wykryj uruchomione"))
        self._update_empty_state()
        if applications:
            self.logger.info("Wykryto %s sesji audio, dodano %s", len(applications), added)

    def _refresh_existing_app_metadata(self) -> None:
        if not self.app_cards:
            return

        def worker() -> None:
            try:
                self.signals.app_metadata.emit(self.audio.list_audio_applications())
            except Exception:
                self.signals.app_metadata.emit([])

        threading.Thread(target=worker, name="app-icon-refresh", daemon=True).start()

    def _apply_existing_app_metadata(self, applications: list[AudioApplication]) -> None:
        detected = {app.process_name.lower(): app for app in applications}
        for card in self.app_cards:
            application = detected.get(card.config.process_name.lower())
            if application is None:
                continue
            if application.executable_path:
                card.set_executable_icon(application.executable_path)
            card.set_volume(application.volume)
            card.set_muted(application.muted)

    def _add_app_card(self, config: AudioAppConfig) -> AppCard:
        card = AppCard(copy.deepcopy(config))
        card.remove_requested.connect(self._remove_app_card)
        card.volume_requested.connect(self._set_app_volume)
        card.mute_requested.connect(self._set_app_mute)
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.app_cards.append(card)
        self._translate_widget_tree(card, self._language)
        self._update_empty_state()
        return card

    def _remove_app_card(self, card: AppCard) -> None:
        if card in self.app_cards:
            self.app_cards.remove(card)
        self.cards_layout.removeWidget(card)
        card.deleteLater()
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        self.empty_apps_label.setVisible(not self.app_cards)

    def _set_app_volume(self, process_name: str, value: int) -> None:
        def worker() -> None:
            if self.audio.set_volume(process_name, value / 100.0):
                self.logger.info("Ustawiono %s na %s%% z interfejsu", process_name, value)
            else:
                self.logger.warning("Brak aktywnej sesji audio dla %s", process_name)

        self._audio_worker.submit(worker)

    def _set_master_volume(self, value: int) -> None:
        def worker() -> None:
            if self.audio.set_master_volume(value / 100.0):
                self.logger.info("Ustawiono główną głośność na %s%% z interfejsu", value)
            else:
                self.logger.warning("Nie można ustawić głównej głośności Windows")

        self._audio_worker.submit(worker)

    def _set_master_mute(self, muted: bool) -> None:
        self._audio_worker.submit(lambda: self.audio.set_master_mute(muted))

    def _set_app_mute(self, process_name: str, muted: bool) -> None:
        self._audio_worker.submit(lambda: self.audio.set_mute(process_name, muted))

    def _set_microphone_volume(self, value: int) -> None:
        self._audio_worker.submit(lambda: self.audio.set_microphone_volume(value / 100.0))

    def _set_microphone_mute(self, muted: bool) -> None:
        self._audio_worker.submit(lambda: self.audio.set_microphone_mute(muted))

    def _set_audio_output(self, name: str) -> None:
        def worker() -> None:
            if not self.audio.set_output_device(name):
                self.logger.warning("Nie można przełączyć wyjścia audio na %s", name)
            self.signals.audio_outputs.emit(self.audio.list_output_devices())

        self._audio_worker.submit(worker)

    def _refresh_audio_outputs(self) -> None:
        def worker() -> None:
            self.signals.audio_outputs.emit(self.audio.list_output_devices())

        threading.Thread(target=worker, name="ui-audio-output-refresh", daemon=True).start()

    def _apply_audio_outputs(self, outputs: list[AudioOutputDevice]) -> None:
        names = [output.name for output in outputs]
        current = next((output.name for output in outputs if output.is_default), "")
        self.audio_output_card.set_devices(names, current)

    def _refresh_card_volumes(self) -> None:
        if not self.isVisible() or self.pages.currentIndex() != self.APPLICATIONS_PAGE or self._volume_refresh_running:
            return
        self._volume_refresh_running = True
        names = [card.config.process_name for card in self.app_cards]

        def worker() -> None:
            try:
                snapshot = self.audio.session_snapshot(names)
                snapshot["__master__"] = self.audio.get_master_snapshot()
                snapshot["__microphone__"] = self.audio.get_microphone_snapshot()
                self.signals.volume_snapshot.emit(snapshot)
            except Exception:
                self.signals.volume_snapshot.emit({})

        threading.Thread(target=worker, name="ui-volume-refresh", daemon=True).start()

    def _apply_volume_snapshot(self, snapshot: dict[str, object]) -> None:
        master = snapshot.get("__master__")
        self.master_volume_card.set_volume(getattr(master, "volume", None))
        self.master_volume_card.set_muted(getattr(master, "muted", None))
        microphone = snapshot.get("__microphone__")
        self.microphone_card.set_state(
            getattr(microphone, "volume", None),
            getattr(microphone, "muted", None),
            getattr(microphone, "active", None),
        )
        for card in self.app_cards:
            state = snapshot.get(card.config.process_name.lower())
            card.set_volume(getattr(state, "volume", None))
            card.set_muted(getattr(state, "muted", None))
            self._translate_widget_tree(card, self._language)
        self._translate_widget_tree(self.microphone_card, self._language)
        self._volume_refresh_running = False

    def test_mqtt_connection(self) -> None:
        config = self._config_from_form()
        self._refresh_log_secrets(config)
        basic_errors = [
            error for error in config.validation_errors() if "aplikac" not in error.lower()
        ]
        if basic_errors:
            QMessageBox.warning(self, "Niepełna konfiguracja", "\n".join(basic_errors))
            return
        self.test_button.setEnabled(False)
        self.test_result.setText(self._t("Łączenie…"))

        def worker() -> None:
            results: list[tuple[bool, str]] = []
            if config.mqtt.host:
                results.append(MqttBridge.test_connection(config))
            if config.home_assistant.enabled:
                results.append(DirectHaBridge.test_connection(config))
            ok = bool(results) and all(result[0] for result in results)
            message = " ".join(result[1] for result in results)
            self.signals.connection_test.emit(ok, message)

        threading.Thread(target=worker, name="connection-test", daemon=True).start()

    def _show_test_result(self, ok: bool, message: str) -> None:
        self.test_button.setEnabled(True)
        self.test_result.setProperty("success", ok)
        self.test_result.style().unpolish(self.test_result)
        self.test_result.style().polish(self.test_result)
        self.test_result.setText(("✓  " if ok else "×  ") + self._t(message))

    def _clear_test_result(self, *_args) -> None:
        if self.test_button.isEnabled():
            self.test_result.clear()
            self.test_result.setProperty("success", False)

    def _update_automatic_base_topic(self, device_name: str) -> None:
        if self._base_topic_is_automatic:
            self.base_topic.setText(f"ha-windows-bridge/{slugify(device_name, 'windows_pc')}")

    def _mark_base_topic_as_custom(self, *_args) -> None:
        self._base_topic_is_automatic = False

    def _set_status(self, text: str, connected: bool) -> None:
        self._last_status_text = text
        color = (
            "#49c483"
            if connected
            else "#dfa64d"
            if "Łącz" in text or "ponaw" in text
            else "#7c8c92"
        )
        self.title_bar.status_dot.setStyleSheet(f"color: {color};")
        self.title_bar.status_label.setText(self._t("Połączono" if connected else text))
        self.footer_status_dot.setStyleSheet(f"color: {color};")
        self.footer_status_label.setText(self._t("Połączono" if connected else text))
        self.tray_status.setText(f"● {self._t(text)}")
        self.discovery_button.setEnabled(bool(self.bridge and self.bridge.connected))
        if connected:
            self.start_button.setText(self._t("Zatrzymaj usługę"))
            self.tray_toggle.setText(self._t("Zatrzymaj usługę"))
        self._refresh_runtime_status()

    def _refresh_runtime_status(self) -> None:
        mqtt_connected = bool(self.bridge and self.bridge.connected)
        direct_connected = bool(self.direct_bridge and self.direct_bridge.connected)
        connected = mqtt_connected or direct_connected
        if self.bridge and self.bridge.started_at:
            elapsed = max(0, int(time.monotonic() - self.bridge.started_at))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            messages = self.bridge.messages_processed
        else:
            uptime = "00:00:00"
            messages = 0
        detail = (
            "Połączono z MQTT i Home Assistant"
            if mqtt_connected and direct_connected
            else "Połączono z brokerem MQTT"
            if mqtt_connected
            else "Połączono bezpośrednio z Home Assistant"
            if direct_connected
            else self._last_status_text
        )
        self.status_card.update_status(connected, detail, uptime, messages)
        self._refresh_direct_connection_badge()

    def _refresh_resource_usage(self) -> None:
        """Refresh a cheap, process-local CPU/RAM indicator in the footer."""
        try:
            raw_cpu = self._self_process.cpu_percent(interval=None)
            cpu = max(0.0, min(100.0, raw_cpu / self._cpu_count))
            memory = self._self_process.memory_full_info()
            private_bytes = getattr(memory, "uss", None)
            if private_bytes is None:
                basic_memory = self._self_process.memory_info()
                private_bytes = getattr(basic_memory, "private", basic_memory.rss)
            ram_mb = private_bytes / (1024 * 1024)
        except (psutil.Error, OSError):
            return
        self.resource_bar.setValue(round(cpu))
        cpu_text = f"{cpu:.1f}".replace(".", ",") if self._language == "pl" else f"{cpu:.1f}"
        self.resource_label.setText(f"CPU {cpu_text}% · RAM {ram_mb:.0f} MB")

    def _toggle_bridge(self) -> None:
        if self.bridge or self.direct_bridge:
            self.stop_bridge()
            return
        form_config = self._config_from_form()
        if form_config != self.current_config:
            if not self.save_and_apply():
                return
            if self.bridge or self.direct_bridge:
                return
        self.start_bridge()

    def logs_clear(self) -> None:
        self.logs.clear()

    def _open_logs_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_dir / "logs")))

    def _show_windows_notification(self, title: str, message: str) -> None:
        self.tray.showMessage(
            title[:128] or "Home Assistant",
            message[:2048],
            QSystemTrayIcon.MessageIcon.Information,
            10000,
        )

    def _automatic_update_check(self) -> None:
        if self.auto_update_row.switch.isChecked():
            self._check_for_updates(silent=True)

    def _check_for_updates(self, _checked: bool = False, *, silent: bool = False) -> None:
        if not self.check_update_button.isEnabled():
            return
        self.check_update_button.setEnabled(False)
        if not silent:
            self.update_status_label.setText(self._t("Sprawdzanie aktualizacji…"))

        def worker() -> None:
            self.signals.update_checked.emit(self.update_checker.check(__version__))

        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _update_check_finished(self, result: UpdateInfo) -> None:
        self.check_update_button.setEnabled(True)
        if result.error:
            self.update_status_label.setText(self._t("Nie udało się sprawdzić aktualizacji."))
            self.logger.info("Nie udało się sprawdzić aktualizacji: %s", result.error)
            return
        if result.available and result.release_url:
            self._latest_release_url = result.release_url
            self.open_update_button.setEnabled(True)
            self.update_status_label.setText(
                self._t("Dostępna jest wersja {version}.").format(version=result.latest_version)
            )
            self._show_windows_notification(
                "HA Windows Bridge",
                self._t("Dostępna jest wersja {version}.").format(version=result.latest_version),
            )
            return
        self._latest_release_url = ""
        self.open_update_button.setEnabled(False)
        self.update_status_label.setText(self._t("Masz najnowszą wersję."))

    def _open_latest_release(self) -> None:
        if self._latest_release_url:
            QDesktopServices.openUrl(QUrl(self._latest_release_url))

    def _export_configuration(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            self._t("Eksport konfiguracji"),
            str(self.store.data_dir / "ha-windows-bridge-config.json"),
            "JSON (*.json)",
        )
        if not file_name:
            return
        try:
            export_configuration(Path(file_name), self._config_from_form())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self._t("Eksport konfiguracji"), str(exc))
            return
        QMessageBox.information(
            self,
            self._t("Eksport konfiguracji"),
            self._t("Zapisano konfigurację bez hasła MQTT."),
        )

    def _import_configuration(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self._t("Import konfiguracji"),
            str(self.store.data_dir),
            "JSON (*.json)",
        )
        if not file_name:
            return
        try:
            imported = import_configuration(Path(file_name), self.password.text())
        except (OSError, ValueError) as exc:
            message = "\n".join(self._t(line) for line in str(exc).splitlines())
            QMessageBox.warning(self, self._t("Import konfiguracji"), message)
            return
        answer = QMessageBox.question(
            self,
            self._t("Import konfiguracji"),
            self._t(
                "Zaimportować ustawienia i zastosować je teraz? Hasło MQTT pozostanie bez zmian."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._load_config(imported)
        self.save_and_apply()

    def _reset_default_settings(self) -> None:
        answer = QMessageBox.question(
            self,
            self._t("Przywrócić ustawienia domyślne?"),
            self._t(
                "Domyślne opcje programu zastąpią bieżące ustawienia. Dane MQTT, bezpośrednie połączenie Home Assistant i ID urządzenia zostaną zachowane."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        current = self._config_from_form()
        defaults = AppConfig(
            device_name=current.device_name,
            device_id=current.device_id,
            mqtt=copy.deepcopy(current.mqtt),
            home_assistant=copy.deepcopy(current.home_assistant),
            language=current.language,
        )
        self._load_config(defaults)
        if self.save_and_apply():
            QMessageBox.information(
                self,
                self._t("Ustawienia domyślne"),
                self._t("Przywrócono domyślne ustawienia programu."),
            )

    def _save_diagnostics(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            self._t("Raport diagnostyczny"),
            str(self.store.data_dir / "ha-windows-bridge-diagnostics.json"),
            "JSON (*.json)",
        )
        if not file_name:
            return
        bridge = self.bridge
        report = build_diagnostic_report(
            self._config_from_form(),
            connected=bool(bridge and bridge.connected),
            messages_processed=bridge.messages_processed if bridge else 0,
            log_path=self.store.data_dir / "logs" / "bridge.log",
            extra={
                "selected_applications": len(
                    [card for card in self.app_cards if card.enabled_switch.isChecked()]
                ),
                "nvidia_smi_available": bool(
                    bridge and getattr(bridge.system, "_nvidia_smi", None)
                ),
            },
        )
        try:
            save_diagnostic_report(Path(file_name), report)
        except OSError as exc:
            QMessageBox.warning(self, self._t("Raport diagnostyczny"), str(exc))
            return
        QMessageBox.information(
            self,
            self._t("Raport diagnostyczny"),
            self._t("Zapisano raport bez hasła i tokenów."),
        )

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_dir)))

    @staticmethod
    def _find_uninstaller() -> Path | None:
        if not getattr(sys, "frozen", False):
            return None
        executable_dir = Path(sys.executable).resolve().parent
        exact = executable_dir / "unins000.exe"
        if exact.is_file():
            return exact
        return next(iter(sorted(executable_dir.glob("unins*.exe"))), None)

    def _remember_mqtt_topics(self, *configs: AppConfig) -> None:
        topics: set[str] = set()
        for config in configs:
            topics.update(all_possible_mqtt_topics(config))
        self._known_mqtt_topics.update(topics)
        if not hasattr(self.store, "remember_mqtt_topics"):
            return
        try:
            self.store.remember_mqtt_topics(topics)
        except OSError:
            self.logger.warning("Nie można zapisać historii topiców MQTT")

    def _cleanup_mqtt_only(self) -> None:
        answer = QMessageBox.question(
            self,
            self._t("Wyczyścić dane MQTT?"),
            self._t(
                "Usunąć zachowane topiki utworzone przez HA Windows Bridge? Aplikacja pozostanie zainstalowana."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_mqtt_cleanup(uninstall_after=False)

    def _uninstall_application(self) -> None:
        if self._uninstaller_path is None or not self._uninstaller_path.is_file():
            QMessageBox.warning(
                self, self._t("Odinstalowanie"), self._t("Nie znaleziono deinstalatora.")
            )
            return
        answer = QMessageBox.question(
            self,
            self._t("Odinstalować HA Windows Bridge?"),
            self._t(
                "Czy przed odinstalowaniem wyczyścić zachowane dane MQTT? Wybierz „Nie”, aby odinstalować bez czyszczenia."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        if answer == QMessageBox.StandardButton.No:
            self.stop_bridge()
            self._start_uninstaller()
            return
        self._start_mqtt_cleanup(uninstall_after=True)

    def _start_mqtt_cleanup(self, *, uninstall_after: bool) -> None:
        config = self._config_from_form()
        self.stop_bridge()
        self._cleanup_then_uninstall = uninstall_after
        self.mqtt_cleanup_button.setEnabled(False)
        self.uninstall_button.setEnabled(False)
        self.mqtt_cleanup_button.setText(self._t("Czyszczenie MQTT…"))
        remembered = set(self._known_mqtt_topics)

        def worker() -> None:
            result = cleanup_application_mqtt_data(config, remembered)
            self.signals.cleanup_finished.emit(result)

        threading.Thread(target=worker, name="mqtt-cleanup", daemon=True).start()

    def _mqtt_cleanup_finished(self, result: MqttCleanupResult) -> None:
        uninstall_after = self._cleanup_then_uninstall
        self._cleanup_then_uninstall = False
        self.mqtt_cleanup_button.setText(self._t("Wyczyść dane MQTT"))
        self.mqtt_cleanup_button.setEnabled(True)
        self.uninstall_button.setText(self._t("Odinstaluj aplikację"))
        self.uninstall_button.setEnabled(self._uninstaller_path is not None)
        if result.publish_success:
            if hasattr(self.store, "clear_mqtt_topic_history"):
                self.store.clear_mqtt_topic_history()
            self._known_mqtt_topics.clear()
            self.logger.info(
                "Usunięto %s zachowanych topiców MQTT",
                result.removed_topics,
            )
            message = self._t("Usunięto {count} zachowanych topiców MQTT.").format(
                count=result.removed_topics
            )
            if uninstall_after:
                message += " " + self._t("Zostanie uruchomiony deinstalator.")
            QMessageBox.information(
                self,
                self._t("Wyczyszczono dane MQTT"),
                message,
            )
            if uninstall_after:
                self._start_uninstaller()
            return

        error = self._t(result.error or "Nieznany błąd")
        if not uninstall_after:
            QMessageBox.warning(
                self,
                self._t("Nie udało się wyczyścić MQTT"),
                self._t("Nie udało się usunąć danych MQTT: {error}").format(error=error),
            )
            return
        answer = QMessageBox.warning(
            self,
            self._t("Nie udało się wyczyścić MQTT"),
            self._t("Nie udało się usunąć danych MQTT: {error}\n\nOdinstalować mimo to?").format(
                error=error
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_uninstaller()

    def _start_uninstaller(self) -> None:
        if self._uninstaller_path is None:
            return
        try:
            self.startup.set_enabled(False)
        except OSError:
            self.logger.warning("Nie można wyłączyć autostartu przed odinstalowaniem")
        self.pending_uninstaller = self._uninstaller_path
        self._force_close = True
        self._overlay_desktop_capture.release()
        self._remove_settings_wheel_guard()
        self.tray.hide()
        QApplication.quit()

    def _show_window(self) -> None:
        self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()
        self._refresh_runtime_status()
        self._refresh_resource_usage()
        self._refresh_card_volumes()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self._force_close
            and self.minimize_to_tray_row.switch.isChecked()
            and self.tray.isVisible()
        ):
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self.tray.showMessage(
                    "HA Windows Bridge",
                    "Program nadal działa w zasobniku systemowym.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
                self._tray_notice_shown = True
            return
        self._stop_ui_resources()
        self.stop_bridge()
        if self.overlay_manager is not None:
            self.overlay_manager.close()
            self.overlay_manager = None
        if self.overlay_preview_manager is not None:
            self.overlay_preview_manager.close()
            self.overlay_preview_manager = None
        self._overlay_desktop_capture.release()
        self._remove_settings_wheel_guard()
        event.accept()

    def quit_application(self) -> None:
        self._force_close = True
        self._stop_ui_resources()
        self.stop_bridge()
        if self.overlay_manager is not None:
            self.overlay_manager.close()
            self.overlay_manager = None
        if self.overlay_preview_manager is not None:
            self.overlay_preview_manager.close()
            self.overlay_preview_manager = None
        self._overlay_desktop_capture.release()
        self._remove_settings_wheel_guard()
        self.tray.hide()
        QApplication.quit()

    def _stop_ui_resources(self) -> None:
        self.pages._clear_transition()
        for timer in (self.volume_timer, self.runtime_timer, self.resource_timer, self.save_feedback_timer):
            timer.stop()
        self.signals.blockSignals(True)
        self.logger.removeHandler(self._qt_log_handler)
        self._qt_log_handler.close()
        self._audio_worker.close(timeout=0.1)

    @staticmethod
    def _create_icon() -> QIcon:
        runtime_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        return QIcon(str(runtime_root / "assets" / "icon.png"))
