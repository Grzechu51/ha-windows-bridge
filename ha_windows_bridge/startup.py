from __future__ import annotations

# Used only for Windows command-line quoting; no child process is created.
import subprocess  # nosec B404
import sys
import winreg
from contextlib import suppress

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "HAWindowsBridge"


class WindowsStartupManager:
    @staticmethod
    def command() -> str:
        if getattr(sys, "frozen", False):
            parts = [sys.executable, "--autostart"]
        else:
            parts = [sys.executable, "-m", "ha_windows_bridge", "--autostart"]
        return subprocess.list2cmdline(parts)

    def is_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
        except FileNotFoundError:
            return False

    def set_enabled(self, enabled: bool) -> None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, self.command())
            else:
                with suppress(FileNotFoundError):
                    winreg.DeleteValue(key, VALUE_NAME)
