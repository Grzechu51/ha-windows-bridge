from __future__ import annotations

from PySide6.QtCore import (
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def build_page(self) -> QWidget:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(30, 24, 30, 28)
    layout.setSpacing(22)
    header, _ = self._page_header(
        "Połączenie", "Połącz komputer z Home Assistant."
    )
    layout.addWidget(header)
    self.connection_tabs = QTabWidget()
    self.connection_tabs.setObjectName("featureTabs")
    layout.addWidget(self.connection_tabs)

    form = QFrame()
    form.setObjectName("connectionForm")
    grid = QGridLayout(form)
    grid.setContentsMargins(18, 18, 18, 18)
    grid.setAlignment(Qt.AlignmentFlag.AlignTop)
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
        "Włącz, jeśli broker obsługuje szyfrowanie TLS."
    )
    self.tls_help = self._help_button(
        "Włącz, jeśli broker obsługuje szyfrowanie TLS."
    )
    # Retained internally for Home Assistant birth-topic compatibility.
    self.discovery_prefix = QLineEdit()
    self.keepalive = QSpinBox()
    self.keepalive.setRange(5, 3600)
    self.keepalive.setSuffix(" s")
    self.keepalive.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    self.keepalive_help = self._help_button(
        "Częstotliwość sprawdzania połączenia. Zalecane: 10 s."
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
    keepalive_label = QLabel("Kontrola połączenia")
    keepalive_label.setObjectName("formLabel")
    grid.addWidget(keepalive_label, keepalive_row, 0, Qt.AlignmentFlag.AlignVCenter)
    grid.addWidget(self.keepalive, keepalive_row, 1)
    grid.addWidget(self.keepalive_help, keepalive_row, 2, Qt.AlignmentFlag.AlignLeft)

    self.connection_tabs.addTab(form, "MQTT")

    direct_form = QFrame()
    direct_form.setObjectName("settingRow")
    direct_grid = QGridLayout(direct_form)
    direct_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
    direct_grid.setContentsMargins(18, 17, 18, 18)
    direct_grid.setHorizontalSpacing(18)
    direct_grid.setVerticalSpacing(11)
    direct_grid.setColumnMinimumWidth(0, 145)
    direct_grid.setColumnStretch(1, 1)
    direct_title = QLabel("Bezpośrednio z Home Assistant")
    direct_title.setObjectName("sectionTitle")
    direct_grid.addWidget(direct_title, 0, 0, 1, 2)
    self.direct_connection_badge = QLabel("Wyłączone")
    self.direct_connection_badge.setObjectName("statusBadge")
    self.direct_connection_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.direct_connection_badge.setMinimumWidth(96)
    direct_grid.addWidget(
        self.direct_connection_badge,
        0,
        2,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    )
    direct_description = QLabel(
        "Wyświetlaj nakładki bez połączenia z MQTT."
    )
    direct_description.setObjectName("settingDescription")
    direct_description.setWordWrap(True)
    direct_grid.addWidget(direct_description, 1, 0, 1, 3)
    self.direct_enabled = QCheckBox("Włącz połączenie bezpośrednie")
    direct_grid.addWidget(self.direct_enabled, 2, 0, 1, 3)
    self.ha_url = QLineEdit()
    self.ha_url.setPlaceholderText("https://homeassistant.local:8123")
    url_label = QLabel("Adres Home Assistant")
    url_label.setObjectName("formLabel")
    direct_grid.addWidget(url_label, 3, 0)
    direct_grid.addWidget(self.ha_url, 3, 1, 1, 2)
    self.ha_token = QLineEdit()
    self.ha_token.setEchoMode(QLineEdit.EchoMode.Password)
    self.ha_token.setPlaceholderText("Długoterminowy token dostępu")
    self.show_ha_token = QCheckBox("Pokaż")
    token_label = QLabel("Token dostępu")
    token_label.setObjectName("formLabel")
    direct_grid.addWidget(token_label, 4, 0)
    direct_grid.addWidget(self.ha_token, 4, 1)
    direct_grid.addWidget(self.show_ha_token, 4, 2)
    self.ha_verify_tls = QCheckBox("Weryfikuj certyfikat TLS")
    self.ha_verify_tls.setChecked(True)
    direct_grid.addWidget(self.ha_verify_tls, 5, 1, 1, 2)
    device_label = QLabel("ID urządzenia")
    device_label.setObjectName("formLabel")
    direct_grid.addWidget(device_label, 6, 0)
    self.ha_device_id = QLineEdit(self.current_config.device_id)
    self.ha_device_id.setReadOnly(True)
    self.ha_device_id.setToolTip(
        "Tego identyfikatora użyj podczas dodawania integracji bezpośredniej w Home Assistant."
    )
    direct_grid.addWidget(self.ha_device_id, 6, 1)
    self.copy_ha_device_id = QPushButton("Kopiuj")
    self.copy_ha_device_id.setObjectName("secondaryButton")
    self.copy_ha_device_id.setToolTip("Skopiuj ID urządzenia do schowka")
    direct_grid.addWidget(self.copy_ha_device_id, 6, 2)
    self.connection_tabs.addTab(direct_form, "Home Assistant")
    if self.current_config.home_assistant.enabled and not self.current_config.mqtt.host:
        self.connection_tabs.setCurrentIndex(1)

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
