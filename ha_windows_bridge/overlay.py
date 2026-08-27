from __future__ import annotations

import base64
import binascii
import html
import io
import re
from collections import deque
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from .system_monitor import WindowsSystemMonitor

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CORNERS = {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
_PRESET_COLORS = {
    "default": "#36c98a",
    "success": "#43ce89",
    "warning": "#f2b84b",
    "error": "#e4656a",
    "info": "#5aa9e6",
}


class OverlayManager(QObject):
    """Passive queued overlay; it never injects into or hooks another process."""

    def __init__(self, duration_seconds: int = 8, allow_fullscreen: bool = False):
        super().__init__()
        self.duration_seconds = max(2, min(60, int(duration_seconds)))
        self.allow_fullscreen = bool(allow_fullscreen)
        self._monitor = WindowsSystemMonitor()
        self._queue: deque[dict[str, Any]] = deque(maxlen=20)
        self._current: dict[str, Any] | None = None
        self._window: QFrame | None = None
        self._icon: QLabel | None = None
        self._label: QLabel | None = None
        self._image: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._timer: QTimer | None = None

    def handle_message(self, title: str, message: str, options: dict[str, Any] | None = None) -> bool:
        raw_options = options or {}
        action = str(raw_options.get("action", "show")).strip().lower()
        if action == "update":
            message_id = str(raw_options.get("id", "")).strip()
            existing = None
            if self._current and self._current["id"] == message_id:
                existing = self._current
            else:
                existing = next(
                    (item for item in self._queue if item["id"] == message_id), None
                )
            if existing is None:
                return False
            merged_options = {**existing, **raw_options, "action": "update", "id": message_id}
            clean = self._validated_request(
                title or existing["title"], message or existing["message"], merged_options
            )
        else:
            clean = self._validated_request(title, message, raw_options)
        action = clean["action"]
        message_id = clean["id"]
        if action == "clear":
            self._queue.clear()
            self._current = None
            self.hide(show_next=False)
            return True
        if action == "remove":
            self._queue = deque(
                (item for item in self._queue if item["id"] != message_id), maxlen=20
            )
            if self._current and self._current["id"] == message_id:
                self._current = None
                self.hide(show_next=True)
            return True
        if action == "update":
            if self._current and self._current["id"] == message_id:
                self._current = clean
                return self._display(clean)
            for index, item in enumerate(self._queue):
                if item["id"] == message_id:
                    self._queue[index] = clean
                    return True
            return False
        if self._current is not None:
            self._queue.append(clean)
            return True
        self._current = clean
        return self._display(clean)

    def show_message(self, title: str, message: str) -> bool:
        return self.handle_message(title, message)

    def hide(self, show_next: bool = True) -> None:
        if self._timer is not None:
            self._timer.stop()
        if self._window is not None:
            self._window.hide()
        if show_next:
            self._current = None
            self._show_next()

    def close(self) -> None:
        self._queue.clear()
        self._current = None
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
        self._window = None
        self._icon = None
        self._label = None
        self._image = None
        self._progress = None
        self._timer = None

    def _show_next(self) -> None:
        if not self._queue:
            return
        self._current = self._queue.popleft()
        self._display(self._current)

    def _display(self, request: dict[str, Any]) -> bool:
        if not self.allow_fullscreen and self._monitor.context_snapshot().fullscreen:
            self._current = None
            QTimer.singleShot(500, self._show_next)
            return False
        self._ensure_window()
        if any(
            item is None
            for item in (
                self._window,
                self._icon,
                self._label,
                self._image,
                self._progress,
                self._timer,
            )
        ):
            return False

        safe_title = html.escape(request["title"])
        safe_message = html.escape(request["message"]).replace("\n", "<br>")
        self._label.setText(f"<b>{safe_title}</b><br>{safe_message}")
        self._icon.setText(request["icon"])
        self._icon.setVisible(bool(request["icon"]))
        pixmap = self._decode_qr(request.get("qr", "")) or self._decode_image(
            request.get("image", "")
        )
        if pixmap is not None:
            self._image.setPixmap(
                pixmap.scaled(
                    440,
                    220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._image.setVisible(True)
        else:
            self._image.clear()
            self._image.setVisible(False)
        progress = request.get("progress")
        self._progress.setVisible(progress is not None)
        if progress is not None:
            self._progress.setValue(progress)

        accent = _PRESET_COLORS[request["preset"]]
        opacity = request["opacity"]
        self._window.setStyleSheet(
            "QFrame#windowsOverlay { background: rgba(10, 13, 15, 235); "
            f"border: 1px solid {accent}; border-radius: 12px; }} "
            "QLabel { color: #f4f7f6; font-size: 14px; background: transparent; } "
            f"QProgressBar {{ background: #293236; border: none; border-radius: 3px; }} "
            f"QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}"
        )
        self._window.setWindowOpacity(opacity)
        widths = {"small": 300, "medium": 420, "large": 580}
        self._window.setFixedWidth(widths[request["size"]])
        self._window.adjustSize()
        self._position(request["monitor"], request["corner"])
        self._window.show()
        self._window.raise_()
        if request["pinned"]:
            self._timer.stop()
        else:
            self._timer.start(request["duration"] * 1000)
        return True

    def _position(self, monitor: int, corner: str) -> None:
        if self._window is None:
            return
        screens = QGuiApplication.screens()
        if not screens:
            return
        screen = screens[max(0, min(len(screens) - 1, monitor))]
        area = screen.availableGeometry()
        margin = 28
        x = area.x() + margin
        y = area.y() + margin
        if corner in {"top_right", "bottom_right"}:
            x = area.right() - self._window.width() - margin
        elif corner == "top_center":
            x = area.x() + (area.width() - self._window.width()) // 2
        if corner in {"bottom_left", "bottom_right"}:
            y = area.bottom() - self._window.height() - margin
        self._window.move(x, y)

    def _ensure_window(self) -> None:
        if self._window is not None:
            return
        window = QFrame()
        window.setObjectName("windowsOverlay")
        window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        window.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setStyleSheet("font-size: 24px")
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(icon)
        top.addWidget(label, 1)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setTextVisible(False)
        progress.setFixedHeight(6)
        layout.addLayout(top)
        layout.addWidget(image)
        layout.addWidget(progress)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.hide(show_next=True))
        self._window = window
        self._icon = icon
        self._label = label
        self._image = image
        self._progress = progress
        self._timer = timer

    def _validated_request(
        self, title: str, message: str, options: dict[str, Any]
    ) -> dict[str, Any]:
        action = str(options.get("action", "show")).strip().lower()
        if action not in {"show", "update", "remove", "clear"}:
            action = "show"
        message_id = str(options.get("id", "default" if action != "show" else "")).strip()
        if message_id and not _ID_RE.fullmatch(message_id):
            message_id = ""
        if not message_id:
            message_id = f"message-{id(options):x}"
        preset = str(options.get("preset", "default")).strip().lower()
        if preset not in _PRESET_COLORS:
            preset = "default"
        corner = str(options.get("corner", "top_right")).strip().lower()
        if corner not in _CORNERS:
            corner = "top_right"
        size = str(options.get("size", "medium")).strip().lower()
        if size not in {"small", "medium", "large"}:
            size = "medium"
        progress = options.get("progress")
        try:
            progress = max(0, min(100, round(float(progress)))) if progress is not None else None
        except (TypeError, ValueError):
            progress = None
        try:
            duration = max(2, min(60, int(options.get("duration", self.duration_seconds))))
        except (TypeError, ValueError):
            duration = self.duration_seconds
        try:
            opacity = max(0.35, min(1.0, float(options.get("opacity", 0.96))))
        except (TypeError, ValueError):
            opacity = 0.96
        try:
            monitor = max(0, min(15, int(options.get("monitor", 0))))
        except (TypeError, ValueError):
            monitor = 0
        return {
            "action": action,
            "id": message_id,
            "title": str(title).strip()[:128] or "Home Assistant",
            "message": str(message).strip()[:2048],
            "icon": str(options.get("icon", "")).strip()[:8],
            "image": str(options.get("image", "")).strip(),
            "qr": str(options.get("qr", "")).strip()[:512],
            "progress": progress,
            "duration": duration,
            "pinned": bool(options.get("pinned", False)),
            "corner": corner,
            "size": size,
            "opacity": opacity,
            "preset": preset,
            "monitor": monitor,
        }

    @staticmethod
    def _decode_image(value: str) -> QPixmap | None:
        if not value.startswith("data:image/") or ";base64," not in value:
            return None
        media_type, encoded = value.split(",", 1)
        if media_type not in {
            "data:image/png;base64",
            "data:image/jpeg;base64",
            "data:image/webp;base64",
            "data:image/gif;base64",
        }:
            return None
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        if not raw or len(raw) > 512 * 1024:
            return None
        signatures = (
            raw.startswith(b"\x89PNG\r\n\x1a\n"),
            raw.startswith(b"\xff\xd8\xff"),
            raw.startswith((b"GIF87a", b"GIF89a")),
            raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        )
        if not any(signatures):
            return None
        pixmap = QPixmap()
        return pixmap if pixmap.loadFromData(raw) else None

    @staticmethod
    def _decode_qr(value: str) -> QPixmap | None:
        if not value:
            return None
        try:
            import qrcode

            image = qrcode.make(value)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            raw = buffer.getvalue()
        except Exception:
            return None
        pixmap = QPixmap()
        return pixmap if pixmap.loadFromData(raw, "PNG") else None
