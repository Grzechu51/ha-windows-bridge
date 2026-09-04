"""Shared motion policy; Qt's animation clock chooses the frame cadence."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QObject, QVariantAnimation
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class MotionToken:
    duration: int
    easing: QEasingCurve.Type
    distance: float = 0.0
    scale: float = 1.0


class MotionSystem:
    TOKENS = {
        "fast": MotionToken(100, QEasingCurve.Type.OutCubic),
        "normal": MotionToken(180, QEasingCurve.Type.OutCubic),
        "slow": MotionToken(260, QEasingCurve.Type.OutCubic),
        "popup_enter": MotionToken(220, QEasingCurve.Type.OutCubic, distance=12, scale=0.98),
        "popup_exit": MotionToken(160, QEasingCurve.Type.InCubic),
        "reposition": MotionToken(180, QEasingCurve.Type.OutCubic),
        "page": MotionToken(180, QEasingCurve.Type.OutCubic),
        "toggle": MotionToken(120, QEasingCurve.Type.OutCubic),
        "hover": MotionToken(100, QEasingCurve.Type.OutCubic),
        "press": MotionToken(80, QEasingCurve.Type.OutCubic),
    }

    @staticmethod
    def enabled() -> bool:
        app = QGuiApplication.instance()
        if app is not None and (app.property("bridgeReducedMotion") or app.platformName() == "offscreen"):
            return False
        if sys.platform != "win32":
            return True
        enabled = ctypes.c_int(1)
        try:
            ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        except (AttributeError, OSError):
            return True
        return bool(ok and enabled.value)

    @classmethod
    def animate(cls, parent: QObject, role: str, frame: Callable[[float], None],
                finished: Callable[[], None]) -> QVariantAnimation:
        token = cls.TOKENS[role]
        animation = QVariantAnimation(parent)
        animation.setProperty("motionRole", role)
        animation.setDuration(token.duration)
        animation.setEasingCurve(token.easing)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.valueChanged.connect(frame)
        animation.finished.connect(finished)
        animation.finished.connect(animation.deleteLater)
        return animation
