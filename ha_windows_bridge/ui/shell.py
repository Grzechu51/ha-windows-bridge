"""Native desktop shell. Owns widgets, not backend services."""
from __future__ import annotations

import copy
import json
import time
from enum import IntEnum
from html import escape
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..communication.state import ConnectionStatus
from ..communication.status import CONNECTION_NAMES, connection_text
from ..config import AppConfig, AudioAppConfig, TrackedDeviceConfig, slugify
from ..core.configuration import ConfigurationStore
from ..i18n import set_active_language, translate
from ..overlays.monitors import monitor_id_from_label
from ..ui_components import AppCard, MasterVolumeCard, SettingControlRow, SettingRow
from .inputs import SettingsWheelGuard
from .navigation import PageStack

FEATURES = (
    ("publish_cpu_stats", "Procesor"), ("publish_ram_stats", "Pamięć RAM"),
    ("publish_gpu_stats", "Karta graficzna"), ("publish_windows_health", "Kondycja Windows"),
    ("publish_disk_stats", "Dyski"), ("publish_devices", "Urządzenia"),
    ("publish_activity", "Aktywne okno i aplikacja"), ("publish_idle", "Bezczynność"),
    ("publish_session_lock", "Blokada sesji"), ("control_master_volume", "Głośność Windows"),
    ("control_microphone", "Mikrofon"), ("control_audio_output", "Wyjście audio"),
    ("control_active_app", "Głośność aktywnej aplikacji"), ("media_player_enabled", "Odtwarzacz multimediów"),
    ("audio_enhancements_enabled", "Rozszerzenia audio"), ("control_channel_balance", "Balans kanałów"),
    ("publish_audio_sessions", "Liczba sesji audio"), ("allow_power_actions", "Zdalne zasilanie komputera"),
    ("enable_windows_notifications", "Powiadomienia Windows"),
)
PAGES = ("Start", "Przegląd", "Komputer", "Aplikacje", "Powiadomienia", "Ustawienia", "Diagnostyka")


class Page(IntEnum):
    ONBOARDING = 0
    OVERVIEW = 1
    COMPUTER = 2
    FEATURES = 2
    APPLICATIONS = 3
    OVERLAYS = 4
    SETTINGS = 5
    DIAGNOSTICS = 6


class UiEvents(QObject):
    received = Signal(object)


