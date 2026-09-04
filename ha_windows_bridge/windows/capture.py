"""Experimental capture adapter; not imported or bundled by the 2.0 runtime."""
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

    def invalidate(self) -> None:
        """Re-enumerate outputs after a display topology/DPI change."""
        self.release()
        self._dxcam = None
        self._outputs = None
        self.disabled = False
        self.last_error = ""


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
