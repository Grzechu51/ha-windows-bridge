from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def enable_per_monitor_v2() -> bool:
    """Enable DPI awareness before QApplication is constructed."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
    except (AttributeError, OSError):
        try:
            return ctypes.windll.shcore.SetProcessDpiAwareness(2) in {0, 0x80070005}
        except (AttributeError, OSError):
            return False


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("accent_state", ctypes.c_int),
        ("accent_flags", ctypes.c_int),
        ("gradient_color", ctypes.c_uint),
        ("animation_id", ctypes.c_int),
    ]


class _WindowCompositionAttributeData(ctypes.Structure):
    _fields_ = [
        ("attribute", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("size_of_data", ctypes.c_size_t),
    ]


class NativeBackdrop:
    """Best-effort Windows Acrylic; the presentation owns its painted fallback."""

    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWA_BORDER_COLOR = 34
    DWMWA_SYSTEMBACKDROP_TYPE = 38
    DWMWCP_DONOTROUND = 1
    DWMWCP_ROUND = 2
    DWMWA_COLOR_NONE = -2
    DWMSBT_NONE = 1
    DWMSBT_TRANSIENTWINDOW = 3
    WCA_ACCENT_POLICY = 19
    ACCENT_DISABLED = 0
    ACCENT_ENABLE_BLURBEHIND = 3
    ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000

    def __init__(self) -> None:
        self.backend = "none"
        self._hwnd = 0

    @staticmethod
    def _dwm_attribute(hwnd: int, attribute: int, value: int) -> bool:
        try:
            setting = ctypes.c_int(value)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(setting),
                ctypes.sizeof(setting),
            )
            return result == 0
        except (AttributeError, OSError):
            return False

    @classmethod
    def _legacy_acrylic(cls, hwnd: int, opacity: float) -> bool:
        try:
            alpha = max(1, min(255, round(float(opacity) * 80)))
            policy = _AccentPolicy(
                cls.ACCENT_ENABLE_ACRYLICBLURBEHIND,
                2,
                (alpha << 24) | 0x181512,
                0,
            )
            data = _WindowCompositionAttributeData(
                cls.WCA_ACCENT_POLICY,
                ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
                ctypes.sizeof(policy),
            )
            return bool(
                ctypes.windll.user32.SetWindowCompositionAttribute(
                    wintypes.HWND(hwnd), ctypes.byref(data)
                )
            )
        except (AttributeError, OSError):
            return False

    @classmethod
    def _is_layered_window(cls, hwnd: int) -> bool:
        try:
            get_style = getattr(ctypes.windll.user32, "GetWindowLongPtrW", None)
            if get_style is None:
                get_style = ctypes.windll.user32.GetWindowLongW
            style = int(get_style(wintypes.HWND(hwnd), cls.GWL_EXSTYLE))
            return bool(style & cls.WS_EX_LAYERED)
        except (AttributeError, OSError):
            return True

    def apply_acrylic(self, hwnd: int, opacity: float = 0.9) -> bool:
        if sys.platform != "win32" or not hwnd:
            self.backend = "none"
            return False
        self._hwnd = int(hwnd)
        self._dwm_attribute(
            self._hwnd, self.DWMWA_BORDER_COLOR, self.DWMWA_COLOR_NONE
        )
        self._dwm_attribute(
            self._hwnd, self.DWMWA_WINDOW_CORNER_PREFERENCE, self.DWMWCP_DONOTROUND
        )
        # Qt's WA_TranslucentBackground creates a layered window. The public
        # DWM transient backdrop can report success for that window and still
        # paint an opaque light-grey sheet. The accent-policy Acrylic path is
        # compatible with layered frameless windows, so prefer it here.
        if self._legacy_acrylic(self._hwnd, opacity):
            self.backend = "legacy_acrylic"
            return True
        if not self._is_layered_window(self._hwnd) and self._dwm_attribute(
            self._hwnd,
            self.DWMWA_SYSTEMBACKDROP_TYPE,
            self.DWMSBT_TRANSIENTWINDOW,
        ):
            self.backend = "dwm_acrylic"
            return True
        self.backend = "none"
        return False

    def prepare_window(self, hwnd: int) -> None:
        """Remove the DWM non-client outline from the frameless Qt surface."""
        if sys.platform != "win32" or not hwnd:
            return
        self._hwnd = int(hwnd)
        self._dwm_attribute(
            self._hwnd, self.DWMWA_BORDER_COLOR, self.DWMWA_COLOR_NONE
        )
        self._dwm_attribute(
            self._hwnd,
            self.DWMWA_WINDOW_CORNER_PREFERENCE,
            self.DWMWCP_DONOTROUND,
        )

    @staticmethod
    def exclude_capture(hwnd, excluded):
        if sys.platform != "win32" or not hwnd:
            return False
        try:
            return bool(ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), wintypes.DWORD(0x11 if excluded else 0)))
        except (AttributeError, OSError):
            return False

    @staticmethod
    def apply_rounded_region(hwnd: int, radius: int = 14) -> bool:
        """Apply an HWND region immediately, independent of DWM's first frame."""
        if sys.platform != "win32" or not hwnd:
            return False
        try:
            rect = wintypes.RECT()
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            get_rect = user32.GetWindowRect
            get_rect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            get_rect.restype = wintypes.BOOL
            if not get_rect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                return False
            width, height = rect.right - rect.left, rect.bottom - rect.top
            get_dpi = getattr(user32, "GetDpiForWindow", None)
            if get_dpi is not None:
                get_dpi.argtypes = (wintypes.HWND,)
                get_dpi.restype = ctypes.c_uint
            dpi = get_dpi(wintypes.HWND(hwnd)) if get_dpi is not None else 96
            dpi = dpi or 96
            diameter = max(2, round(radius * 2 * dpi / 96))
            create_region = gdi32.CreateRoundRectRgn
            create_region.argtypes = (ctypes.c_int,) * 6
            create_region.restype = wintypes.HANDLE
            region = create_region(0, 0, width + 1, height + 1, diameter, diameter)
            if not region:
                return False
            set_region = user32.SetWindowRgn
            set_region.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
            set_region.restype = ctypes.c_int
            if set_region(wintypes.HWND(hwnd), region, True):
                # Windows owns the region after a successful SetWindowRgn.
                return True
            delete_object = gdi32.DeleteObject
            delete_object.argtypes = (wintypes.HANDLE,)
            delete_object.restype = wintypes.BOOL
            delete_object(region)
        except (AttributeError, OSError):
            pass
        return False

    def apply_blur(self, hwnd):
        self.prepare_window(hwnd)
        try:
            policy = _AccentPolicy(self.ACCENT_ENABLE_BLURBEHIND, 0, 0, 0)
            data = _WindowCompositionAttributeData(self.WCA_ACCENT_POLICY, ctypes.cast(ctypes.byref(policy), ctypes.c_void_p), ctypes.sizeof(policy))
            if ctypes.windll.user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data)):
                self.backend = "native_blur"
                return True
        except (AttributeError, OSError):
            pass
        return self.apply_acrylic(hwnd, .3)

    def disable(self) -> None:
        hwnd = self._hwnd
        if sys.platform != "win32" or not hwnd:
            self.backend = "none"
            return
        self._dwm_attribute(hwnd, self.DWMWA_SYSTEMBACKDROP_TYPE, self.DWMSBT_NONE)
        self._dwm_attribute(hwnd, self.DWMWA_BORDER_COLOR, self.DWMWA_COLOR_NONE)
        self._dwm_attribute(
            hwnd,
            self.DWMWA_WINDOW_CORNER_PREFERENCE,
            self.DWMWCP_DONOTROUND,
        )
        try:
            policy = _AccentPolicy(self.ACCENT_DISABLED, 0, 0, 0)
            data = _WindowCompositionAttributeData(
                self.WCA_ACCENT_POLICY,
                ctypes.cast(ctypes.byref(policy), ctypes.c_void_p),
                ctypes.sizeof(policy),
            )
            ctypes.windll.user32.SetWindowCompositionAttribute(
                wintypes.HWND(hwnd), ctypes.byref(data)
            )
        except (AttributeError, OSError):
            pass
        self.backend = "none"
