from __future__ import annotations

import base64
import binascii
import ctypes
import io
import re
import sys
import time
from collections import deque
from typing import Any

import qtawesome as qta
from PIL import Image, ImageDraw, ImageFilter, ImageGrab
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
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
from .windows_effects import DesktopDuplicationCapture, NativeBackdrop, on_battery_power

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CORNERS = {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
_CHANNELS = {"general", "security", "system", "media", "work"}
_PRIORITIES = {"low": 0, "normal": 1, "high": 2, "critical": 3}
_PRESET_COLORS = {
    "default": "#91a1a8",
    "success": "#43ce89",
    "warning": "#f2b84b",
    "error": "#e4656a",
    "info": "#5aa9e6",
}
class OverlayCard(QFrame):
    """Card surface that can paint glass or full-card media artwork."""

    def __init__(self) -> None:
        super().__init__()
        self._glass_background: QPixmap | None = None
        self._glass_opacity = 0.0
        self._glass_effect = "none"
        self._media_background: QPixmap | None = None
        self._media_surface = QColor(18, 22, 24)
        self._media_opacity = 1.0
        self._text_scrim = QColor(0, 0, 0, 0)

    def set_glass_background(
        self,
        pixmap: QPixmap | None,
        opacity: float = 0.0,
        effect: str = "none",
    ) -> None:
        self._glass_background = pixmap
        self._glass_opacity = max(0.0, min(1.0, float(opacity)))
        self._glass_effect = effect if effect in {"blur", "liquid"} else "none"
        self.update()

    def set_media_background(
        self,
        pixmap: QPixmap | None,
        surface: QColor | None = None,
        opacity: float = 1.0,
    ) -> None:
        self._media_background = pixmap
        if surface is not None:
            self._media_surface = QColor(surface)
        self._media_opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def set_text_scrim(self, color: QColor | None = None) -> None:
        self._text_scrim = QColor(color) if color is not None else QColor(0, 0, 0, 0)
        self.update()

    @staticmethod
    def _right_artwork_rect(card_size: QSize, artwork_size: QSize) -> QRect:
        """Fit the complete artwork into the right side without cropping it."""
        card_width = max(1, card_size.width())
        card_height = max(1, card_size.height())
        artwork_width = max(1, artwork_size.width())
        artwork_height = max(1, artwork_size.height())
        maximum_width = max(1, round(card_width * 0.68))
        scale = min(maximum_width / artwork_width, card_height / artwork_height)
        width = max(1, round(artwork_width * scale))
        height = max(1, round(artwork_height * scale))
        return QRect(card_width - width, (card_height - height) // 2, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        background = self._media_background or self._glass_background
        if background is None or background.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card_rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(card_rect, 16, 16)
        painter.setClipPath(path)
        if self._media_background is not None:
            painter.setOpacity(self._media_opacity)
            painter.fillPath(path, self._media_surface)
            artwork_rect = self._right_artwork_rect(self.size(), background.size())
            scaled = background.scaled(
                artwork_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(artwork_rect.topLeft(), scaled)
            transition_width = max(
                72,
                min(
                    round(self.width() * 0.29),
                    round(artwork_rect.width() * 0.72),
                ),
            )
            transition_start = max(
                0,
                artwork_rect.left() - round(transition_width * 0.22),
            )
            transition_end = min(
                self.width(),
                artwork_rect.left() + transition_width,
            )
            blend = QLinearGradient(
                transition_start,
                0,
                transition_end,
                0,
            )
            solid = QColor(self._media_surface)
            blend.setColorAt(0.0, solid)
            near_edge = QColor(solid)
            near_edge.setAlpha(250)
            blend.setColorAt(0.18, near_edge)
            middle = QColor(solid)
            middle.setAlpha(205)
            blend.setColorAt(0.45, middle)
            soft_edge = QColor(solid)
            soft_edge.setAlpha(105)
            blend.setColorAt(0.72, soft_edge)
            clear = QColor(solid)
            clear.setAlpha(0)
            blend.setColorAt(1.0, clear)
            painter.fillPath(path, QBrush(blend))
            painter.setOpacity(1.0)
        else:
            painter.setOpacity(self._glass_opacity)
            if self._glass_effect == "liquid":
                # A slight magnification of the blurred capture suggests the
                # lensing used by thicker glass without distorting the content.
                source_rect = QRectF(background.rect()).adjusted(4, 4, -4, -4)
                painter.drawPixmap(QRectF(self.rect()), background, source_rect)
            else:
                painter.drawPixmap(self.rect(), background)
            painter.setOpacity(1.0)
            if self._glass_effect == "liquid":
                shade = QLinearGradient(0, 0, 0, self.height())
                shade.setColorAt(0.0, QColor(255, 255, 255, 36))
                shade.setColorAt(0.42, QColor(255, 255, 255, 8))
                shade.setColorAt(1.0, QColor(5, 12, 18, 38))
                painter.fillPath(path, QBrush(shade))
                gloss = QRadialGradient(
                    self.width() * 0.18,
                    0,
                    max(self.width(), self.height()) * 0.78,
                )
                gloss.setColorAt(0.0, QColor(255, 255, 255, 86))
                gloss.setColorAt(0.34, QColor(255, 255, 255, 30))
                gloss.setColorAt(0.72, QColor(188, 224, 238, 10))
                gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(path, QBrush(gloss))
                painter.setClipping(False)
                edge = QLinearGradient(0, 0, 0, self.height())
                edge.setColorAt(0.0, QColor(255, 255, 255, 168))
                edge.setColorAt(0.48, QColor(255, 255, 255, 58))
                edge.setColorAt(1.0, QColor(225, 242, 248, 104))
                painter.setPen(QPen(QBrush(edge), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), 15, 15)
                painter.setPen(QPen(QColor(255, 255, 255, 30), 2.2))
                painter.drawRoundedRect(card_rect.adjusted(3, 3, -3, -3), 13, 13)
        if self._text_scrim.alpha() > 0 and self._media_background is None:
            painter.setClipPath(path)
            scrim = QLinearGradient(0, 0, max(1, self.width() * 0.82), 0)
            solid_scrim = QColor(self._text_scrim)
            scrim.setColorAt(0.0, solid_scrim)
            middle_scrim = QColor(solid_scrim)
            middle_scrim.setAlpha(round(solid_scrim.alpha() * 0.82))
            scrim.setColorAt(0.62, middle_scrim)
            clear_scrim = QColor(solid_scrim)
            clear_scrim.setAlpha(0)
            scrim.setColorAt(1.0, clear_scrim)
            painter.fillPath(path, QBrush(scrim))
        painter.end()


class OverlayManager(QObject):
    """Passive queued overlay; it never injects into or hooks another process."""

    def __init__(
        self,
        duration_seconds: int = 8,
        allow_fullscreen: bool = False,
        *,
        default_monitor: int = 0,
        close_tooltip: str = "Close overlay",
    ):
        super().__init__()
        self.duration_seconds = max(2, min(60, int(duration_seconds)))
        self.allow_fullscreen = bool(allow_fullscreen)
        self.default_monitor = max(0, min(15, int(default_monitor)))
        self.close_tooltip = close_tooltip
        self._monitor = WindowsSystemMonitor()
        self._queue: deque[dict[str, Any]] = deque(maxlen=20)
        self._current: dict[str, Any] | None = None
        self._window: QFrame | None = None
        self._card: QFrame | None = None
        self._icon: QLabel | None = None
        self._title: QLabel | None = None
        self._media_title: QLabel | None = None
        self._label: QLabel | None = None
        self._cover: QLabel | None = None
        self._image: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._lifetime_progress: QProgressBar | None = None
        self._progress_time: QLabel | None = None
        self._close_button: QToolButton | None = None
        self._timer: QTimer | None = None
        self._progress_timer: QTimer | None = None
        self._glass_timer: QTimer | None = None
        self._lifetime_timer: QTimer | None = None
        self._animation: QVariantAnimation | None = None
        self._progress_started_at = 0.0
        self._animations_allowed = self._system_animations_enabled()
        self._liquid_compatible = not self._is_remote_session()
        self._glass_capture_failures = 0
        self._glass_slow_frames = 0
        self._glass_text_mode = ""
        self._native_backdrop = NativeBackdrop()
        self._desktop_capture = DesktopDuplicationCapture()
        self._capture_backend = "imagegrab"
        self._last_capture_signature = b""
        self._glass_idle_frames = 0
        self._glass_interval_ms = 220
        self._last_capture_changed = True
        self._gpu_capture_failures = 0
        self._dismiss_deadline = 0.0
        self._dismiss_remaining_ms = 0
        self._hover_paused = False
        self._screen_signals_connected = False
        self._screen_signal_ids: set[int] = set()

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
            channel = clean.get("channel", "")
            if channel:
                self._queue = deque(
                    (item for item in self._queue if item.get("channel") != channel),
                    maxlen=20,
                )
                if self._current and self._current.get("channel") == channel:
                    self._current = None
                    self.hide(show_next=True)
            else:
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
                    self._sort_queue()
                    return True
            return False
        if self._current is not None:
            if (
                clean["priority"] > self._current.get("priority", 1)
                and not self._current.get("pinned", False)
            ):
                self._queue.append(self._current)
                self._sort_queue()
                self._current = clean
                return self._display(clean)
            self._queue.append(clean)
            self._sort_queue()
            return True
        self._current = clean
        return self._display(clean)

    def show_message(self, title: str, message: str) -> bool:
        return self.handle_message(title, message)

    @staticmethod
    def test_pattern_names() -> tuple[tuple[str, str], ...]:
        return (
            ("compact", "Krótka wiadomość"),
            ("long", "Długa treść"),
            ("liquid", "Liquid Glass"),
            ("camera", "Kamera priorytetowa"),
            ("channels", "Kanały i priorytety"),
        )

    @staticmethod
    def _test_camera_image() -> str:
        image = Image.new("RGB", (960, 540), "#122636")
        draw = ImageDraw.Draw(image)
        for y in range(image.height):
            ratio = y / max(1, image.height - 1)
            draw.line(
                (0, y, image.width, y),
                fill=(round(18 + 30 * ratio), round(38 + 66 * ratio), round(54 + 70 * ratio)),
            )
        draw.ellipse((360, 90, 600, 330), fill="#d5a75b", outline="#f8ddb0", width=8)
        draw.rectangle((0, 390, 960, 540), fill="#152129")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=86, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    def show_test_pattern(self, name: str) -> bool:
        patterns: dict[str, tuple[str, str, dict[str, Any]]] = {
            "compact": (
                "Home Assistant",
                "Drzwi wejściowe zostały zamknięte.",
                {"icon": "mdi:door-closed", "layout": "compact", "preset": "success"},
            ),
            "long": (
                "Podsumowanie automatyzacji",
                "Ogrzewanie przeszło w tryb ekonomiczny, rolety zostały opuszczone, "
                "a światła w nieużywanych pomieszczeniach wyłączone.",
                {"icon": "mdi:home-automation", "layout": "standard"},
            ),
            "liquid": (
                "Liquid Glass",
                "Tło jest przechwytywane przez GPU i odświeżane zależnie od zmian obrazu.",
                {"icon": "mdi:blur", "background_effect": "liquid"},
            ),
            "camera": (
                "Kamera: podjazd",
                "Wykryto ruch w strefie wejściowej.",
                {
                    "icon": "mdi:cctv",
                    "layout": "camera",
                    "image": self._test_camera_image(),
                    "channel": "security",
                    "priority": "critical",
                },
            ),
            "channels": (
                "Kanał systemowy · wysoki priorytet",
                "Wiadomości o wyższym priorytecie wyprzedzają zwykłą kolejkę.",
                {"icon": "mdi:layers-triple", "channel": "system", "priority": "high"},
            ),
        }
        title, message, options = patterns.get(name, patterns["compact"])
        return self.handle_message(
            title,
            message,
            {
                "id": f"local-test-{name}",
                "duration": 8,
                "show_lifetime": True,
                "pause_on_hover": True,
                **options,
            },
        )

    def _sort_queue(self) -> None:
        self._queue = deque(
            sorted(self._queue, key=lambda item: item.get("priority", 1), reverse=True),
            maxlen=20,
        )

    def hide(self, show_next: bool = True) -> None:
        if self._timer is not None:
            self._timer.stop()
        if self._progress_timer is not None:
            self._progress_timer.stop()
        if self._glass_timer is not None:
            self._glass_timer.stop()
        if self._lifetime_timer is not None:
            self._lifetime_timer.stop()
        if (
            self._window is not None
            and self._card is not None
            and self._window.isVisible()
            and self._animations_allowed
        ):
            self._stop_animation()
            start_size = QSize(self._card.size())
            request = self._current
            animation = QVariantAnimation(self._window)
            animation.setDuration(360)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.InCubic)

            def apply_frame(value: object) -> None:
                if self._window is None or self._card is None:
                    return
                progress = max(0.0, min(1.0, float(value)))
                scale = 1.0 - progress * 0.035
                width = max(1, round(start_size.width() * scale))
                height = max(1, round(start_size.height() * scale))
                self._card.setFixedSize(width, height)
                self._window.setFixedSize(width + 20, height + 12)
                if request is not None:
                    self._position(
                        request["monitor"],
                        request["corner"],
                        request["edge_offset"],
                    )
                self._window.setWindowOpacity(1.0 - progress)

            def finish() -> None:
                if self._window is not None and self._card is not None:
                    self._card.setFixedSize(start_size)
                    self._window.setFixedSize(
                        start_size.width() + 20,
                        start_size.height() + 12,
                    )
                    if request is not None:
                        self._position(
                            request["monitor"],
                            request["corner"],
                            request["edge_offset"],
                        )
                self._finish_hide(show_next)

            animation.valueChanged.connect(apply_frame)
            animation.finished.connect(finish)
            self._animation = animation
            animation.start()
            return
        self._finish_hide(show_next)

    def _finish_hide(self, show_next: bool) -> None:
        if self._window is not None:
            self._window.hide()
            self._window.setWindowOpacity(1.0)
        self._native_backdrop.disable()
        self._animation = None
        if show_next:
            self._current = None
            self._show_next()

    def _stop_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None

    def _show_with_animation(
        self,
        request: dict[str, Any],
        previous_size: QSize,
        was_visible: bool,
    ) -> None:
        if self._window is None or self._card is None:
            return
        final_size = QSize(self._card.size())
        self._stop_animation()
        if not self._animations_allowed:
            self._window.setWindowOpacity(1.0)
            self._window.show()
            self._window.raise_()
            self._configure_dynamic_glass(request)
            return
        if was_visible and previous_size.isValid():
            start_size = previous_size
        else:
            start_size = QSize(
                max(1, round(final_size.width() * 0.94)),
                max(1, round(final_size.height() * 0.94)),
            )
        animation = QVariantAnimation(self._window)
        animation.setDuration(380 if was_visible else 520)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic if was_visible else QEasingCurve.Type.OutBack
        )

        def apply_frame(value: object) -> None:
            if self._window is None or self._card is None:
                return
            progress = float(value)
            width = round(
                start_size.width()
                + (final_size.width() - start_size.width()) * progress
            )
            height = round(
                start_size.height()
                + (final_size.height() - start_size.height()) * progress
            )
            self._card.setFixedSize(max(1, width), max(1, height))
            self._window.setFixedSize(max(1, width) + 20, max(1, height) + 12)
            self._position(
                request["monitor"], request["corner"], request["edge_offset"]
            )
            opacity = (
                min(1.0, max(0.0, progress))
                if not was_visible
                else min(1.0, 0.9 + max(0.0, progress) * 0.1)
            )
            self._window.setWindowOpacity(opacity)

        def finish() -> None:
            if self._window is None or self._card is None:
                return
            self._card.setFixedSize(final_size)
            self._window.setFixedSize(final_size.width() + 20, final_size.height() + 12)
            self._window.setWindowOpacity(1.0)
            self._position(
                request["monitor"], request["corner"], request["edge_offset"]
            )
            self._animation = None
            self._configure_dynamic_glass(request)

        animation.valueChanged.connect(apply_frame)
        animation.finished.connect(finish)
        self._animation = animation
        apply_frame(0.0)
        self._window.show()
        self._window.raise_()
        animation.start()

    def close(self) -> None:
        self._queue.clear()
        self._current = None
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        if self._glass_timer is not None:
            self._glass_timer.stop()
        if self._lifetime_timer is not None:
            self._lifetime_timer.stop()
        self._native_backdrop.disable()
        self._desktop_capture.release()
        if self._window is not None:
            self._window.close()
            self._window.deleteLater()
        self._window = None
        self._card = None
        self._icon = None
        self._title = None
        self._media_title = None
        self._label = None
        self._cover = None
        self._image = None
        self._progress = None
        self._lifetime_progress = None
        self._progress_time = None
        self._close_button = None
        self._timer = None
        self._progress_timer = None
        self._glass_timer = None
        self._lifetime_timer = None

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
        if card_content and self._current is not None and self._current.get(
            "pause_on_hover", False
        ):
            if event.type() == QEvent.Type.Enter:
                self._pause_dismiss_timer()
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._resume_if_pointer_left)
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
                self._media_title,
                self._label,
                self._cover,
                self._image,
                self._progress,
                self._lifetime_progress,
                self._progress_time,
                self._close_button,
                self._timer,
                self._progress_timer,
                self._glass_timer,
                self._lifetime_timer,
            )
        ):
            return False

        if self._glass_timer is not None:
            self._glass_timer.stop()
        was_visible = self._window.isVisible()
        previous_size = QSize(self._card.size())
        self._clear_adaptive_legibility()
        pixmap = self._decode_qr(request.get("qr", "")) or self._decode_image(
            request.get("image", "")
        )
        resolved_layout = self._resolve_layout(request, pixmap is not None)
        request["_resolved_layout"] = resolved_layout
        media_layout = resolved_layout == "media"
        camera_layout = resolved_layout == "camera"
        compact_layout = resolved_layout == "compact"
        self._title.setText(
            request["media_source"] or "Media Player"
            if media_layout
            else request["title"]
        )
        self._media_title.setText(request["title"])
        self._media_title.setVisible(media_layout)
        self._label.setText(request["message"])
        self._label.setVisible(bool(request["message"]))
        card_width = (
            request["width"]
            if request["size_mode"] == "manual"
            else self._automatic_width(request, pixmap is not None)
        )
        media_artwork = pixmap is not None and media_layout
        if pixmap is not None:
            if media_layout:
                self._cover.clear()
                self._cover.setVisible(False)
                self._image.clear()
                self._image.setVisible(False)
            else:
                self._image.setPixmap(
                    pixmap.scaled(
                        card_width - (30 if camera_layout else 48),
                        min(620, max(120, request["height"] - 80))
                        if request["size_mode"] == "manual"
                        else 360 if camera_layout else 240,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding
                        if camera_layout
                        else Qt.AspectRatioMode.KeepAspectRatio,
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
        media_surface, media_primary, media_secondary = self._media_palette(
            pixmap if media_artwork else None
        )
        accent_color = (
            QColor(media_primary)
            if media_layout
            else QColor(_PRESET_COLORS[request["preset"]])
        )
        accent = accent_color.name()
        tint_strength = 0.0 if request["preset"] == "default" else 0.08
        background = tuple(
            round(base * (1.0 - tint_strength) + value * tint_strength)
            for base, value in zip(
                (12, 15, 18),
                (accent_color.red(), accent_color.green(), accent_color.blue()),
                strict=True,
            )
        )
        background_effect = self._effective_background_effect(request["background_effect"])
        request["_effective_background_effect"] = background_effect
        native_blur = False
        application = QGuiApplication.instance()
        native_allowed = (
            sys.platform == "win32"
            and application is not None
            and application.platformName() != "offscreen"
            and not self._is_remote_session()
        )
        if background_effect == "blur" and not media_layout and native_allowed:
            native_blur = self._native_backdrop.apply_acrylic(
                int(self._window.winId()), request["opacity"]
            )
        else:
            self._native_backdrop.disable()
        request["_backdrop_backend"] = (
            self._native_backdrop.backend if native_blur else "capture"
        )
        surface_alpha = (
            86
            if native_blur
            else {"none": 255, "blur": 150, "liquid": 92}[background_effect]
        )
        background_alpha = round(surface_alpha * request["opacity"])
        border_alpha = (
            132
            if background_effect == "liquid"
            else 105
            if background_effect == "blur" and request["preset"] == "default"
            else 72
            if request["preset"] == "default"
            else 165
        )
        icon_background = (
            f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 36)"
        )
        if media_artwork:
            card_surface = "background: transparent; "
            border_color = media_primary
            border_alpha = 88
            title_color = media_primary.name()
            media_title_color = media_primary.name()
            message_color = media_secondary.name()
        elif media_layout:
            card_surface = (
                f"background-color: rgba({media_surface.red()}, {media_surface.green()}, "
                f"{media_surface.blue()}, {round(255 * request['opacity'])}); "
            )
            border_color = media_primary
            border_alpha = 88
            title_color = media_primary.name()
            media_title_color = media_primary.name()
            message_color = media_secondary.name()
        else:
            card_surface = (
                f"background-color: rgba({background[0]}, {background[1]}, "
                f"{background[2]}, {background_alpha}); "
            )
            border_color = accent_color
            title_color = "#f5f8f7"
            media_title_color = "#f5f8f7"
            message_color = "#b9c3c7"
        if isinstance(self._card, OverlayCard):
            self._card.set_media_background(
                pixmap if media_artwork else None,
                media_surface,
                request["opacity"],
            )
        self._icon.setFixedSize(25, 25) if media_layout else self._icon.setFixedSize(36, 36)
        self._set_icon(request["icon"], accent)
        title_size = 12 if media_layout else 15
        title_weight = 600 if media_layout else 700
        icon_surface = "transparent" if media_layout else icon_background
        icon_border = "transparent" if media_layout else accent
        icon_radius = 0 if media_layout else 18
        track_color = (
            "rgba(0, 0, 0, 58)"
            if media_layout and media_surface.lightness() >= 145
            else "rgba(255, 255, 255, 54)"
            if media_layout
            else "#273034"
        )
        self._window.setStyleSheet(
            "QFrame#windowsOverlay { background: transparent; border: none; } "
            f"QFrame#overlayCard {{ {card_surface}"
            f"border: 1px solid rgba({border_color.red()}, {border_color.green()}, "
            f"{border_color.blue()}, {border_alpha}); border-radius: 17px; }} "
            "QLabel { background: transparent; } "
            f"QLabel#overlayTitle {{ color: {title_color}; font-size: {title_size}px; "
            f"font-weight: {title_weight}; }} "
            f"QLabel#overlayMediaTitle {{ color: {media_title_color}; font-size: 15px; "
            "font-weight: 700; } "
            f"QLabel#overlayMessage {{ color: {message_color}; font-size: "
            f"{12 if media_layout else 13}px; }} "
            "QLabel#overlayCover { background-color: #171d20; border: 1px solid #334044; "
            "border-radius: 12px; padding: 3px; } "
            f"QLabel#overlayIcon {{ color: {accent}; background-color: {icon_surface}; "
            f"border: 1px solid {icon_border}; border-radius: {icon_radius}px; font-size: 17px; "
            "font-weight: 700; } "
            f"QToolButton#overlayClose {{ color: {message_color}; background: transparent; "
            "border: none; "
            "border-radius: 12px; font-size: 17px; font-weight: 600; } "
            f"QToolButton#overlayClose:hover {{ color: {title_color}; "
            "background: rgba(255,255,255,24); } "
            f"QProgressBar#overlayProgress {{ background: {track_color}; border: none; "
            "border-radius: 3px; } "
            f"QProgressBar#overlayProgress::chunk {{ background: {accent}; "
            "border-radius: 3px; } "
            "QProgressBar#overlayLifetime { background: rgba(255,255,255,24); "
            "border: none; border-radius: 1px; } "
            f"QProgressBar#overlayLifetime::chunk {{ background: {accent}; "
            "border-radius: 1px; } "
            f"QLabel#overlayProgressTime {{ color: {message_color}; font-size: 11px; }}"
        )
        self._window.setWindowOpacity(1.0)
        self._close_button.setVisible(request["show_close_button"])
        interactive = (
            request["show_close_button"]
            or request["close_on_click"]
            or request["pause_on_hover"]
        )
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
        if request["size_mode"] == "manual":
            self._card.setFixedHeight(request["height"])
            self._window.setFixedHeight(request["height"] + 12)
        else:
            self._fit_automatic_height(
                card_width,
                minimum_height=(
                    180
                    if media_layout
                    else 280
                    if camera_layout
                    else 72
                    if compact_layout
                    else 72
                ),
            )
        self._position(
            request["monitor"], request["corner"], request["edge_offset"]
        )
        if isinstance(self._card, OverlayCard):
            if media_artwork or background_effect == "blur" and native_blur:
                self._card.set_glass_background(None)
            elif background_effect != "none":
                captured = self._capture_glass_background(
                    request["opacity"],
                    background_effect,
                )
                if not captured and background_effect == "liquid":
                    self._fallback_liquid_to_blur()
            else:
                self._card.set_glass_background(None)
                self._clear_adaptive_legibility()
        self._show_with_animation(request, previous_size, was_visible)
        self._progress_started_at = time.monotonic()
        if request["media_playing"] and request["media_duration"] > 0:
            self._progress_timer.start(500)
        else:
            self._progress_timer.stop()
        self._start_dismiss_timer(request)
        return True

    @staticmethod
    def _resolve_layout(request: dict[str, Any], has_image: bool) -> str:
        layout = str(request.get("layout", "default"))
        if layout in {"compact", "standard", "media", "camera"}:
            return layout
        if request.get("camera"):
            return "camera"
        if request.get("media_source"):
            return "media"
        content_length = len(request.get("title", "")) + len(request.get("message", ""))
        if not has_image and request.get("progress") is None and content_length <= 96:
            return "compact"
        return "standard"

    @staticmethod
    def _automatic_width(request: dict[str, Any], has_image: bool) -> int:
        longest_line = max(
            (
                len(line)
                for line in (
                    f"{request.get('media_source', '')}\n"
                    f"{request['title']}\n{request['message']}"
                ).splitlines()
            ),
            default=0,
        )
        text_width = max(170, min(430, longest_line * 7))
        chrome = 54
        if request["icon"]:
            chrome += 44
        if request["show_close_button"]:
            chrome += 30
        width = text_width + chrome
        layout = request.get("_resolved_layout", request.get("layout"))
        if layout == "media":
            width = max(width, 480)
        elif layout == "camera":
            width = max(width, 520)
        elif layout == "compact":
            width = min(width, 430)
        elif has_image:
            width = max(width, 440)
        return max(280, min(600, width))

    def _fit_automatic_height(self, card_width: int, minimum_height: int = 72) -> None:
        if self._window is None or self._card is None:
            return
        self._card.setMinimumHeight(0)
        self._card.setMaximumHeight(16_777_215)
        self._window.setMinimumHeight(0)
        self._window.setMaximumHeight(16_777_215)
        layout = self._card.layout()
        layout.invalidate()
        layout.activate()
        card_height = layout.heightForWidth(card_width)
        if card_height < 0:
            card_height = self._card.sizeHint().height()
        card_height = max(minimum_height, min(900, card_height))
        self._card.setFixedHeight(card_height)
        self._window.setFixedHeight(card_height + 12)

    @staticmethod
    def _average_artwork_color(
        pixmap: QPixmap | None, left_fraction: float = 1.0
    ) -> QColor | None:
        if pixmap is None or pixmap.isNull():
            return None
        sample = pixmap.toImage().scaled(
            24,
            24,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        red = green = blue = weight_total = 0.0
        sampled_width = max(
            1,
            min(sample.width(), round(sample.width() * max(0.05, left_fraction))),
        )
        for x in range(sampled_width):
            for y in range(sample.height()):
                color = sample.pixelColor(x, y)
                if color.alpha() < 32:
                    continue
                saturation_weight = 1.0 + color.hsvSaturationF() * 1.6
                if color.lightness() >= 242:
                    saturation_weight *= 0.35
                red += color.red() * saturation_weight
                green += color.green() * saturation_weight
                blue += color.blue() * saturation_weight
                weight_total += saturation_weight
        if not weight_total:
            return QColor(28, 34, 38)
        return QColor(
            round(red / weight_total),
            round(green / weight_total),
            round(blue / weight_total),
        )

    @staticmethod
    def _relative_luminance(color: QColor) -> float:
        def linear(channel: int) -> float:
            value = channel / 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        return (
            0.2126 * linear(color.red())
            + 0.7152 * linear(color.green())
            + 0.0722 * linear(color.blue())
        )

    @classmethod
    def _contrast_ratio(cls, foreground: QColor, background: QColor) -> float:
        lighter, darker = sorted(
            (
                cls._relative_luminance(foreground),
                cls._relative_luminance(background),
            ),
            reverse=True,
        )
        return (lighter + 0.05) / (darker + 0.05)

    @classmethod
    def _ensure_contrast(
        cls, foreground: QColor, background: QColor, minimum: float
    ) -> QColor:
        candidate = QColor(foreground)
        if cls._contrast_ratio(candidate, background) >= minimum:
            return candidate
        hsl = candidate.toHsl()
        hue = hsl.hslHue() if hsl.hslHue() >= 0 else 190
        saturation = max(0, hsl.hslSaturation())
        target = 18 if background.lightness() >= 145 else 238
        start = hsl.lightness()
        for step in range(1, 21):
            lightness = round(start + (target - start) * step / 20)
            adjusted = QColor()
            adjusted.setHsl(hue, saturation, lightness)
            if cls._contrast_ratio(adjusted, background) >= minimum:
                return adjusted
        return QColor("#111617" if background.lightness() >= 145 else "#f3f7f5")

    @classmethod
    def _media_palette(
        cls, pixmap: QPixmap | None
    ) -> tuple[QColor, QColor, QColor]:
        # The artwork's left edge touches the generated surface, so sampling it
        # produces a natural continuation instead of an unrelated average tint.
        artwork = cls._average_artwork_color(pixmap, 0.35) or QColor(47, 61, 67)
        hsl = artwork.toHsl()
        hue = hsl.hslHue() if hsl.hslHue() >= 0 else 190
        saturation = max(28, min(150, hsl.hslSaturation()))
        light_surface = artwork.lightness() >= 145
        surface = QColor()
        surface.setHsl(
            hue,
            max(24, round(saturation * 0.72)),
            205 if light_surface else max(38, min(92, round(artwork.lightness() * 0.78))),
        )
        primary = QColor()
        secondary = QColor()
        if light_surface:
            primary.setHsl(hue, max(32, min(115, saturation)), 42)
            secondary.setHsl(hue, max(20, min(80, round(saturation * 0.65))), 72)
        else:
            primary.setHsl(hue, max(32, min(135, saturation)), 220)
            secondary.setHsl(hue, max(18, min(90, round(saturation * 0.58))), 178)
        return (
            surface,
            cls._ensure_contrast(primary, surface, 4.8),
            cls._ensure_contrast(secondary, surface, 3.6),
        )

    @staticmethod
    def _is_remote_session() -> bool:
        if sys.platform != "win32":
            return False
        try:
            return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
        except (AttributeError, OSError):
            return False

    @staticmethod
    def _system_animations_enabled() -> bool:
        application = QGuiApplication.instance()
        if application is not None and application.platformName() == "offscreen":
            return False
        if sys.platform != "win32":
            return True
        enabled = ctypes.c_int(1)
        try:
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x1042,
                0,
                ctypes.byref(enabled),
                0,
            )
        except (AttributeError, OSError):
            return True
        return bool(ok and enabled.value)

    def _effective_background_effect(self, requested: str) -> str:
        if requested == "liquid" and not self._liquid_compatible:
            return "blur"
        return requested

    @staticmethod
    def _pixmap_from_pil(image: Image.Image) -> QPixmap:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        data = rgba.tobytes("raw", "RGBA")
        qimage = QImage(
            data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        return QPixmap.fromImage(qimage)

    def _desktop_region(
        self,
        top_left: QPoint,
        width: int,
        height: int,
        *,
        prefer_gpu: bool = False,
    ) -> QPixmap | None:
        if width <= 0 or height <= 0:
            return None
        screens = QGuiApplication.screens()
        screen = QGuiApplication.screenAt(top_left + QPoint(width // 2, height // 2))
        if screen is None and screens:
            screen = screens[0]
        if prefer_gpu and screen is not None and self._desktop_capture.available:
            screen_index = screens.index(screen) if screen in screens else 0
            origin = screen.geometry().topLeft()
            local = QRect(top_left - origin, QSize(width, height))
            result = self._desktop_capture.grab(
                screen_index,
                local,
                screen.devicePixelRatio(),
                int(self._window.winId()) if self._window is not None else 0,
            )
            if result is not None and not result.pixmap.isNull():
                self._capture_backend = result.backend
                self._gpu_capture_failures = 0
                return result.pixmap
            self._gpu_capture_failures += 1
            if self._gpu_capture_failures >= 3:
                self._desktop_capture.disabled = True
        bounds = self._physical_capture_bounds(
            top_left,
            width,
            height,
            screen.geometry() if screen is not None else QRect(),
            screen.devicePixelRatio() if screen is not None else 1.0,
        )
        try:
            capture = ImageGrab.grab(
                bbox=bounds,
                include_layered_windows=False,
                all_screens=True,
            )
            pixmap = self._pixmap_from_pil(capture)
            if not pixmap.isNull():
                self._capture_backend = "imagegrab"
                return pixmap
        except (OSError, TypeError, ValueError):
            pass
        if self._window is not None and self._window.isVisible():
            return None
        top_left = self._card.mapToGlobal(QPoint(0, 0))
        if screen is None:
            return None
        screen_origin = screen.geometry().topLeft()
        source = screen.grabWindow(
            0,
            top_left.x() - screen_origin.x(),
            top_left.y() - screen_origin.y(),
            width,
            height,
        )
        if source.isNull():
            return None
        self._capture_backend = "qt"
        return source

    @staticmethod
    def _physical_capture_bounds(
        top_left: QPoint,
        width: int,
        height: int,
        screen_geometry: QRect,
        device_pixel_ratio: float,
    ) -> tuple[int, int, int, int]:
        if screen_geometry.isEmpty():
            return (
                top_left.x(),
                top_left.y(),
                top_left.x() + width,
                top_left.y() + height,
            )
        scale = max(0.5, min(8.0, float(device_pixel_ratio)))
        local = top_left - screen_geometry.topLeft()
        left = screen_geometry.left() + round(local.x() * scale)
        top = screen_geometry.top() + round(local.y() * scale)
        return (
            left,
            top,
            left + round(width * scale),
            top + round(height * scale),
        )

    @staticmethod
    def _capture_signature(source: QPixmap) -> bytes:
        if source.isNull():
            return b""
        sample = source.toImage().scaled(
            20,
            12,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ).convertToFormat(QImage.Format.Format_RGB888)
        return bytes(sample.constBits())

    def _capture_glass_background(self, opacity: float, effect: str) -> bool:
        if not isinstance(self._card, OverlayCard) or self._window is None:
            return False
        if opacity <= 0:
            self._card.set_glass_background(None)
            self._clear_adaptive_legibility()
            return True
        top_left = self._card.mapToGlobal(QPoint(0, 0))
        source = self._desktop_region(
            top_left,
            self._card.width(),
            self._card.height(),
            prefer_gpu=effect == "liquid" and self._liquid_compatible,
        )
        if source is None:
            return False
        signature = self._capture_signature(source)
        self._last_capture_changed = signature != self._last_capture_signature
        if (
            not self._last_capture_changed
            and self._card._glass_background is not None
            and self._card._glass_effect == effect
        ):
            return True
        self._last_capture_signature = signature
        radius = 32 if effect == "liquid" else 20
        blurred = self._blur_pixmap(source, radius)
        self._card.set_glass_background(blurred, opacity, effect)
        self._apply_adaptive_legibility(blurred)
        return True

    @staticmethod
    def _blur_pixmap(source: QPixmap, radius: float = 24) -> QPixmap:
        if source.isNull() or radius <= 0:
            return QPixmap(source)
        image = source.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        width = image.width()
        height = image.height()
        raw = bytes(image.constBits())
        pil_image = Image.frombytes(
            "RGBA",
            (width, height),
            raw,
            "raw",
            "RGBA",
            image.bytesPerLine(),
            1,
        )
        blurred = pil_image.filter(ImageFilter.GaussianBlur(float(radius)))
        return OverlayManager._pixmap_from_pil(blurred)

    @classmethod
    def _backdrop_luminance(cls, pixmap: QPixmap) -> float:
        if pixmap.isNull():
            return 0.0
        sample = pixmap.toImage().scaled(
            20,
            12,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        text_columns = max(1, round(sample.width() * 0.72))
        values = [
            cls._relative_luminance(sample.pixelColor(x, y))
            for x in range(text_columns)
            for y in range(sample.height())
        ]
        return sum(values) / len(values) if values else 0.0

    def _clear_adaptive_legibility(self) -> None:
        self._glass_text_mode = ""
        for widget in (
            self._title,
            self._media_title,
            self._label,
            self._progress_time,
            self._close_button,
        ):
            if widget is not None:
                widget.setStyleSheet("")
        if isinstance(self._card, OverlayCard):
            self._card.set_text_scrim(None)

    def _apply_adaptive_legibility(self, background: QPixmap) -> None:
        if self._current is None or self._current.get(
            "_resolved_layout", self._current.get("layout")
        ) == "media":
            return
        luminance = self._backdrop_luminance(background)
        if self._glass_text_mode == "dark":
            mode = "light" if luminance < 0.34 else "dark"
        elif self._glass_text_mode == "light":
            mode = "dark" if luminance > 0.58 else "light"
        else:
            mode = "dark" if luminance >= 0.5 else "light"
        if mode == self._glass_text_mode:
            return
        self._glass_text_mode = mode
        if mode == "dark":
            title_color = "#11191c"
            message_color = "#314046"
            scrim = QColor(255, 255, 255, 118)
        else:
            title_color = "#f7fbfa"
            message_color = "#d1dcdf"
            scrim = QColor(0, 0, 0, 104)
        if self._title is not None:
            self._title.setStyleSheet(f"color: {title_color};")
        if self._label is not None:
            self._label.setStyleSheet(f"color: {message_color};")
        if self._progress_time is not None:
            self._progress_time.setStyleSheet(f"color: {message_color};")
        if self._close_button is not None:
            self._close_button.setStyleSheet(f"color: {message_color};")
        if self._current is not None:
            self._set_icon(self._current.get("icon", ""), title_color)
        if isinstance(self._card, OverlayCard):
            self._card.set_text_scrim(scrim)

    def _fallback_liquid_to_blur(self) -> None:
        self._liquid_compatible = False
        if self._current is None or not isinstance(self._card, OverlayCard):
            return
        self._current["_effective_background_effect"] = "blur"
        self._glass_capture_failures = 0
        self._glass_slow_frames = 0
        native = False
        application = QGuiApplication.instance()
        if (
            self._window is not None
            and sys.platform == "win32"
            and application is not None
            and application.platformName() != "offscreen"
            and not self._is_remote_session()
        ):
            native = self._native_backdrop.apply_acrylic(
                int(self._window.winId()), self._current.get("opacity", 0.94)
            )
        if native:
            self._current["_backdrop_backend"] = self._native_backdrop.backend
            self._card.set_glass_background(None)
            if self._glass_timer is not None:
                self._glass_timer.stop()
        elif self._card._glass_background is not None:
            self._card.set_glass_background(
                self._card._glass_background,
                self._current.get("opacity", 0.94),
                "blur",
            )
        if not native and self._glass_timer is not None and self._window is not None:
            self._glass_timer.start(320)

    def _refresh_glass_background(self) -> None:
        request = self._current
        effect = str(request.get("_effective_background_effect", "")) if request else ""
        if (
            request is None
            or effect not in {"blur", "liquid"}
            or request.get("_resolved_layout", request.get("layout")) == "media"
            or request.get("opacity", 0.0) <= 0
            or self._window is None
            or not self._window.isVisible()
        ):
            if self._glass_timer is not None:
                self._glass_timer.stop()
            return
        started = time.perf_counter()
        captured = self._capture_glass_background(request["opacity"], effect)
        elapsed = time.perf_counter() - started
        if not captured:
            self._glass_capture_failures += 1
        else:
            self._glass_capture_failures = 0
        if elapsed > 0.12:
            self._glass_slow_frames += 1
        else:
            self._glass_slow_frames = max(0, self._glass_slow_frames - 1)
        if self._glass_capture_failures >= 2 and effect == "liquid":
            self._fallback_liquid_to_blur()
        elif self._glass_capture_failures >= 2:
            if self._glass_timer is not None:
                self._glass_timer.stop()
        elif self._glass_slow_frames >= 3 and effect == "liquid":
            self._fallback_liquid_to_blur()
        elif self._glass_slow_frames >= 3 and self._glass_timer is not None:
            self._glass_timer.setInterval(500)
            self._glass_slow_frames = 0
        elif captured and self._glass_timer is not None:
            if self._last_capture_changed:
                self._glass_idle_frames = 0
            else:
                self._glass_idle_frames = min(8, self._glass_idle_frames + 1)
            base = 100 if self._capture_backend == "dxgi" else 220
            if on_battery_power():
                base = max(base, 250)
            idle_delay = min(900, self._glass_idle_frames * 110)
            work_delay = max(0, round(elapsed * 1000) - 35)
            self._glass_interval_ms = max(80, min(1000, base + idle_delay + work_delay))
            self._glass_timer.setInterval(self._glass_interval_ms)

    def _configure_dynamic_glass(self, request: dict[str, Any]) -> None:
        if self._glass_timer is None:
            return
        self._glass_timer.stop()
        effect = request.get("_effective_background_effect")
        if (
            effect in {"blur", "liquid"}
            and request.get("_resolved_layout", request.get("layout")) != "media"
            and request.get("opacity", 0.0) > 0
            and request.get("_backdrop_backend") not in {
                "dwm_acrylic",
                "legacy_acrylic",
            }
        ):
            self._glass_capture_failures = 0
            self._glass_slow_frames = 0
            self._glass_idle_frames = 0
            self._last_capture_signature = b""
            interval = 100 if effect == "liquid" and self._desktop_capture.available else 300
            if on_battery_power():
                interval = max(interval, 250)
            self._glass_interval_ms = interval
            self._glass_timer.start(interval)

    def _set_icon(self, value: str, color: str) -> None:
        if self._icon is None:
            return
        self._icon.clear()
        if not value:
            self._icon.setVisible(False)
            return
        if value.casefold().startswith("mdi:"):
            name = value.split(":", 1)[1].strip().casefold()
            try:
                pixmap = qta.icon(f"mdi6.{name}", color=color).pixmap(QSize(21, 21))
            except Exception:
                self._icon.setVisible(False)
                return
            self._icon.setPixmap(pixmap)
        else:
            self._icon.setText(value[:8])
        self._icon.setVisible(True)

    def _position(self, monitor: int, corner: str, edge_offset: int = 0) -> None:
        if self._window is None:
            return
        screens = QGuiApplication.screens()
        if not screens:
            return
        screen = screens[max(0, min(len(screens) - 1, monitor))]
        area = screen.availableGeometry()
        offset = max(0, min(240, int(edge_offset)))
        x, y = self._position_for_geometry(
            area,
            self._window.width(),
            self._window.height(),
            corner,
            offset,
        )
        layout = self._window.layout()
        if layout is not None:
            layout.activate()
        if self._card is not None:
            card_geometry = self._card.geometry()
            if corner in {"top_left", "bottom_left"}:
                x = area.left() + offset - card_geometry.left()
            elif corner in {"top_right", "bottom_right"}:
                x = area.right() - offset - card_geometry.right()
            else:
                x = (
                    area.left()
                    + (area.width() - card_geometry.width()) // 2
                    - card_geometry.left()
                )
            if corner in {"bottom_left", "bottom_right"}:
                y = area.bottom() - offset - card_geometry.bottom()
            else:
                y = area.top() + offset - card_geometry.top()
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

        card = OverlayCard()
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
        media_title = QLabel()
        media_title.setObjectName("overlayMediaTitle")
        media_title.setWordWrap(True)
        media_title.setTextFormat(Qt.TextFormat.PlainText)
        media_title.setVisible(False)
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
        lifetime_progress = QProgressBar()
        lifetime_progress.setObjectName("overlayLifetime")
        lifetime_progress.setRange(0, 1000)
        lifetime_progress.setValue(1000)
        lifetime_progress.setTextVisible(False)
        lifetime_progress.setFixedHeight(3)
        lifetime_progress.setVisible(False)
        text.addLayout(top)
        text.addWidget(media_title)
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
        for clickable in (
            card,
            cover,
            icon,
            title,
            media_title,
            label,
            image,
            progress,
            lifetime_progress,
            progress_time,
        ):
            clickable.installEventFilter(self)
        progress_row.addWidget(progress, 1)
        progress_row.addWidget(progress_time)
        content.addLayout(progress_row)
        content.addWidget(lifetime_progress)
        card_layout.addLayout(content, 1)
        outer.addWidget(card)
        timer = QTimer(window)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.hide(show_next=True))
        progress_timer = QTimer(window)
        progress_timer.timeout.connect(self._refresh_live_progress)
        glass_timer = QTimer(window)
        glass_timer.timeout.connect(self._refresh_glass_background)
        lifetime_timer = QTimer(window)
        lifetime_timer.setInterval(50)
        lifetime_timer.timeout.connect(self._refresh_lifetime_progress)
        self._window = window
        self._card = card
        self._icon = icon
        self._title = title
        self._media_title = media_title
        self._label = label
        self._cover = cover
        self._image = image
        self._progress = progress
        self._lifetime_progress = lifetime_progress
        self._progress_time = progress_time
        self._close_button = close_button
        self._timer = timer
        self._progress_timer = progress_timer
        self._glass_timer = glass_timer
        self._lifetime_timer = lifetime_timer

        if not self._screen_signals_connected:
            application = QGuiApplication.instance()
            if application is not None:
                application.screenAdded.connect(self._screen_configuration_changed)
                application.screenRemoved.connect(self._screen_configuration_changed)
                self._screen_signals_connected = True
            self._connect_screen_signals()

    def _connect_screen_signals(self) -> None:
        for screen in QGuiApplication.screens():
            screen_id = id(screen)
            if screen_id in self._screen_signal_ids:
                continue
            screen.geometryChanged.connect(self._screen_configuration_changed)
            screen.availableGeometryChanged.connect(self._screen_configuration_changed)
            screen.logicalDotsPerInchChanged.connect(self._screen_configuration_changed)
            self._screen_signal_ids.add(screen_id)

    def _start_dismiss_timer(self, request: dict[str, Any]) -> None:
        if self._timer is None or self._lifetime_timer is None or self._lifetime_progress is None:
            return
        self._timer.stop()
        self._lifetime_timer.stop()
        self._hover_paused = False
        self._dismiss_remaining_ms = request["duration"] * 1000
        self._dismiss_deadline = time.monotonic() + self._dismiss_remaining_ms / 1000
        show_lifetime = bool(request.get("show_lifetime", False)) and not request["pinned"]
        self._lifetime_progress.setVisible(show_lifetime)
        self._lifetime_progress.setValue(1000)
        if request["pinned"]:
            return
        self._timer.start(self._dismiss_remaining_ms)
        if show_lifetime:
            self._lifetime_timer.start()

    def _refresh_lifetime_progress(self) -> None:
        if self._lifetime_progress is None or self._current is None:
            return
        duration_ms = max(1, int(self._current["duration"]) * 1000)
        if self._hover_paused:
            remaining = self._dismiss_remaining_ms
        else:
            remaining = max(0, round((self._dismiss_deadline - time.monotonic()) * 1000))
        self._lifetime_progress.setValue(round(remaining / duration_ms * 1000))

    def _pause_dismiss_timer(self) -> None:
        if (
            self._hover_paused
            or self._current is None
            or self._current.get("pinned", False)
            or self._timer is None
        ):
            return
        self._dismiss_remaining_ms = max(
            1, round((self._dismiss_deadline - time.monotonic()) * 1000)
        )
        self._timer.stop()
        self._hover_paused = True
        self._refresh_lifetime_progress()

    def _resume_if_pointer_left(self) -> None:
        if self._card is not None and self._card.underMouse():
            return
        self._resume_dismiss_timer()

    def _resume_dismiss_timer(self) -> None:
        if not self._hover_paused or self._timer is None or self._current is None:
            return
        self._hover_paused = False
        self._dismiss_deadline = time.monotonic() + self._dismiss_remaining_ms / 1000
        self._timer.start(max(1, self._dismiss_remaining_ms))

    def _screen_configuration_changed(self, *_args: object) -> None:
        self._connect_screen_signals()
        if self._current is None or self._window is None or not self._window.isVisible():
            return
        self._position(
            self._current["monitor"],
            self._current["corner"],
            self._current["edge_offset"],
        )

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
        raw_channel = str(options.get("channel", "")).strip().lower()
        channel = raw_channel if raw_channel in _CHANNELS else "general"
        if action == "clear" and not raw_channel:
            channel = ""
        default_preset = {
            "security": "error",
            "system": "info",
            "media": "default",
            "work": "info",
        }.get(channel, "default")
        preset = str(options.get("preset", default_preset)).strip().lower()
        if preset not in _PRESET_COLORS:
            preset = "default"
        raw_priority = options.get("priority", "normal")
        if isinstance(raw_priority, int):
            priority = max(0, min(3, raw_priority))
            priority_name = next(
                (name for name, score in _PRIORITIES.items() if score == priority),
                "normal",
            )
        else:
            priority_name = str(raw_priority).strip().lower()
            if priority_name not in _PRIORITIES:
                priority_name = "normal"
            priority = _PRIORITIES[priority_name]
        corner = str(options.get("corner", "top_right")).strip().lower()
        if corner not in _CORNERS:
            corner = "top_right"
        size_mode = str(options.get("size_mode", "auto")).strip().lower()
        if size_mode not in {"auto", "manual"}:
            size_mode = "auto"
        legacy_size = str(options.get("size", "")).strip().lower()
        if "size_mode" not in options and legacy_size in {"small", "medium", "large"}:
            size_mode = "manual"
        try:
            legacy_width = {"small": 320, "medium": 400, "large": 520}.get(
                legacy_size, 400
            )
            width = max(240, min(1200, int(options.get("width", legacy_width))))
        except (TypeError, ValueError):
            width = 400
        try:
            height = max(90, min(900, int(options.get("height", 160))))
        except (TypeError, ValueError):
            height = 160
        layout = str(options.get("layout", "default")).strip().lower()
        if layout == "auto":
            layout = "default"
        if layout not in {"default", "compact", "standard", "media", "camera"}:
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
            opacity = max(0.0, min(1.0, float(options.get("opacity", 0.94))))
        except (TypeError, ValueError):
            opacity = 0.94
        raw_effect = options.get("background_effect")
        if raw_effect is None:
            background_effect = "blur" if bool(options.get("glass", False)) else "none"
        else:
            background_effect = str(raw_effect).strip().lower()
        if background_effect not in {"none", "blur", "liquid"}:
            background_effect = "none"
        try:
            monitor = max(0, min(15, int(options.get("monitor", self.default_monitor))))
        except (TypeError, ValueError):
            monitor = 0
        try:
            edge_offset = max(0, min(240, int(options.get("edge_offset", 0))))
        except (TypeError, ValueError):
            edge_offset = 0
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
            "icon": str(options.get("icon", "")).strip()[:128],
            "image": str(options.get("image", "")).strip(),
            "qr": str(options.get("qr", "")).strip()[:512],
            "progress": progress,
            "duration": duration,
            "pinned": bool(options.get("pinned", False)),
            "show_close_button": bool(options.get("show_close_button", False)),
            "close_on_click": bool(options.get("close_on_click", False)),
            "pause_on_hover": bool(options.get("pause_on_hover", False)),
            "show_lifetime": bool(options.get("show_lifetime", False)),
            "corner": corner,
            "size_mode": size_mode,
            "width": width,
            "height": height,
            "layout": layout,
            "camera": bool(options.get("camera", False)) or layout == "camera",
            "media_source": str(options.get("media_source", "")).strip()[:128],
            "opacity": opacity,
            "background_effect": background_effect,
            "glass": background_effect != "none",
            "preset": preset,
            "channel": channel,
            "priority": priority,
            "priority_name": priority_name,
            "monitor": monitor,
            "edge_offset": edge_offset,
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
