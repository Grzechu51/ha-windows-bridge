"""Compatibility imports for the desktop UI."""

from .ui.inputs import SettingsWheelGuard, WheelSafeComboBox
from .ui.main_window import MainWindow, QtLogHandler, UiSignals

__all__ = ["MainWindow", "QtLogHandler", "UiSignals", "SettingsWheelGuard", "WheelSafeComboBox"]
