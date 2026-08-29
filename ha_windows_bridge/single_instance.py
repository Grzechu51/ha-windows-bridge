from __future__ import annotations

import ctypes

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = "Local\\HAWindowsBridge"):
        self._kernel32 = ctypes.windll.kernel32
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        self.already_running = self._kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
