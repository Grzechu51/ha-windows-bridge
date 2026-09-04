from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...overlay import OverlayManager
from ..inputs import WheelSafeComboBox


def build_page(self) -> QFrame:
    card = QFrame()
    card.setObjectName("settingRow")
    layout = QHBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(14)

    text = QVBoxLayout()
    text.setSpacing(3)
    title = QLabel("Przykłady nakładek")
    title.setObjectName("settingTitle")
    description = QLabel("Sprawdź wygląd nakładki bez używania Home Assistant.")
    description.setObjectName("settingDescription")
    description.setWordWrap(True)
    text.addWidget(title)
    text.addWidget(description)
    layout.addLayout(text, 1)

    self.overlay_example_combo = WheelSafeComboBox()
    self.overlay_example_combo.setMinimumWidth(210)
    for name, label in OverlayManager.test_pattern_names():
        self.overlay_example_combo.addItem(label, name)
    self.overlay_example_button = QPushButton("Pokaż przykład")
    self.overlay_example_button.setObjectName("secondaryButton")
    layout.addWidget(self.overlay_example_combo)
    layout.addWidget(self.overlay_example_button)
    self.overlay_examples_card = card
    return card
