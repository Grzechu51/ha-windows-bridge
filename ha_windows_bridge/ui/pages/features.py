from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...ui_components import (
    SettingRow,
)
from ..inputs import WheelSafeComboBox


def build_page(self) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(24, 22, 24, 24)
    layout.setSpacing(14)
    header, _ = self._page_header("Funkcje", "Dodatkowe dane z Windows.")
    layout.addWidget(header)

    self.feature_tabs = QTabWidget()
    self.feature_tabs.setObjectName("featureTabs")
    layout.addWidget(self.feature_tabs, 1)

    def add_tab(title: str) -> QVBoxLayout:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 18, 16, 22)
        page_layout.setSpacing(12)
        scroll = self._scroll_page(page)
        self.feature_tabs.addTab(scroll, title)
        return page_layout

    def number_card(
        title: str, description: str, editor: QWidget, editor_width: int = 125
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("settingRow")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 14, 16, 14)
        text = QVBoxLayout()
        name = QLabel(title)
        name.setObjectName("settingTitle")
        detail = QLabel(description)
        detail.setObjectName("settingDescription")
        detail.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(detail)
        row.addLayout(text, 1)
        if isinstance(editor, QAbstractSpinBox):
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        editor.setFixedWidth(editor_width)
        row.addWidget(editor)
        return card

    general = add_tab("Ogólne")
    self.power_actions_row = SettingRow(
        "Bezpieczne akcje systemowe",
        "Dodaj blokadę, uśpienie, restart i wyłączenie z 30-sekundowym anulowaniem.",
    )
    self.windows_notifications_row = SettingRow(
        "Powiadomienia Windows",
        "Wyświetlaj powiadomienia wysyłane z Home Assistant.",
    )
    self.publish_activity_row = SettingRow(
        "Aktywna aplikacja i pełny ekran",
        "Publikuj proces, tytuł aktywnego okna i stan pełnego ekranu.",
    )
    self.publish_idle_row = SettingRow(
        "Czas bezczynności",
        "Publikuj czas od użycia klawiatury lub myszy oraz stan aktywności PC.",
    )
    self.publish_session_lock_row = SettingRow(
        "Stan blokady Windows",
        "Informuj, czy bieżąca sesja Windows jest zablokowana.",
    )
    for row in (
        self.power_actions_row,
        self.windows_notifications_row,
        self.publish_activity_row,
        self.publish_idle_row,
        self.publish_session_lock_row,
    ):
        general.addWidget(row)
    self.idle_threshold = QSpinBox()
    self.idle_threshold.setRange(30, 7200)
    self.idle_threshold.setSingleStep(30)
    self.idle_threshold.setSuffix(" s")
    general.addWidget(
        number_card(
            "Próg aktywności komputera",
            "Czas bez użycia klawiatury lub myszy, po którym komputer jest nieaktywny.",
            self.idle_threshold,
        )
    )
    general.addStretch()

    system = add_tab("System i dyski")
    self.publish_windows_health_row = SettingRow(
        "Stan Windows",
        "Windows Update, restart, czas działania, zasilanie i bateria.",
    )
    self.publish_ram_stats_row = SettingRow(
        "Pamięć RAM",
        "Użycie oraz zajęta, dostępna i całkowita pamięć.",
    )
    self.publish_disk_stats_row = SettingRow(
        "Stan i aktywność dysków",
        "Publikuj zajęte i wolne miejsce oraz łączny odczyt i zapis dysków.",
    )
    self.publish_cpu_stats_row = SettingRow(
        "Procesor",
        "Użycie, taktowanie i dostępne dane procesora.",
    )
    self.publish_gpu_stats_row = SettingRow(
        "Karta graficzna",
        "Użycie i dostępne dane karty NVIDIA lub AMD.",
    )
    for row in (
        self.publish_windows_health_row,
        self.publish_cpu_stats_row,
        self.publish_ram_stats_row,
        self.publish_gpu_stats_row,
        self.publish_disk_stats_row,
    ):
        system.addWidget(row)
    disk_controls = QHBoxLayout()
    disk_label = QLabel("Monitorowane dyski")
    disk_label.setObjectName("sectionTitle")
    self.scan_disks_button = QPushButton("Odśwież dyski")
    self.scan_disks_button.setObjectName("secondaryButton")
    disk_controls.addWidget(disk_label)
    disk_controls.addStretch()
    disk_controls.addWidget(self.scan_disks_button)
    system.addLayout(disk_controls)
    self.disk_volumes_list = QListWidget()
    self.disk_volumes_list.setObjectName("devicesList")
    self.disk_volumes_list.setMinimumHeight(140)
    system.addWidget(self.disk_volumes_list)
    system.addStretch()

    audio = add_tab("Audio")
    self.media_player_row = SettingRow(
        "Media Player",
        "Utwórz w Home Assistant odtwarzacz aktywnej sesji multimediów Windows.",
    )
    self.audio_enhancements_row = SettingRow(
        "Rozszerzone funkcje audio",
        "Dodaj w Home Assistant balans kanałów i liczniki sesji audio.",
    )
    self.audio_enhancements_row.setObjectName("featureGroupHeader")
    self.channel_balance_row = SettingRow(
        "Balans kanałów",
        "Dodaj w Home Assistant regulator balansu lewy/prawy dla urządzeń stereo.",
    )
    self.publish_audio_sessions_row = SettingRow(
        "Liczba sesji audio",
        "Publikuj łączną liczbę sesji Windows oraz liczbę sesji każdej włączonej aplikacji.",
    )
    audio.addWidget(self.media_player_row)
    audio.addWidget(self.audio_enhancements_row)
    audio.addWidget(self.channel_balance_row)
    audio.addWidget(self.publish_audio_sessions_row)
    audio.addStretch()

    devices = add_tab("Urządzenia")
    self.publish_devices_row = SettingRow(
        "Urządzenia jako encje",
        "Sprawdzaj w Home Assistant, czy wybrane urządzenia są podłączone.",
    )
    devices.addWidget(self.publish_devices_row)
    controls = QHBoxLayout()
    label = QLabel("Urządzenia Windows")
    label.setObjectName("sectionTitle")
    self.device_filter_combo = QComboBox()
    self.device_filter_combo.addItem("Wszystkie", "all")
    self.device_filter_combo.addItem("Aktywne", "active")
    self.device_filter_combo.addItem("Nieaktywne", "inactive")
    self.device_filter_combo.setFixedWidth(150)
    self.scan_devices_button = QPushButton("Odśwież listę")
    self.scan_devices_button.setObjectName("secondaryButton")
    controls.addWidget(label)
    controls.addStretch()
    controls.addWidget(self.device_filter_combo)
    controls.addWidget(self.scan_devices_button)
    devices.addLayout(controls)
    self.devices_list = QListWidget()
    self.devices_list.setObjectName("devicesList")
    self.devices_list.setMinimumHeight(260)
    devices.addWidget(self.devices_list)
    devices.addStretch()

    overlay = add_tab("Nakładka")
    overlay_info = QLabel(
        "Wiadomości, statusy, obrazy i multimedia wyświetlane nad pulpitem."
    )
    overlay_info.setObjectName("settingDescription")
    overlay_info.setWordWrap(True)
    overlay.addWidget(overlay_info)
    self.overlay_enabled_row = SettingRow(
        "Wiadomości na ekranie",
        "Dodaj w Home Assistant encję i akcje do wyświetlania wiadomości na tym komputerze.",
    )
    self.overlay_fullscreen_row = SettingRow(
        "Zezwalaj w pełnym ekranie",
        "Pozwala wyświetlać nakładkę nad aplikacją pełnoekranową.",
    )
    self.overlay_monitor_combo = WheelSafeComboBox()
    for index, screen in enumerate(QApplication.screens()):
        self.overlay_monitor_combo.addItem(
            f"{index + 1}: {screen.name()} ({screen.size().width()}×{screen.size().height()})",
            index,
        )
    if not self.overlay_monitor_combo.count():
        self.overlay_monitor_combo.addItem("1: Monitor", 0)
    self.overlay_monitor_combo.setMinimumWidth(280)
    overlay.addWidget(self.overlay_enabled_row)
    overlay.addWidget(self.overlay_fullscreen_row)
    monitor_card = QFrame()
    monitor_card.setObjectName("settingRow")
    monitor_row = QHBoxLayout(monitor_card)
    monitor_row.setContentsMargins(16, 14, 16, 14)
    monitor_text = QVBoxLayout()
    monitor_title = QLabel("Monitor nakładki")
    monitor_title.setObjectName("settingTitle")
    monitor_description = QLabel(
        "Wybierz ekran tutaj albo encją wyboru w Home Assistant."
    )
    monitor_description.setObjectName("settingDescription")
    monitor_description.setWordWrap(True)
    monitor_text.addWidget(monitor_title)
    monitor_text.addWidget(monitor_description)
    monitor_row.addLayout(monitor_text, 1)
    monitor_row.addWidget(self.overlay_monitor_combo)
    overlay.addWidget(monitor_card)
    overlay.addWidget(self._build_overlay_examples())
    overlay.addStretch()
    return content
