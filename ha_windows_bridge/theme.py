from __future__ import annotations

VALID_THEMES = frozenset({"dark", "light"})


def normalize_theme(theme: str) -> str:
    normalized = str(theme).strip().lower()
    return normalized if normalized in VALID_THEMES else "dark"


DARK_OVERRIDES = """
QFrame#windowFrame {
    background: #050607;
    border-color: #2b2f33;
}
QFrame#titleBar, QFrame#sidebar, QFrame#sidebarFooter, QFrame#footer {
    background: #070809;
}
QStackedWidget#pageStack, QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget > QWidget {
    background: #08090a;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QFrame#passwordBox, QPushButton#outlineButton, QPushButton#secondaryButton {
    background: #0c0e10;
}
QFrame#appCard, QFrame#masterVolumeCard, QFrame#microphoneCard,
QFrame#audioOutputCard, QFrame#settingRow, QFrame#dataCard,
QFrame#statusCard, QLabel#infoBanner {
    background: #0d0f11;
}
QFrame#appCard:hover, QFrame#masterVolumeCard:hover,
QFrame#microphoneCard:hover, QFrame#audioOutputCard:hover {
    background: #111316;
}
QPlainTextEdit#logViewer {
    background: #060708;
}
QMenu, QComboBox QAbstractItemView, QToolTip {
    background: #0d0f11;
}
QFrame#appCard[featureEnabled="false"],
QFrame#masterVolumeCard[featureEnabled="false"],
QFrame#microphoneCard[featureEnabled="false"],
QFrame#audioOutputCard[featureEnabled="false"],
QFrame#settingRow[featureEnabled="false"] {
    background: #070809;
}
"""


