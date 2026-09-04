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
from .ui.theme import PALETTES

STYLE = ""


class BridgeProxyStyle(QProxyStyle):
    """Draw checks with the shared theme; QSS must not cover the checkmark."""

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

        palette = PALETTES[normalize_theme(QApplication.instance().property("bridgeTheme"))]
        border = QColor(palette.accent if hovered or checked else palette.muted)
        fill = QColor(palette.accent if checked else palette.field)
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
            ink = QColor(palette.accent_text)
            if not enabled:
                ink.setAlpha(150)
            pen = QPen(ink, 2.2)
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