class DesktopWindow(QMainWindow):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.applied = copy.deepcopy(application.config)
        self.draft = copy.deepcopy(application.config)
        self._pending_apply = None
        self._refreshing = False
        self._last_error = ""
        self._last_apply_error_code = None
        self.setWindowTitle("HA Windows Bridge")
        self.setWindowIcon(qta.icon("mdi6.lan-connect"))
        self.setMinimumSize(700, 520)
        self.resize(1040, 720)
        self._signals = UiEvents(self)
        self._signals.received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        ui_topics = (
            "inventory.disks", "inventory.devices", "inventory.applications",
            "resources.updated", "notification.show", "updates.checked",
            "log.appended", "windows.explorer_restarted", "windows.theme_changed",
            "audio.snapshot", "computer_state.changed", "connection.changed",
            "services.changed", "inventory.published", "sensors.paused",
            "application.running", "configuration.changed", "application.error",
            "command.result", "configuration.apply_finished", "configuration.apply_progress", "overlay.lifecycle", "windows.activate_requested",
            "notifications.quiet", "ui.theme_preview", "overlay.monitors_changed",
        )
        self._unsubscribers = [
            application.events.subscribe(topic, self._signals.received.emit)
            for topic in ui_topics
        ]
        self._wheel_guard = SettingsWheelGuard(self)
        QApplication.instance().installEventFilter(self._wheel_guard)
        self._toggles = {}
        self._fields = {}
        self._cards = []
        self._dismissed_apps = set()
        self._connection_states = {item["transport"]: ConnectionStatus(**item) for item in application.connection_snapshot()}
        self._last_overlay_id = "phase5-local-preview"
        self._local_overlay_command_id = None
        self._local_overlay_pending_id = None
        self._local_overlay_pending_action = None
        self._local_overlay_presented = False
        self._last_overlay_render = None
        self._last_resource_usage = None
        self._local_app_commands = {}
        self._connection_test_pending = False
        self._connection_test_expected = set()
        self._connection_test_states = {}
        self._connection_test_id = 0
        self._connection_test_note = ""
        self._force_close = False
        self._disposed = False
        self._build()
        self._tray()
        self._page_timer = QTimer(self)
        self._page_timer.timeout.connect(self._refresh_visible_page)
        self._state_timer = QTimer(self)
        self._state_timer.timeout.connect(self._refresh_timed_state)
        self._state_timer.start(1000)
        self.navigation.currentRowChanged.connect(self._activate_page)
        self._refresh_logs()
        self._translate_static(self.draft.language)
        self._refresh_master_audio()
        self._refresh_computer_state()
        self._refresh_status()

    def _build(self):
        root = QFrame()
        root.setObjectName("windowFrame")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigationRail")
        self.navigation.setAccessibleName("Główna nawigacja")
        self.navigation.addItems(PAGES)
        self.navigation.setFixedWidth(176)
        self.navigation.setIconSize(QSize(20, 20))
        icons = ("rocket-launch-outline", "view-dashboard-outline", "monitor-dashboard", "apps",
                 "message-badge-outline", "cog-outline", "text-box-search-outline")
        self._navigation_icons = icons
        self._refresh_navigation_icons()
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 12, 10, 12)
        sidebar_layout.addWidget(self.navigation, 1)
        self.pages = PageStack()
        for title in PAGES:
            page = QWidget()
            content = QVBoxLayout(page)
            content.setContentsMargins(18, 18, 18, 18)
            content.setSpacing(12)
            header = QLabel(title)
            header.setObjectName("pageTitle")
            content.addWidget(header)
            scroll = QScrollArea()
            scroll.setObjectName("pageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(Page.ONBOARDING)
        body.addWidget(sidebar)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 8, 16, 10)
        self.dirty_status = QLabel("Brak niezapisanych zmian")
        self.dirty_status.setObjectName("statusBadge")
        self.dirty_status.setAccessibleName("Stan zmian ustawień")
        footer.addWidget(self.dirty_status)
        self.status = QLabel("Gotowy")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.discard = self._button("Odrzuć", self._discard)
        self.discard.setAccessibleName("Odrzuć niezapisane zmiany")
        footer.addWidget(self.discard)
        self.save = self._button("Zastosuj", self._save)
        self.save.setObjectName("primaryButton")
        self.save.setAccessibleName("Zastosuj ustawienia")
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.setCentralWidget(root)

        self._onboarding()
        self._dashboard()
        self._computer()
        self._applications()
        self._overlays()
        self._connections()
        self._settings()

        resources, resource_layout = self._card("Zużycie zasobów aplikacji")
        self.resource_usage = QLabel("CPU: —   ·   RAM: —   ·   Wątki: —")
        self.resource_usage.setObjectName("metricValue")
        self.resource_usage.setWordWrap(True)
        resource_layout.addWidget(self.resource_usage)
        self._content(Page.DIAGNOSTICS).addWidget(resources)
        diagnostics, diagnostic_layout = self._card("Stan runtime", f"Wersja {__version__}")
        self.diagnostic_status = QLabel()
        self.diagnostic_status.setWordWrap(True)
        self.diagnostic_status.setTextFormat(Qt.TextFormat.PlainText)
        diagnostic_layout.addWidget(self.diagnostic_status)
        self._content(Page.DIAGNOSTICS).addWidget(diagnostics)
        preview, preview_layout = self._card("Podgląd bezpiecznego eksportu", "Dokładnie te dane trafią do pliku. Treść logów, hosty, użytkownicy, ścieżki i dane aplikacji są pomijane.")
        self.diagnostic_preview = QPlainTextEdit()
        self.diagnostic_preview.setReadOnly(True)
        self.diagnostic_preview.setAccessibleName("Podgląd raportu diagnostycznego")
        self.diagnostic_preview.setMaximumHeight(180)
        preview_layout.addWidget(self.diagnostic_preview)
        self._content(Page.DIAGNOSTICS).addWidget(preview)
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText("Filtruj ostatnie 200 wpisów…")
        self.log_filter.setAccessibleName("Filtr logów")
        self.log_filter.textChanged.connect(self._refresh_logs)
        self._content(Page.DIAGNOSTICS).addWidget(self.log_filter)
        self.logs = QPlainTextEdit()
        self.logs.setObjectName("logViewer")
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(200)
        self.logs.setMinimumHeight(180)
        self.logs.setPlaceholderText("Brak zdarzeń.")
        self._content(Page.DIAGNOSTICS).addWidget(self.logs, 1)
        self._content(Page.DIAGNOSTICS).addWidget(self._button("Eksportuj pokazany raport…", self._diagnostics))
        self._update_dirty()
    def _content(self, index):
        return self.pages.widget(index).widget().layout()

    def _localized(self, polish, english):
        return english if self.draft.language == "en" else polish

    def _apply_failure_message(self, code):
        return self._localized(
            "Nie zastosowano ustawień; wymagane ręczne odzyskanie konfiguracji."
            if code == "configuration_rollback_failed"
            else f"Nie zastosowano ustawień; sprawdź stan usług i diagnostykę ({code}).",
            "Settings were not applied; manual configuration recovery is required."
            if code == "configuration_rollback_failed"
            else f"Settings were not applied; check services and diagnostics ({code}).",
        )

    @staticmethod
    def _button(text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _card(self, title, detail=""):
        card = QFrame()
        card.setObjectName("statusCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        name = QLabel(title)
        name.setObjectName("sectionTitle")
        description = QLabel(detail)
        description.setObjectName("settingDescription")
        description.setWordWrap(True)
        layout.addWidget(name)
        if detail:
            layout.addWidget(description)
        else:
            description.deleteLater()
        return card, layout

    def _onboarding(self):
        layout = self._content(Page.ONBOARDING)
        intro, inner = self._card("Połącz komputer w 3 krokach", "Możesz skonfigurować wszystko lokalnie i przetestować powiadomienie przed połączeniem z Home Assistant.")
        self.channel = QComboBox()
        self.channel.setAccessibleName("Kanał połączenia")
        self.channel.setMaximumWidth(480)
        self.channel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.channel.addItem("MQTT — pełny produkt: sensory, audio i sterowanie", "mqtt")
        self.channel.addItem("Direct — tylko powiadomienia ekranowe", "direct")
        self.channel.addItem("Lokalnie — konfiguracja bez połączenia", "local")
        initial = "mqtt" if self.draft.mqtt.host else "direct" if self.draft.home_assistant.enabled else "local"
        self.channel.setCurrentIndex(self.channel.findData(initial))
        inner.addWidget(QLabel("1. Wybierz kanał"))
        inner.addWidget(self.channel)
        steps = QLabel("2. Uzupełnij połączenie w Ustawieniach.  3. Wybierz dane i uprawnienia na stronie Komputer.")
        steps.setWordWrap(True)
        inner.addWidget(steps)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Połączenie", lambda: self.navigation.setCurrentRow(Page.SETTINGS)))
        actions.addWidget(self._button("Funkcje", lambda: self.navigation.setCurrentRow(Page.COMPUTER)))
        self.onboarding_test = self._button("Test lokalny", self._preview_overlay)
        self.onboarding_test.setAccessibleName("Wyświetl lokalne powiadomienie testowe")
        actions.addWidget(self.onboarding_test)
        self.connection_test = self._button("Test połączenia", self._test_connection)
        self.connection_test.setAccessibleName("Test zastosowanego połączenia")
        actions.addWidget(self.connection_test)
        inner.addLayout(actions)
        self.onboarding_result = QLabel("Test wymaga zastosowanej opcji Wiadomości na ekranie.")
        self.onboarding_result.setWordWrap(True)
        self.onboarding_result.setAccessibleName("Wynik testu lokalnego")
        inner.addWidget(self.onboarding_result)
        self.connection_test_result = QLabel("Test używa zastosowanej konfiguracji.")
        self.connection_test_result.setWordWrap(True)
        self.connection_test_result.setAccessibleName("Wynik testu połączenia")
        inner.addWidget(self.connection_test_result)
        layout.addWidget(intro)
        layout.addStretch()
        self.channel.currentIndexChanged.connect(self._channel_changed)

    def _channel_changed(self):
        channel = self.channel.currentData()
        if channel == "mqtt":
            self.draft.home_assistant.enabled = False
        elif channel == "direct":
            self.draft.home_assistant.enabled = True
            self.draft.overlay_enabled = True
        else:
            self.draft.home_assistant.enabled = False
            self.draft.mqtt.host = ""
        self._refresh_fields()
        self._update_dirty()

    def _test_connection(self):
        if self._pending_apply is not None:
            self.connection_test_result.setText(self._localized("Poczekaj na wynik stosowania ustawień.", "Wait for the settings apply result."))
            return
        connection_changed = (
            self.draft.mqtt != self.applied.mqtt
            or self.draft.home_assistant != self.applied.home_assistant
            or self.draft.overlay_enabled != self.applied.overlay_enabled
        )
        self._connection_test_note = self._localized(
            "Test używa zastosowanego serwera i danych logowania. Zastosuj zmiany, aby przetestować nowe. ",
            "Testing the applied server and credentials. Apply changes to test the new ones. ",
        ) if connection_changed else ""
        if not self.applied.mqtt.host and not self.applied.home_assistant.enabled:
            self.connection_test_result.setText(self._localized("Skonfiguruj i zastosuj kanał połączenia przed testem.", "Configure and apply a connection channel before testing."))
            return
        self._connection_test_expected = ({"mqtt"} if self.applied.mqtt.host else set())
        if self.applied.home_assistant.enabled:
            self._connection_test_expected.add("home_assistant")
        self._connection_test_states = {}
        self._connection_test_id += 1
        request_id = self._connection_test_id
        self._connection_test_pending = True
        accepted = self.application.reconnect() if self.application.supervisor.active else self.application.start()
        if not accepted:
            self._connection_test_pending = False
        self.connection_test_result.setText(self._connection_test_note + self._localized(
            "Test połączenia rozpoczęty; oczekiwanie na stan kanału…" if accepted else "Nie udało się rozpocząć testu połączenia.",
            "Connection test started; waiting for channel status…" if accepted else "Could not start the connection test.",
        ))
        if accepted:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda rid=request_id: self._connection_test_timeout(rid))
            timer.start(15000)

    def _connection_test_timeout(self, request_id):
        if self._disposed or request_id != self._connection_test_id or not self._connection_test_pending:
            return
        self._connection_test_pending = False
        self.connection_test_result.setText(self._connection_test_note + self._localized("Test połączenia: przekroczono czas oczekiwania. Sprawdź stan kanału i diagnostykę.", "Connection test timed out. Check channel status and diagnostics."))

    def _dashboard(self):
        layout = self._content(Page.OVERVIEW)
        hero, hero_layout = self._card(self.applied.device_name, "Bieżący stan aplikacji — bez domyślania dostarczenia po stronie Home Assistant")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setAccessibleName("Stan kanałów połączenia")
        hero_layout.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Uruchom", self.application.start))
        actions.addWidget(self._button("Zatrzymaj", self.application.stop))
        actions.addWidget(self._button("Połącz ponownie", self.application.reconnect))
        hero_layout.addLayout(actions)
        layout.addWidget(hero)
        health, health_layout = self._card("Zdrowie i świeżość", "Stan lokalnych danych i czas ostatniej aktualizacji.")
        self.overview_health = QLabel()
        self.overview_health.setWordWrap(True)
        self.overview_health.setTextFormat(Qt.TextFormat.PlainText)
        health_layout.addWidget(self.overview_health)
        layout.addWidget(health)
        capabilities, capability_layout = self._card("Skonfigurowane funkcje", "Pokazuje ustawienia zastosowane w działającej aplikacji.")
        self.capability_summary = QLabel()
        self.capability_summary.setWordWrap(True)
        capability_layout.addWidget(self.capability_summary)
        layout.addWidget(capabilities)
        error, error_layout = self._card("Ostatni problem")
        self.last_error = QLabel("Brak zarejestrowanych błędów.")
        self.last_error.setWordWrap(True)
        error_layout.addWidget(self.last_error)
        recovery = QHBoxLayout()
        recovery.addWidget(self._button("Sprawdź ustawienia", lambda: self.navigation.setCurrentRow(Page.SETTINGS)))
        recovery.addWidget(self._button("Otwórz diagnostykę", lambda: self.navigation.setCurrentRow(Page.DIAGNOSTICS)))
        error_layout.addLayout(recovery)
        layout.addWidget(error)
        layout.addStretch()
        self.connections = self.summary

    def _computer(self):
        content = self._content(Page.COMPUTER)
        self.master_audio = MasterVolumeCard()
        self.master_audio.setAccessibleName("Głośność systemu Windows")
        self.master_audio.volume_requested.connect(
            lambda value: self.application.command("audio.master.volume", {"value": value / 100})
        )
        self.master_audio.mute_requested.connect(
            lambda muted: self.application.command("audio.master.mute", {"value": muted})
        )
        content.addWidget(self.master_audio)
        groups = {
            "System": {"publish_cpu_stats", "publish_ram_stats", "publish_gpu_stats", "publish_windows_health", "publish_disk_stats"},
            "Obecność i prywatność": {"publish_activity", "publish_idle", "publish_session_lock"},
            "Urządzenia": {"publish_devices"},
            "Audio i sterowanie": {key for key, _title in FEATURES} - {"publish_cpu_stats", "publish_ram_stats", "publish_gpu_stats", "publish_windows_health", "publish_disk_stats", "publish_activity", "publish_idle", "publish_session_lock", "publish_devices"},
        }
        by_key = dict(FEATURES)
        self.feature_values = {}
        for title, keys in groups.items():
            card, inner = self._card(title)
            for key in (key for key, _label in FEATURES if key in keys):
                row = SettingRow(by_key[key], self._feature_detail(key))
                row.switch.setChecked(bool(self._get(key)))
                row.switch.setAccessibleName(f"Udostępniaj: {by_key[key]}")
                row.switch.toggled.connect(lambda _checked=False, selected=key: self._feature_changed(selected))
                self._toggles[key] = row.switch
                inner.addWidget(row)
                value = QLabel()
                value.setObjectName("dataLabel")
                value.setWordWrap(True)
                value.setAccessibleName(f"Stan funkcji: {by_key[key]}")
                self.feature_values[key] = value
                inner.addWidget(value)
                if key in {"publish_disk_stats", "publish_devices"}:
                    kind = "disks" if key == "publish_disk_stats" else "devices"
                    inner.addWidget(self._button("Wybierz dyski…" if kind == "disks" else "Wybierz urządzenia…", lambda _checked=False, selected=kind: self.application.request_inventory(selected)))
            content.addWidget(card)
        content.addStretch()

    @staticmethod
    def _feature_detail(key):
        if key == "publish_activity":
            return "Prywatność: może ujawniać nazwę aktywnej aplikacji i okna."
        if key in {"allow_power_actions", "enable_windows_notifications"}:
            return "Jawne uprawnienie dla zdalnej akcji Home Assistant."
        return "Bieżąca wartość, źródło i czas ostatniej aktualizacji są pokazane poniżej."

    def _feature_changed(self, key):
        self._set(key, self._toggles[key].isChecked())
        if key == "control_master_volume":
            self.master_audio.set_feature_enabled(self.applied.control_master_volume)
        self._update_dirty()

    def _connections(self):
        layout = self._content(Page.SETTINGS)
        card, inner = self._card("MQTT", "Pełny kanał: sensory, audio i sterowanie komputerem. Stan publikacji nie potwierdza odbioru przez Home Assistant.")
        form = QFormLayout()
        form.setSpacing(10)

        def field(target, key, title, value, password=False, port=False):
            widget = QSpinBox() if port else QLineEdit()
            if port:
                widget.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                widget.setRange(1, 65535)
                widget.setValue(value)
                widget.valueChanged.connect(self._update_dirty)
            else:
                widget.setText(value)
                widget.setEchoMode(QLineEdit.EchoMode.Password if password else QLineEdit.EchoMode.Normal)
                widget.textChanged.connect(self._update_dirty)
            widget.setAccessibleName(title)
            self._fields[key] = widget
            label = QLabel(title)
            label.setBuddy(widget)
            target.addRow(label, widget)
        field(form, "device_name", "Nazwa komputera", self.draft.device_name)
        field(form, "mqtt.host", "Broker", self.draft.mqtt.host)
        field(form, "mqtt.port", "Port", self.draft.mqtt.port, port=True)
        field(form, "mqtt.username", "Użytkownik", self.draft.mqtt.username)
        field(form, "mqtt.password", "Hasło", self.draft.mqtt.password, password=True)
        field(form, "mqtt.base_topic", "Topic urządzenia", self.draft.mqtt.base_topic)
        consequences = QLabel("Zmiana serwera lub użytkownika wymaga Zastosuj i ponownego połączenia. Zapisane hasło nie jest przenoszone na inny serwer.")
        consequences.setWordWrap(True)
        inner.addWidget(consequences)
        inner.addLayout(form)
        layout.addWidget(card)
        self._toggle(Page.SETTINGS, "mqtt.tls", "Szyfrowanie MQTT (TLS)")
        card, inner = self._card("Direct Home Assistant", "Kanał ograniczony do powiadomień ekranowych; nie publikuje sensorów.")
        direct = QFormLayout()
        field(direct, "home_assistant.url", "Adres HA", self.draft.home_assistant.url)
        field(direct, "home_assistant.token", "Token dostępu", self.draft.home_assistant.token, password=True)
        inner.addLayout(direct)
        identity = QLineEdit(self.draft.device_id)
        identity.setReadOnly(True)
        identity.setAccessibleName("Identyfikator urządzenia")
        inner.addWidget(identity)
        layout.addWidget(card)
        self._toggle(Page.SETTINGS, "home_assistant.enabled", "Włącz Direct")
        self._toggle(Page.SETTINGS, "home_assistant.verify_tls", "Weryfikuj certyfikat HA")
    def _get(self, key):
        current = self.draft
        for part in key.split("."):
            current = getattr(current, part)
        return current

    def _set(self, key, value):
        parts = key.split(".")
        current = self.draft
        for part in parts[:-1]:
            current = getattr(current, part)
        setattr(current, parts[-1], value)

    def _toggle(self, page, key, title):
        row = SettingRow(title, "")
        row.switch.setChecked(bool(self._get(key)))
        row.switch.setAccessibleName(title)
        row.switch.toggled.connect(self._update_dirty)
        self._toggles[key] = row.switch
        self._content(page).addWidget(row)
        return row

    def _applications(self):
        content = self._content(Page.APPLICATIONS)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Dodaj program…", self._add_app))
        actions.addWidget(self._button("Wykryj aktywne", lambda: self.application.request_inventory("applications")))
        content.addLayout(actions)
        self.app_state = QLabel("Stan sesji audio oczekuje na pierwszy lokalny snapshot.")
        self.app_state.setWordWrap(True)
        self.app_state.setAccessibleName("Stan źródła aplikacji audio")
        content.addWidget(self.app_state)
        self._apps_container = QVBoxLayout()
        content.addLayout(self._apps_container)
        for config in self.draft.apps:
            self._add_card(config)
        content.addStretch()

    def _applied_app(self, process_name):
        return next((app for app in self.applied.apps if app.process_name.casefold() == process_name.casefold() and app.enabled), None)

    def _add_card(self, config):
        card = AppCard(config)
        card.more_button.setText("")
        card.more_button.setIcon(qta.icon("mdi6.dots-vertical"))
        card.remove_requested.connect(self._remove_card)
        card.configuration_changed.connect(self._update_dirty)
        applied = self._applied_app(config.process_name)
        card.set_runtime_enabled(applied is not None)
        card.options_menu.addSeparator()
        card.local_start_action = card.options_menu.addAction("Uruchom lokalnie", lambda: self._local_app_command(card, "application.start"))
        card.local_close_action = card.options_menu.addAction("Zamknij lokalnie", lambda: self._local_app_command(card, "application.close"))
        card.local_result = QLabel("Brak lokalnego polecenia.")
        card.local_result.setWordWrap(True)
        card.local_result.setAccessibleName("Wynik lokalnego polecenia aplikacji")
        card.layout().addWidget(card.local_result, 3, 1, 1, 5)
        self._sync_app_actions(card)
        self._translate_card(card, self.draft.language)
        card.volume_requested.connect(
            lambda process, value: self.application.command(
                "application.volume", {"value": value / 100},
                self._applied_app(process).slug if self._applied_app(process) else "",
            )
        )
        card.mute_requested.connect(
            lambda process, muted: self.application.command(
                "application.mute", {"value": muted},
                self._applied_app(process).slug if self._applied_app(process) else "",
            )
        )
        self._cards.append(card)
        self._apps_container.addWidget(card)
    def _sync_app_actions(self, card):
        applied = self._applied_app(card.config.process_name)
        can_start = bool(applied and applied.allow_remote_start and applied.executable_path)
        can_close = bool(applied and applied.allow_remote_close)
        card.local_start_action.setEnabled(can_start)
        card.local_close_action.setEnabled(can_close)
        card.local_start_action.setToolTip(self._localized("Wymaga zastosowanej ścieżki EXE i uprawnienia uruchamiania.", "Requires an applied EXE path and start permission.") if not can_start else applied.executable_path)
        card.local_close_action.setToolTip(self._localized("Wymaga zastosowanego uprawnienia zamykania.", "Requires applied close permission.") if not can_close else applied.process_name)

    def _local_app_command(self, card, kind):
        applied = self._applied_app(card.config.process_name)
        if applied is None or (kind == "application.start" and not (applied.allow_remote_start and applied.executable_path)) or (kind == "application.close" and not applied.allow_remote_close):
            card.local_result.setText(self._localized("Zastosuj ścieżkę programu i uprawnienia przed poleceniem.", "Apply the program path and permissions before this command."))
            return
        result = self.application.command(kind, {}, applied.slug)
        self._local_app_commands[result.id] = card
        pending = result.code or self._localized("oczekuje na wynik", "awaiting result")
        card.local_result.setText(f"{kind}: {result.status} · {pending}")

    def _add_app(self):
        filename, _ = QFileDialog.getOpenFileName(self, self._localized("Wybierz aplikację", "Choose application"), "", self._localized("Aplikacje (*.exe)", "Applications (*.exe)"))
        if filename:
            path = Path(filename)
            config = AudioAppConfig(path.name, path.stem, slugify(path.stem), True, executable_path=str(path))
            self.draft.apps.append(config)
            self._add_card(config)
            self._update_dirty()

    def _remove_card(self, card):
        self._dismissed_apps.add(card.config.process_name.casefold())
        self._cards.remove(card)
        self._apps_container.removeWidget(card)
        card.deleteLater()
        self._update_dirty()

    def _activate_page(self, _index=None):
        self._page_timer.stop()
        if not self.isVisible():
            return
        self._refresh_visible_page()
        if self.navigation.currentRow() in {Page.DIAGNOSTICS, Page.COMPUTER, Page.OVERVIEW}:
            self._page_timer.start(2000)

    def _refresh_timed_state(self):
        self._refresh_master_audio()
        if self.isVisible() and self.navigation.currentRow() == Page.COMPUTER:
            self._refresh_computer_state()

    def _refresh_visible_page(self):
        if self._disposed or not self.isVisible():
            return
        if self.navigation.currentRow() == Page.COMPUTER:
            self._refresh_computer_state()
        elif self.navigation.currentRow() == Page.OVERVIEW:
            self._refresh_status()
        elif self.navigation.currentRow() == Page.APPLICATIONS:
            self._update_applications_from_state()
        elif self.navigation.currentRow() == Page.DIAGNOSTICS:
            self._refresh_status()
            self.application.request_resources()

    def _update_applications_from_state(self):
        sample = self.application.computer_snapshot().provider("audio")
        if sample is None:
            self.app_state.setText(self._localized("Źródło audio nie jest uruchomione lub nie ma jeszcze próbki.", "Audio source is stopped or has no sample yet."))
            self._update_applications([], discover=False)
            return
        age = max(0, round(time.time() - sample.observed_at))
        if sample.quality.value != "good":
            self.app_state.setText(self._localized(f"Źródło audio: {sample.quality.value}, ostatnia próbka {age} s temu.", f"Audio source: {sample.quality.value}, last sample {age} s ago."))
            self._update_applications([], discover=False)
            return
        self.app_state.setText(self._localized(f"Aktualny lokalny snapshot audio · {age} s temu. Brak sesji jest poprawnym stanem.", f"Current local audio sample · {age} s ago. Zero sessions is valid."))
        self._update_applications(list(sample.value.applications), discover=False)
    def _update_applications(self, items, *, discover=True):
        if self._pending_apply is not None and discover:
            return
        existing = {card.config.process_name.casefold(): card for card in self._cards}
        slugs = {card.config.slug for card in self._cards}
        present = set()
        for item in items[:128]:
            key = item.process_name.casefold()
            if key in self._dismissed_apps:
                continue
            present.add(key)
            card = existing.get(key)
            if card is None and not discover:
                continue
            if card is None:
                if len(self._cards) >= 128:
                    break
                slug = base = slugify(item.display_name)
                suffix = 2
                while slug in slugs:
                    slug = f"{base}_{suffix}"
                    suffix += 1
                slugs.add(slug)
                # Discovery never grants remote access without the user's switch/save.
                self._add_card(AudioAppConfig(item.process_name, item.display_name, slug, False, executable_path=item.executable_path))
                card = self._cards[-1]
                existing[key] = card
            elif item.executable_path:
                # Refresh the displayed icon after app upgrades. Never silently
                # redirect a previously authorised remote-launch executable.
                card.set_executable_icon(item.executable_path, update_config=discover and not card.config.allow_remote_start)
            card.set_volume(item.volume)
            card.set_muted(item.muted)
        for key, card in existing.items():
            if key not in present:
                card.set_volume(None)
                card.set_muted(None)

    def _overlays(self):
        content = self._content(Page.OVERLAYS)
        self._toggle(Page.OVERLAYS, "overlay_enabled", "Wiadomości na ekranie")
        self._toggle(Page.OVERLAYS, "overlay_allow_fullscreen", "Zezwalaj nad pełnym ekranem")
        editor, inner = self._card("Lokalny edytor", "Podgląd korzysta z tej samej kolejki i tych samych zasad co polecenia z Home Assistant. Działa bez sieci, gdy nakładki są zastosowane w runtime.")
        form = QFormLayout()
        self.overlay_title = QLineEdit("Test HA Windows Bridge")
        self.overlay_message = QLineEdit("Lokalny podgląd powiadomienia")
        self.overlay_layout = QComboBox()
        for label, value in (("Kompaktowy", "compact"), ("Standardowy", "standard"), ("Status", "status"), ("Badge", "badge"), ("Media", "media"), ("Kamera", "camera")):
            self.overlay_layout.addItem(label, value)
        self.overlay_monitor = QComboBox()
        for index, label in enumerate(self.application.monitors):
            self.overlay_monitor.addItem(label, index)
        initial_monitor = next(
            (index for index, label in enumerate(self.application.monitors)
             if monitor_id_from_label(label) == self.draft.overlay_monitor_id),
            min(self.applied.overlay_monitor, max(0, self.overlay_monitor.count() - 1)),
        )
        self.overlay_monitor.setCurrentIndex(initial_monitor)
        for label, widget in (("Tytuł", self.overlay_title), ("Wiadomość", self.overlay_message), ("Układ", self.overlay_layout), ("Monitor", self.overlay_monitor)):
            widget.setAccessibleName(label)
            field_label = QLabel(label)
            field_label.setBuddy(widget)
            form.addRow(field_label, widget)
        inner.addLayout(form)
        advanced = QVBoxLayout()
        self.overlay_pinned = SettingRow("Przypięte", "Bez automatycznego zamknięcia")
        self.overlay_close = SettingRow("Przycisk zamknięcia", "Pozwala zamknąć myszą")
        self.overlay_hover = SettingRow("Pauza po najechaniu", "Zatrzymuje czas życia")
        advanced.addWidget(self.overlay_pinned)
        advanced.addWidget(self.overlay_close)
        advanced.addWidget(self.overlay_hover)
        inner.addLayout(advanced)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Podgląd", self._preview_overlay))
        actions.addWidget(self._button("Aktualizuj", self._update_overlay))
        actions.addWidget(self._button("Usuń", self._remove_overlay))
        actions.addWidget(self._button("Wyczyść wszystkie", self._clear_overlays))
        inner.addLayout(actions)
        self.overlay_result = QLabel("Brak lokalnego wyniku cyklu życia.")
        self.overlay_result.setWordWrap(True)
        self.overlay_result.setAccessibleName("Wynik kolejki powiadomień")
        inner.addWidget(self.overlay_result)
        content.addWidget(editor)
        for key, title, choices in (
            ("overlay_animation", "Animacja", (("Przesunięcie", "slide"), ("Przenikanie", "fade"), ("Rozwinięcie", "reveal"), ("Brak", "none"))),
            ("overlay_background_effect", "Tło", (("Jednolite", "none"), ("Rozmycie", "blur"), ("Liquid Glass", "liquid"))),
        ):
            combo = QComboBox()
            for label, value in choices:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(self._get(key))))
            combo.setAccessibleName(title)
            combo.currentIndexChanged.connect(self._update_dirty)
            self._fields[key] = combo
            content.addWidget(SettingControlRow(title, combo))
        spin = QSpinBox()
        spin.setRange(80, 1000)
        spin.setSuffix(" ms")
        spin.setValue(self._get("overlay_animation_duration"))
        spin.setAccessibleName("Czas animacji")
        spin.valueChanged.connect(self._update_dirty)
        self._fields["overlay_animation_duration"] = spin
        content.addWidget(SettingControlRow("Czas animacji", spin))
        duration = QSpinBox()
        duration.setRange(2, 60)
        duration.setSuffix(" s")
        duration.setValue(self._get("overlay_example_duration"))
        duration.setAccessibleName("Czas lokalnego przykładu")
        duration.valueChanged.connect(self._update_dirty)
        self._fields["overlay_example_duration"] = duration
        content.addWidget(SettingControlRow("Czas lokalnego przykładu", duration))
        content.addStretch()

    def _refresh_overlay_monitors(self, labels):
        selected_id = monitor_id_from_label(self.overlay_monitor.currentText()) or self.draft.overlay_monitor_id
        self.overlay_monitor.blockSignals(True)
        self.overlay_monitor.clear()
        for index, label in enumerate(labels):
            self.overlay_monitor.addItem(label, index)
        selected = next((index for index, label in enumerate(labels) if monitor_id_from_label(label) == selected_id), 0)
        self.overlay_monitor.setCurrentIndex(selected)
        self.overlay_monitor.blockSignals(False)
    def _overlay_arguments(self, action):
        data = {"action": action, "id": self._last_overlay_id}
        if action in {"show", "update"}:
            data.update(
                layout=self.overlay_layout.currentData(),
                monitor=self.overlay_monitor.currentData() or 0,
                duration=self.application.config.overlay_example_duration,
                monitor_id=monitor_id_from_label(self.overlay_monitor.currentText()),
                pinned=self.overlay_pinned.switch.isChecked(),
                show_close_button=self.overlay_close.switch.isChecked(),
                pause_on_hover=self.overlay_hover.switch.isChecked(),
            )
        value = {"data": data}
        if action in {"show", "update"}:
            value.update(title=self.overlay_title.text(), message=self.overlay_message.text())
        return value

    def _set_local_overlay_result(self, polish, english):
        self._last_overlay_render = (polish, english)
        message = self._localized(polish, english)
        self.overlay_result.setText(message)
        self.onboarding_result.setText(message)

    def _overlay_command(self, action):
        result = self.application.command("overlay.show", self._overlay_arguments(action))
        accepted = result.status in {"accepted", "pending"}
        self._local_overlay_pending_id = result.id if accepted else None
        self._local_overlay_pending_action = action if accepted else None
        self._local_overlay_command_id = result.id if action == "show" and accepted else None
        self._local_overlay_presented = False
        waiting_pl = "oczekuje na prezentację" if action == "show" else "oczekuje na wynik"
        waiting_en = "awaiting presentation" if action == "show" else "awaiting result"
        self._set_local_overlay_result(
            f"{action}: {result.status} · {result.code or waiting_pl}",
            f"{action}: {result.status} · {result.code or waiting_en}",
        )

    def _preview_overlay(self):
        if not self.application.config.overlay_enabled:
            self._last_overlay_render = None
            self.onboarding_result.setText(self._localized("Włącz Wiadomości na ekranie, zastosuj ustawienia i ponów test.", "Enable on-screen messages, apply settings and retry the test."))
            return
        self._overlay_command("show")

    def _update_overlay(self):
        self._overlay_command("update")

    def _remove_overlay(self):
        self._overlay_command("remove")

    def _clear_overlays(self):
        self._overlay_command("clear")
    def _settings(self):
        content = self._content(Page.SETTINGS)
        for key, label in (("auto_connect", "Łącz automatycznie"), ("start_with_windows", "Uruchamiaj z Windows"),
                           ("start_minimized", "Uruchamiaj w zasobniku"),
                           ("reduced_motion", "Ogranicz animacje"), ("auto_check_updates", "Sprawdzaj aktualizacje")):
            self._toggle(Page.SETTINGS, key, label)
        self.theme = QComboBox()
        for label, value in (("Ciemny", "dark"), ("Jasny", "light"), ("Systemowy", "system")):
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.draft.theme)))
        self.theme.setFixedWidth(220)
        self.theme_row = SettingControlRow("Motyw", self.theme)
        self.theme.setAccessibleName("Motyw")
        self.theme.currentIndexChanged.connect(self._theme_preview)
        content.addWidget(self.theme_row)
        self.language = QComboBox()
        self.language.addItem("Polski", "pl")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(max(0, self.language.findData(self.draft.language)))
        self.language.setAccessibleName("Język")
        self.language.currentIndexChanged.connect(self._language_preview)
        content.addWidget(SettingControlRow("Język", self.language))
        card, inner = self._card("Konfiguracja", "Eksport nie zawiera haseł ani tokenów.")
        inner.addWidget(self._button("Eksportuj ustawienia…", self._export_settings))
        inner.addWidget(self._button("Importuj ustawienia…", self._import_settings))
        inner.addWidget(self._button("Przywróć domyślne ustawienia…", self._reset_settings))
        content.addWidget(card)
        content.addWidget(self._button("Sprawdź aktualizacje", self.application.check_updates))
        content.addStretch()

    def _collect(self):
        self.draft.apps = [card.to_config() for card in self._cards]
        for key, widget in self._fields.items():
            value = widget.currentData() if isinstance(widget, QComboBox) else widget.value() if isinstance(widget, QSpinBox) else widget.text()
            self._set(key, value)
        for key, widget in self._toggles.items():
            self._set(key, widget.isChecked())
        self.draft.theme = self.theme.currentData()
        self.draft.language = self.language.currentData()

    def _update_dirty(self, *_args):
        if self._refreshing:
            return
        self._collect()
        dirty = self.draft != self.applied
        self.dirty_status.setText(translate("Niezapisane zmiany" if dirty else "Brak niezapisanych zmian", self.draft.language))
        self.save.setEnabled(dirty and self._pending_apply is None)
        self.discard.setEnabled(dirty and self._pending_apply is None)

    def _language_preview(self, *_args):
        if self._refreshing:
            return
        self._collect()
        self._translate_static(self.draft.language)
        self._refresh_status()
        if self._last_apply_error_code:
            old = self.last_error.text()
            message = self._apply_failure_message(self._last_apply_error_code)
            if self.status.text() == old:
                self.status.setText(message)
            self._last_error = message
            self.last_error.setText(message)
        self._update_dirty()

    def _translate_static(self, language):
        set_active_language(language)
        for index, source in enumerate(PAGES):
            self.navigation.item(index).setText(translate(source, language))
        dynamic = set(self.feature_values.values()) | {
            self.status, self.dirty_status, self.summary, self.overview_health,
            self.capability_summary, self.last_error, self.app_state,
            self.onboarding_result, self.connection_test_result, self.overlay_result, self.resource_usage,
            self.diagnostic_status,
        }
        for widget in dynamic:
            localized = translate(widget.text(), language)
            if localized != widget.text():
                widget.setText(localized)
        for widget in (*self.findChildren(QLabel), *self.findChildren(QPushButton)):
            if widget in dynamic or self._inside_app_card(widget):
                continue
            source = widget.property("bridgePolishText")
            if source is None:
                source = widget.text()
                widget.setProperty("bridgePolishText", source)
            if source == f"Wersja {__version__}" or source == f"Version {__version__}":
                widget.setText(self._localized(f"Wersja {__version__}", f"Version {__version__}"))
            else:
                widget.setText(translate(source, language))
        for combo in self.findChildren(QComboBox):
            if combo is self.overlay_monitor:
                continue
            for index in range(combo.count()):
                source = combo.itemData(index, Qt.ItemDataRole.UserRole + 1)
                if source is None:
                    source = combo.itemText(index)
                    combo.setItemData(index, source, Qt.ItemDataRole.UserRole + 1)
                combo.setItemText(index, translate(source, language))
        for widget in self.findChildren(QWidget):
            if widget in dynamic or self._inside_app_card(widget):
                continue
            source = widget.property("bridgePolishAccessibleName")
            if source is None:
                source = widget.accessibleName()
                widget.setProperty("bridgePolishAccessibleName", source)
            if source:
                widget.setAccessibleName(translate(source, language))
            if isinstance(widget, QLineEdit) and widget is self.log_filter:
                widget.setPlaceholderText(translate("Filtruj ostatnie 200 wpisów…", language))
        self.logs.setPlaceholderText(translate("Brak zdarzeń.", language))
        for key, title in FEATURES:
            name = translate(title, language)
            self._toggles[key].setAccessibleName(
                f"{translate('Udostępniaj', language)}: {name}"
            )
            self.feature_values[key].setAccessibleName(
                f"{translate('Stan funkcji', language)}: {name}"
            )
        for card in self._cards:
            self._translate_card(card, language)
        if hasattr(self, "tray"):
            for action in self.tray.contextMenu().actions():
                if not action.isEnabled() or not action.text():
                    continue
                source = action.property("bridgePolishText")
                if source is None:
                    source = action.text()
                    action.setProperty("bridgePolishText", source)
                action.setText(translate(source, language))
        if self._last_overlay_render is not None:
            polish, english = self._last_overlay_render
            message = self._localized(polish, english)
            self.overlay_result.setText(message)
            self.onboarding_result.setText(message)
        self._refresh_navigation_icons()
        self._refresh_computer_state()
        self._refresh_resource_usage()

    @staticmethod
    def _translate_card(card, language):
        card.language = language
        localized = translate(card.local_result.text(), language)
        if localized != card.local_result.text():
            card.local_result.setText(localized)
        card.local_result.setAccessibleName(
            translate("Wynik lokalnego polecenia aplikacji", language)
        )
        for action in card.options_menu.actions():
            if not action.text():
                continue
            source = action.property("bridgePolishText")
            if source is None:
                source = action.text()
                action.setProperty("bridgePolishText", source)
            action.setText(translate(source, language))
        for widget in (card.mute_button, card.enabled_switch, card.more_button):
            source = widget.property("bridgePolishTooltip")
            if source is None:
                source = widget.toolTip()
                widget.setProperty("bridgePolishTooltip", source)
            if source:
                widget.setToolTip(translate(source, language))

    @staticmethod
    def _inside_app_card(widget):
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, AppCard):
                return True
            parent = parent.parentWidget()
        return False

    def _refresh_navigation_icons(self):
        if self._disposed:
            return
        app = QApplication.instance()
        colour = app.property("bridgeIcon") if app is not None else None
        colour = colour or "#f4f4f4"
        for index, icon in enumerate(self._navigation_icons):
            self.navigation.item(index).setIcon(qta.icon("mdi6." + icon, color=colour))
    def _theme_preview(self, *_args):
        if self._refreshing:
            return
        self._collect()
        self.application.events.emit("ui.theme_preview", copy.deepcopy(self.draft))
        self._update_dirty()

    def _set_editing_enabled(self, enabled):
        self.pages.setEnabled(enabled)
        self.save.setEnabled(enabled and self.draft != self.applied)
        self.discard.setEnabled(enabled and self.draft != self.applied)

    def _save(self):
        self._collect()
        submitted = copy.deepcopy(self.draft)
        request_id = self.application.request_configuration_apply(submitted)
        if request_id is None:
            self.status.setText("Nie przyjęto zmian. Sprawdź pola i diagnostykę.")
            self._update_dirty()
            return
        self._pending_apply = request_id
        self.status.setText(self._localized("Stosowanie ustawień… edycja jest chwilowo zablokowana.", "Applying settings… editing is temporarily disabled."))
        self._set_editing_enabled(False)

    def _discard(self):
        if self._pending_apply is not None:
            return
        self.draft = copy.deepcopy(self.applied)
        self._refresh_fields()
        self.application.events.emit("ui.theme_preview", copy.deepcopy(self.applied))
        self._translate_static(self.applied.language)
        self.status.setText(self._localized("Odrzucono niezapisane zmiany.", "Unsaved changes discarded."))
        self._update_dirty()

    def _refresh_fields(self):
        self._refreshing = True
        self._local_app_commands.clear()
        try:
            for key, widget in self._fields.items():
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(max(0, widget.findData(self._get(key))))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(self._get(key))
                else:
                    widget.setText(self._get(key))
            for key, widget in self._toggles.items():
                widget.setChecked(self._get(key))
            self.theme.setCurrentIndex(max(0, self.theme.findData(self.draft.theme)))
            self.language.setCurrentIndex(max(0, self.language.findData(self.draft.language)))
            for card in self._cards:
                self._apps_container.removeWidget(card)
                card.deleteLater()
            self._cards.clear()
            for config in self.draft.apps:
                self._add_card(config)
            self.master_audio.set_feature_enabled(self.applied.control_master_volume)
        finally:
            self._refreshing = False
        self._update_dirty()
        self._translate_static(self.draft.language)
    def _export_settings(self):
        filename, _ = QFileDialog.getSaveFileName(self, self._localized("Eksportuj ustawienia", "Export settings"), "bridge-settings.json", "JSON (*.json)")
        if filename:
            self._collect()
            try:
                ConfigurationStore.export(self.draft, Path(filename))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, self._localized("Eksport", "Export"), str(exc))

    def _import_settings(self):
        filename, _ = QFileDialog.getOpenFileName(self, self._localized("Importuj ustawienia 2.0", "Import settings 2.0"), "", "JSON (*.json)")
        if not filename:
            return
        try:
            imported = ConfigurationStore.import_settings(Path(filename))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, self._localized("Import", "Import"), str(exc))
            return
        self._collect()
        # Do not send an existing secret to a different server from an imported file.
        if (imported.mqtt.host, imported.mqtt.port, imported.mqtt.username) == (self.draft.mqtt.host, self.draft.mqtt.port, self.draft.mqtt.username):
            imported.mqtt.password = self.draft.mqtt.password
        if imported.home_assistant.url == self.draft.home_assistant.url:
            imported.home_assistant.token = self.draft.home_assistant.token
        imported.device_id = self.draft.device_id
        self.draft = imported
        self._refresh_fields()
        self.application.events.emit("ui.theme_preview", copy.deepcopy(self.draft))
        self._translate_static(self.draft.language)
        self._update_dirty()
        self.status.setText(self._localized("Wczytano ustawienia. Sprawdź je i wybierz Zapisz i zastosuj.", "Settings imported. Review them and choose Apply."))

    def _reset_settings(self):
        if QMessageBox.question(
            self,
            self._localized("Domyślne ustawienia", "Default settings"),
            self._localized("Przywrócić ustawienia domyślne? Dane połączeń zostaną zachowane.",
                            "Restore default settings? Connection details will be retained."),
        ) != QMessageBox.StandardButton.Yes:
            return
        self._collect()
        self.draft = AppConfig(device_name=self.draft.device_name, device_id=self.draft.device_id,
                               mqtt=copy.deepcopy(self.draft.mqtt), home_assistant=copy.deepcopy(self.draft.home_assistant),
                               start_with_windows=False, auto_connect=False, theme="system")
        self._refresh_fields()
        self.application.events.emit("ui.theme_preview", copy.deepcopy(self.draft))
        self._translate_static(self.draft.language)
        self._update_dirty()
        self.status.setText(self._localized("Przywrócono wartości w formularzu. Zapisz, aby zastosować.", "Default values restored in the form. Apply to save."))

    def _select_inventory(self, kind, items):
        if self._pending_apply is not None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self._localized(
            "Wybierz dyski" if kind == "disks" else "Wybierz urządzenia",
            "Choose disks" if kind == "disks" else "Choose devices",
        ))
        dialog.resize(580, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        selected = set(self.draft.disk_mounts) if kind == "disks" else {device.instance_id for device in self.draft.tracked_devices if device.enabled}
        for device in items:
            identity = device.mountpoint if kind == "disks" else device.instance_id
            item = QListWidgetItem(f"{identity} · {device.total_gb:.0f} GB" if kind == "disks" else f"{device.display_name} · {device.category}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if identity in selected else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, device)
            listing.addItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self._localized("Anuluj", "Cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._localized("Wybierz", "Choose"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and self._pending_apply is None:
            chosen = [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count()) if listing.item(i).checkState() == Qt.CheckState.Checked]
            if kind == "disks":
                self.draft.disk_mounts = [device.mountpoint for device in chosen]
            else:
                visible_ids = {device.instance_id for device in items}
                preserved = [device for device in self.draft.tracked_devices if device.instance_id not in visible_ids]
                self.draft.tracked_devices = preserved + [TrackedDeviceConfig(device.instance_id, device.display_name, device.category) for device in chosen]
            self.status.setText(self._localized("Wybrano urządzenia. Zapisz ustawienia, aby zastosować.", "Selection updated. Apply settings to use it."))
            self._update_dirty()

    def _refresh_resource_usage(self):
        usage = self._last_resource_usage
        if usage is None:
            self.resource_usage.setText(self._localized("CPU: —   ·   RAM: —   ·   Wątki: —",
                                                        "CPU: —   ·   RAM: —   ·   Threads: —"))
        elif usage is False:
            self.resource_usage.setText(self._localized("Zużycie zasobów jest chwilowo niedostępne.",
                                                        "Resource usage is temporarily unavailable."))
        else:
            cpu = "—" if usage["cpu_percent"] is None else f"{usage['cpu_percent']:.1f}%"
            self.resource_usage.setText(self._localized(
                f"CPU: {cpu}   ·   RAM: {usage['memory_mib']:.1f} MiB   ·   Wątki: {usage['threads']}",
                f"CPU: {cpu}   ·   RAM: {usage['memory_mib']:.1f} MiB   ·   Threads: {usage['threads']}",
            ))

    def _refresh_logs(self, *_args):
        query = self.log_filter.text().casefold().strip()
        lines = self.application.diagnostics.snapshot()[-200:]
        self.logs.setPlainText("\n".join(line for line in lines if query in line.casefold()))

    def _diagnostics(self):
        preview = self.diagnostic_preview.toPlainText()
        filename, _ = QFileDialog.getSaveFileName(self, self._localized("Raport diagnostyczny", "Diagnostic report"), "bridge-diagnostics.json", "JSON (*.json)")
        if filename:
            try:
                json.loads(preview)
                Path(filename).write_text(preview, encoding="utf-8")
            except (OSError, ValueError):
                self.status.setText(self._localized("Nie można zapisać raportu w wybranym miejscu.", "Cannot save the report at the selected location."))
            else:
                self.status.setText(self._localized("Zapisano dokładnie pokazany raport diagnostyczny.", "Saved exactly the shown diagnostic report."))
    def _refresh_status(self):
        config = self.application.config
        lines = []
        rich_lines = []
        for name, enabled in (("mqtt", bool(config.mqtt.host)), ("home_assistant", config.home_assistant.enabled)):
            state = self._connection_states.get(name)
            label = connection_text(state) if enabled and state else self._localized("Stan odbioru HA: nieznany", "HA receipt: unknown") if enabled else self._localized("Wyłączone", "Disabled")
            if name == "home_assistant" and enabled and not config.overlay_enabled:
                label = self._localized("Nakładki wyłączone — włącz je na stronie Powiadomienia", "Overlays disabled — enable them on Notifications")
            line = f"{CONNECTION_NAMES[name]}: {label}"
            lines.append(line)
            value = getattr(state.state, "value", state.state) if enabled and state else "stopped"
            colour = "#43c982" if value == "connected" else "#e5b94f" if value in {"connecting", "retry_wait"} else "#e06c75" if value in {"auth_error", "configuration_error"} else "#899297"
            rich_lines.append(f'<span style="color:{colour}; font-size:13pt;">●</span>&nbsp; {escape(line)}')
        text = "\n".join(lines)
        self.connections.setText("<br>".join(rich_lines))
        self.connections.setAccessibleName(text)
        state = self.application.computer_snapshot()
        health_lines = []
        for item in state.health:
            age = max(0, round(time.time() - item.checked_at))
            last = self._localized("brak udanej próbki", "no successful sample") if item.last_success_at is None else self._localized(
                f"ostatni sukces {max(0, round(time.time() - item.last_success_at))} s temu",
                f"last success {max(0, round(time.time() - item.last_success_at))} s ago",
            )
            checked = self._localized(f"sprawdzono {age} s temu", f"checked {age} s ago")
            health_lines.append(f"{item.source}: {item.quality.value} · {checked} · {last}" + (f" · {item.detail}" if item.detail else ""))
        self.overview_health.setText("\n".join(health_lines) or self._localized(
            "Brak aktywnych providerów. Włącz funkcje na stronie Komputer i zastosuj zmiany.",
            "No active providers. Enable features on Computer and apply changes.",
        ))
        active = [translate(title, self.draft.language) for key, title in FEATURES if bool(getattr(config, key))]
        caption = self._localized(f"{len(active)} skonfigurowanych do udostępniania: ", f"{len(active)} configured to share: ")
        self.capability_summary.setText(caption + (", ".join(active) if active else self._localized("brak", "none")))
        service_lines = [f"{item.name}: {item.state.value}" for item in self.application.states.snapshot()]
        preview = self.application.diagnostic_preview()
        queue = preview["notifications"]
        diagnostic = [*lines, *service_lines,
                      self._localized(
                           f"Kolejka: widoczne {queue['visible']}, oczekujące {queue['pending']}, zamykane {queue['retiring']}",
                           f"Queue: visible {queue['visible']}, pending {queue['pending']}, retiring {queue['retiring']}",
                       ),
                       f"{self._localized('Sensory', 'Sensors')}: {self._sensor_state_text()}",
                      self._localized(
                           f"Powiadomienia: {'wyciszone' if queue['quiet'] else 'aktywne'}",
                           f"Notifications: {'quiet' if queue['quiet'] else 'active'}",
                       )]
        self.diagnostic_status.setText("\n".join(diagnostic))
        self.diagnostic_preview.setPlainText(json.dumps(preview, ensure_ascii=False, indent=2))
        self.tray.setToolTip("HA Windows Bridge 2.0\n" + text)
        self.tray_status.setText(text.replace("\n", " · "))
        self.tray_sensors.setText(f"{self._localized('Sensory', 'Sensors')}: {self._sensor_state_text()}")
        active_transports = {"mqtt"} if config.mqtt.host else set()
        if config.home_assistant.enabled and config.overlay_enabled:
            active_transports.add("home_assistant")
        values = {getattr(item.state, "value", item.state) for name, item in self._connection_states.items() if name in active_transports}
        color = "#ef8794" if values & {"auth_error", "configuration_error"} else "#efc261" if values & {"connecting", "retry_wait"} else "#69d7a0" if "connected" in values else "#a4adb2"
        self.tray.setIcon(qta.icon("mdi6.lan-connect", color=color))

    def _sensor_state_text(self):
        statuses = self.application.states.snapshot()
        providers = [item for item in statuses if item.name.startswith("provider_") or item.name in {"audio", "media", "sensors"}]
        if any(item.state.value == "error" for item in providers):
            return self._localized("błąd", "error")
        if not any(item.state.value == "running" for item in providers):
            return self._localized("zatrzymane", "stopped")
        return self._localized("wstrzymane", "paused") if self.application.sensors_paused else self._localized("działają", "running")

    def _refresh_computer_state(self):
        state = self.application.computer_snapshot()
        source_for = {
            "publish_cpu_stats": "cpu_ram", "publish_ram_stats": "cpu_ram",
            "publish_gpu_stats": "gpu", "publish_windows_health": "windows_health",
            "publish_disk_stats": "storage", "publish_devices": "pnp",
            "publish_activity": "desktop_context", "publish_idle": "desktop_context",
            "publish_session_lock": "desktop_context", "control_master_volume": "audio",
            "control_microphone": "audio", "control_audio_output": "audio",
            "control_active_app": "audio", "audio_enhancements_enabled": "audio",
            "control_channel_balance": "audio", "publish_audio_sessions": "audio",
            "media_player_enabled": "media",
        }
        for key, label in self.feature_values.items():
            source = source_for.get(key)
            if source is None:
                enabled = bool(getattr(self.application.config, key))
                label.setText(self._localized(
                    f"runtime: {'dozwolone' if enabled else 'wyłączone'} · lokalna polityka",
                    f"runtime: {'allowed' if enabled else 'disabled'} · local policy",
                ))
                continue
            sample = state.provider(source)
            health = state.health_for(source)
            if sample is None:
                quality = health.quality.value if health else "unavailable"
                detail = f" · {health.detail}" if health and health.detail else ""
                label.setText(f"{source}: {quality} · {self._localized('brak próbki', 'no sample')}{detail}")
                continue
            age = max(0, round(time.time() - sample.observed_at))
            detail = f" · {health.detail}" if health and health.detail else ""
            age_text = self._localized(f"{age} s temu", f"{age} s ago")
            label.setText(f"{source}: {sample.quality.value} · {age_text} · {self._feature_value(key, sample.value)}{detail}")

    def _feature_value(self, key, value):
        if key == "publish_cpu_stats":
            return f"CPU {getattr(value, 'cpu_percent', 0):.1f}%"
        if key == "publish_ram_stats":
            return f"RAM {getattr(value, 'ram_percent', 0):.1f}%"
        if key == "publish_gpu_stats":
            percent = getattr(value, "gpu_percent", None)
            return "GPU —" if percent is None else f"GPU {percent:.1f}%"
        if key == "publish_windows_health":
            pending = getattr(value, "pending_restart", False)
            return self._localized(f"restart: {'wymagany' if pending else 'nie'}",
                                   f"restart: {'required' if pending else 'no'}")
        if key == "publish_disk_stats":
            selected = [v for v in getattr(value, "volumes", ()) if getattr(v, "mountpoint", "") in self.draft.disk_mounts]
            return ", ".join(
                f"{v.mountpoint}: {v.used_percent:.0f}% {self._localized('zajęte', 'used')}, {v.free_gb:.1f} GB {self._localized('wolne', 'free')}"
                for v in selected
            ) if selected else self._localized("brak wybranych dysków w próbce", "no selected disks in sample")
        if key == "publish_devices":
            selected = {item.instance_id for item in self.draft.tracked_devices if item.enabled}
            found = [v for v in getattr(value, "devices", ()) if getattr(v, "instance_id", "") in selected]
            return ", ".join(f"{v.display_name}: {self._localized('obecne', 'present') if v.present else self._localized('nieobecne', 'absent')}" for v in found) if found else self._localized("brak wybranych urządzeń w próbce", "no selected devices in sample")
        if key == "publish_activity":
            return f"{self._localized('aktywna aplikacja', 'active application')}: {getattr(value, 'process_name', '') or self._localized('brak', 'none')}"
        if key == "publish_idle":
            return f"{self._localized('bezczynność', 'idle')}: {getattr(value, 'idle_seconds', 0)} s"
        if key == "publish_session_lock":
            return self._localized("sesja zablokowana", "session locked") if getattr(value, "locked", False) else self._localized("sesja odblokowana", "session unlocked")
        if key == "control_microphone":
            microphone = getattr(value, "microphone", None)
            if microphone is None:
                return self._localized("mikrofon niedostępny", "microphone unavailable")
            state = self._localized("wyciszony", "muted") if microphone.muted else self._localized("aktywny", "active")
            return f"{self._localized('mikrofon', 'microphone')} {microphone.volume * 100:.0f}% · {state}"
        if key == "control_audio_output":
            outputs = getattr(value, "outputs", ())
            return ", ".join(f"{v.name}{self._localized(' (domyślne)', ' (default)') if v.is_default else ''}" for v in outputs) or self._localized("brak wyjść audio", "no audio outputs")
        if key == "control_active_app":
            return f"{self._localized('cel', 'target')}: {getattr(value, 'active_process', '') or self._localized('brak', 'none')}"
        if key == "publish_audio_sessions":
            return f"{self._localized('sesje', 'sessions')}: {len(getattr(value, 'sessions', ()))}"
        if key == "media_player_enabled":
            return f"{self._localized('odtwarzanie', 'playback')}: {getattr(value, 'state', 'unavailable')}"
        if key == "control_master_volume":
            master = getattr(value, "master", None)
            if master is None:
                return self._localized("głośność główna niedostępna", "master volume unavailable")
            state = self._localized("wyciszona", "muted") if master.muted else self._localized("aktywna", "active")
            return f"{self._localized('głośność główna', 'master volume')} {master.volume * 100:.0f}% · {state}"
        if key == "control_channel_balance":
            balance = getattr(value, "balance", None)
            return self._localized("balans niedostępny", "balance unavailable") if balance is None else f"{self._localized('balans', 'balance')} L/R {balance:.2f}"
        if key == "audio_enhancements_enabled":
            return self._localized("rozszerzenia audio: włączone w konfiguracji", "audio enhancements: enabled in configuration") if self.applied.audio_enhancements_enabled else self._localized("rozszerzenia audio: wyłączone", "audio enhancements: disabled")
        return self._localized("dane dostępne", "data available")
    def _refresh_master_audio(self):
        state = self.application.computer_snapshot()
        master = state.master_audio
        if master is None:
            self.master_audio.set_volume(None)
            self.master_audio.set_muted(None)
            health = state.health_for("master_audio")
            quality = health.quality.value if health is not None else "unavailable"
            detail = health.detail if health is not None else ""
        else:
            self.master_audio.set_volume(master.volume)
            self.master_audio.set_muted(master.muted)
            quality = master.quality.value
            detail = master.detail
        self.master_audio.set_feature_enabled(self.applied.control_master_volume)
        self.master_audio.set_quality(quality, detail)

    def _event(self, event):
        if self._disposed:
            return
        if event.topic in {"inventory.disks", "inventory.devices"}:
            if self._pending_apply is None:
                self._select_inventory(event.topic.split(".")[1], event.data)
        elif event.topic == "inventory.applications":
            if self._pending_apply is None:
                self._update_applications(event.data, discover=True)
                self._update_dirty()
        elif event.topic == "resources.updated":
            self._last_resource_usage = event.data if event.data else False
            self._refresh_resource_usage()
        elif event.topic == "notification.show" and not self.application.notifications_quiet:
            self.tray.showMessage(event.data["title"], event.data["message"], QSystemTrayIcon.MessageIcon.Information, 10000)
        elif event.topic == "updates.checked":
            self.status.setText(self._localized(
                "Nie można sprawdzić aktualizacji." if event.data.error else f"Dostępna wersja {event.data.latest_version}." if event.data.available else "Nie ma nowszego stabilnego wydania.",
                "Could not check for updates." if event.data.error else f"Version {event.data.latest_version} is available." if event.data.available else "No newer stable release is available.",
            ))
        elif event.topic == "log.appended":
            if self.isVisible() and self.navigation.currentRow() == Page.DIAGNOSTICS:
                self._refresh_logs()
        elif event.topic == "windows.explorer_restarted":
            self.tray.show()
        elif event.topic == "computer_state.changed":
            if self.isVisible() and self.navigation.currentRow() == Page.COMPUTER:
                self._refresh_master_audio()
                self._refresh_computer_state()
            elif self.isVisible() and self.navigation.currentRow() == Page.APPLICATIONS:
                self._update_applications_from_state()
            if self.isVisible() and self.navigation.currentRow() in {Page.OVERVIEW, Page.DIAGNOSTICS}:
                self._refresh_status()
        elif event.topic == "connection.changed":
            self._connection_states[event.data.transport] = event.data
            if self._connection_test_pending and event.data.transport in self._connection_test_expected:
                self._connection_test_states[event.data.transport] = event.data
                parts = [
                    f"{CONNECTION_NAMES.get(name, name)}: {connection_text(self._connection_test_states[name])}"
                    if name in self._connection_test_states else f"{CONNECTION_NAMES.get(name, name)}: {self._localized('oczekiwanie', 'waiting')}"
                    for name in sorted(self._connection_test_expected)
                ]
                self.connection_test_result.setText(self._connection_test_note + self._localized("Test połączenia — ", "Connection test — ") + " · ".join(parts))
                terminal = {"connected", "auth_error", "configuration_error"}
                self._connection_test_pending = not all(
                    name in self._connection_test_states and
                    getattr(self._connection_test_states[name].state, "value", self._connection_test_states[name].state) in terminal
                    for name in self._connection_test_expected
                )
            self._refresh_status()
        elif event.topic == "services.changed":
            self._refresh_status()
        elif event.topic == "inventory.published":
            self.tray_sensors.setText(f"{self._localized('Sensory', 'Sensors')}: {event.data['sensors']}")
        elif event.topic == "sensors.paused":
            self.pause_action.blockSignals(True)
            self.pause_action.setChecked(bool(event.data))
            self.pause_action.blockSignals(False)
            self._refresh_status()
        elif event.topic == "notifications.quiet":
            self.quiet_action.blockSignals(True)
            self.quiet_action.setChecked(bool(event.data))
            self.quiet_action.blockSignals(False)
            self._refresh_status()
        elif event.topic == "application.running":
            self.status.setText(self._localized("Uruchomiono usługi" if event.data else "Zatrzymano usługi",
                                            "Services started" if event.data else "Services stopped"))
        elif event.topic == "configuration.changed":
            self.applied = copy.deepcopy(event.data)
            self.status.setText(self._localized("Zapisano ustawienia; oczekiwanie na wynik transakcji…",
                                                "Settings saved; waiting for transaction result…"))
            self._connection_states = {item["transport"]: ConnectionStatus(**item) for item in self.application.connection_snapshot()}
            for card in self._cards:
                card.set_runtime_enabled(self._applied_app(card.config.process_name) is not None)
                self._sync_app_actions(card)
            self._refresh_master_audio()
            self._refresh_status()
        elif event.topic in {"ui.theme_preview", "windows.theme_changed"}:
            QTimer.singleShot(0, self._refresh_navigation_icons)
        elif event.topic == "configuration.apply_progress":
            if event.data["request_id"] == self._pending_apply:
                stage = event.data["stage"]
                names = {"preflight": "Sprawdzanie", "stopping": "Zatrzymywanie", "saving": "Zapisywanie",
                         "startup": "Autostart", "rebuilding": "Uruchamianie", "rollback": "Cofanie zmian", "complete": "Zakończono"}
                english = {"preflight": "Checking", "stopping": "Stopping", "saving": "Saving",
                           "startup": "Startup", "rebuilding": "Starting", "rollback": "Rolling back", "complete": "Complete"}
                self.status.setText(self._localized(f"Stosowanie ustawień: {names.get(stage, stage)}…",
                                                     f"Applying settings: {english.get(stage, stage)}…"))
        elif event.topic == "configuration.apply_finished":
            if event.data["request_id"] != self._pending_apply:
                return
            self._pending_apply = None
            self._set_editing_enabled(True)
            if event.data["ok"]:
                self._last_apply_error_code = None
                self.draft = copy.deepcopy(self.applied)
                self._refresh_fields()
                self.status.setText(self._localized("Ustawienia zastosowano.", "Settings applied."))
            else:
                self.applied = copy.deepcopy(self.application.config)
                code = event.data["code"]
                self._last_apply_error_code = code
                self.status.setText(self._apply_failure_message(code))
                self._last_error = self.status.text()
                self.last_error.setText(self._last_error)
            self._update_dirty()
        elif event.topic == "application.error":
            self._last_apply_error_code = None
            self._last_error = str(event.data)
            self.last_error.setText(self._last_error)
            self.status.setText(self._last_error)
        elif event.topic == "command.result":
            if event.data.id == self._local_overlay_pending_id:
                action = self._local_overlay_pending_action
                terminal = event.data.status in {"succeeded", "failed", "rejected", "cancelled"}
                if terminal:
                    self._local_overlay_pending_id = None
                    self._local_overlay_pending_action = None
                if event.data.status in {"failed", "rejected", "cancelled"}:
                    self._local_overlay_command_id = None
                if not (action == "show" and event.data.status == "succeeded" and self._local_overlay_presented):
                    awaiting = action == "show" and event.data.status == "succeeded"
                    detail_pl = event.data.code or ("oczekuje na prezentację" if awaiting else "wykonano")
                    detail_en = event.data.code or ("awaiting presentation" if awaiting else "completed")
                    self._set_local_overlay_result(
                        f"{action}: {event.data.status} · {detail_pl}",
                        f"{action}: {event.data.status} · {detail_en}",
                    )
            card = self._local_app_commands.pop(event.data.id, None)
            if card is not None and card in self._cards:
                card.local_result.setText(f"{event.data.status} · {event.data.code or self._localized('wykonano', 'completed')}")
            if event.data.status in {"failed", "rejected"}:
                self.status.setText(self._localized(f"Nie wykonano polecenia: {event.data.code}", f"Command failed: {event.data.code}"))
            else:
                self.status.setText(self._localized(f"Polecenie lokalne: {event.data.status}", f"Local command: {event.data.status}"))
        elif event.topic == "overlay.monitors_changed":
            self._refresh_overlay_monitors(event.data)
        elif event.topic == "overlay.lifecycle":
            if event.data.get("notification_id") != self._last_overlay_id:
                return
            command_id = event.data.get("command_id")
            if self._local_overlay_command_id is None or (command_id and command_id != self._local_overlay_command_id):
                return
            self._local_overlay_presented = True
            message = f"{event.data['notification_id']}: {event.data['disposition']} · {event.data['reason']}"
            self._set_local_overlay_result(message, message)
        elif event.topic == "windows.activate_requested":
            self._restore_window()
    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _request_exit(self):
        self._collect()
        if self._pending_apply is not None:
            QMessageBox.information(
                self, self._localized("Stosowanie ustawień", "Applying settings"),
                self._localized("Poczekaj na zakończenie stosowania ustawień.", "Wait for settings to finish applying."),
            )
            return
        if self.draft != self.applied and QMessageBox.question(
            self, self._localized("Niezapisane zmiany", "Unsaved changes"),
            self._localized("Zakończyć i odrzucić niezapisane zmiany?", "Exit and discard unsaved changes?")
        ) != QMessageBox.StandardButton.Yes:
            return
        self._force_close = True
        self.close()
        QApplication.instance().quit()

    def _tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        self.tray_status = menu.addAction("Zatrzymano")
        self.tray_status.setEnabled(False)
        self.tray_sensors = menu.addAction("Sensory: zatrzymane")
        self.tray_sensors.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Otwórz", self._restore_window)
        menu.addAction("Połącz ponownie", self.application.reconnect)
        self.pause_action = menu.addAction("Wstrzymaj sensory")
        self.pause_action.setCheckable(True)
        self.pause_action.setChecked(self.application.sensors_paused)
        self.pause_action.toggled.connect(self.application.pause_sensors)
        self.quiet_action = menu.addAction("Wycisz nowe powiadomienia")
        self.quiet_action.setCheckable(True)
        self.quiet_action.setChecked(self.application.notifications_quiet)
        self.quiet_action.toggled.connect(self.application.set_notifications_quiet)
        menu.addAction("Wyczyść powiadomienia", self._clear_overlays)
        menu.addAction("Ustawienia", lambda: (self.navigation.setCurrentRow(Page.SETTINGS), self._restore_window()))
        menu.addSeparator()
        menu.addAction("Zakończ", self._request_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_window()
            if reason in {QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger}
            else None
        )
        self.tray.show()
    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._page_timer.stop()
        self._state_timer.stop()
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self.tray.hide()
        QApplication.instance().removeEventFilter(self._wheel_guard)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.StyleChange, QEvent.Type.PaletteChange} and hasattr(self, "_navigation_icons"):
            QTimer.singleShot(0, self._refresh_navigation_icons)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "_page_timer"):
            self._activate_page()

    def hideEvent(self, event):
        if hasattr(self, "_page_timer"):
            self._page_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self.application.config.minimize_to_tray and not self._force_close:
            event.ignore()
            self.hide()
            return
        if not self._force_close:
            self._collect()
            if self._pending_apply is not None:
                event.ignore()
                return
            if self.draft != self.applied and QMessageBox.question(
                self, self._localized("Niezapisane zmiany", "Unsaved changes"),
                self._localized("Zakończyć i odrzucić niezapisane zmiany?", "Exit and discard unsaved changes?")
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.dispose()
        event.accept()
        if not self._force_close:
            QApplication.instance().quit()
