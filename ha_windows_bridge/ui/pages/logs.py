from __future__ import annotations

from PySide6.QtWidgets import (
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def build_page(self) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(16)
    header, header_layout = self._page_header(
        "Logi", "Ostatnie zdarzenia i błędy aplikacji."
    )
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
