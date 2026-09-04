from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...ui_components import (
    AudioOutputCard,
    MasterVolumeCard,
    MicrophoneCard,
    SettingRow,
)


def build_page(self) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(24, 24, 24, 28)
    layout.setSpacing(18)
    header, header_layout = self._page_header(
        "Aplikacje",
        "Wybierz programy do sterowania. Każdy otrzyma własny Media Player w Home Assistant.",
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
