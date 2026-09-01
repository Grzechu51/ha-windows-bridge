from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ha_windows_bridge.windows_effects import DesktopDuplicationCapture


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

    fake_dxcam = SimpleNamespace(
        output_info=lambda: "Device[0] Output[0]: Res:(3840, 2160)",
        create=lambda **_kwargs: Camera(),
    )
    monkeypatch.setitem(__import__("sys").modules, "dxcam", fake_dxcam)
    capture = DesktopDuplicationCapture()

    result = capture.grab(0, QRect(10, 20, 100, 50), 2.0)

    assert result is not None
    assert result.backend == "dxgi"
    assert result.pixmap.size().width() == 100
    assert result.pixmap.size().height() == 50


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
