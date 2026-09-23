from __future__ import annotations

import ctypes

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = "Local\\HAWindowsBridge"):
        self._kernel32 = ctypes.windll.kernel32
        self._handle = self._kernel32.CreateMutexW(None, False, name)
        self.already_running = self._kernel32.GetLastError() == ERROR_ALREADY_EXISTS

    def activate_existing(self, title: str = "HA Windows Bridge") -> bool:
        """Restore the existing top-level window when a second launch is detected."""
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
        user32.FindWindowW.restype = ctypes.c_void_p
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            return False
        from .windows.native import INSTANCE_ACTIVATE_MESSAGE

        message = user32.RegisterWindowMessageW(INSTANCE_ACTIVATE_MESSAGE)
        if not message:
            return False
        user32.SendMessageTimeoutW.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t),
        )
        user32.SendMessageTimeoutW.restype = ctypes.c_void_p
        result = ctypes.c_size_t()
        return bool(user32.SendMessageTimeoutW(
            hwnd, message, 0, 0, 0x0002, 1000, ctypes.byref(result),
        ))
    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
