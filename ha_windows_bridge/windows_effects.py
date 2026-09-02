from __future__ import annotations

import ctypes
import re
import sys
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPixmap


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
    """Best-effort Windows Acrylic with a reliable capture fallback."""

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
            alpha = max(1, min(255, round(float(opacity) * 190)))
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
            self._hwnd, self.DWMWA_WINDOW_CORNER_PREFERENCE, self.DWMWCP_ROUND
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


@dataclass(slots=True)
class CaptureResult:
    pixmap: QPixmap
    backend: str


class DesktopDuplicationCapture:
    """Lazy DXGI Desktop Duplication capture used by Liquid Glass."""

    _OUTPUT_RE = re.compile(r"Device\[(\d+)\]\s+Output\[(\d+)\]")
    _WDA_NONE = 0x00
    _WDA_EXCLUDEFROMCAPTURE = 0x11

    def __init__(self) -> None:
        self._dxcam: Any | None = None
        self._cameras: dict[tuple[int, int], Any] = {}
        self._outputs: list[tuple[int, int]] | None = None
        self.disabled = False
        self.last_error = ""

    @property
    def available(self) -> bool:
        if self.disabled or sys.platform != "win32":
            return False
        try:
            self._load()
        except Exception as exc:
            self.last_error = str(exc)
            return False
        return bool(self._outputs)

    def _load(self) -> None:
        if self._dxcam is not None:
            return
        import dxcam

        self._dxcam = dxcam
        self._outputs = [
            (int(device), int(output))
            for device, output in self._OUTPUT_RE.findall(str(dxcam.output_info()))
        ]

    def _camera(self, screen_index: int) -> Any | None:
        self._load()
        outputs = self._outputs or []
        if not outputs:
            return None
        device_idx, output_idx = outputs[max(0, min(len(outputs) - 1, screen_index))]
        key = (device_idx, output_idx)
        camera = self._cameras.get(key)
        if camera is None:
            camera = self._dxcam.create(
                device_idx=device_idx,
                output_idx=output_idx,
                # Desktop Duplication already exposes BGRA. Keeping that native
                # layout avoids DXCam''s OpenMP RGBA conversion, which otherwise
                # wakes every logical CPU even for a small overlay region.
                output_color="BGRA",
                backend="dxgi",
                processor_backend="numpy",
            )
            self._cameras[key] = camera
        return camera

    @classmethod
    def _set_capture_excluded(cls, hwnd: int, excluded: bool) -> bool:
        if sys.platform != "win32" or not hwnd:
            return False
        affinity = cls._WDA_EXCLUDEFROMCAPTURE if excluded else cls._WDA_NONE
        try:
            applied = bool(
                ctypes.windll.user32.SetWindowDisplayAffinity(
                    wintypes.HWND(hwnd),
                    wintypes.DWORD(affinity),
                )
            )
            return applied
        except (AttributeError, OSError):
            return False

    def grab(
        self,
        screen_index: int,
        logical_region: QRect,
        device_pixel_ratio: float = 1.0,
        excluded_hwnd: int = 0,
    ) -> CaptureResult | None:
        if self.disabled or logical_region.isEmpty():
            return None
        try:
            camera = self._camera(screen_index)
            if camera is None:
                return None
            scale = max(0.5, min(8.0, float(device_pixel_ratio)))
            left = max(0, round(logical_region.left() * scale))
            top = max(0, round(logical_region.top() * scale))
            right = min(camera.width, round((logical_region.right() + 1) * scale))
            bottom = min(camera.height, round((logical_region.bottom() + 1) * scale))
            if right <= left or bottom <= top:
                return None
            capture_excluded = self._set_capture_excluded(excluded_hwnd, True)
            try:
                frame = camera.grab(
                    region=(left, top, right, bottom), new_frame_only=False
                )
            finally:
                if capture_excluded:
                    self._set_capture_excluded(excluded_hwnd, False)
            if frame is None:
                return None
            height, width, channels = frame.shape
            if channels != 4:
                return None
            image = QImage(
                frame.data,
                width,
                height,
                int(frame.strides[0]),
                # ARGB32 is stored as BGRA bytes on little-endian Windows, so
                # this is a zero-conversion mapping of the DXGI frame.
                QImage.Format.Format_ARGB32,
            ).copy()
            target = QSize(logical_region.width(), logical_region.height())
            if image.size() != target:
                image = image.scaled(
                    target,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return CaptureResult(QPixmap.fromImage(image), "dxgi")
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def release(self) -> None:
        for camera in tuple(self._cameras.values()):
            with suppress(Exception):
                camera.release()
        self._cameras.clear()


def on_battery_power() -> bool:
    if sys.platform != "win32":
        return False

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ac_line_status", ctypes.c_ubyte),
            ("battery_flag", ctypes.c_ubyte),
            ("battery_life_percent", ctypes.c_ubyte),
            ("system_status_flag", ctypes.c_ubyte),
            ("battery_life_time", ctypes.c_ulong),
            ("battery_full_life_time", ctypes.c_ulong),
        ]

    status = SystemPowerStatus()
    try:
        return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status))) and (
            status.ac_line_status == 0
        )
    except (AttributeError, OSError):
        return False
