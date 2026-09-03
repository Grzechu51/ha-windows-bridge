from __future__ import annotations

import argparse
import ctypes
import logging
import subprocess  # nosec B404
from contextlib import suppress
from logging.handlers import RotatingFileHandler

# Loading the selected binding before QtPy avoids ambiguous binding discovery
# in frozen builds that contain QtAwesome.
import PySide6.QtCore as QtCore
import qtawesome as qta
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QMessageBox, QProxyStyle, QStyle

from .config import SettingsStore, default_data_dir
from .gui import MainWindow
from .i18n import LocalizedFormatter, set_active_language
from .single_instance import SingleInstance
from .startup import WindowsStartupManager
from .theme import normalize_theme, style_for_theme

STYLE = """
QWidget {
    background: transparent;
    color: #edf4f1;
    font-family: "Segoe UI";
    font-size: 10pt;
}
QFrame#windowFrame {
    background: #090a0c;
    border: 1px solid #33373b;
    border-radius: 12px;
}
QFrame#titleBar {
    background: #0b0c0e;
    border: none;
    border-bottom: 1px solid #292d31;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}
QFrame#titleDivider, QFrame#statusVerticalDivider {
    background: #373c41;
    border: none;
}
QToolButton#hamburgerButton, QToolButton#windowButton, QToolButton#closeButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #e8efed;
    font-size: 14pt;
}
QToolButton#hamburgerButton:hover, QToolButton#windowButton:hover {
    background: #141b1e;
}
QToolButton#closeButton:hover {
    background: #b63d48;
    color: #ffffff;
}
QLabel#windowTitle {
    color: #ffffff;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#windowSubtitle, QLabel#pageSubtitle, QLabel#hint, QLabel#dataLabel {
    color: #90989e;
}
QLabel#windowSubtitle {
    font-size: 8.5pt;
}
QLabel#topStatusDot, QLabel#footerStatusDot {
    color: #46c184;
    font-size: 12pt;
}
QLabel#topStatusLabel, QLabel#footerStatusLabel {
    color: #dde8e4;
}
QFrame#sidebar, QFrame#sidebarFooter {
    background: #0b0c0e;
    border: none;
    border-right: 1px solid #292d31;
}
QPushButton#navButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    color: #e2ebe8;
    padding: 8px 13px;
    text-align: left;
}
QPushButton#navButton:hover {
    background: #171a1d;
    border-color: #394047;
}
QPushButton#navButton:checked {
    background: #16181b;
    border-color: #465047;
    border-left: 3px solid #39b97b;
    color: #ffffff;
}
QFrame#footer {
    background: #0b0c0e;
    border: none;
    border-top: 1px solid #292d31;
}
QLabel#resourceLabel {
    color: #777f85;
    font-size: 7.5pt;
}
QProgressBar#resourceBar {
    background: #1b2428;
    border: none;
    border-radius: 3px;
}
QProgressBar#resourceBar::chunk {
    background: #37835f;
    border-radius: 3px;
}
QLabel#versionLabel {
    color: #90989e;
}
QStackedWidget#pageStack, QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget > QWidget {
    background: #0e0f11;
    border: none;
}
QTabWidget#featureTabs::pane {
    background: #0e0f11;
    border: 1px solid #30363a;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: #0b0c0e;
    color: #8f9995;
    border: 1px solid #30363a;
    padding: 9px 15px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #15191a;
    color: #f4f8f6;
    border-bottom-color: #15191a;
}
QListWidget#devicesList {
    background: #0b0d0f;
    color: #e8efec;
    border: 1px solid #353c40;
    border-radius: 7px;
    padding: 6px;
}
QListWidget#devicesList::item {
    min-height: 30px;
    border-bottom: 1px solid #252a2d;
}
QListWidget#devicesList::item:selected {
    background: #183629;
}
QLabel#pageTitle {
    color: #ffffff;
    font-size: 18pt;
    font-weight: 600;
}
QLabel#sectionTitle {
    color: #f4f8f6;
    font-size: 14pt;
    font-weight: 600;
}
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #121417;
    border: 1px solid #40464b;
    border-radius: 6px;
    color: #edf4f1;
    min-height: 20px;
    padding: 8px 10px;
    selection-background-color: #2f9868;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #465a61;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #46b87b;
}
QFrame#passwordBox {
    background: #15181b;
    border: 1px solid #444a4f;
    border-radius: 6px;
}
QFrame#passwordBox:focus-within {
    border-color: #46b87b;
}
QFrame#passwordBox QLineEdit {
    background: transparent;
    border: none;
    border-radius: 0;
}
QFrame#passwordBox QToolButton {
    background: transparent;
    border: none;
    color: #dfe8e5;
    padding: 7px 10px;
}
QPushButton {
    background: #16181b;
    border: 1px solid #42484d;
    border-radius: 7px;
    color: #edf4f1;
    padding: 8px 14px;
}
QPushButton:hover {
    background: #202328;
    border-color: #5a6269;
}
QPushButton:pressed {
    background: #171a1e;
}
QPushButton:disabled {
    background: #111b20;
    border-color: #28353a;
    color: #65747a;
}
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #287d57, stop:1 #3da872);
    border-color: #4ac486;
    color: #ffffff;
    font-weight: 600;
    padding: 10px 18px;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #319568, stop:1 #46bb80);
}
QPushButton#primaryButton[saved="true"] {
    background: #1f6849;
    border-color: #55d394;
}
QPushButton#outlineButton, QPushButton#secondaryButton {
    background: #121417;
    padding: 10px 18px;
}
QPushButton#mdiPickerButton {
    background: #121417;
    border: 1px solid #40464b;
    border-radius: 6px;
    min-height: 22px;
    padding: 8px 12px;
    text-align: left;
}
QPushButton#mdiPickerButton:hover {
    border-color: #46b87b;
    background: #171b1e;
}
QPushButton#outlineButton:hover, QPushButton#secondaryButton:hover {
    background: #202428;
}
QFrame#appCard, QFrame#masterVolumeCard, QFrame#microphoneCard,
QFrame#audioOutputCard, QFrame#settingRow, QFrame#dataCard {
    background: #131518;
    border: 1px solid #373c42;
    border-radius: 8px;
}
QFrame#featureGroupHeader {
    background: #101714;
    border: 1px solid #327558;
    border-radius: 8px;
}
QFrame#uninstallCard {
    background: #100d0e;
    border: 1px solid #493035;
    border-radius: 8px;
}
QPushButton#dangerButton {
    background: #3a1f24;
    border: 1px solid #73404a;
    border-radius: 6px;
    color: #ffdce2;
    padding: 9px 15px;
}
QPushButton#dangerButton:hover {
    background: #51272f;
    border-color: #a45463;
}
QPushButton#dangerButton:disabled {
    background: #171315;
    border-color: #30272a;
    color: #695d61;
}
QFrame#appCard:hover, QFrame#masterVolumeCard:hover,
QFrame#microphoneCard:hover, QFrame#audioOutputCard:hover {
    background: #181b1f;
    border-color: #4a5258;
}
QLabel#appName, QLabel#settingTitle, QLabel#statusCardTitle {
    color: #f5f8f7;
    font-weight: 600;
}
QLabel#appProcess, QLabel#settingDescription, QLabel#statusCardDetail {
    color: #8e969c;
    font-size: 8.5pt;
}
QLabel#volumePercent {
    color: #eef5f2;
    font-weight: 600;
}
QToolButton#moreButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #aab7b3;
    font-size: 16pt;
}
QToolButton#moreButton:hover {
    background: #223239;
    color: #ffffff;
}
QToolButton#muteButton {
    background: #1b2025;
    border: 1px solid #484f55;
    border-radius: 7px;
    color: #d7e3df;
    font-size: 12pt;
}
QToolButton#muteButton:hover {
    background: #252b30;
    border-color: #4c656d;
}
QToolButton#muteButton:checked {
    background: #4a2429;
    border-color: #a95059;
    color: #ffabb1;
}
QToolButton#moreButton::menu-indicator {
    image: none;
    width: 0px;
}
QLabel#masterAvatar {
    background: #121a1d;
    border: 1px solid #327457;
    border-radius: 20px;
    color: #59d596;
    font-size: 15pt;
}
QLabel#microphoneAvatar, QLabel#audioOutputAvatar {
    background: #1d242a;
    border: 1px solid #365967;
    border-radius: 20px;
    color: #84c9df;
    font-size: 15pt;
}
QLabel#microphoneActivity {
    color: #8e969c;
    font-size: 8.5pt;
}
QLabel#microphoneActivity[active="true"] {
    color: #4bd18d;
    font-weight: 600;
}
QSlider::groove:horizontal {
    background: #262a2e;
    border-radius: 2px;
    height: 3px;
}
QSlider::sub-page:horizontal {
    background: #3aa873;
    border-radius: 2px;
}
QSlider::add-page:horizontal {
    background: #262a2e;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #43ba7d;
    border: 1px solid #2a7955;
    border-radius: 6px;
    margin: -5px 0;
    width: 12px;
}
QSlider::handle:horizontal:hover {
    background: #6cdaa1;
}
QComboBox {
    background: #121417;
    border: 1px solid #40464b;
    border-radius: 6px;
    color: #edf4f1;
    min-height: 22px;
    padding: 7px 10px;
}
QComboBox:hover, QComboBox:focus {
    border-color: #46b87b;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background: #131518;
    border: 1px solid #484f55;
    color: #edf4f1;
    selection-background-color: #1c3d31;
    outline: none;
}
QFrame#statusCard {
    background: #121417;
    border: 1px solid #373c42;
    border-radius: 8px;
}
QLabel#statusBadge {
    background: #141719;
    border: 1px solid #3ba772;
    border-radius: 31px;
    color: #4bd18d;
}
QLabel#statusBadge[connectionState="off"] {
    border-color: #4b5358;
    color: #9ca6a2;
}
QLabel#statusBadge[connectionState="ready"],
QLabel#statusBadge[connectionState="warning"] {
    border-color: #b88736;
    color: #e8b65e;
}
QLabel#metricValue {
    color: #4bd18d;
    font-weight: 600;
}
QLabel#testResult {
    padding-left: 10px;
}
QLabel#testResult[success="true"] {
    color: #4bd18d;
    font-weight: 600;
}
QLabel#testResult[success="false"] {
    color: #f0747d;
    font-weight: 600;
}
QPlainTextEdit#logViewer {
    background: #090a0c;
    border: 1px solid #3b4147;
    border-radius: 7px;
    color: #cbd8d4;
    font-family: "Cascadia Mono", "Consolas";
    padding: 10px;
    selection-background-color: #2f9868;
}
QCheckBox {
    color: #d9e4e0;
    spacing: 10px;
}
QCheckBox::indicator {
    height: 19px;
    width: 19px;
}
QMenu {
    background: #131518;
    border: 1px solid #484f55;
    border-radius: 6px;
    color: #e8efed;
    padding: 5px;
}
QMenu::item {
    border-radius: 4px;
    padding: 8px 30px 8px 12px;
}
QMenu::item:selected {
    background: #1c3d31;
}
QMenu::separator {
    background: #2b3b41;
    height: 1px;
    margin: 4px 8px;
}
QToolTip {
    background: #141d20;
    border: 1px solid #40545b;
    color: #edf4f1;
    padding: 5px;
}
QScrollBar:vertical {
    background: transparent;
    border: none;
    margin: 2px;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #484f55;
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #476068;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
    height: 0;
}
QLabel#formHint {
    color: #858d93;
    font-size: 8.5pt;
    padding: 0 2px 4px 2px;
}
QLabel#infoBanner {
    background: #121417;
    border: 1px solid #383d42;
    border-left: 3px solid #35b878;
    border-radius: 6px;
    color: #a8b8b1;
    padding: 10px 12px;
}
QFrame#appCard[featureEnabled="false"],
QFrame#masterVolumeCard[featureEnabled="false"],
QFrame#microphoneCard[featureEnabled="false"],
QFrame#audioOutputCard[featureEnabled="false"],
QFrame#settingRow[featureEnabled="false"] {
    background: #080b0d;
    border-color: #24282c;
}
QFrame#appCard[featureEnabled="false"]:hover,
QFrame#masterVolumeCard[featureEnabled="false"]:hover,
QFrame#microphoneCard[featureEnabled="false"]:hover,
QFrame#audioOutputCard[featureEnabled="false"]:hover {
    background: #090d0f;
    border-color: #303438;
}
QLabel:disabled {
    color: #465157;
}
QSlider::groove:horizontal:disabled {
    background: #111619;
}
QSlider::sub-page:horizontal:disabled,
QSlider::handle:horizontal:disabled {
    background: #343d41;
    border-color: #343d41;
}
QSlider::add-page:horizontal:disabled {
    background: #111619;
}
QToolButton:disabled, QComboBox:disabled {
    color: #526066;
    background: #0b1012;
    border-color: #202a2e;
}
QSlider {
    background: transparent;
}
QToolButton#helpButton {
    background: #141619;
    border: 1px solid #344148;
    border-radius: 14px;
    color: #9aa8ad;
    font-size: 9pt;
    font-weight: 700;
}
QToolButton#helpButton:hover {
    background: #1b1e21;
    border-color: #3e9e70;
    color: #56ca8e;
}
"""


