"""Documented Windows messages, native caption theme and user accent."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication


def system_accent() -> str | None:
    if sys.platform != "win32":
        return None
    color, opaque = wintypes.DWORD(), wintypes.BOOL()
    try:
        result = ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.byref(opaque))
        return f"#{color.value & 0xFFFFFF:06x}" if result == 0 else None
    except (AttributeError, OSError):
        return None


class WindowsEventBridge(QAbstractNativeEventFilter):
    def __init__(self, application, hwnd: int):
        super().__init__()
        self.application = application
        self.hwnd = hwnd
        self._registered = False
        self._taskbar_message = 0
        self._enabled = sys.platform == "win32" and QApplication.instance().platformName() != "offscreen"
        if self._enabled:
            self._taskbar_message = ctypes.windll.user32.RegisterWindowMessageW("TaskbarCreated")
            self._registered = bool(ctypes.windll.wtsapi32.WTSRegisterSessionNotification(wintypes.HWND(hwnd), 0))
            QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if not self._enabled:
            return False, 0
        record = wintypes.MSG.from_address(int(message))
        if record.hWnd != self.hwnd:
            return False, 0
        if record.message == 0x0218:
            if record.wParam == 4:
                self.application.suspend()
            elif record.wParam in {7, 18}:
                self.application.resume()
        elif record.message == 0x02B1 and record.wParam in {7, 8}:
            self.application.events.emit("windows.locked", record.wParam == 7)
        elif record.message == 0x007E:
            self.application.events.emit("windows.display_changed")
        elif record.message in {0x001A, 0x0320}:
            self.application.events.emit("windows.theme_changed")
        elif record.message == self._taskbar_message:
            self.application.events.emit("windows.explorer_restarted")
        return False, 0

    def close(self):
        if self._enabled:
            QApplication.instance().removeNativeEventFilter(self)
        if self._registered:
            ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(wintypes.HWND(self.hwnd))
            self._registered = False
