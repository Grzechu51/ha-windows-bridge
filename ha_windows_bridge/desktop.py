"""Composition root for the 2.0 desktop preview."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .application.application import Application
from .audio import WindowsAudioService
from .config import AppConfig
from .core.configuration import ConfigurationStore
from .core.secrets import SecretStore
from .core.soak_telemetry import SoakTelemetry
from .media import WindowsMediaService
from .overlays.service import OverlayService
from .single_instance import SingleInstance
from .startup import WindowsStartupManager
from .system_actions import WindowsPowerActions
from .system_monitor import WindowsSystemMonitor
from .ui.control_style import BridgeProxyStyle
from .ui.shell import DesktopWindow
from .ui.theme import style_for_theme, tokens_for_theme
from .windows.credentials import DpapiCipher
from .windows.native import WindowsEventBridge, system_accent
from .windows_effects import NativeBackdrop, enable_per_monitor_v2


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--startup-diagnostic", type=Path, metavar="ABSOLUTE_JSON_PATH")
    parser.add_argument("--soak-telemetry", type=Path, metavar="ABSOLUTE_JSON_PATH")
    args = parser.parse_args(argv)
    if args.startup_diagnostic is not None and (
        not args.startup_diagnostic.is_absolute() or args.smoke_test
    ):
        parser.error("--startup-diagnostic requires an absolute path and normal profile loading")
    trace = {"frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable}

    def checkpoint(stage, **values):
        if args.startup_diagnostic is not None:
            trace.update(stage=stage, **values)
            args.startup_diagnostic.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    if args.soak_telemetry is not None and not args.soak_telemetry.is_absolute():
        parser.error("--soak-telemetry requires an absolute path")
    enable_per_monitor_v2()
    qt = QApplication.instance() or QApplication([])
    qt.setApplicationName("HA Windows Bridge")
    qt.setQuitOnLastWindowClosed(False)
    qt.setStyle(BridgeProxyStyle(qt.style()))
    store = ConfigurationStore(SecretStore(DpapiCipher()))
    if args.startup_diagnostic is not None:
        store.load_diagnostic = lambda values: checkpoint("loader", loader=values)
    checkpoint("resolved", config_path=str(store.config_path), profile_exists=store.config_path.exists())
    instance = None
    if args.smoke_test:
        config = AppConfig(auto_connect=False, start_with_windows=False, control_master_volume=False)
    else:
        if args.startup_diagnostic is None:
            instance = SingleInstance()
            if instance.already_running:
                if not instance.activate_existing():
                    QMessageBox.information(None, "HA Windows Bridge", "Program jest już uruchomiony w zasobniku.")
                instance.close()
                return 0
        try:
            config = store.load()
        except (RuntimeError, ValueError, OSError) as exc:
            if args.startup_diagnostic is not None:
                checkpoint("load_failed", error_type=type(exc).__name__)
                return 1
            QMessageBox.warning(None, "Konfiguracja", str(exc))
            instance.close()
            return 1
        checkpoint("loaded", mqtt_host_present=bool(config.mqtt.host),
                   ha_url_present=bool(config.home_assistant.url),
                   ha_enabled=config.home_assistant.enabled, auto_connect=config.auto_connect)

    runtime = Application(config, store, WindowsStartupManager(), WindowsAudioService(),
                          WindowsSystemMonitor(), WindowsMediaService(logging.getLogger("bridge.media")),
                          WindowsPowerActions(),
                          monitors=[f"{i + 1}: {screen.name()}" for i, screen in enumerate(qt.screens())])
    checkpoint("runtime_created", runtime_matches_loaded=runtime.config == config,
               services=[item.name for item in runtime.states.snapshot()])
    soak = SoakTelemetry(runtime, args.soak_telemetry) if args.soak_telemetry else None
    soak_timer = None
    if soak:
        soak.write()
        soak_timer = QTimer(qt)
        soak_timer.setInterval(5000)
        soak_timer.timeout.connect(soak.write)
        soak_timer.start()
    overlays = OverlayService(runtime)
    window = DesktopWindow(runtime)
    native_events = WindowsEventBridge(runtime, int(window.winId()))
    def apply_theme(configuration):
        selected = configuration.theme
        if selected == "system":
            selected = "dark" if qt.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        accent = system_accent() if qt.platformName() != "offscreen" else None
        tokens = tokens_for_theme(selected, accent)
        qt.setProperty("bridgeTheme", selected)
        qt.setProperty("bridgeAccent", tokens.accent)
        qt.setProperty("bridgeAccentText", tokens.accent_text)
        qt.setProperty("bridgeIcon", tokens.text)
        qt.setProperty("bridgeFocus", tokens.text)
        qt.setProperty("bridgeReducedMotion", configuration.reduced_motion)
        qt.setStyleSheet(style_for_theme("", selected, accent))
        window._refresh_navigation_icons()
        window.update()
        if sys.platform == "win32" and qt.platformName() != "offscreen":
            NativeBackdrop._dwm_attribute(int(window.winId()), 20, int(selected == "dark"))
            caption = 0x151515 if selected == "dark" else 0xF3F3F3
            NativeBackdrop._dwm_attribute(int(window.winId()), 35, caption)
        # Native window frame owns resize, caption buttons, Snap and the system menu.
    apply_theme(config)
    window._signals.received.connect(
        lambda event: apply_theme(event.data if event.topic in {"configuration.changed", "ui.theme_preview"} else window.draft)
        if event.topic in {"configuration.changed", "ui.theme_preview", "windows.theme_changed"} else None
    )
    qt.styleHints().colorSchemeChanged.connect(lambda *_: apply_theme(window.draft))
    if args.startup_diagnostic is not None:
        try:
            checkpoint("gui_created", gui_matches_runtime=window.applied == runtime.config,
                       draft_matches_loaded=window.draft == config,
                       fields_match_loaded=all(
                           window._fields[key].text() == value
                           for key, value in (
                               ("mqtt.host", config.mqtt.host),
                               ("mqtt.username", config.mqtt.username),
                               ("mqtt.password", config.mqtt.password),
                               ("home_assistant.url", config.home_assistant.url),
                               ("home_assistant.token", config.home_assistant.token),
                           )), services_started=False)
        finally:
            window._force_close = True
            window.close()
            native_events.close()
            overlays.close()
            runtime.shutdown()
        return 0
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
        overlays_stopped = overlays.close()
        stopped = runtime.shutdown()
        if soak_timer:
            soak_timer.stop()
        if soak:
            soak.close()
        return 0 if stopped and overlays_stopped else 1
    if not args.minimized and not (args.autostart and config.start_minimized):
        window.show()
    if config.auto_connect:
        runtime.start()
    if config.auto_check_updates:
        QTimer.singleShot(10000, runtime.check_updates)
    result = qt.exec()
    native_events.close()
    overlays_stopped = overlays.close()
    window.dispose()
    stopped = runtime.shutdown()
    if soak_timer:
        soak_timer.stop()
    if soak:
        soak.close()
    instance.close()
    if not overlays_stopped:
        logging.getLogger("bridge").error("Overlay shutdown incomplete")
    return result if stopped and overlays_stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())
