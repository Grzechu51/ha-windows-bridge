"""Fluent-inspired design tokens. One stylesheet owns both theme variants."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from string import Template

VALID_THEMES = frozenset({"dark", "light"})


@dataclass(frozen=True)
class ThemeTokens:
    canvas: str
    chrome: str
    surface: str
    hover: str
    field: str
    border: str
    text: str
    muted: str
    disabled: str
    accent: str
    accent_text: str
    selection: str
    danger: str
    danger_surface: str


PALETTES = {
    "dark": ThemeTokens("#202020", "#181818", "#2b2b2b", "#343434", "#242424", "#454545",
                        "#f4f4f4", "#b5b5b5", "#858585", "#69d7a0", "#10251b", "#294439", "#ffb4bd", "#462c32"),
    "light": ThemeTokens("#f3f3f3", "#ebebeb", "#ffffff", "#f6f6f6", "#ffffff", "#d0d0d0",
                         "#1b1b1b", "#606060", "#737373", "#19764d", "#ffffff", "#e0eee6", "#a5283f", "#fff1f3"),
}


def normalize_theme(theme: str) -> str:
    normalized = str(theme).strip().lower()
    return normalized if normalized in VALID_THEMES else "dark"


_STYLE = Template('''
QWidget { background: transparent; color: $text; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#windowFrame { background: $canvas; border: 1px solid $border; border-radius: 10px; }
QFrame#titleBar { background: $chrome; border: none; border-top-left-radius: 10px; border-top-right-radius: 10px; }
QFrame#sidebar, QFrame#sidebarFooter, QFrame#footer { background: $chrome; border: none; }
QFrame#titleDivider, QFrame#statusVerticalDivider { background: $border; border: none; }
QToolButton { border: 1px solid transparent; border-radius: 5px; padding: 2px; }
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $selection; }
QToolButton:focus, QPushButton:focus { border: 1px solid $accent; }
QToolButton#hamburgerButton, QToolButton#windowButton, QToolButton#closeButton { font-size: 14pt; }
QToolButton#closeButton:hover { background: #c42b1c; color: #ffffff; }
QLabel#windowTitle { font-size: 12pt; font-weight: 600; }
QLabel#windowSubtitle { font-size: 8.5pt; color: $muted; }
QLabel#pageTitle { font-size: 22pt; font-weight: 600; }
QLabel#sectionTitle { font-size: 14pt; font-weight: 600; }
QLabel#settingTitle, QLabel#appName { font-size: 10.5pt; font-weight: 600; }
QLabel#pageSubtitle, QLabel#hint, QLabel#dataLabel, QLabel#formHint,
QLabel#appProcess, QLabel#settingDescription, QLabel#statusCardDetail,
QLabel#versionLabel { color: $muted; }
QLabel#resourceLabel { font-size: 7.5pt; color: $muted; }
QLabel#topStatusDot, QLabel#footerStatusDot { color: $accent; }
QPushButton#navButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 8px 12px; text-align: left; icon-size: 20px; }
QPushButton#navButton:hover { background: $hover; }
QPushButton#navButton:checked { background: $selection; border-left: 3px solid $accent; font-weight: 600; }
QStackedWidget#pageStack, QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget { background: $canvas; border: none; }
QTabWidget#featureTabs::pane { background: $canvas; border: none; border-top: 1px solid $border; }
QTabBar::tab { background: transparent; color: $muted; border: none; border-bottom: 2px solid transparent; padding: 10px 14px; margin-right: 4px; }
QTabBar::tab:hover { background: $hover; color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $field; border: 1px solid $border; border-bottom: 1px solid $muted;
    border-radius: 5px; min-height: 22px; padding: 7px 10px; selection-background-color: $selection;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-bottom: 2px solid $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: $disabled; background: $chrome; border-color: $border; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { background: $surface; color: $text; border: 1px solid $border; selection-background-color: $selection; outline: none; padding: 4px; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 3px 8px; }
QPushButton { background: $surface; border: 1px solid $border; border-radius: 5px; padding: 9px 16px; min-height: 18px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $selection; }
QPushButton#primaryButton { background: $accent; color: $accent_text; border-color: $accent; font-weight: 600; }
QPushButton#primaryButton:hover { border-color: $text; }
QPushButton#primaryButton:pressed { background: $selection; color: $text; }
QPushButton#primaryButton[saved="true"] { background: $selection; color: $text; }
QPushButton#dangerButton { background: $danger_surface; color: $danger; border-color: $danger; }
QPushButton#dangerButton:hover { background: $hover; }
QPushButton:disabled, QPushButton#primaryButton:disabled, QPushButton#dangerButton:disabled { color: $disabled; background: $chrome; border-color: $border; }
QFrame#appCard, QFrame#masterVolumeCard, QFrame#microphoneCard, QFrame#audioOutputCard,
QFrame#settingRow, QFrame#dataCard, QFrame#statusCard, QFrame#connectionForm {
    background: $surface; border: 1px solid $border; border-radius: 8px;
}
QFrame#appCard:hover, QFrame#masterVolumeCard:hover, QFrame#microphoneCard:hover, QFrame#audioOutputCard:hover { background: $hover; }
QFrame#featureGroupHeader { background: $selection; border: 1px solid $border; border-radius: 8px; }
QFrame#uninstallCard { background: $surface; border: 1px solid $border; border-radius: 8px; }
QFrame#appCard[featureEnabled="false"], QFrame#masterVolumeCard[featureEnabled="false"],
QFrame#microphoneCard[featureEnabled="false"], QFrame#audioOutputCard[featureEnabled="false"], QFrame#settingRow[featureEnabled="false"] { background: $field; }
QLabel:disabled { color: $disabled; }
QLabel#masterAvatar, QLabel#microphoneAvatar, QLabel#audioOutputAvatar { background: $selection; color: $accent; border-radius: 20px; font-size: 17pt; }
QLabel#volumePercent { font-weight: 600; }
QToolButton#muteButton { background: $field; border: 1px solid $border; }
QToolButton#muteButton:checked { color: $danger; background: $danger_surface; }
QToolButton#moreButton { font-size: 16pt; }
QToolButton#helpButton { border: 1px solid $border; color: $muted; border-radius: 14px; }
QToolButton:disabled { color: $disabled; }
QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; border: 3px solid $surface; width: 12px; height: 12px; margin: -7px 0; border-radius: 9px; }
QSlider::handle:horizontal:hover { border-color: $hover; }
QSlider::groove:horizontal:disabled, QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled { background: $disabled; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QCheckBox:disabled { color: $disabled; }
QListWidget#devicesList { background: $surface; border: 1px solid $border; border-radius: 6px; padding: 6px; }
QListWidget#devicesList::item { min-height: 30px; padding: 4px; }
QListWidget#devicesList::item:selected { background: $selection; }
QListWidget#devicesList:disabled, QListWidget#devicesList::item:disabled { background: $field; color: $disabled; }
QLabel#statusCardTitle { font-size: 14pt; font-weight: 600; }
QLabel#metricValue { font-weight: 600; }
QLabel#statusBadge { color: $accent; background: $selection; border: none; border-radius: 4px; padding: 4px 8px; }
QLabel#emptyState { color: $muted; border: 1px dashed $border; border-radius: 8px; padding: 24px; }
QLabel#infoBanner { color: $muted; background: $selection; border: none; border-radius: 6px; padding: 12px; }
QPlainTextEdit#logViewer { background: $field; border: 1px solid $border; border-radius: 6px; padding: 10px; font-family: "Cascadia Mono", "Consolas"; font-size: 9pt; selection-background-color: $selection; }
QMenu { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px; padding: 5px; }
QMenu::item { padding: 8px 20px; border-radius: 4px; }
QMenu::item:selected { background: $selection; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { background: $border; height: 1px; margin: 5px 8px; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar#resourceBar, QProgressBar#microphoneLevelBar { background: $border; border: none; border-radius: 2px; }
QProgressBar#resourceBar::chunk, QProgressBar#microphoneLevelBar::chunk { background: $accent; border-radius: 2px; }
''')


def style_for_theme(base_style: str, theme: str) -> str:
    return base_style + "\n" + _STYLE.substitute(asdict(PALETTES[normalize_theme(theme)]))
