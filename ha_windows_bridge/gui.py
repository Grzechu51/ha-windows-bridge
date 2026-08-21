from __future__ import annotations

import copy
import logging
import sys
import threading
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .audio import AudioApplication, AudioOutputDevice, WindowsAudioService
from .config import AppConfig, AudioAppConfig, MqttConfig, SettingsStore, slugify
from .discovery import all_possible_mqtt_topics
from .i18n import LocalizedFormatter, set_active_language, translate
from .mqtt_bridge import MqttBridge
from .mqtt_cleanup import MqttCleanupResult, cleanup_application_mqtt_data
from .startup import WindowsStartupManager
from .ui_components import (
    AppCard,
    AudioOutputCard,
    HelpButton,
    MasterVolumeCard,
    MicrophoneCard,
    NavButton,
    SettingRow,
    StatusCard,
    TitleBar,
)


class UiSignals(QObject):
    status = Signal(str, bool)
    log_line = Signal(str)
    audio_apps = Signal(object)
    app_metadata = Signal(object)
    audio_outputs = Signal(object)
    volume_snapshot = Signal(object)
    connection_test = Signal(bool, str)
    cleanup_finished = Signal(object)


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
        self._base_topic_is_automatic = legacy_base_topic or loaded_config.mqtt.base_topic == suggested_topic
        self.current_config = loaded_config
        self.store = store
        self.startup = startup
        self.logger = logger
        self.pending_uninstaller: Path | None = None
        self._uninstaller_path = self._find_uninstaller()
        self._known_mqtt_topics: set[str] = set()
        if hasattr(self.store, "load_mqtt_topic_history"):
            self._known_mqtt_topics.update(self.store.load_mqtt_topic_history())
        self._remember_mqtt_topics(original_config, loaded_config)
        self.audio = WindowsAudioService()
        self.bridge: MqttBridge | None = None
        self.signals = UiSignals()
        self.app_cards: list[AppCard] = []
        self._force_close = False
        self._tray_notice_shown = False
        self._volume_refresh_running = False
        self._last_status_text = "Zatrzymano"
        self._language = "pl"
        self._self_process = psutil.Process()
        self._cpu_count = max(1, psutil.cpu_count(logical=True) or 1)
        self._self_process.cpu_percent(interval=None)

        self.setWindowTitle("HA Windows Bridge")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(980, 660)
        self.resize(1120, 760)
        self.setWindowIcon(self._create_icon())

        self._build_ui()
        self.save_feedback_timer = QTimer(self)
        self.save_feedback_timer.setSingleShot(True)
        self.save_feedback_timer.timeout.connect(self._reset_save_button)
        self._build_tray()
        self._connect_signals()
        self._load_config(self.current_config)
        self._install_log_handler()

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
        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        self.pages.addWidget(self._connection_page())
        self.pages.addWidget(self._applications_page())
        self.pages.addWidget(self._features_page())
        self.pages.addWidget(self._logs_page())
        self.pages.addWidget(self._settings_page())
        body.addWidget(self.pages, 1)
        frame_layout.addLayout(body, 1)

        frame_layout.addWidget(self._build_footer())

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
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 30, 28)
        layout.setSpacing(22)
        header, _ = self._page_header("Połączenie z brokerem MQTT", "Skonfiguruj połączenie z brokerem MQTT.")
        layout.addWidget(header)

        form = QFrame()
        form.setObjectName("connectionForm")
        grid = QGridLayout(form)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(13)
        grid.setColumnMinimumWidth(0, 165)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 82)

        self.device_name = QLineEdit()
        self.device_name.setPlaceholderText("np. Gaming PC")
        self.base_topic = QLineEdit()
        self.base_topic.setPlaceholderText("ha-windows-bridge/gaming_pc")
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.1.10 lub homeassistant.local")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Hasło MQTT")
        self.show_password = QCheckBox("Pokaż")
        self.tls = QCheckBox("Szyfrowane połączenie TLS")
        self.tls.setToolTip(
            "TLS szyfruje login, hasło i wiadomości. Włącz, jeśli broker obsługuje TLS — zwykle na porcie 8883."
        )
        self.tls_help = self._help_button(
            "TLS szyfruje login, hasło i wiadomości przesyłane do brokera. Włącz tę opcję tylko, "
            "jeśli broker obsługuje TLS — zwykle na porcie 8883."
        )
        # Kept in configuration only to locate and remove legacy 0.9 Discovery topics.
        self.discovery_prefix = QLineEdit()
        self.keepalive = QSpinBox()
        self.keepalive.setRange(5, 3600)
        self.keepalive.setSuffix(" s")
        self.keepalive.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.keepalive_help = self._help_button(
            "Keepalive określa, jak często aplikacja potwierdza połączenie z brokerem. LWT dzięki "
            "temu szybciej oznaczy komputer jako offline po utracie połączenia. Zalecane: 10 s."
        )

        rows = (
            ("Nazwa urządzenia", self.device_name),
            ("Główny topic", self.base_topic),
            ("Broker MQTT", self.host),
            ("Port", self.port),
            ("Użytkownik", self.username),
        )
        for row, (label, widget) in enumerate(rows):
            label_widget = QLabel(label)
            label_widget.setObjectName("formLabel")
            grid.addWidget(label_widget, row, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(widget, row, 1, 1, 2)

        password_row = len(rows)
        password_label = QLabel("Hasło")
        password_label.setObjectName("formLabel")
        grid.addWidget(password_label, password_row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.password, password_row, 1)
        grid.addWidget(self.show_password, password_row, 2, Qt.AlignmentFlag.AlignLeft)

        tls_row = password_row + 1
        grid.addWidget(self.tls, tls_row, 1)
        grid.addWidget(self.tls_help, tls_row, 2, Qt.AlignmentFlag.AlignLeft)
        keepalive_row = tls_row + 1
        keepalive_label = QLabel("Keepalive / LWT")
        keepalive_label.setObjectName("formLabel")
        grid.addWidget(keepalive_label, keepalive_row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.keepalive, keepalive_row, 1)
        grid.addWidget(self.keepalive_help, keepalive_row, 2, Qt.AlignmentFlag.AlignLeft)

        form.setMaximumWidth(850)
        layout.addWidget(form, 0, Qt.AlignmentFlag.AlignLeft)

        test_row = QHBoxLayout()
        test_row.setSpacing(18)
        self.test_button = QPushButton("Testuj połączenie")
        self.discovery_button = QPushButton("Opublikuj encje ponownie")
        self.discovery_button.setObjectName("outlineButton")
        self.discovery_button.setEnabled(False)
        self.test_result = QLabel("")
        self.test_result.setObjectName("testResult")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.discovery_button)
        test_row.addWidget(self.test_result, 1)
        test_row.addStretch()
        layout.addLayout(test_row)
        layout.addStretch()
        return self._scroll_page(content)

    def _applications_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 28)
        layout.setSpacing(18)
        header, header_layout = self._page_header(
            "Aplikacje",
            "Wybierz programy, którymi chcesz sterować z Home Assistant.",
        )
        self.scan_apps_button = QPushButton("Wykryj uruchomione")
        self.scan_apps_button.setObjectName("secondaryButton")
        self.scan_apps_button.setFixedWidth(180)
        self.add_exe_button = QPushButton("＋  Dodaj aplikację")
        self.add_exe_button.setObjectName("outlineButton")
        self.add_exe_button.setFixedWidth(160)
        header_layout.addWidget(self.scan_apps_button)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.add_exe_button)
        layout.addWidget(header)

        master_title = QLabel("Głośność systemu")
        master_title.setObjectName("sectionTitle")
        layout.addWidget(master_title)
        audio_cards = QWidget()
        self.audio_cards_layout = QVBoxLayout(audio_cards)
        self.audio_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.audio_cards_layout.setSpacing(12)
        self.master_volume_card = MasterVolumeCard()
        self.audio_cards_layout.addWidget(self.master_volume_card)
        self.microphone_card = MicrophoneCard()
        self.audio_cards_layout.addWidget(self.microphone_card)
        self.audio_output_card = AudioOutputCard()
        self.audio_cards_layout.addWidget(self.audio_output_card)

        self.control_active_row = SettingRow(
            "Sterowanie aktywną aplikacją",
            "Dodaj w Home Assistant suwak kontrolujący program z aktywnym oknem.",
        )
        self.audio_cards_layout.addWidget(self.control_active_row)
        layout.addWidget(audio_cards)

        apps_title = QLabel("Wybrane aplikacje")
        apps_title.setObjectName("sectionTitle")
        layout.addWidget(apps_title)

        self.empty_apps_label = QLabel(
            "Nie wybrano żadnych aplikacji. Uruchom program z dźwiękiem i kliknij „Wykryj uruchomione”."
        )
        self.empty_apps_label.setObjectName("emptyState")
        self.empty_apps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_apps_label.setWordWrap(True)
        layout.addWidget(self.empty_apps_label)

        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch()
        layout.addWidget(self.cards_widget)
        layout.addStretch()
        return self._scroll_page(content)

    def _features_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 30, 28)
        layout.setSpacing(18)
        header, _ = self._page_header(
            "Funkcje",
            "Dodatkowe dane z Windows.",
        )
        layout.addWidget(header)

        multimedia_title = QLabel("Multimedia")
        multimedia_title.setObjectName("sectionTitle")
        layout.addWidget(multimedia_title)
        self.media_player_row = SettingRow(
            "Media Player",
            "Utwórz w Home Assistant odtwarzacz aktywnej sesji multimediów Windows. Wymaga integracji HA Windows Bridge.",
        )
        layout.addWidget(self.media_player_row)

        features_title = QLabel("Dodatkowe sensory")
        features_title.setObjectName("sectionTitle")
        layout.addWidget(features_title)
        self.publish_activity_row = SettingRow(
            "Aktywna aplikacja i pełny ekran",
            "Publikuj nazwę procesu, tytuł aktywnego okna i stan fullscreen.",
        )
        self.publish_idle_row = SettingRow(
            "Czas bezczynności",
            "Publikuj czas od ostatniego użycia klawiatury lub myszy oraz stan PC Active.",
        )
        self.publish_session_lock_row = SettingRow(
            "Stan blokady Windows",
            "Wystaw sensor informujący, czy sesja Windows jest zablokowana.",
        )
        self.publish_system_stats_row = SettingRow(
            "Statystyki systemu",
            "Publikuj użycie CPU, RAM oraz czas działania Windows.",
        )
        self.publish_gpu_stats_row = SettingRow(
            "Telemetria NVIDIA GPU",
            "Publikuj obciążenie, temperaturę, moc i VRAM przez nvidia-smi, jeśli jest dostępne.",
        )
        features_group = QFrame()
        features_group.setObjectName("settingsGroup")
        features_layout = QVBoxLayout(features_group)
        features_layout.setContentsMargins(0, 0, 0, 0)
        features_layout.setSpacing(12)
        for row in (
            self.publish_activity_row,
            self.publish_idle_row,
            self.publish_session_lock_row,
            self.publish_system_stats_row,
            self.publish_gpu_stats_row,
        ):
            features_layout.addWidget(row)
        layout.addWidget(features_group)

        idle_card = QFrame()
        idle_card.setObjectName("settingRow")
        idle_layout = QHBoxLayout(idle_card)
        idle_layout.setContentsMargins(16, 14, 16, 14)
        idle_text = QVBoxLayout()
        idle_title = QLabel("Czas do uznania komputera za nieaktywny")
        idle_title.setObjectName("settingTitle")
        idle_description = QLabel(
            "Po tylu sekundach bez klawiatury lub myszy status „Komputer aktywny” zmieni się na wyłączony."
        )
        idle_description.setObjectName("settingDescription")
        idle_description.setWordWrap(True)
        idle_text.addWidget(idle_title)
        idle_text.addWidget(idle_description)
        idle_layout.addLayout(idle_text, 1)
        self.idle_threshold = QSpinBox()
        self.idle_threshold.setRange(30, 7200)
        self.idle_threshold.setSingleStep(30)
        self.idle_threshold.setSuffix(" s")
        self.idle_threshold.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.idle_threshold.setFixedWidth(125)
        idle_layout.addWidget(self.idle_threshold)
        layout.addWidget(idle_card)
        layout.addStretch()
        return self._scroll_page(content)

    def _logs_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        header, header_layout = self._page_header("Logi", "Podgląd zdarzeń aplikacji, MQTT i Windows Core Audio.")
        clear_button = QPushButton("Wyczyść")
        clear_button.setObjectName("outlineButton")
        clear_button.clicked.connect(self.logs_clear)
        open_button = QPushButton("Otwórz folder logów")
        open_button.setObjectName("outlineButton")
        open_button.clicked.connect(self._open_logs_folder)
        header_layout.addWidget(clear_button)
        header_layout.addSpacing(8)
        header_layout.addWidget(open_button)
        layout.addWidget(header)
        self.logs = QPlainTextEdit()
        self.logs.setObjectName("logViewer")
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(1500)
        layout.addWidget(self.logs, 1)
        return content

    def _settings_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 24, 30, 28)
        layout.setSpacing(18)
        header, _ = self._page_header("Ustawienia", "Uruchamianie, synchronizacja i dane aplikacji.")
        layout.addWidget(header)

        status_title = QLabel("Status")
        status_title.setObjectName("sectionTitle")
        layout.addWidget(status_title)
        self.status_card = StatusCard()
        layout.addWidget(self.status_card)

        startup_title = QLabel("Uruchamianie")
        startup_title.setObjectName("sectionTitle")
        layout.addWidget(startup_title)
        self.start_with_windows_row = SettingRow(
            "Uruchom przy starcie systemu",
            "Aplikacja będzie uruchamiana automatycznie razem z Windowsem.",
        )
        self.start_minimized_row = SettingRow(
            "Uruchom zminimalizowaną",
            "Po autostarcie aplikacja pojawi się tylko w zasobniku systemowym.",
        )
        self.minimize_to_tray_row = SettingRow(
            "Minimalizuj do zasobnika",
            "Zamknięcie głównego okna pozostawi aplikację działającą w tle.",
        )
        self.auto_connect_row = SettingRow(
            "Łącz automatycznie",
            "Usługa MQTT uruchomi się automatycznie po starcie aplikacji.",
        )
        startup_group = QFrame()
        startup_group.setObjectName("settingsGroup")
        startup_layout = QVBoxLayout(startup_group)
        startup_layout.setContentsMargins(0, 0, 0, 0)
        startup_layout.setSpacing(12)
        for row in (
            self.start_with_windows_row,
            self.start_minimized_row,
            self.minimize_to_tray_row,
            self.auto_connect_row,
        ):
            startup_layout.addWidget(row)
        layout.addWidget(startup_group)

        sync_title = QLabel("Synchronizacja")
        sync_title.setObjectName("sectionTitle")
        layout.addWidget(sync_title)
        self.publish_initial_row = SettingRow(
            "Wyślij stan po połączeniu",
            "Po starcie komputera prześlij do Home Assistant bieżące poziomy głośności.",
        )

        poll_card = QFrame()
        poll_card.setObjectName("settingRow")
        poll_layout = QHBoxLayout(poll_card)
        poll_layout.setContentsMargins(16, 14, 16, 14)
        poll_text = QVBoxLayout()
        poll_title = QLabel("Interwał odczytu głośności")
        poll_title.setObjectName("settingTitle")
        poll_description = QLabel("Jak często aplikacja sprawdza zmiany w mikserze Windows.")
        poll_description.setObjectName("settingDescription")
        poll_text.addWidget(poll_title)
        poll_text.addWidget(poll_description)
        poll_layout.addLayout(poll_text, 1)
        self.poll_interval = QDoubleSpinBox()
        self.poll_interval.setRange(0.2, 10.0)
        self.poll_interval.setSingleStep(0.1)
        self.poll_interval.setDecimals(1)
        self.poll_interval.setSuffix(" s")
        self.poll_interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.poll_interval.setFixedWidth(125)
        poll_layout.addWidget(self.poll_interval)

        sync_group = QFrame()
        sync_group.setObjectName("settingsGroup")
        sync_layout = QVBoxLayout(sync_group)
        sync_layout.setContentsMargins(0, 0, 0, 0)
        sync_layout.setSpacing(12)
        sync_layout.addWidget(self.publish_initial_row)
        sync_layout.addWidget(poll_card)
        layout.addWidget(sync_group)

        general_title = QLabel("Ogólne")
        general_title.setObjectName("sectionTitle")
        layout.addWidget(general_title)

        language_card = QFrame()
        language_card.setObjectName("settingRow")
        language_layout = QHBoxLayout(language_card)
        language_layout.setContentsMargins(16, 14, 16, 14)
        language_text = QVBoxLayout()
        language_title = QLabel("Język")
        language_title.setObjectName("settingTitle")
        language_description = QLabel(
            "Język interfejsu zmienia się od razu i zostanie zapamiętany po zapisaniu."
        )
        language_description.setObjectName("settingDescription")
        language_text.addWidget(language_title)
        language_text.addWidget(language_description)
        language_layout.addLayout(language_text, 1)
        self.language_combo = QComboBox()
        self.language_combo.addItem("Polski", "pl")
        self.language_combo.addItem("English", "en")
        self.language_combo.setFixedWidth(150)
        language_layout.addWidget(self.language_combo)

        data_card = QFrame()
        data_card.setObjectName("dataCard")
        data_layout = QHBoxLayout(data_card)
        data_text = QVBoxLayout()
        data_title = QLabel("Dane aplikacji")
        data_title.setObjectName("settingTitle")
        self.config_path_label = QLabel(str(self.store.config_path))
        self.config_path_label.setObjectName("settingDescription")
        self.config_path_label.setWordWrap(True)
        data_text.addWidget(data_title)
        data_text.addWidget(self.config_path_label)
        data_layout.addLayout(data_text, 1)
        open_data = QPushButton("Otwórz folder")
        open_data.setObjectName("outlineButton")
        open_data.clicked.connect(self._open_data_folder)
        data_layout.addWidget(open_data)

        license_card = QFrame()
        license_card.setObjectName("dataCard")
        license_layout = QHBoxLayout(license_card)
        license_text = QVBoxLayout()
        license_title = QLabel("Kod źródłowy i licencja")
        license_title.setObjectName("settingTitle")
        license_description = QLabel(
            "GNU AGPL-3.0. Program jest dostarczany bez gwarancji."
        )
        license_description.setObjectName("settingDescription")
        license_text.addWidget(license_title)
        license_text.addWidget(license_description)
        license_layout.addLayout(license_text, 1)
        open_source = QPushButton("Otwórz GitHub")
        open_source.setObjectName("outlineButton")
        open_source.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://github.com/Grzechu51/ha-windows-bridge")
            )
        )
        license_layout.addWidget(open_source)

        general_group = QFrame()
        general_group.setObjectName("settingsGroup")
        general_layout = QVBoxLayout(general_group)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(12)
        general_layout.addWidget(language_card)
        general_layout.addWidget(data_card)
        general_layout.addWidget(license_card)
        layout.addWidget(general_group)

        uninstall_title = QLabel("Odinstalowanie")
        uninstall_title.setObjectName("sectionTitle")
        layout.addWidget(uninstall_title)
        uninstall_card = QFrame()
        uninstall_card.setObjectName("uninstallCard")
        uninstall_layout = QHBoxLayout(uninstall_card)
        uninstall_layout.setContentsMargins(16, 14, 16, 14)
        uninstall_text = QVBoxLayout()
        uninstall_name = QLabel("Odinstalowanie")
        uninstall_name.setObjectName("settingTitle")
        uninstall_description = QLabel(
            "Usuń aplikację oraz znane topiki MQTT zapisane przez HA Windows Bridge."
        )
        uninstall_description.setObjectName("settingDescription")
        uninstall_description.setWordWrap(True)
        uninstall_text.addWidget(uninstall_name)
        uninstall_text.addWidget(uninstall_description)
        uninstall_layout.addLayout(uninstall_text, 1)
        self.uninstall_button = QPushButton("Wyczyść MQTT i odinstaluj")
        self.uninstall_button.setObjectName("dangerButton")
        self.uninstall_button.setEnabled(self._uninstaller_path is not None)
        if self._uninstaller_path is None:
            self.uninstall_button.setToolTip(
                "Odinstalator jest dostępny tylko po zainstalowaniu aplikacji instalatorem."
            )
        uninstall_layout.addWidget(self.uninstall_button)
        layout.addWidget(uninstall_card)
        layout.addStretch()
        return self._scroll_page(content)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        self.tray_status = QAction("● Zatrzymano", menu)
        self.tray_status.setEnabled(False)
        open_action = menu.addAction("Otwórz")
        self.tray_toggle = menu.addAction("Uruchom usługę")
        reconnect_action = menu.addAction("Połącz ponownie")
        menu.addSeparator()
        quit_action = menu.addAction("Zakończ")
        menu.insertAction(open_action, self.tray_status)
        open_action.triggered.connect(self._show_window)
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
        self.title_bar.menu_clicked.connect(self._toggle_sidebar)
        self.show_password.toggled.connect(
            lambda checked: self.password.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        for editor in (self.host, self.username, self.password):
            editor.textChanged.connect(self._clear_test_result)
        for editor in (self.port, self.keepalive):
            editor.valueChanged.connect(self._clear_test_result)
        self.tls.toggled.connect(self._clear_test_result)
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
        self.publish_system_stats_row.switch.toggled.connect(
            self.publish_gpu_stats_row.switch.setEnabled
        )
        self.publish_idle_row.switch.toggled.connect(self.idle_threshold.setEnabled)
        self.test_button.clicked.connect(self.test_mqtt_connection)
        self.discovery_button.clicked.connect(self._republish_discovery)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        self.save_button.clicked.connect(self.save_and_apply)
        self.start_button.clicked.connect(self._toggle_bridge)
        self.uninstall_button.clicked.connect(self._uninstall_application)

    def _language_changed(self, _index: int) -> None:
        self._apply_language(str(self.language_combo.currentData() or "pl"))

    def _apply_language(self, language: str) -> None:
        self._language = language if language in {"pl", "en"} else "pl"
        set_active_language(self._language)
        for button in self.nav_buttons:
            button.set_language(self._language)
        self._translate_widget_tree(self, self._language)
        self.status_card.set_language(self._language)
        displayed = "Połączono" if self.bridge and self.bridge.connected else self._last_status_text
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
        handler.setFormatter(LocalizedFormatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
        self.logger.addHandler(handler)

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def _toggle_sidebar(self) -> None:
        visible = not self.sidebar.isVisible()
        self.sidebar.setVisible(visible)
        self.sidebar_footer.setVisible(visible)

    def _load_config(self, config: AppConfig) -> None:
        self.device_name.setText(config.device_name)
        self.base_topic.setText(config.mqtt.base_topic)
        self.host.setText(config.mqtt.host)
        self.port.setValue(config.mqtt.port)
        self.username.setText(config.mqtt.username)
        self.password.setText(config.mqtt.password)
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
        self.publish_system_stats_row.switch.setChecked(config.publish_system_stats)
        self.publish_gpu_stats_row.switch.setChecked(config.publish_gpu_stats)
        self.publish_gpu_stats_row.switch.setEnabled(config.publish_system_stats)
        self.media_player_row.switch.setChecked(config.media_player_enabled)
        self.master_volume_card.set_feature_enabled(config.control_master_volume)
        self.microphone_card.set_feature_enabled(config.control_microphone)
        self.audio_output_card.set_feature_enabled(config.control_audio_output)
        self.idle_threshold.setEnabled(config.publish_idle)
        language_index = self.language_combo.findData(config.language)
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.language_combo.blockSignals(False)
        for card in list(self.app_cards):
            self._remove_app_card(card)
        for app_config in config.apps:
            self._add_app_card(app_config)
        self._update_empty_state()
        self._apply_language(config.language)

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
            publish_activity=self.publish_activity_row.switch.isChecked(),
            publish_idle=self.publish_idle_row.switch.isChecked(),
            idle_threshold=self.idle_threshold.value(),
            publish_session_lock=self.publish_session_lock_row.switch.isChecked(),
            publish_system_stats=self.publish_system_stats_row.switch.isChecked(),
            publish_gpu_stats=self.publish_gpu_stats_row.switch.isChecked(),
            control_microphone=self.microphone_card.enabled_switch.isChecked(),
            control_audio_output=self.audio_output_card.enabled_switch.isChecked(),
            media_player_enabled=self.media_player_row.switch.isChecked(),
        )

    def save_and_apply(self) -> bool:
        try:
            new_config = self._config_from_form()
            errors = new_config.validation_errors()
            if errors:
                raise ValueError("\n".join(self._t(error) for error in errors))
            self._remember_mqtt_topics(self.current_config, new_config)
            if self.bridge:
                self.bridge.stop()
                self.bridge = None
            self.store.save(new_config)
            self.startup.set_enabled(new_config.start_with_windows)
            self.current_config = copy.deepcopy(new_config)
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
        if self.bridge is not None:
            return
        errors = self.current_config.validation_errors()
        if errors:
            self._set_status("Wymagana konfiguracja", False)
            self._switch_page(self.CONNECTION_PAGE)
            return
        try:
            self.bridge = MqttBridge(
                copy.deepcopy(self.current_config),
                audio=self.audio,
                logger=self.logger,
                status_callback=lambda text, connected: self.signals.status.emit(text, connected),
            )
            self.bridge.start()
            self.start_button.setText(self._t("Zatrzymaj usługę"))
            self.tray_toggle.setText(self._t("Zatrzymaj usługę"))
        except Exception as exc:
            self.bridge = None
            self._set_status(f"Błąd: {exc}", False)
            self.logger.exception("Nie można uruchomić usługi")

    def stop_bridge(self) -> None:
        if self.bridge:
            self.bridge.stop()
            self.bridge = None
        self.start_button.setText(self._t("Uruchom usługę"))
        self.tray_toggle.setText(self._t("Uruchom usługę"))
        self.discovery_button.setEnabled(False)
        self._refresh_runtime_status()

    def restart_bridge(self) -> None:
        self.stop_bridge()
        self.start_bridge()

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
        file_name, _ = QFileDialog.getOpenFileName(self, "Wybierz aplikację", "", "Programy Windows (*.exe)")
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
                    card for card in self.app_cards
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

        threading.Thread(target=worker, name="ui-volume-set", daemon=True).start()

    def _set_master_volume(self, value: int) -> None:
        def worker() -> None:
            if self.audio.set_master_volume(value / 100.0):
                self.logger.info("Ustawiono główną głośność na %s%% z interfejsu", value)
            else:
                self.logger.warning("Nie można ustawić głównej głośności Windows")

        threading.Thread(target=worker, name="ui-master-volume-set", daemon=True).start()

    def _set_master_mute(self, muted: bool) -> None:
        threading.Thread(
            target=lambda: self.audio.set_master_mute(muted),
            name="ui-master-mute",
            daemon=True,
        ).start()

    def _set_app_mute(self, process_name: str, muted: bool) -> None:
        threading.Thread(
            target=lambda: self.audio.set_mute(process_name, muted),
            name="ui-app-mute",
            daemon=True,
        ).start()

    def _set_microphone_volume(self, value: int) -> None:
        threading.Thread(
            target=lambda: self.audio.set_microphone_volume(value / 100.0),
            name="ui-microphone-volume",
            daemon=True,
        ).start()

    def _set_microphone_mute(self, muted: bool) -> None:
        threading.Thread(
            target=lambda: self.audio.set_microphone_mute(muted),
            name="ui-microphone-mute",
            daemon=True,
        ).start()

    def _set_audio_output(self, name: str) -> None:
        def worker() -> None:
            if not self.audio.set_output_device(name):
                self.logger.warning("Nie można przełączyć wyjścia audio na %s", name)
            self.signals.audio_outputs.emit(self.audio.list_output_devices())

        threading.Thread(target=worker, name="ui-audio-output", daemon=True).start()

    def _refresh_audio_outputs(self) -> None:
        def worker() -> None:
            self.signals.audio_outputs.emit(self.audio.list_output_devices())

        threading.Thread(target=worker, name="ui-audio-output-refresh", daemon=True).start()

    def _apply_audio_outputs(self, outputs: list[AudioOutputDevice]) -> None:
        names = [output.name for output in outputs]
        current = next((output.name for output in outputs if output.is_default), "")
        self.audio_output_card.set_devices(names, current)

    def _refresh_card_volumes(self) -> None:
        if not self.isVisible() or self._volume_refresh_running:
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
        basic_errors = [error for error in config.validation_errors() if "aplikac" not in error.lower()]
        if basic_errors:
            QMessageBox.warning(self, "Niepełna konfiguracja", "\n".join(basic_errors))
            return
        self.test_button.setEnabled(False)
        self.test_result.setText(self._t("Łączenie…"))

        def worker() -> None:
            ok, message = MqttBridge.test_connection(config)
            self.signals.connection_test.emit(ok, message)

        threading.Thread(target=worker, name="mqtt-test", daemon=True).start()

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
        color = "#49c483" if connected else "#dfa64d" if "Łącz" in text or "ponaw" in text else "#7c8c92"
        self.title_bar.status_dot.setStyleSheet(f"color: {color};")
        self.title_bar.status_label.setText(self._t("Połączono" if connected else text))
        self.footer_status_dot.setStyleSheet(f"color: {color};")
        self.footer_status_label.setText(self._t("Połączono" if connected else text))
        self.tray_status.setText(f"● {self._t(text)}")
        self.discovery_button.setEnabled(connected)
        if connected:
            self.start_button.setText(self._t("Zatrzymaj usługę"))
            self.tray_toggle.setText(self._t("Zatrzymaj usługę"))
        self._refresh_runtime_status()

    def _refresh_runtime_status(self) -> None:
        connected = bool(self.bridge and self.bridge.connected)
        if self.bridge and self.bridge.started_at:
            elapsed = max(0, int(time.monotonic() - self.bridge.started_at))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            messages = self.bridge.messages_processed
        else:
            uptime = "00:00:00"
            messages = 0
        detail = "Połączono z brokerem MQTT" if connected else self._last_status_text
        self.status_card.update_status(connected, detail, uptime, messages)

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
        if self.bridge:
            self.stop_bridge()
            return
        form_config = self._config_from_form()
        if form_config != self.current_config:
            if not self.save_and_apply():
                return
            if self.bridge:
                return
        self.start_bridge()

    def logs_clear(self) -> None:
        self.logs.clear()

    def _open_logs_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.data_dir / "logs")))

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

    def _uninstall_application(self) -> None:
        if self._uninstaller_path is None or not self._uninstaller_path.is_file():
            QMessageBox.warning(self, self._t("Odinstalowanie"), self._t("Nie znaleziono deinstalatora."))
            return
        answer = QMessageBox.question(
            self,
            self._t("Odinstalować HA Windows Bridge?"),
            self._t(
                "Program zatrzyma usługę, usunie znane zachowane topiki MQTT utworzone przez "
                "HA Windows Bridge i uruchomi deinstalator."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        config = self._config_from_form()
        self.stop_bridge()
        self.uninstall_button.setEnabled(False)
        self.uninstall_button.setText(self._t("Czyszczenie MQTT…"))
        remembered = set(self._known_mqtt_topics)

        def worker() -> None:
            result = cleanup_application_mqtt_data(config, remembered)
            self.signals.cleanup_finished.emit(result)

        threading.Thread(target=worker, name="mqtt-cleanup", daemon=True).start()

    def _mqtt_cleanup_finished(self, result: MqttCleanupResult) -> None:
        self.uninstall_button.setText(self._t("Wyczyść MQTT i odinstaluj"))
        self.uninstall_button.setEnabled(self._uninstaller_path is not None)
        proceed = False
        if result.publish_success:
            if hasattr(self.store, "clear_mqtt_topic_history"):
                self.store.clear_mqtt_topic_history()
            self._known_mqtt_topics.clear()
            self.logger.info(
                "Usunięto %s zachowanych topiców MQTT przed odinstalowaniem",
                result.removed_topics,
            )
            QMessageBox.information(
                self,
                self._t("Wyczyszczono dane MQTT"),
                self._t(
                    "Usunięto {count} zachowanych topiców MQTT. Zostanie uruchomiony deinstalator."
                ).format(count=result.removed_topics),
            )
            proceed = True
        else:
            answer = QMessageBox.warning(
                self,
                self._t("Nie udało się wyczyścić MQTT"),
                self._t("Nie udało się usunąć danych MQTT: {error}\n\nOdinstalować mimo to?").format(
                    error=self._t(result.error or "Nieznany błąd")
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            proceed = answer == QMessageBox.StandardButton.Yes
        if proceed:
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
        self.tray.hide()
        QApplication.quit()

    def _show_window(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        self._refresh_runtime_status()
        self._refresh_resource_usage()
        self._refresh_card_volumes()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_window()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._force_close and self.minimize_to_tray_row.switch.isChecked() and self.tray.isVisible():
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
        self.stop_bridge()
        event.accept()

    def quit_application(self) -> None:
        self._force_close = True
        self.stop_bridge()
        self.tray.hide()
        QApplication.quit()

    @staticmethod
    def _create_icon() -> QIcon:
        runtime_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return QIcon(str(runtime_root / "assets" / "icon.png"))
