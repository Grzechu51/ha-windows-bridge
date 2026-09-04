"""Native desktop shell. Owns widgets, not backend services."""
from __future__ import annotations

import copy
from enum import IntEnum
from pathlib import Path

import qtawesome as qta
from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
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
from ..ui_components import AppCard, SettingControlRow, SettingRow
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
PAGES = ("Przegląd", "Sensory i funkcje", "Aplikacje", "Nakładki", "Ustawienia", "Diagnostyka")


class Page(IntEnum):
    OVERVIEW = 0
    FEATURES = 1
    APPLICATIONS = 2
    OVERLAYS = 3
    SETTINGS = 4
    DIAGNOSTICS = 5


class UiEvents(QObject):
    received = Signal(object)


class DesktopWindow(QMainWindow):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.draft = copy.deepcopy(application.config)
        self.setWindowTitle("HA Windows Bridge 2.0 · wersja rozwojowa")
        self.setWindowIcon(qta.icon("mdi6.lan-connect"))
        self.setMinimumSize(820, 620)
        self.resize(1120, 780)
        self._signals = UiEvents(self)
        self._signals.received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self._unsubscribe = application.events.subscribe("*", self._signals.received.emit)
        self._wheel_guard = SettingsWheelGuard(self)
        QApplication.instance().installEventFilter(self._wheel_guard)
        self._toggles = {}
        self._fields = {}
        self._cards = []
        self._dismissed_apps = set()
        self._connection_states = {item["transport"]: ConnectionStatus(**item) for item in application.connection_snapshot()}
        self._force_close = False
        self._disposed = False
        self._build()
        self._tray()
        self._page_timer = QTimer(self)
        self._page_timer.timeout.connect(self._refresh_visible_page)
        self.navigation.currentRowChanged.connect(self._activate_page)
        self.logs.setPlainText("\n".join(application.diagnostics.snapshot()))
        self._refresh_status()

    def _build(self):
        root = QFrame()
        root.setObjectName("windowFrame")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        body = QHBoxLayout()
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigationRail")
        self.navigation.addItems(PAGES)
        self.navigation.setFixedWidth(205)
        self.navigation.setIconSize(QSize(20, 20))
        for index, icon in enumerate(("view-dashboard-outline", "tune", "apps", "message-badge-outline", "cog-outline", "text-box-search-outline")):
            self.navigation.item(index).setIcon(qta.icon("mdi6." + icon, color="#a5bdb2"))
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 24, 12, 16)
        brand = QLabel("HA Windows Bridge")
        brand.setObjectName("settingTitle")
        sidebar_layout.addWidget(brand)
        version = QLabel("2.0 • wersja rozwojowa")
        version.setObjectName("settingDescription")
        sidebar_layout.addWidget(version)
        sidebar_layout.addSpacing(24)
        sidebar_layout.addWidget(self.navigation, 1)
        self.pages = PageStack()
        for title in PAGES:
            page = QWidget()
            content = QVBoxLayout(page)
            content.setContentsMargins(28, 26, 28, 26)
            content.setSpacing(14)
            header = QLabel(title)
            header.setObjectName("pageTitle")
            content.addWidget(header)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        body.addWidget(sidebar)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(20, 10, 20, 12)
        self.status = QLabel("Gotowy do konfiguracji")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.save = self._button("Zapisz i zastosuj", self._save)
        self.save.setObjectName("primaryButton")
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.setCentralWidget(root)
        self._dashboard()
        self._connections()
        for key, title in FEATURES:
            self._toggle(Page.FEATURES, key, title)
            if key in {"publish_disk_stats", "publish_devices"}:
                kind = "disks" if key == "publish_disk_stats" else "devices"
                self._content(Page.FEATURES).addWidget(self._button("Wybierz dyski…" if kind == "disks" else "Wybierz urządzenia…", lambda _checked=False, selected=kind: self.application.request_inventory(selected)))
        self._content(Page.FEATURES).addStretch()
        self._applications()
        self._overlays()
        self._settings()
        resources, resource_layout = self._card("Zużycie zasobów aplikacji")
        self.resource_usage = QLabel("CPU: —   ·   RAM: —   ·   Wątki: —")
        self.resource_usage.setWordWrap(True)
        self.resource_usage.setObjectName("metricValue")
        resource_layout.addWidget(self.resource_usage)
        self._content(Page.DIAGNOSTICS).addWidget(resources)
        diagnostics, diagnostic_layout = self._card("Stan aplikacji", f"Wersja {__version__}")
        self.diagnostic_status = QLabel()
        self.diagnostic_status.setWordWrap(True)
        self.diagnostic_status.setTextFormat(Qt.TextFormat.PlainText)
        diagnostic_layout.addWidget(self.diagnostic_status)
        self._content(Page.DIAGNOSTICS).addWidget(diagnostics)
        self.logs = QPlainTextEdit()
        self.logs.setObjectName("logViewer")
        self.logs.setReadOnly(True)
        self.logs.document().setMaximumBlockCount(500)
        self.logs.setMinimumHeight(180)
        self.logs.setPlaceholderText("Brak zdarzeń. Uruchom usługi, aby sprawdzić połączenia.")
        self._content(Page.DIAGNOSTICS).addWidget(self.logs, 1)
        self._content(Page.DIAGNOSTICS).addWidget(self._button("Eksportuj raport", self._diagnostics))

    def _content(self, index):
        return self.pages.widget(index).widget().layout()

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

    def _dashboard(self):
        layout = self._content(Page.OVERVIEW)
        hero, hero_layout = self._card(self.draft.device_name, "Twój komputer w Home Assistant")
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        hero_layout.addWidget(self.summary)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Uruchom", self.application.start))
        actions.addWidget(self._button("Zatrzymaj", self.application.stop))
        actions.addWidget(self._button("Połącz ponownie", self.application.reconnect))
        hero_layout.addLayout(actions)
        layout.addWidget(hero)
        self.connections = self.summary

    def _connections(self):
        layout = self._content(Page.OVERVIEW)
        card, inner = self._card("MQTT", "Sensory, audio i sterowanie komputerem")
        form = QFormLayout()
        form.setSpacing(12)
        def field(key, title, value, password=False, port=False):
            widget = QSpinBox() if port else QLineEdit()
            if port:
                widget.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
                widget.setRange(1, 65535)
                widget.setValue(value)
            else:
                widget.setText(value)
                if password:
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
            self._fields[key] = widget
            form.addRow(title, widget)
        field("device_name", "Nazwa komputera", self.draft.device_name)
        field("mqtt.host", "Broker", self.draft.mqtt.host)
        field("mqtt.port", "Port", self.draft.mqtt.port, port=True)
        field("mqtt.username", "Użytkownik", self.draft.mqtt.username)
        field("mqtt.password", "Hasło", self.draft.mqtt.password, password=True)
        field("mqtt.base_topic", "Topic urządzenia", self.draft.mqtt.base_topic)
        inner.addLayout(form)
        layout.addWidget(card)
        self._toggle(Page.OVERVIEW, "mqtt.tls", "Szyfrowanie MQTT (TLS)")
        card, inner = self._card("Bezpośrednio z Home Assistant", "Nakładki przez lokalne połączenie WebSocket")
        form = QFormLayout()
        form.setSpacing(12)
        field("home_assistant.url", "Adres HA", self.draft.home_assistant.url)
        field("home_assistant.token", "Token dostępu", self.draft.home_assistant.token, password=True)
        inner.addLayout(form)
        identity = QHBoxLayout()
        device_id = QLineEdit(self.draft.device_id)
        device_id.setReadOnly(True)
        identity.addWidget(device_id)
        identity.addWidget(self._button("Kopiuj ID", lambda: QApplication.clipboard().setText(self.draft.device_id)))
        inner.addLayout(identity)
        layout.addWidget(card)
        self._toggle(Page.OVERVIEW, "home_assistant.enabled", "Włącz bezpośrednie połączenie")
        self._toggle(Page.OVERVIEW, "home_assistant.verify_tls", "Weryfikuj certyfikat HA")
        layout.addStretch()

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
        self._toggles[key] = row.switch
        self._content(page).addWidget(row)
        return row

    def _applications(self):
        content = self._content(Page.APPLICATIONS)
        actions = QHBoxLayout()
        actions.addWidget(self._button("Dodaj program…", self._add_app))
        actions.addWidget(self._button("Wykryj aktywne", lambda: self.application.request_inventory("applications")))
        content.addLayout(actions)
        self._apps_container = QVBoxLayout()
        content.addLayout(self._apps_container)
        for config in self.draft.apps:
            self._add_card(config)
        content.addStretch()

    def _add_card(self, config):
        card = AppCard(config)
        card.more_button.setText("")
        card.more_button.setIcon(qta.icon("mdi6.dots-vertical", color="#aaaaaa"))
        card.remove_requested.connect(self._remove_card)
        card.volume_requested.connect(lambda _process, value: self.application.command("application.volume", {"value": value / 100}, card.config.slug))
        card.mute_requested.connect(lambda _process, muted: self.application.command("application.mute", {"value": muted}, card.config.slug))
        self._cards.append(card)
        self._apps_container.addWidget(card)

    def _add_app(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Wybierz aplikację", "", "Aplikacje (*.exe)")
        if filename:
            path = Path(filename)
            config = AudioAppConfig(path.name, path.stem, slugify(path.stem), True, executable_path=str(path))
            self.draft.apps.append(config)
            self._add_card(config)

    def _remove_card(self, card):
        self._dismissed_apps.add(card.config.process_name.casefold())
        self._cards.remove(card)
        self._apps_container.removeWidget(card)
        card.deleteLater()

    def _activate_page(self, _index=None):
        self._page_timer.stop()
        if self.isVisible() and self.navigation.currentRow() in {Page.APPLICATIONS, Page.DIAGNOSTICS}:
            self._refresh_visible_page()
            self._page_timer.start(6000 if self.navigation.currentRow() == Page.APPLICATIONS else 2000)

    def _refresh_visible_page(self):
        if self._disposed or not self.isVisible():
            return
        if self.navigation.currentRow() == Page.APPLICATIONS:
            self.application.request_inventory("applications")
        elif self.navigation.currentRow() == Page.DIAGNOSTICS:
            self._refresh_status()
            self.application.request_resources()

    def _update_applications(self, items):
        existing = {card.config.process_name.casefold(): card for card in self._cards}
        slugs = {card.config.slug for card in self._cards}
        present = set()
        for item in items[:128]:
            key = item.process_name.casefold()
            if key in self._dismissed_apps:
                continue
            present.add(key)
            card = existing.get(key)
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
                card.set_executable_icon(item.executable_path, update_config=not card.config.allow_remote_start)
            card.set_volume(item.volume)
            card.set_muted(item.muted)
        for key, card in existing.items():
            if key not in present:
                card.set_volume(None)
                card.set_muted(None)

    def _overlays(self):
        self._toggle(Page.OVERLAYS, "overlay_enabled", "Wiadomości na ekranie")
        self._toggle(Page.OVERLAYS, "overlay_allow_fullscreen", "Wyświetlaj także nad pełnym ekranem")
        content = self._content(Page.OVERLAYS)
        card, inner = self._card("Sprawdź nakładki", "Przykłady wyświetlają się tylko na tym komputerze.")
        for title, pattern in (("Krótka wiadomość", "compact"), ("Zestaw wskaźników", "badges"),
                               ("Odtwarzacz", "media"), ("Duża wiadomość", "standard")):
            inner.addWidget(self._button(title, lambda _checked=False, selected=pattern: self.application.events.emit("overlay.example", selected)))
        inner.addWidget(self._button("Zamknij przykłady", lambda: self.application.events.emit("overlay.clear")))
        content.addWidget(card)
        content.addStretch()

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
        content.addWidget(self.theme_row)
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
            self._set(key, widget.value() if isinstance(widget, QSpinBox) else widget.text())
        for key, widget in self._toggles.items():
            self._set(key, widget.isChecked())
        self.draft.theme = self.theme.currentData()

    def _save(self):
        self._collect()
        self.application.apply_configuration(self.draft)

    def _refresh_fields(self):
        for key, widget in self._fields.items():
            widget.setValue(self._get(key)) if isinstance(widget, QSpinBox) else widget.setText(self._get(key))
        for key, widget in self._toggles.items():
            widget.setChecked(self._get(key))
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.draft.theme)))
        for card in self._cards:
            self._apps_container.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        for config in self.draft.apps:
            self._add_card(config)

    def _export_settings(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Eksportuj ustawienia", "bridge-settings.json", "JSON (*.json)")
        if filename:
            self._collect()
            try:
                ConfigurationStore.export(self.draft, Path(filename))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Eksport", str(exc))

    def _import_settings(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Importuj ustawienia 2.0", "", "JSON (*.json)")
        if not filename:
            return
        try:
            imported = ConfigurationStore.import_settings(Path(filename))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Import", str(exc))
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
        self.status.setText("Wczytano ustawienia. Sprawdź je i wybierz Zapisz i zastosuj.")

    def _reset_settings(self):
        if QMessageBox.question(self, "Domyślne ustawienia", "Przywrócić ustawienia domyślne? Dane połączeń zostaną zachowane.") != QMessageBox.StandardButton.Yes:
            return
        self._collect()
        self.draft = AppConfig(device_name=self.draft.device_name, device_id=self.draft.device_id,
                               mqtt=copy.deepcopy(self.draft.mqtt), home_assistant=copy.deepcopy(self.draft.home_assistant),
                               start_with_windows=False, auto_connect=False, theme="system")
        self._refresh_fields()
        self.status.setText("Przywrócono wartości w formularzu. Zapisz, aby zastosować.")

    def _select_inventory(self, kind, items):
        dialog = QDialog(self)
        dialog.setWindowTitle("Wybierz dyski" if kind == "disks" else "Wybierz urządzenia")
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
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count()) if listing.item(i).checkState() == Qt.CheckState.Checked]
            if kind == "disks":
                self.draft.disk_mounts = [device.mountpoint for device in chosen]
            else:
                visible_ids = {device.instance_id for device in items}
                preserved = [device for device in self.draft.tracked_devices if device.instance_id not in visible_ids]
                self.draft.tracked_devices = preserved + [TrackedDeviceConfig(device.instance_id, device.display_name, device.category) for device in chosen]
            self.status.setText("Wybrano urządzenia. Zapisz ustawienia, aby zastosować.")

    def _diagnostics(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Raport diagnostyczny", "bridge-diagnostics.json", "JSON (*.json)")
        if filename:
            try:
                self.application.export_diagnostics(Path(filename))
            except (OSError, ValueError):
                self.status.setText("Nie można zapisać raportu w wybranym miejscu.")
            else:
                self.status.setText("Zapisano raport diagnostyczny.")

    def _refresh_status(self):
        config = self.application.config
        lines = []
        for name, enabled in (("mqtt", bool(config.mqtt.host)), ("home_assistant", config.home_assistant.enabled)):
            state = self._connection_states.get(name)
            label = connection_text(state) if enabled and state else "Zatrzymane" if enabled else "Wyłączone"
            if name == "home_assistant" and enabled and not config.overlay_enabled:
                label = "Nakładki wyłączone — włącz „Wiadomości na ekranie” na stronie Nakładki"
            lines.append(f"{CONNECTION_NAMES[name]}: {label}")
        text = "\n".join(lines)
        self.connections.setText(text)
        labels = {"running": "uruchomiona", "stopped": "zatrzymana", "starting": "uruchamianie",
                  "stopping": "zatrzymywanie", "error": "błąd"}
        services = [f"Usługa {CONNECTION_NAMES.get(item.name, 'Sensory')}: {labels.get(item.state, item.state)}"
                    for item in self.application.states.snapshot()]
        self.diagnostic_status.setText(text + "\n\n" + ("\n".join(services) or "Brak skonfigurowanych usług."))
        self.tray.setToolTip("HA Windows Bridge 2.0\n" + text)
        self.tray_status.setText(text.replace("\n", " · "))
        active_transports = {"mqtt"} if config.mqtt.host else set()
        if config.home_assistant.enabled and config.overlay_enabled:
            active_transports.add("home_assistant")
        values = {item.state for name, item in self._connection_states.items() if name in active_transports}
        color = "#ef8794" if values & {"auth_error", "configuration_error"} else "#efc261" if values & {"connecting", "retry_wait"} else "#69d7a0" if "connected" in values else "#a4adb2"
        self.tray.setIcon(qta.icon("mdi6.lan-connect", color=color))

    def _event(self, event):
        if self._disposed:
            return
        if event.topic in {"inventory.disks", "inventory.devices"}:
            self._select_inventory(event.topic.split(".")[1], event.data)
        elif event.topic == "inventory.applications":
            self._update_applications(event.data)
        elif event.topic == "resources.updated":
            usage = event.data
            if usage:
                cpu = "—" if usage["cpu_percent"] is None else f"{usage['cpu_percent']:.1f}%"
                self.resource_usage.setText(f"CPU: {cpu}   ·   RAM: {usage['memory_mib']:.1f} MiB   ·   Wątki: {usage['threads']}")
            else:
                self.resource_usage.setText("Zużycie zasobów jest chwilowo niedostępne.")
        elif event.topic == "notification.show":
            self.tray.showMessage(event.data["title"], event.data["message"], QSystemTrayIcon.MessageIcon.Information, 10000)
        elif event.topic == "updates.checked":
            self.status.setText("Nie można sprawdzić aktualizacji." if event.data.error else f"Dostępna wersja {event.data.latest_version} w GitHub Releases." if event.data.available else "Nie ma nowszego stabilnego wydania.")
        elif event.topic == "log.appended":
            self.logs.appendPlainText(event.data)
        elif event.topic == "windows.explorer_restarted":
            self.tray.show()
        elif event.topic == "audio.snapshot":
            if self.isVisible() and self.navigation.currentRow() == Page.APPLICATIONS:
                return  # This page uses its local inventory, independently of MQTT.
            for card in self._cards:
                state = event.data.get(card.config.process_name.lower())
                card.set_volume(state.volume if state else None)
                card.set_muted(state.muted if state else None)
        elif event.topic == "connection.changed":
            self._connection_states[event.data.transport] = event.data
            self._refresh_status()
        elif event.topic == "services.changed":
            self._refresh_status()
        elif event.topic == "inventory.published":
            self.tray_sensors.setText(f"Sensory: {event.data['sensors']}")
        elif event.topic == "sensors.paused":
            self.tray_sensors.setText("Sensory: wstrzymane" if event.data else "Sensory: działają")
        elif event.topic == "application.running":
            self.status.setText("Uruchomiono usługi" if event.data else "Zatrzymano usługi")
        elif event.topic == "configuration.changed":
            self.status.setText("Zapisano ustawienia")
            self.draft = copy.deepcopy(event.data)
            self._connection_states = {item["transport"]: ConnectionStatus(**item) for item in self.application.connection_snapshot()}
            self._refresh_status()
        elif event.topic == "application.error":
            self.status.setText(str(event.data))
        elif event.topic == "command.result" and event.data.status in {"failed", "rejected"}:
            self.status.setText(f"Nie wykonano polecenia: {event.data.code}")

    def _tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        self.tray_status = menu.addAction("Zatrzymano")
        self.tray_status.setEnabled(False)
        self.tray_sensors = menu.addAction("Sensory: zatrzymane")
        self.tray_sensors.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Otwórz", self.showNormal)
        menu.addAction("Połącz ponownie", self.application.reconnect)
        menu.addAction("Przykładowa nakładka", lambda: self.application.events.emit("overlay.example", "compact"))
        pause = menu.addAction("Wstrzymaj sensory")
        pause.setCheckable(True)
        pause.toggled.connect(self.application.pause_sensors)
        menu.addAction("Ustawienia", lambda: (self.navigation.setCurrentRow(Page.SETTINGS), self.showNormal()))
        menu.addSeparator()
        menu.addAction("Zakończ", QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._page_timer.stop()
        self._unsubscribe()
        self.tray.hide()
        QApplication.instance().removeEventFilter(self._wheel_guard)

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
        else:
            self.dispose()
            event.accept()
            if not self._force_close:
                QApplication.instance().quit()
