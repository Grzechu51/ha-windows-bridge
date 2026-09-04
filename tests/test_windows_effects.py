from __future__ import annotations

import ctypes
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ha_windows_bridge.windows.capture import DesktopDuplicationCapture
from ha_windows_bridge.windows_effects import NativeBackdrop


class _WinCall:
    def __init__(self, callback):
        self.callback = callback
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


def test_native_backdrop_prefers_layered_window_acrylic(monkeypatch) -> None:
    backdrop = NativeBackdrop()
    dwm_calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr("ha_windows_bridge.windows_effects.sys.platform", "win32")
    monkeypatch.setattr(backdrop, "_legacy_acrylic", lambda _hwnd, _opacity: True)
    monkeypatch.setattr(backdrop, "_is_layered_window", lambda _hwnd: True)
    monkeypatch.setattr(
        backdrop,
        "_dwm_attribute",
        lambda hwnd, attribute, value: dwm_calls.append((hwnd, attribute, value)) or True,
    )

    assert backdrop.apply_acrylic(1234, 0.5)
    assert backdrop.backend == "legacy_acrylic"
    assert all(call[1] != NativeBackdrop.DWMWA_SYSTEMBACKDROP_TYPE for call in dwm_calls)


def test_layered_window_falls_back_to_capture_instead_of_grey_dwm(monkeypatch) -> None:
    backdrop = NativeBackdrop()
    monkeypatch.setattr("ha_windows_bridge.windows_effects.sys.platform", "win32")
    monkeypatch.setattr(backdrop, "_legacy_acrylic", lambda _hwnd, _opacity: False)
    monkeypatch.setattr(backdrop, "_is_layered_window", lambda _hwnd: True)

    assert not backdrop.apply_acrylic(1234, 0.5)
    assert backdrop.backend == "none"


def test_prepare_window_removes_dwm_border_and_outer_rounding(monkeypatch) -> None:
    backdrop = NativeBackdrop()
    dwm_calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr("ha_windows_bridge.windows_effects.sys.platform", "win32")
    monkeypatch.setattr(
        backdrop,
        "_dwm_attribute",
        lambda hwnd, attribute, value: dwm_calls.append((hwnd, attribute, value)) or True,
    )

    backdrop.prepare_window(1234)

    assert (
        1234,
        NativeBackdrop.DWMWA_BORDER_COLOR,
        NativeBackdrop.DWMWA_COLOR_NONE,
    ) in dwm_calls
    assert (
        1234,
        NativeBackdrop.DWMWA_WINDOW_CORNER_PREFERENCE,
        NativeBackdrop.DWMWCP_DONOTROUND,
    ) in dwm_calls


def test_rounded_region_uses_real_window_pixels_and_transfers_ownership(monkeypatch) -> None:
    calls = []

    def get_rect(_hwnd, target):
        target._obj.left, target._obj.top = 100, 200
        target._obj.right, target._obj.bottom = 620, 414
        return 1

    create = _WinCall(lambda left, top, right, bottom, width, height: calls.append(
        ("create", left, top, right, bottom, width, height)
    ) or 4321)
    user32 = SimpleNamespace(
        GetWindowRect=get_rect,
        GetDpiForWindow=lambda _hwnd: 96,
        SetWindowRgn=lambda hwnd, region, redraw: calls.append(("set", int(hwnd.value), region, redraw)) or 1,
    )
    gdi32 = SimpleNamespace(
        CreateRoundRectRgn=create,
        DeleteObject=lambda region: calls.append(("delete", region)) or 1,
    )
    monkeypatch.setattr("ha_windows_bridge.windows_effects.sys.platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, gdi32=gdi32))

    assert NativeBackdrop.apply_rounded_region(1234, 14)
    assert ("create", 0, 0, 521, 215, 28, 28) in calls
    assert any(call[0] == "set" for call in calls)
    assert not any(call[0] == "delete" for call in calls)


def test_desktop_duplication_returns_logical_sized_pixmap(monkeypatch) -> None:
    QApplication.instance() or QApplication([])

    class Camera:
        width = 3840
        height = 2160

        def grab(self, *, region, new_frame_only):
            assert region == (20, 40, 220, 140)
            assert new_frame_only is False
            return np.zeros((100, 200, 4), dtype=np.uint8)

        def release(self):
            return None

    create_options = {}

    def create(**kwargs):
        create_options.update(kwargs)
        return Camera()

    fake_dxcam = SimpleNamespace(
        output_info=lambda: "Device[0] Output[0]: Res:(3840, 2160)",
        create=create,
    )
    monkeypatch.setitem(__import__("sys").modules, "dxcam", fake_dxcam)
    capture = DesktopDuplicationCapture()

    result = capture.grab(0, QRect(10, 20, 100, 50), 2.0)

    assert result is not None
    assert result.backend == "dxgi"
    assert result.pixmap.size().width() == 100
    assert result.pixmap.size().height() == 50
    assert create_options["output_color"] == "BGRA"


def test_desktop_duplication_temporarily_excludes_own_window(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    exclusions: list[tuple[int, bool]] = []

    class Camera:
        width = 1920
        height = 1080

        def grab(self, *, region, new_frame_only):
            assert exclusions[-1] == (1234, True)
            return np.zeros((50, 100, 4), dtype=np.uint8)

    fake_dxcam = SimpleNamespace(
        output_info=lambda: "Device[0] Output[0]: Res:(1920, 1080)",
        create=lambda **_kwargs: Camera(),
    )
    monkeypatch.setitem(__import__("sys").modules, "dxcam", fake_dxcam)
    capture = DesktopDuplicationCapture()
    monkeypatch.setattr(
        capture,
        "_set_capture_excluded",
        lambda hwnd, excluded: exclusions.append((hwnd, excluded)) or True,
    )

    result = capture.grab(0, QRect(0, 0, 100, 50), excluded_hwnd=1234)

    assert result is not None
    assert exclusions == [(1234, True), (1234, False)]
