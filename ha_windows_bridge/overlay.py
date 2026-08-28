from __future__ import annotations

import base64
import binascii
import io
import re
import time
from collections import deque
from typing import Any

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .system_monitor import WindowsSystemMonitor

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CORNERS = {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
_PRESET_COLORS = {
    "default": "#91a1a8",
    "success": "#43ce89",
    "warning": "#f2b84b",
    "error": "#e4656a",
    "info": "#5aa9e6",
}


class OverlayManager(QObject):
    """Passive queued overlay; it never injects into or hooks another process."""

    def __init__(
        self,
        duration_seconds: int = 8,
        allow_fullscreen: bool = False,
        *,
        default_monitor: int = 0,
        default_corner: str = "top_right",
        default_size: str = "medium",
        default_opacity: float = 0.94,
        default_show_close_button: bool = True,
        default_close_on_click: bool = False,
        close_tooltip: str = "Close overlay",
    ):
        super().__init__()
        self.duration_seconds = max(2, min(60, int(duration_seconds)))
        self.allow_fullscreen = bool(allow_fullscreen)
        self.default_monitor = max(0, min(15, int(default_monitor)))
        self.default_corner = default_corner if default_corner in _CORNERS else "top_right"
        self.default_size = (
            default_size if default_size in {"small", "medium", "large"} else "medium"
        )
        self.default_opacity = max(0.65, min(1.0, float(default_opacity)))
        self.default_show_close_button = bool(default_show_close_button)
        self.default_close_on_click = bool(default_close_on_click)
        self.close_tooltip = close_tooltip
        self._monitor = WindowsSystemMonitor()
        self._queue: deque[dict[str, Any]] = deque(maxlen=20)
        self._current: dict[str, Any] | None = None
        self._window: QFrame | None = None
        self._card: QFrame | None = None
        self._icon: QLabel | None = None
        self._title: QLabel | None = None
        self._label: QLabel | None = None
        self._cover: QLabel | None = None
        self._image: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._progress_time: QLabel | None = None
        self._close_button: QToolButton | None = None
        self._timer: QTimer | None = None
        self._progress_timer: QTimer | None = None
        self._progress_started_at = 0.0

    def handle_message(
        self, title: str, message: str, options: dict[str, Any] | None = None
    ) -> bool:
        raw_options = options or {}
        action = str(raw_options.get("action", "show")).strip().lower()
        if action == "update":
            message_id = str(raw_options.get("id", "")).strip()
            existing = None
            if self._current and self._current["id"] == message_id:
                existing = self._current
            else:
                existing = next((item for item in self._queue if item["id"] == message_id), None)
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
        if self._progress_timer is not None:
            self._progress_timer.stop()
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
        self._card = None
        self._icon = None
        self._title = None
        self._label = None
        self._cover = None
        self._image = None
        self._progress = None
        self._progress_time = None
        self._close_button = None
        self._timer = None
        self._progress_timer = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        card_content = self._card is not None and (
            watched is self._card
            or (isinstance(watched, QWidget) and self._card.isAncestorOf(watched))
        )
        if (
            card_content
            and event.type() == QEvent.Type.MouseButtonRelease
            and self._current is not None
            and self._current.get("close_on_click", False)
        ):
            self.hide(show_next=True)
            return True
        return super().eventFilter(watched, event)

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
                self._card,
                self._icon,
                self._title,
                self._label,
                self._cover,
                self._image,
                self._progress,
                self._progress_time,
                self._close_button,
                self._timer,
                self._progress_timer,
            )
        ):
            return False

        self._title.setText(request["title"])
        self._label.setText(request["message"])
        self._label.setVisible(bool(request["message"]))
        self._icon.setText(request["icon"])
        self._icon.setVisible(bool(request["icon"]))
        pixmap = self._decode_qr(request.get("qr", "")) or self._decode_image(
            request.get("image", "")
        )
        widths = {"small": 320, "medium": 400, "large": 520}
        card_width = widths[request["size"]]
        if pixmap is not None:
            if request["layout"] == "media":
                self._cover.setPixmap(
                    pixmap.scaled(
                        104,
                        104,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._cover.setVisible(True)
                self._image.clear()
                self._image.setVisible(False)
            else:
                self._image.setPixmap(
                    pixmap.scaled(
                        card_width - 48,
                        240,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self._image.setVisible(True)
                self._cover.clear()
                self._cover.setVisible(False)
        else:
            self._cover.clear()
            self._cover.setVisible(False)
            self._image.clear()
            self._image.setVisible(False)
        self._progress_started_at = 0.0
        progress = self._current_progress(request)
        self._progress.setVisible(progress is not None)
        if progress is not None:
            self._progress.setValue(progress)
        self._update_progress_time(request)

        accent = _PRESET_COLORS[request["preset"]]
        accent_color = QColor(accent)
        tint_strength = 0.0 if request["preset"] == "default" else 0.08
        background = tuple(
            round(base * (1.0 - tint_strength) + value * tint_strength)
            for base, value in zip(
                (12, 15, 18),
                (accent_color.red(), accent_color.green(), accent_color.blue()),
                strict=True,
            )
        )
        background_alpha = round(255 * request["opacity"])
        border_alpha = 72 if request["preset"] == "default" else 165
        icon_background = (
            f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 36)"
        )
        self._window.setStyleSheet(
            "QFrame#windowsOverlay { background: transparent; border: none; } "
            f"QFrame#overlayCard {{ background-color: rgba({background[0]}, "
            f"{background[1]}, {background[2]}, {background_alpha}); "
            f"border: 1px solid rgba({accent_color.red()}, {accent_color.green()}, "
            f"{accent_color.blue()}, {border_alpha}); border-radius: 17px; }} "
            "QLabel { background: transparent; } "
            "QLabel#overlayTitle { color: #f5f8f7; font-size: 15px; "
            "font-weight: 700; } "
            "QLabel#overlayMessage { color: #b9c3c7; font-size: 13px; } "
            "QLabel#overlayCover { background-color: #171d20; border: 1px solid #334044; "
            "border-radius: 12px; padding: 3px; } "
            f"QLabel#overlayIcon {{ color: {accent}; background-color: {icon_background}; "
            f"border: 1px solid {accent}; border-radius: 18px; font-size: 17px; "
            "font-weight: 700; } "
            "QToolButton#overlayClose { color: #9da9ad; background: transparent; border: none; "
            "border-radius: 12px; font-size: 17px; font-weight: 600; } "
            "QToolButton#overlayClose:hover { color: #ffffff; background: rgba(255,255,255,24); } "
            "QProgressBar#overlayProgress { background: #273034; border: none; "
            "border-radius: 3px; } "
            f"QProgressBar#overlayProgress::chunk {{ background: {accent}; "
            "border-radius: 3px; } "
            "QLabel#overlayProgressTime { color: #93a0a5; font-size: 11px; }"
        )
        self._window.setWindowOpacity(1.0)
        self._close_button.setVisible(request["show_close_button"])
        interactive = request["show_close_button"] or request["close_on_click"]
        self._window.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not interactive,
        )
        self._card.setCursor(
            Qt.CursorShape.PointingHandCursor
            if request["close_on_click"]
            else Qt.CursorShape.ArrowCursor
        )
        self._card.setFixedWidth(card_width)
        self._window.setFixedWidth(card_width + 20)
        self._window.ensurePolished()
        self._window.adjustSize()
        self._position(request["monitor"], request["corner"])
        self._window.show()
        self._window.raise_()
        self._progress_started_at = time.monotonic()
        if request["media_playing"] and request["media_duration"] > 0:
            self._progress_timer.start(500)
        else:
            self._progress_timer.stop()
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
        x, y = self._position_for_geometry(
            area,
            self._window.width(),
            self._window.height(),
            corner,
        )
        self._window.move(x, y)

    @staticmethod
    def _position_for_geometry(
        area: QRect,
        width: int,
        height: int,
        corner: str,
        margin: int = 0,
    ) -> tuple[int, int]:
        """Position the transparent shadow window; the visible card adds 8 px."""
        x = area.left() + margin
        y = area.top() + margin
        if corner in {"top_right", "bottom_right"}:
            x = area.right() + 1 - width - margin
        elif corner == "top_center":
            x = area.left() + (area.width() - width) // 2
        if corner in {"bottom_left", "bottom_right"}:
            y = area.bottom() + 1 - height - margin
        return x, y

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
        outer = QHBoxLayout(window)
        outer.setContentsMargins(4, 4, 4, 8)

        card = QFrame()
        card.setObjectName("overlayCard")
        card.installEventFilter(self)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 175))
        card.setGraphicsEffect(shadow)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        content = QVBoxLayout()
        content.setContentsMargins(15, 14, 16, 14)
        content.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(14)
        cover = QLabel()
        cover.setObjectName("overlayCover")
        cover.setFixedSize(112, 112)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setVisible(False)
        body.addWidget(cover, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(10)
        icon = QLabel()
        icon.setObjectName("overlayIcon")
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel()
        title.setObjectName("overlayTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(title, 1, Qt.AlignmentFlag.AlignVCenter)
        close_button = QToolButton()
        close_button.setObjectName("overlayClose")
        close_button.setText("×")
        close_button.setToolTip(self.close_tooltip)
        close_button.setFixedSize(26, 26)
        close_button.setVisible(False)
        close_button.clicked.connect(lambda: self.hide(show_next=True))
        top.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel()
        label.setObjectName("overlayMessage")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress = QProgressBar()
        progress.setObjectName("overlayProgress")
        progress.setRange(0, 100)
        progress.setTextVisible(False)
        progress.setFixedHeight(6)
        text.addLayout(top)
        text.addWidget(label)
        text.addStretch()
        body.addLayout(text, 1)
        content.addLayout(body)
        content.addWidget(image)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        progress_time = QLabel()
        progress_time.setObjectName("overlayProgressTime")
        progress_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_time.setVisible(False)
        for clickable in (card, cover, icon, title, label, image, progress, progress_time):
            clickable.installEventFilter(self)
        progress_row.addWidget(progress, 1)
        progress_row.addWidget(progress_time)
        content.addLayout(progress_row)
        card_layout.addLayout(content, 1)
        outer.addWidget(card)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.hide(show_next=True))
        progress_timer = QTimer(window)
        progress_timer.timeout.connect(self._refresh_live_progress)
        self._window = window
        self._card = card
        self._icon = icon
        self._title = title
        self._label = label
        self._cover = cover
        self._image = image
        self._progress = progress
        self._progress_time = progress_time
        self._close_button = close_button
        self._timer = timer
        self._progress_timer = progress_timer

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
        corner = str(options.get("corner", self.default_corner)).strip().lower()
        if corner not in _CORNERS:
            corner = self.default_corner
        size = str(options.get("size", self.default_size)).strip().lower()
        if size not in {"small", "medium", "large"}:
            size = self.default_size
        layout = str(options.get("layout", "default")).strip().lower()
        if layout not in {"default", "media"}:
            layout = "default"
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
            opacity = max(0.65, min(1.0, float(options.get("opacity", self.default_opacity))))
        except (TypeError, ValueError):
            opacity = self.default_opacity
        try:
            monitor = max(0, min(15, int(options.get("monitor", self.default_monitor))))
        except (TypeError, ValueError):
            monitor = 0
        try:
            media_position = max(0.0, float(options.get("media_position", 0.0)))
        except (TypeError, ValueError):
            media_position = 0.0
        try:
            media_duration = max(0.0, float(options.get("media_duration", 0.0)))
        except (TypeError, ValueError):
            media_duration = 0.0
        if media_duration:
            media_position = min(media_position, media_duration)
            progress = round(media_position / media_duration * 100)
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
            "show_close_button": bool(
                options.get("show_close_button", self.default_show_close_button)
            ),
            "close_on_click": bool(options.get("close_on_click", self.default_close_on_click)),
            "corner": corner,
            "size": size,
            "layout": layout,
            "opacity": opacity,
            "preset": preset,
            "monitor": monitor,
            "media_position": media_position,
            "media_duration": media_duration,
            "media_playing": bool(options.get("media_playing", False)),
        }

    def _current_progress(self, request: dict[str, Any]) -> int | None:
        duration = float(request.get("media_duration", 0.0))
        if duration <= 0:
            return request.get("progress")
        position = float(request.get("media_position", 0.0))
        if request.get("media_playing") and self._progress_started_at:
            position += max(0.0, time.monotonic() - self._progress_started_at)
        return max(0, min(100, round(min(position, duration) / duration * 100)))

    @staticmethod
    def _clock(seconds: float) -> str:
        value = max(0, round(seconds))
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    def _update_progress_time(self, request: dict[str, Any]) -> None:
        if self._progress_time is None:
            return
        duration = float(request.get("media_duration", 0.0))
        if duration <= 0:
            self._progress_time.clear()
            self._progress_time.setVisible(False)
            return
        position = float(request.get("media_position", 0.0))
        if request.get("media_playing") and self._progress_started_at:
            position += max(0.0, time.monotonic() - self._progress_started_at)
        position = min(position, duration)
        self._progress_time.setText(f"{self._clock(position)} / {self._clock(duration)}")
        self._progress_time.setVisible(True)

    def _refresh_live_progress(self) -> None:
        if self._current is None or self._progress is None:
            return
        progress = self._current_progress(self._current)
        if progress is not None:
            self._progress.setValue(progress)
        self._update_progress_time(self._current)
        if progress is not None and progress >= 100 and self._progress_timer is not None:
            self._progress_timer.stop()

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
