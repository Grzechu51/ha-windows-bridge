"""Composition root for the 2.0 desktop preview."""
from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .application.application import Application
from .audio import WindowsAudioService
from .config import AppConfig
from .core.configuration import ConfigurationStore
from .core.secrets import SecretStore
from .media import WindowsMediaService
from .overlays.service import OverlayService
from .single_instance import SingleInstance
from .startup import WindowsStartupManager
from .system_actions import WindowsPowerActions
from .system_monitor import WindowsSystemMonitor
from .ui.control_style import BridgeProxyStyle
from .ui.shell import DesktopWindow
from .ui.theme import style_for_theme
from .windows.credentials import DpapiCipher
from .windows.native import WindowsEventBridge, system_accent
from .windows_effects import NativeBackdrop, enable_per_monitor_v2


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    enable_per_monitor_v2()
    qt = QApplication.instance() or QApplication([])
    qt.setApplicationName("HA Windows Bridge")
    qt.setQuitOnLastWindowClosed(False)
    qt.setStyle(BridgeProxyStyle(qt.style()))
    store = ConfigurationStore(SecretStore(DpapiCipher()))
    instance = None
    if args.smoke_test:
        config = AppConfig(auto_connect=False, start_with_windows=False, control_master_volume=False)
    else:
        instance = SingleInstance()
        if instance.already_running:
            QMessageBox.information(None, "HA Windows Bridge", "Program jest już uruchomiony w zasobniku.")
            instance.close()
            return 0
        try:
            config = store.load()
        except (RuntimeError, ValueError, OSError) as exc:
            QMessageBox.warning(None, "Konfiguracja", str(exc))
            instance.close()
            return 1

    runtime = Application(config, store, WindowsStartupManager(), WindowsAudioService(),
                          WindowsSystemMonitor(), WindowsMediaService(logging.getLogger("bridge.media")),
                          WindowsPowerActions(),
                          monitors=[f"{i + 1}: {screen.name()}" for i, screen in enumerate(qt.screens())])
    overlays = OverlayService(runtime)
    window = DesktopWindow(runtime)
    native_events = WindowsEventBridge(runtime, int(window.winId()))
    def apply_theme(configuration):
        selected = configuration.theme
        if selected == "system":
            selected = "dark" if qt.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        qt.setProperty("bridgeTheme", selected)
        qt.setProperty("bridgeReducedMotion", configuration.reduced_motion)
        qt.setStyleSheet(style_for_theme("", selected, system_accent() if qt.platformName() != "offscreen" else None))
        if sys.platform == "win32" and qt.platformName() != "offscreen":
            NativeBackdrop._dwm_attribute(int(window.winId()), 20, int(selected == "dark"))
        # Native window frame owns resize, caption buttons, Snap and the system menu.
    apply_theme(config)
    window._signals.received.connect(lambda event: apply_theme(event.data if event.topic == "configuration.changed" else runtime.config) if event.topic in {"configuration.changed", "windows.theme_changed"} else None)
    qt.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(runtime.config))
    if args.smoke_test:
        window.show()
        qt.processEvents()
        overlays.example("badges")
        qt.processEvents()
        if len(overlays.windows) != 3 or not runtime.diagnostic_report()["qt"]:
            raise RuntimeError("Packaged presentation or diagnostics did not initialize")
        window._force_close = True
        window.close()
        native_events.close()
        overlays.close()
        return 0 if runtime.shutdown() else 1
    if not args.minimized and not (args.autostart and config.start_minimized):
        window.show()
    if config.auto_connect:
        runtime.start()
    if config.auto_check_updates:
        QTimer.singleShot(10000, runtime.check_updates)
    result = qt.exec()
    native_events.close()
    overlays.close()
    window.dispose()
    stopped = runtime.shutdown()
    instance.close()
    return result if stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())