class BridgeProxyStyle(QProxyStyle):
    """Draws a high-contrast checkbox that stays readable in the dark theme."""

    def drawPrimitive(self, element, option, painter: QPainter, widget=None) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect.adjusted(1, 1, -1, -1))
        checked = bool(option.state & QStyle.StateFlag.State_On)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)

        light = QApplication.instance().property("bridgeTheme") == "light"
        if light:
            border = QColor("#299968" if hovered or checked else "#788680")
            fill = QColor("#319866" if checked else "#ffffff")
        else:
            border = QColor("#62d49a" if hovered or checked else "#65747a")
            fill = QColor("#319866" if checked else "#15181b")
        if not enabled:
            border.setAlpha(105)
            fill.setAlpha(105)
        painter.setPen(QPen(border, 1.8))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4.5, 4.5)

        if checked:
            check = QPainterPath()
            check.moveTo(rect.left() + 4.2, rect.center().y())
            check.lineTo(rect.left() + 7.7, rect.bottom() - 4.4)
            check.lineTo(rect.right() - 3.7, rect.top() + 4.1)
            pen = QPen(QColor("#ffffff"), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(check)
        painter.restore()


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("ha_windows_bridge")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    log_dir = default_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "bridge.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(LocalizedFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    return logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args, _ = parser.parse_known_args(argv)

    from .windows_effects import enable_per_monitor_v2

    enable_per_monitor_v2()
    with suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HAWindowsBridge.App")

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("HA Windows Bridge")
    app.setOrganizationName("HA Windows Bridge")
    app.setQuitOnLastWindowClosed(False)
    bridge_style = BridgeProxyStyle(app.style())
    app.setStyle(bridge_style)

    if args.smoke_test:
        import dxcam
        import websocket

        # Hardware enumeration may legitimately be empty in CI, RDP or a
        # headless session.  The smoke test verifies that the packaged modules
        # and their native dependencies can be imported.
        dependencies_ready = (
            bool(QtCore.qVersion())
            and callable(dxcam.output_info)
            and bool(websocket.__version__)
        )
        return int(qta.icon("mdi6.music").isNull() or not dependencies_ready)
    app._bridge_style = bridge_style

    def apply_theme(theme: str) -> None:
        selected = normalize_theme(theme)
        app.setProperty("bridgeTheme", selected)
        app.setStyleSheet(style_for_theme(STYLE, selected))

    apply_theme("dark")

    instance = SingleInstance()
    if instance.already_running:
        QMessageBox.information(
            None, "HA Windows Bridge", "Program jest już uruchomiony w zasobniku systemowym."
        )
        instance.close()
        return 0

    logger = configure_logging()
    store = SettingsStore()
    try:
        config = store.load()
    except RuntimeError as exc:
        logger.exception("Błąd konfiguracji")
        QMessageBox.warning(
            None, "Błąd konfiguracji", f"{exc}\n\nZostaną użyte ustawienia domyślne."
        )
        from .config import AppConfig

        config = AppConfig()

    apply_theme(config.theme)
    set_active_language(config.language)

    launch_minimized = args.minimized or (args.autostart and config.start_minimized)
    window = MainWindow(
        config,
        store,
        WindowsStartupManager(),
        logger,
        theme_changed=apply_theme,
        launch_minimized=launch_minimized,
    )
    if not launch_minimized:
        window.show()
    app.aboutToQuit.connect(window.stop_bridge)
    exit_code = app.exec()
    pending_uninstaller = window.pending_uninstaller
    instance.close()
    if pending_uninstaller and pending_uninstaller.is_file():
        try:
            # The path is resolved by _find_uninstaller() inside the installed app directory.
            subprocess.Popen([str(pending_uninstaller)], close_fds=True)  # nosec B603
        except OSError as exc:
            logger.error("Nie można uruchomić deinstalatora: %s", exc)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
