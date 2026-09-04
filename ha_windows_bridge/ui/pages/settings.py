from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_components import (
    SettingRow,
    StatusCard,
)


def build_page(self) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(30, 24, 30, 28)
    layout.setSpacing(18)
    header, _ = self._page_header(
        "Ustawienia", "Uruchamianie, synchronizacja i dane aplikacji."
    )
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
    self.poll_interval.setFixedWidth(96)
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

    self.reduced_motion_row = SettingRow("Ogranicz animacje", "Spokojniejszy interfejs i natychmiastowe przejścia nakładek.")
    layout.addWidget(self.reduced_motion_row)

    theme_card = QFrame()
    theme_card.setObjectName("settingRow")
    theme_layout = QHBoxLayout(theme_card)
    theme_layout.setContentsMargins(16, 14, 16, 14)
    theme_text = QVBoxLayout()
    theme_title = QLabel("Motyw")
    theme_title.setObjectName("settingTitle")
    theme_description = QLabel("Wybierz ciemny lub jasny wygląd aplikacji.")
    theme_description.setObjectName("settingDescription")
    theme_text.addWidget(theme_title)
    theme_text.addWidget(theme_description)
    theme_layout.addLayout(theme_text, 1)
    self.theme_combo = QComboBox()
    self.theme_combo.addItem("Ciemny", "dark")
    self.theme_combo.addItem("Jasny", "light")
    self.theme_combo.setFixedWidth(112)
    theme_layout.addWidget(self.theme_combo)

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
    self.language_combo.setFixedWidth(112)
    language_layout.addWidget(self.language_combo)

    data_card = QFrame()
    data_card.setObjectName("dataCard")
    data_layout = QVBoxLayout(data_card)
    data_layout.setContentsMargins(16, 14, 16, 14)
    data_layout.setSpacing(10)
    data_text = QVBoxLayout()
    data_title = QLabel("Dane aplikacji")
    data_title.setObjectName("settingTitle")
    self.config_path_label = QLabel(str(self.store.config_path))
    self.config_path_label.setObjectName("settingDescription")
    self.config_path_label.setWordWrap(True)
    data_text.addWidget(data_title)
    data_text.addWidget(self.config_path_label)
    data_layout.addLayout(data_text)
    data_buttons = QHBoxLayout()
    data_buttons.setSpacing(8)
    data_buttons.addStretch()
    open_data = QPushButton("Otwórz folder")
    open_data.setObjectName("outlineButton")
    open_data.clicked.connect(self._open_data_folder)
    self.import_button = QPushButton("Importuj")
    self.import_button.setObjectName("outlineButton")
    self.export_button = QPushButton("Eksportuj")
    self.export_button.setObjectName("outlineButton")
    self.diagnostics_button = QPushButton("Raport diagnostyczny")
    self.diagnostics_button.setObjectName("outlineButton")
    for button in (
        open_data,
        self.import_button,
        self.export_button,
        self.diagnostics_button,
    ):
        data_buttons.addWidget(button)
    data_layout.addLayout(data_buttons)

    self.auto_update_row = SettingRow(
        "Automatycznie sprawdzaj aktualizacje",
        "Aplikacja sprawdzi oficjalne wydania GitHub i poinformuje o dostępnej wersji.",
    )
    update_card = QFrame()
    update_card.setObjectName("dataCard")
    update_layout = QHBoxLayout(update_card)
    update_layout.setContentsMargins(16, 14, 16, 14)
    self.update_status_label = QLabel("Nie sprawdzono aktualizacji.")
    self.update_status_label.setObjectName("settingDescription")
    update_layout.addWidget(self.update_status_label, 1)
    self.check_update_button = QPushButton("Sprawdź teraz")
    self.check_update_button.setObjectName("outlineButton")
    self.open_update_button = QPushButton("Otwórz wydanie")
    self.open_update_button.setObjectName("outlineButton")
    self.open_update_button.setEnabled(False)
    update_layout.addWidget(self.check_update_button)
    update_layout.addWidget(self.open_update_button)

    general_group = QFrame()
    general_group.setObjectName("settingsGroup")
    general_layout = QVBoxLayout(general_group)
    general_layout.setContentsMargins(0, 0, 0, 0)
    general_layout.setSpacing(12)
    general_layout.addWidget(language_card)
    general_layout.addWidget(theme_card)
    general_layout.addWidget(self.auto_update_row)
    general_layout.addWidget(update_card)
    general_layout.addWidget(data_card)
    layout.addWidget(general_group)
    maintenance_title = QLabel("Konserwacja")
    maintenance_title.setObjectName("sectionTitle")
    layout.addWidget(maintenance_title)
    reset_card = QFrame()
    reset_card.setObjectName("dataCard")
    reset_layout = QHBoxLayout(reset_card)
    reset_layout.setContentsMargins(16, 14, 16, 14)
    reset_text = QVBoxLayout()
    reset_name = QLabel("Ustawienia domyślne")
    reset_name.setObjectName("settingTitle")
    reset_description = QLabel(
        "Przywróć domyślne opcje programu, zachowując dane połączenia i ID urządzenia."
    )
    reset_description.setObjectName("settingDescription")
    reset_description.setWordWrap(True)
    reset_text.addWidget(reset_name)
    reset_text.addWidget(reset_description)
    reset_layout.addLayout(reset_text, 1)
    self.reset_defaults_button = QPushButton("Przywróć domyślne")
    self.reset_defaults_button.setObjectName("outlineButton")
    reset_layout.addWidget(self.reset_defaults_button)
    layout.addWidget(reset_card)
    mqtt_cleanup_card = QFrame()
    mqtt_cleanup_card.setObjectName("dataCard")
    mqtt_cleanup_layout = QHBoxLayout(mqtt_cleanup_card)
    mqtt_cleanup_layout.setContentsMargins(16, 14, 16, 14)
    mqtt_cleanup_text = QVBoxLayout()
    mqtt_cleanup_name = QLabel("Dane MQTT")
    mqtt_cleanup_name.setObjectName("settingTitle")
    mqtt_cleanup_description = QLabel(
        "Usuń zachowane topiki utworzone przez HA Windows Bridge bez odinstalowywania aplikacji."
    )
    mqtt_cleanup_description.setObjectName("settingDescription")
    mqtt_cleanup_description.setWordWrap(True)
    mqtt_cleanup_text.addWidget(mqtt_cleanup_name)
    mqtt_cleanup_text.addWidget(mqtt_cleanup_description)
    mqtt_cleanup_layout.addLayout(mqtt_cleanup_text, 1)
    self.mqtt_cleanup_button = QPushButton("Wyczyść dane MQTT")
    self.mqtt_cleanup_button.setObjectName("outlineButton")
    mqtt_cleanup_layout.addWidget(self.mqtt_cleanup_button)
    layout.addWidget(mqtt_cleanup_card)

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
        "Usuń aplikację z tego komputera. W następnym kroku wybierzesz, czy wyczyścić także dane MQTT."
    )
    uninstall_description.setObjectName("settingDescription")
    uninstall_description.setWordWrap(True)
    uninstall_text.addWidget(uninstall_name)
    uninstall_text.addWidget(uninstall_description)
    uninstall_layout.addLayout(uninstall_text, 1)
    self.uninstall_button = QPushButton("Odinstaluj aplikację")
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