LIGHT_OVERRIDES = """
QWidget {
    color: #17211d;
}
QFrame#windowFrame {
    background: #f4f6f7;
    border-color: #bcc5ca;
}
QFrame#titleBar, QFrame#sidebar, QFrame#sidebarFooter, QFrame#footer {
    background: #eef1f2;
    border-color: #cbd2d6;
}
QFrame#titleDivider, QFrame#statusVerticalDivider {
    background: #c7ced2;
}
QToolButton#hamburgerButton, QToolButton#windowButton, QToolButton#closeButton {
    color: #25312c;
}
QToolButton#hamburgerButton:hover, QToolButton#windowButton:hover {
    background: #dfe5e7;
}
QLabel#windowTitle, QLabel#pageTitle, QLabel#sectionTitle,
QLabel#appName, QLabel#settingTitle, QLabel#statusCardTitle {
    color: #101713;
}
QLabel#windowSubtitle, QLabel#pageSubtitle, QLabel#hint, QLabel#dataLabel,
QLabel#appProcess, QLabel#settingDescription, QLabel#statusCardDetail,
QLabel#formHint, QLabel#versionLabel, QLabel#resourceLabel {
    color: #5d6964;
}
QLabel#topStatusLabel, QLabel#footerStatusLabel {
    color: #26332e;
}
QPushButton#navButton {
    color: #24312c;
}
QPushButton#navButton:hover {
    background: #e1e6e8;
    border-color: #b9c3c8;
}
QPushButton#navButton:checked {
    background: #dce6e1;
    border-color: #9eaaa4;
    border-left-color: #24895b;
    color: #0f1713;
}
QStackedWidget#pageStack, QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget > QWidget {
    background: #f7f8f9;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QFrame#passwordBox {
    background: #ffffff;
    border-color: #b7c1c6;
    color: #17211d;
    selection-background-color: #65b991;
}
QFrame#passwordBox QToolButton {
    color: #26332e;
}
QPushButton, QPushButton#outlineButton, QPushButton#secondaryButton {
    background: #ffffff;
    border-color: #b7c1c6;
    color: #18221e;
}
QPushButton:hover, QPushButton#outlineButton:hover, QPushButton#secondaryButton:hover {
    background: #e9edef;
    border-color: #8f9da4;
}
QPushButton:pressed {
    background: #dde3e6;
}
QPushButton:disabled {
    background: #e6eaec;
    border-color: #cdd4d7;
    color: #8b9691;
}
QFrame#appCard, QFrame#masterVolumeCard, QFrame#microphoneCard,
QFrame#audioOutputCard, QFrame#settingRow, QFrame#dataCard,
QFrame#statusCard, QLabel#infoBanner {
    background: #ffffff;
    border-color: #c4ccd0;
}
QFrame#appCard:hover, QFrame#masterVolumeCard:hover,
QFrame#microphoneCard:hover, QFrame#audioOutputCard:hover {
    background: #f8faf9;
    border-color: #9faab0;
}
QLabel#volumePercent {
    color: #18221e;
}
QToolButton#moreButton {
    color: #52615b;
}
QToolButton#moreButton:hover {
    background: #e2e8e5;
    color: #17211d;
}
QToolButton#muteButton {
    background: #f2f5f6;
    border-color: #adb8bd;
    color: #26332e;
}
QSlider::groove:horizontal, QSlider::add-page:horizontal {
    background: #cfd6d9;
}
QComboBox QAbstractItemView, QMenu {
    background: #ffffff;
    border-color: #aeb9be;
    color: #17211d;
    selection-background-color: #d6e9df;
}
QLabel#statusBadge {
    background: #edf7f2;
}
QPlainTextEdit#logViewer {
    background: #ffffff;
    border-color: #b9c3c8;
    color: #24312c;
    selection-background-color: #8bc8aa;
}
QCheckBox {
    color: #24312c;
}
QMenu::item:selected {
    background: #d6e9df;
}
QMenu::separator {
    background: #d2d8db;
}
QToolTip {
    background: #ffffff;
    border-color: #8f9da4;
    color: #17211d;
}
QScrollBar::handle:vertical {
    background: #aeb8bd;
}
QLabel#infoBanner {
    color: #3e5148;
}
QFrame#appCard[featureEnabled="false"],
QFrame#masterVolumeCard[featureEnabled="false"],
QFrame#microphoneCard[featureEnabled="false"],
QFrame#audioOutputCard[featureEnabled="false"],
QFrame#settingRow[featureEnabled="false"] {
    background: #eceff0;
    border-color: #d2d8db;
}
QLabel:disabled {
    color: #89938f;
}
QSlider::groove:horizontal:disabled,
QSlider::add-page:horizontal:disabled {
    background: #d9dfe1;
}
QSlider::sub-page:horizontal:disabled,
QSlider::handle:horizontal:disabled {
    background: #aeb8bd;
    border-color: #aeb8bd;
}
QToolButton:disabled, QComboBox:disabled {
    color: #89938f;
    background: #e6eaec;
    border-color: #cdd4d7;
}
QToolButton#helpButton {
    background: #ffffff;
    border-color: #aab6bb;
    color: #50605a;
}
QToolButton#helpButton:hover {
    background: #e7eeea;
}
QProgressBar#resourceBar {
    background: #d4dcdf;
}
QFrame#uninstallCard {
    background: #fffafb;
    border-color: #d8b9c0;
}
QPushButton#dangerButton {
    background: #fff1f3;
    border-color: #c98693;
    color: #7a2638;
}
QPushButton#dangerButton:hover {
    background: #fbe2e7;
    border-color: #b96878;
}
QPushButton#dangerButton:disabled {
    background: #f1ecee;
    border-color: #d8cdd0;
    color: #9a878b;
}
QLabel#masterAvatar,
QLabel#microphoneAvatar,
QLabel#audioOutputAvatar {
    background: #f1f5f6;
}
QLabel#masterAvatar {
    color: #18774e;
}
QLabel#microphoneAvatar,
QLabel#audioOutputAvatar {
    color: #316b80;
}
QLabel#statusBadge {
    background: #f5fbf8;
}
"""


def style_for_theme(base_style: str, theme: str) -> str:
    selected = normalize_theme(theme)
    overrides = LIGHT_OVERRIDES if selected == "light" else DARK_OVERRIDES
    return f"{base_style}\n{overrides}"
