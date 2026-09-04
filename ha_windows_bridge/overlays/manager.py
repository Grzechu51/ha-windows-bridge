from __future__ import annotations

import base64
import binascii
import ctypes
import io
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import qtawesome as qta
from PIL import Image, ImageDraw, ImageFilter, ImageGrab
from PySide6.QtCore import (
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
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import active_language, translate
from ..system_monitor import WindowsSystemMonitor
from ..ui.motion import MotionSystem
from ..windows_effects import DesktopDuplicationCapture, NativeBackdrop, on_battery_power
from .card import OverlayCard
from .constants import (
    _MAX_PARALLEL_CARDS,
    _PARALLEL_GAP,
    _PRESET_COLORS,
    _WINDOW_EXTRA_HEIGHT,
    _WINDOW_EXTRA_WIDTH,
)
from .models import validated_request
from .positioning import position_at_edge
from .queue import NotificationQueue


class OverlayManager(QObject):
    """Passive queued overlay; it never injects into or hooks another process."""

    def __init__(
        self,
        duration_seconds: int = 8,
        allow_fullscreen: bool = False,
        *,
        default_monitor: int = 0,
        close_tooltip: str = "Close overlay",
        desktop_capture: DesktopDuplicationCapture | None = None,
        _parallel_child: bool = False,
        _on_hidden: Callable[[OverlayManager], None] | None = None,
        _on_geometry_changed: Callable[[], None] | None = None,
    ):
        super().__init__()
        self.duration_seconds = max(2, min(60, int(duration_seconds)))
        self.allow_fullscreen = bool(allow_fullscreen)
        self.default_monitor = max(0, min(15, int(default_monitor)))
        self.close_tooltip = close_tooltip
        self._parallel_child = bool(_parallel_child)
        self._on_hidden = _on_hidden
        self._on_geometry_changed = _on_geometry_changed
        self._parallel_cards: dict[str, OverlayManager] = {}
        self._parallel_offset_x = 0
        self._parallel_group_width = 0
        self._parallel_y_offset = 0
        self._animation_offset_x = 0
        self._animation_offset_y = 0
        self._monitor = WindowsSystemMonitor()
        self._queue = NotificationQueue()
        self._current: dict[str, Any] | None = None
        self._window: QFrame | None = None
        self._card: QFrame | None = None
        self._icon: QLabel | None = None
        self._title: QLabel | None = None
        self._media_title: QLabel | None = None
        self._label: QLabel | None = None
        self._image: QLabel | None = None
        self._progress: QProgressBar | None = None
        self._lifetime_progress: QProgressBar | None = None
        self._progress_time: QLabel | None = None
        self._close_button: QToolButton | None = None
        self._content_layout: QVBoxLayout | None = None
        self._body_layout: QGridLayout | None = None
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
        self._desktop_capture = desktop_capture or DesktopDuplicationCapture()
        self._owns_desktop_capture = desktop_capture is None
        self._capture_backend = "imagegrab"
        self._last_capture_signature = b""
        self._glass_idle_frames = 0
        self._glass_interval_ms = 240
        self._last_capture_changed = True
        self._gpu_capture_failures = 0
        self._dismiss_deadline = 0.0
        self._dismiss_remaining_ms = 0
        self._hover_paused = False
        self._screen_signals_connected = False
        self._tracked_screens: list[Any] = []
        self._screen_connections: list[Any] = []

    def set_motion_enabled(self, enabled: bool) -> None:
        self._animations_allowed = enabled
        if not enabled and self._animation is not None:
            self._animation.setCurrentTime(self._animation.duration())
        for child in tuple(self._parallel_cards.values()):
            child.set_motion_enabled(enabled)

    def handle_message(
        self, title: str, message: str, options: dict[str, Any] | None = None
    ) -> bool:
        raw_options = options if isinstance(options, dict) else {}
        action = str(raw_options.get("action", "show")).strip().lower()
        raw_message_id = str(raw_options.get("id", "")).strip()
        parallel = self._parallel_cards.get(raw_message_id)
        if not self._parallel_child and parallel is not None:
            if action == "update":
                updated = parallel.handle_message(title, message, raw_options)
                QTimer.singleShot(0, self._reflow_parallel_cards)
                return updated
            if action == "remove":
                parallel.hide(show_next=True)
                return True
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
            if not self._parallel_child:
                self._clear_parallel_cards()
            self._queue.clear()
            self._current = None
            self.hide(show_next=False)
            return True
        if action == "remove":
            self._queue.remove(message_id)
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
        if clean["display_mode"] == "parallel" and not self._parallel_child:
            return self._show_parallel_card(clean)
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

    def _show_parallel_card(self, request: dict[str, Any]) -> bool:
        message_id = request["id"]
        existing = self._parallel_cards.get(message_id)
        if existing is not None:
            updated = existing.handle_message(
                request["title"],
                request["message"],
                {**request, "action": "update"},
            )
            QTimer.singleShot(0, self._reflow_parallel_cards)
            return updated

        while len(self._parallel_cards) >= _MAX_PARALLEL_CARDS:
            oldest_id = next(iter(self._parallel_cards))
            oldest = self._parallel_cards.pop(oldest_id)
            oldest._on_hidden = None
            oldest.close()

        child = OverlayManager(
            duration_seconds=self.duration_seconds,
            allow_fullscreen=self.allow_fullscreen,
            default_monitor=self.default_monitor,
            close_tooltip=self.close_tooltip,
            desktop_capture=self._desktop_capture,
            _parallel_child=True,
            _on_hidden=self._parallel_card_hidden,
            _on_geometry_changed=self._reflow_parallel_cards,
        )
        child._animations_allowed = self._animations_allowed
        child._liquid_compatible = self._liquid_compatible
        child._current = request
        self._parallel_cards[message_id] = child
        if not child._display(request):
            child._on_hidden = None
            child.close()
            self._parallel_cards.pop(message_id, None)
            return False
        QTimer.singleShot(0, self._reflow_parallel_cards)
        return True

    def _parallel_card_hidden(self, child: OverlayManager) -> None:
        message_id = next(
            (
                item_id
                for item_id, candidate in self._parallel_cards.items()
                if candidate is child
            ),
            "",
        )
        if message_id:
            self._parallel_cards.pop(message_id, None)
        child._on_hidden = None
        child.close()
        QTimer.singleShot(0, self._reflow_parallel_cards)

    def _clear_parallel_cards(self) -> None:
        for message_id, child in tuple(self._parallel_cards.items()):
            self._parallel_cards.pop(message_id, None)
            child._on_hidden = None
            child.close()
        QTimer.singleShot(0, self._reflow_parallel_cards)

    def _reflow_parallel_cards(self) -> None:
        groups: dict[tuple[int, str, int], list[OverlayManager]] = {}
        for child in self._parallel_cards.values():
            if child._current is None or child._window is None:
                continue
            request = child._current
            key = (request["monitor"], request["corner"], request["edge_offset"])
            groups.setdefault(key, []).append(child)

        group_heights: dict[tuple[int, str, int], int] = {}
        screens = QGuiApplication.screens()
        for key, children in groups.items():
            monitor, _corner, edge_offset = key
            available_width = 1920
            if screens:
                screen = screens[max(0, min(len(screens) - 1, monitor))]
                available_width = max(280, screen.availableGeometry().width() - edge_offset * 2)

            rows: list[list[OverlayManager]] = []
            row: list[OverlayManager] = []
            row_width = 0
            for child in children:
                visible_width = child._card.width() if child._card is not None else 280
                candidate_width = visible_width if not row else row_width + _PARALLEL_GAP + visible_width
                if row and candidate_width > available_width:
                    rows.append(row)
                    row = []
                    row_width = 0
                row.append(child)
                row_width = visible_width if len(row) == 1 else row_width + _PARALLEL_GAP + visible_width
            if row:
                rows.append(row)

            vertical_offset = 0
            for current_row in rows:
                group_width = sum(
                    child._card.width() if child._card is not None else 280
                    for child in current_row
                ) + max(0, len(current_row) - 1) * _PARALLEL_GAP
                horizontal_offset = 0
                row_height = 0
                for child in current_row:
                    visible_width = child._card.width() if child._card is not None else 280
                    visible_height = child._card.height() if child._card is not None else 78
                    child._parallel_offset_x = horizontal_offset
                    child._parallel_group_width = group_width
                    child._parallel_y_offset = vertical_offset
                    request = child._current
                    child._position(
                        request["monitor"], request["corner"], request["edge_offset"]
                    )
                    horizontal_offset += visible_width + _PARALLEL_GAP
                    row_height = max(row_height, visible_height)
                vertical_offset += row_height + _PARALLEL_GAP
            group_heights[key] = max(0, vertical_offset - _PARALLEL_GAP)

        self._parallel_y_offset = 0
        if self._current is not None and self._window is not None:
            request = self._current
            key = (request["monitor"], request["corner"], request["edge_offset"])
            if key in groups:
                self._parallel_y_offset = group_heights[key] + _PARALLEL_GAP
            self._position(
                request["monitor"], request["corner"], request["edge_offset"]
            )

    @staticmethod
    def test_pattern_names() -> tuple[tuple[str, str], ...]:
        return (
            ("compact", "Krótka wiadomość"),
            ("parallel", "Panel statusu"),
            ("badges", "Pasek wskaźników"),
            ("long", "Długa treść"),
            ("media", "Media Player"),
            ("blur", "Standardowe rozmycie"),
            ("liquid", "Liquid Glass"),
            ("camera", "Kamera priorytetowa"),
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

    @staticmethod
    def _test_media_image() -> str:
        image = Image.new("RGB", (640, 640), "#172234")
        draw = ImageDraw.Draw(image)
        for y in range(image.height):
            ratio = y / max(1, image.height - 1)
            draw.line(
                (0, y, image.width, y),
                fill=(round(22 + 42 * ratio), round(34 + 36 * ratio), round(52 + 74 * ratio)),
            )
        draw.ellipse((120, 120, 520, 520), fill="#151b25", outline="#67d4a7", width=18)
        draw.ellipse((286, 286, 354, 354), fill="#67d4a7")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    def show_test_pattern(self, name: str) -> bool:
        language = active_language()
        if name == "badges":
            badges = (
                ("clock", time.strftime("%H:%M"), "", "", "default", None),
                ("person", "", "", "mdi:account", "info", None),
                ("light", "", "", "mdi:lightbulb-on", "warning", None),
                ("battery", "", "88%", "mdi:battery-80", "success", 88),
            )
            shown = True
            for item_id, title, value, icon, preset, progress in badges:
                shown = self.handle_message(
                    translate(title, language),
                    value,
                    {
                        "id": f"local-test-badge-{item_id}",
                        "duration": 8,
                        "display_mode": "parallel",
                        "layout": "badge",
                        "icon": icon,
                        "preset": preset,
                        "progress": progress,
                        "opacity": 0.82,
                        "pause_on_hover": True,
                    },
                ) and shown
            return shown
        if name == "parallel":
            cards = (
                ("battery", "Bateria", "78%", "mdi:battery-80", "success", 78),
                ("cpu", "Procesor", "24%", "mdi:cpu-64-bit", "info", 24),
                ("memory", "Pamięć RAM", "61%", "mdi:memory", "warning", 61),
            )
            shown = True
            for item_id, title, value, icon, preset, progress in cards:
                shown = self.handle_message(
                    translate(title, language),
                    value,
                    {
                        "id": f"local-test-status-{item_id}",
                        "duration": 8,
                        "display_mode": "parallel",
                        "layout": "status",
                        "icon": icon,
                        "preset": preset,
                        "progress": progress,
                        "pause_on_hover": True,
                    },
                ) and shown
            return shown
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
                "Przejrzyste tło dopasowane do pulpitu.",
                {"icon": "mdi:blur", "background_effect": "liquid"},
            ),
            "blur": (
                "Standardowe rozmycie",
                "Delikatne rozmycie pulpitu za wiadomością.",
                {"icon": "mdi:blur", "background_effect": "blur"},
            ),
            "camera": (
                "Kamera: podjazd",
                "Wykryto ruch w strefie wejściowej.",
                {
                    "icon": "mdi:cctv",
                    "layout": "camera",
                    "image": self._test_camera_image(),
                    "priority": "critical",
                },
            ),
            "media": (
                "Midnight Drive",
                "Neon Avenue · After Hours",
                {
                    "icon": "mdi:music",
                    "layout": "media",
                    "media_source": "Media Player",
                    "media_position": 94,
                    "media_duration": 238,
                    "media_playing": True,
                    "image": self._test_media_image(),
                },
            ),
        }
        title, message, options = patterns.get(name, patterns["compact"])
        return self.handle_message(
            translate(title, language),
            translate(message, language),
            {
                "id": f"local-test-{name}",
                "duration": 8,
                "show_lifetime": True,
                "pause_on_hover": True,
                **options,
            },
        )

    def _sort_queue(self) -> None:
        self._queue.sort()

    def hide(self, show_next: bool = True) -> None:
        for timer in (self._timer, self._progress_timer, self._glass_timer, self._lifetime_timer):
            if timer is not None:
                timer.stop()
        if self._window is None or self._card is None or not self._window.isVisible() or not self._animations_allowed:
            self._stop_animation()
            self._finish_hide(show_next)
            return
        self._stop_animation()
        start_position = QPoint(self._window.pos())
        start_opacity = self._window.windowOpacity()
        corner = self._current["corner"] if self._current else "top_right"
        direction, _ = self._animation_directions(corner)

        def frame(progress: float) -> None:
            if self._window is not None:
                self._window.move(start_position + QPoint(round(direction * 8 * progress), 0))
                self._window.setWindowOpacity(start_opacity * (1 - progress))

        self._animation = MotionSystem.animate(self._window, "popup_exit", frame, lambda: self._finish_hide(show_next))
        self._animation.start()

    def _finish_hide(self, show_next: bool) -> None:
        if self._card is not None:
            self._card.layout().setEnabled(True)
        if self._window is not None:
            self._window.hide()
            self._window.setWindowOpacity(1.0)
        self._animation_offset_x = 0
        self._animation_offset_y = 0
        self._native_backdrop.disable()
        self._animation = None
        if show_next:
            self._current = None
            self._show_next()
        if (
            self._parallel_child
            and self._current is None
            and not self._queue
            and self._on_hidden is not None
        ):
            callback = self._on_hidden
            self._on_hidden = None
            callback(self)

    def _stop_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
        if self._card is not None:
            self._card.layout().setEnabled(True)

    def _arrange_card_contents(self) -> None:
        """Lay out hidden/new cards at their final size before freezing a reveal."""
        if self._card is None:
            return
        layout = self._card.layout()
        layout.setEnabled(True)
        layout.invalidate()
        # Hidden widgets defer resize events. activate() alone can keep Qt's
        # initial 640x480 geometry, putting centered badges outside a 40px card.
        layout.setGeometry(self._card.contentsRect())
        layout.activate()

    def _show_with_animation(
        self, request: dict[str, Any], previous_size: QSize, was_visible: bool
    ) -> None:
        if self._window is None or self._card is None:
            return
        self._stop_animation()
        self._arrange_card_contents()
        if self._glass_timer is not None:
            self._glass_timer.stop()
        self._animation_offset_y = 0

        def finish() -> None:
            self._animation = None
            self._animation_offset_x = 0
            self._animation_offset_y = 0
            if self._window is None:
                return
            self._window.setWindowOpacity(1.0)
            self._position(request["monitor"], request["corner"], request["edge_offset"])
            self._configure_dynamic_glass(request)
            if self._on_geometry_changed is not None:
                self._on_geometry_changed()

        if not self._animations_allowed:
            self._window.show()
            self._window.raise_()
            finish()
            return
        direction, _ = self._animation_directions(request["corner"])
        start_opacity = self._window.windowOpacity() if was_visible else 0.0

        def frame(progress: float) -> None:
            if self._window is None:
                return
            self._animation_offset_x = 0 if was_visible else round(direction * 12 * (1 - progress))
            self._position(request["monitor"], request["corner"], request["edge_offset"])
            self._window.setWindowOpacity(start_opacity + (1 - start_opacity) * progress)

        # Keep the final card and text geometry throughout. Moving the native
        # window avoids re-wrapping text and re-allocating blur surfaces per frame.
        frame(0.0)
        self._window.show()
        self._window.raise_()
        self._animation = MotionSystem.animate(
            self._window, "reposition" if was_visible else "popup_enter", frame, finish
        )
        self._animation.start()

    @staticmethod
    def _animation_directions(corner: str) -> tuple[int, int]:
        """Return the outside-screen and vertical-centering animation directions."""
        horizontal = (
            1
            if corner in {"top_right", "bottom_right"}
            else -1
            if corner in {"top_left", "bottom_left"}
            else 0
        )
        vertical = 1 if corner.startswith("top") else -1
        return horizontal, vertical

    def close(self) -> None:
        for connection in self._screen_connections:
            with suppress(RuntimeError, TypeError):
                QObject.disconnect(connection)
        self._screen_connections.clear()
        self._tracked_screens.clear()
        self._screen_signals_connected = False
        for child in tuple(self._parallel_cards.values()):
            child._on_hidden = None
            child.close()
        self._parallel_cards.clear()
        self._on_geometry_changed = None
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
        if self._owns_desktop_capture:
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
        self._image = None
        self._progress = None
        self._lifetime_progress = None
        self._progress_time = None
        self._close_button = None
        self._content_layout = None
        self._body_layout = None
        self._timer = None
        self._progress_timer = None
        self._glass_timer = None
        self._lifetime_timer = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            card_content = self._card is not None and (
                watched is self._card
                or (isinstance(watched, QWidget) and self._card.isAncestorOf(watched))
            )
        except RuntimeError:
            card_content = False
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
        self._stop_animation()
        self._clear_adaptive_legibility()
        pixmap = self._decode_qr(request.get("qr", "")) or self._decode_image(
            request.get("image", "")
        )
        resolved_layout = self._resolve_layout(request, pixmap is not None)
        request["_resolved_layout"] = resolved_layout
        media_layout = resolved_layout == "media"
        camera_layout = resolved_layout == "camera"
        compact_layout = resolved_layout == "compact"
        status_layout = resolved_layout == "status"
        badge_layout = resolved_layout == "badge"
        if badge_layout:
            content_margins = (8, 5, 8, 5)
            content_spacing = 0
            body_spacing = 5
            text_spacing = 0
        elif status_layout:
            content_margins = (10, 7, 10, 7)
            content_spacing = 3
            body_spacing = 7
            text_spacing = 1
        elif compact_layout:
            content_margins = (14, 10, 14, 9)
            content_spacing = 5
            body_spacing = 10
            text_spacing = 3
        else:
            content_margins = (15, 14, 16, 14)
            content_spacing = 10
            body_spacing = 14
            text_spacing = 8
        if self._content_layout is not None:
            self._content_layout.setContentsMargins(*content_margins)
            self._content_layout.setSpacing(content_spacing)
        if self._body_layout is not None:
            self._body_layout.setHorizontalSpacing(body_spacing)
            self._body_layout.setVerticalSpacing(text_spacing)
        badge_alignment = (
            Qt.AlignmentFlag.AlignCenter if badge_layout else Qt.AlignmentFlag(0)
        )
        if self._content_layout is not None:
            self._content_layout.setAlignment(badge_alignment)
        if self._body_layout is not None:
            self._body_layout.setAlignment(badge_alignment)
            self._body_layout.setColumnStretch(1, 0 if badge_layout else 1)
            self._body_layout.setRowStretch(3, 0 if badge_layout else 1)
        self._title.setAlignment(
            Qt.AlignmentFlag.AlignCenter
            if badge_layout
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        badge_value = (
            request["message"]
            or (
                f"{request['progress']}%"
                if badge_layout and request["progress"] is not None
                else ""
            )
            or request["title"]
        )
        self._title.setText(
            request["media_source"] or "Media Player"
            if media_layout
            else badge_value
            if badge_layout
            else request["title"]
        )
        self._title.setVisible(not badge_layout or bool(badge_value))
        self._media_title.setText(request["title"])
        self._media_title.setVisible(media_layout)
        self._label.setText(request["message"])
        self._label.setVisible(bool(request["message"]) and not badge_layout)
        self._label.setContentsMargins(0, 0, 0, 0)
        request["_badge_pixmap"] = pixmap if badge_layout else None
        card_width = (
            request["width"]
            if request["size_mode"] == "manual"
            else self._automatic_width(request, pixmap is not None)
        )
        media_artwork = pixmap is not None and media_layout
        if pixmap is not None:
            if media_layout or badge_layout:
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
        else:
            self._image.clear()
            self._image.setVisible(False)
        self._progress_started_at = 0.0
        progress = self._current_progress(request)
        self._progress.setVisible(progress is not None and not badge_layout)
        if progress is not None and not badge_layout:
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
        if isinstance(self._card, OverlayCard):
            self._card.set_glass_accent(accent_color)
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
        if badge_layout and background_effect == "none":
            surface_alpha = 210
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
        if badge_layout:
            message_color = "#f5f8f7"
            if not badge_value:
                card_surface = "background: transparent; "
        elif status_layout:
            message_color = "#f5f8f7"
            border_alpha = min(border_alpha, 100)
        if isinstance(self._card, OverlayCard):
            self._card.set_media_background(
                pixmap if media_artwork else None,
                media_surface,
                request["opacity"],
            )
        self._icon.setFixedSize(25, 25) if media_layout else self._icon.setFixedSize(
            26 if badge_layout or status_layout else 34 if compact_layout else 36,
            26 if badge_layout or status_layout else 34 if compact_layout else 36,
        )
        if self._body_layout is not None:
            self._body_layout.removeWidget(self._icon)
            self._body_layout.addWidget(
                self._icon,
                0,
                0,
                1 if badge_layout else 3,
                1,
                Qt.AlignmentFlag.AlignHCenter
                | (
                    Qt.AlignmentFlag.AlignVCenter
                    if badge_layout or status_layout or compact_layout
                    else Qt.AlignmentFlag.AlignTop
                ),
            )
        if badge_layout and pixmap is not None:
            self._set_badge_image(pixmap)
        else:
            self._set_icon(request["icon"], accent)
        title_size = 14 if badge_layout else 10 if status_layout else 12 if media_layout else 15
        title_weight = 600 if media_layout or status_layout or badge_layout else 700
        icon_surface = (
            "transparent" if media_layout or (badge_layout and not badge_value) else icon_background
        )
        icon_border = (
            "transparent"
            if media_layout or badge_layout
            else f"rgba({accent_color.red()}, {accent_color.green()}, "
            f"{accent_color.blue()}, 145)"
            if status_layout
            else accent
        )
        icon_radius = 0 if media_layout else 13 if badge_layout or status_layout else 18
        track_color = (
            "rgba(0, 0, 0, 58)"
            if media_layout and media_surface.lightness() >= 145
            else "rgba(255, 255, 255, 54)"
            if media_layout
            else "#273034"
        )
        card_border_alpha = (
            0
            if badge_layout or (background_effect == "liquid" and not media_layout)
            else border_alpha
        )
        card_radius = (
            8
            if native_blur
            else 20
            if badge_layout and not badge_value
            else 11
            if badge_layout
            else 14
            if status_layout
            else 17
        )
        self._window.setStyleSheet(
            "QFrame#windowsOverlay { background: transparent; border: none; } "
            f"QFrame#overlayCard {{ {card_surface}"
            f"border: 1px solid rgba({border_color.red()}, {border_color.green()}, "
            f"{border_color.blue()}, {card_border_alpha}); border-radius: {card_radius}px; }} "
            'QLabel { background: transparent; font-family: "Segoe UI"; } '
            f"QLabel#overlayTitle {{ color: {title_color}; font-size: {title_size}px; "
            f"font-weight: {title_weight}; }} "
            f"QLabel#overlayMediaTitle {{ color: {media_title_color}; font-size: 15px; "
            "font-weight: 700; } "
            f"QLabel#overlayMessage {{ color: {message_color}; font-size: "
            f"{17 if status_layout else 12 if media_layout else 13}px; "
            f"font-weight: {700 if status_layout else 400}; }} "
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
            "border: none; border-radius: 2px; } "
            f"QProgressBar#overlayLifetime::chunk {{ background: {accent}; "
            "border-radius: 2px; } "
            f"QLabel#overlayProgressTime {{ color: {message_color}; font-size: 11px; }}"
        )
        self._window.setWindowOpacity(1.0)
        self._progress.setFixedHeight(3 if status_layout or badge_layout else 6)
        # Include the lifetime track in the height calculation before the reveal.
        self._lifetime_progress.setVisible(
            request["show_lifetime"] and not request["pinned"] and not badge_layout
        )
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
        self._window.setFixedWidth(card_width + _WINDOW_EXTRA_WIDTH)
        self._window.ensurePolished()
        if request["size_mode"] == "manual":
            self._card.setFixedHeight(request["height"])
            self._window.setFixedHeight(request["height"] + _WINDOW_EXTRA_HEIGHT)
        else:
            self._fit_automatic_height(
                card_width,
                minimum_height=(
                    180
                    if media_layout
                    else 280
                    if camera_layout
                    else 40
                    if badge_layout
                    else 60
                    if status_layout
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
            elif badge_layout:
                self._image.clear()
                self._image.setVisible(False)
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
        if not self._parallel_child and self._parallel_cards:
            QTimer.singleShot(0, self._reflow_parallel_cards)
        return True

    @staticmethod
    def _resolve_layout(request: dict[str, Any], has_image: bool) -> str:
        layout = str(request.get("layout", "default"))
        if layout in {"compact", "status", "badge", "standard", "media", "camera"}:
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
    def _text_width(text: str, pixels: int, weight: QFont.Weight) -> int:
        font = QFont("Segoe UI")
        font.setPixelSize(pixels)
        font.setWeight(weight)
        metrics = QFontMetrics(font)
        return max(
            (metrics.horizontalAdvance(line) for line in text.splitlines()),
            default=0,
        )

    @classmethod
    def _automatic_width(cls, request: dict[str, Any], has_image: bool) -> int:
        text_width = max(
            170,
            min(
                430,
                max(
                    cls._text_width(request["title"], 15, QFont.Weight.Bold),
                    cls._text_width(request["message"], 13, QFont.Weight.Normal),
                    cls._text_width(
                        request.get("media_source", ""), 12, QFont.Weight.DemiBold
                    ),
                ),
            ),
        )
        chrome = 54
        if request["icon"]:
            chrome += 44
        if request["show_close_button"]:
            chrome += 30
        width = text_width + chrome
        layout = request.get("_resolved_layout", request.get("layout"))
        if layout == "badge":
            value = (
                request.get("message", "")
                or (f"{request['progress']}%" if request.get("progress") is not None else "")
                or request.get("title", "")
            )
            width = cls._text_width(value, 14, QFont.Weight.DemiBold) + 20
            if request.get("icon") or request.get("_badge_pixmap") is not None:
                width += 32
            if request.get("show_close_button"):
                width += 26
            has_visual = bool(request.get("icon") or request.get("_badge_pixmap") is not None)
            minimum = 42 if not value else 86 if has_visual else 64
            return max(minimum, min(180, width))
        if layout == "status":
            title_width = cls._text_width(
                request.get("title", ""), 10, QFont.Weight.DemiBold
            )
            value_width = cls._text_width(
                request.get("message", ""), 17, QFont.Weight.Bold
            )
            width = max(54, title_width, value_width) + 24
            if request.get("icon"):
                width += 32
            if request.get("show_close_button"):
                width += 26
            return max(150, min(220, width))
        if layout == "media":
            width = max(width, 480)
        elif layout == "camera":
            width = max(width, 520)
        elif layout == "compact":
            width = min(width, 430)
        elif has_image:
            width = max(width, 440)
        if request.get("display_mode") == "parallel" and request.get("size_mode") == "auto":
            width = min(width, 300)
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
        # Include the frame's border; heightForWidth alone clips the last pixels.
        card_height = layout.totalHeightForWidth(card_width)
        if card_height < 0:
            card_height = self._card.sizeHint().height()
        card_height = max(minimum_height, min(900, card_height))
        self._card.setFixedHeight(card_height)
        self._window.setFixedHeight(card_height + _WINDOW_EXTRA_HEIGHT)

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
        return MotionSystem.enabled()

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
        original_size = image.size()
        longest_edge = max(image.width(), image.height())
        scale = min(1.0, 320 / max(1, longest_edge))
        if scale < 1.0:
            image = image.scaled(
                max(1, round(image.width() * scale)),
                max(1, round(image.height() * scale)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
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
        blurred = pil_image.filter(
            ImageFilter.GaussianBlur(max(1.0, float(radius) * scale))
        )
        result = OverlayManager._pixmap_from_pil(blurred)
        if result.size() != original_size:
            result = result.scaled(
                original_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return result

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
            badge_pixmap = self._current.get("_badge_pixmap")
            if isinstance(badge_pixmap, QPixmap) and not badge_pixmap.isNull():
                self._set_badge_image(badge_pixmap)
            else:
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
            base = 180 if self._capture_backend == "dxgi" else 300
            if on_battery_power():
                base = max(base, 400)
            idle_delay = min(1_500, self._glass_idle_frames * 180)
            work_delay = max(0, round(elapsed * 1000) - 35)
            self._glass_interval_ms = max(
                160, min(2_000, base + idle_delay + work_delay)
            )
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
            interval = (
                180
                if effect == "liquid" and self._desktop_capture.available
                else 300
            )
            if on_battery_power():
                interval = max(interval, 400)
            self._glass_interval_ms = interval
            self._glass_timer.start(interval)

    def _set_badge_image(self, source: QPixmap) -> None:
        if self._icon is None or source.isNull():
            return
        side = min(source.width(), source.height())
        source_rect = QRectF(
            (source.width() - side) / 2,
            (source.height() - side) / 2,
            side,
            side,
        )
        thumbnail = QPixmap(22, 22)
        thumbnail.fill(Qt.GlobalColor.transparent)
        painter = QPainter(thumbnail)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, 22, 22), 6, 6)
        painter.setClipPath(clip)
        painter.drawPixmap(QRectF(0, 0, 22, 22), source, source_rect)
        painter.end()
        self._icon.clear()
        self._icon.setPixmap(thumbnail)
        self._icon.setVisible(True)

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
        if corner in {"top_right", "bottom_right"}:
            x -= self._parallel_offset_x
        elif corner in {"top_left", "bottom_left"}:
            x += self._parallel_offset_x
        elif corner == "top_center" and self._parallel_group_width > 0:
            x = (
                area.left()
                + (area.width() - self._parallel_group_width) // 2
                + self._parallel_offset_x
                - (card_geometry.left() if self._card is not None else 0)
            )
        if corner in {"bottom_left", "bottom_right"}:
            y -= self._parallel_y_offset
        else:
            y += self._parallel_y_offset
        x += self._animation_offset_x
        y += self._animation_offset_y
        self._window.move(x, y)

    @staticmethod
    def _position_for_geometry(
        area: QRect,
        width: int,
        height: int,
        corner: str,
        margin: int = 0,
    ) -> tuple[int, int]:
        """Position the frameless window against the selected screen edge."""
        return position_at_edge((area.x(), area.y(), area.width(), area.height()), width, height, corner, margin)

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
        self._native_backdrop.prepare_window(int(window.winId()))
        outer = QHBoxLayout(window)
        outer.setContentsMargins(0, 0, 0, 0)

        card = OverlayCard()
        card.setObjectName("overlayCard")
        card.installEventFilter(self)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        content = QVBoxLayout()
        content.setContentsMargins(15, 14, 16, 14)
        content.setSpacing(10)
        body = QGridLayout()
        body.setHorizontalSpacing(14)
        body.setVerticalSpacing(5)
        body.setColumnStretch(1, 1)
        body.setRowStretch(3, 1)
        icon = QLabel()
        icon.setObjectName("overlayIcon")
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel()
        title.setObjectName("overlayTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        close_button = QToolButton()
        close_button.setObjectName("overlayClose")
        close_button.setText("×")
        close_button.setToolTip(self.close_tooltip)
        close_button.setFixedSize(26, 26)
        close_button.setVisible(False)
        close_button.clicked.connect(lambda: self.hide(show_next=True))
        media_title = QLabel()
        media_title.setObjectName("overlayMediaTitle")
        media_title.setWordWrap(True)
        media_title.setTextFormat(Qt.TextFormat.PlainText)
        media_title.setVisible(False)
        label = QLabel()
        label.setObjectName("overlayMessage")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        body.addWidget(
            icon,
            0,
            0,
            3,
            1,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
        )
        body.addWidget(title, 0, 1, Qt.AlignmentFlag.AlignVCenter)
        body.addWidget(close_button, 0, 2, Qt.AlignmentFlag.AlignTop)
        body.addWidget(media_title, 1, 1, 1, 2)
        body.addWidget(label, 2, 1, 1, 2)
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
        lifetime_progress.setFixedHeight(4)
        lifetime_progress.setVisible(False)
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
        lifetime_timer.setInterval(100)
        lifetime_timer.timeout.connect(self._refresh_lifetime_progress)
        self._window = window
        self._card = card
        self._icon = icon
        self._title = title
        self._media_title = media_title
        self._label = label
        self._image = image
        self._progress = progress
        self._lifetime_progress = lifetime_progress
        self._progress_time = progress_time
        self._close_button = close_button
        self._content_layout = content
        self._body_layout = body
        self._timer = timer
        self._progress_timer = progress_timer
        self._glass_timer = glass_timer
        self._lifetime_timer = lifetime_timer

        if not self._screen_signals_connected:
            application = QGuiApplication.instance()
            if application is not None:
                self._screen_connections.extend((
                    application.screenAdded.connect(self._screen_configuration_changed),
                    application.screenRemoved.connect(self._screen_configuration_changed),
                ))
                self._screen_signals_connected = True
            self._connect_screen_signals()

    def _connect_screen_signals(self) -> None:
        for screen in QGuiApplication.screens():
            if screen in self._tracked_screens:
                continue
            self._screen_connections.extend((
                screen.geometryChanged.connect(self._screen_configuration_changed),
                screen.availableGeometryChanged.connect(self._screen_configuration_changed),
                screen.logicalDotsPerInchChanged.connect(self._screen_configuration_changed),
            ))
            # Keep wrappers alive: transient Python ids do not identify native screens.
            self._tracked_screens.append(screen)

    def _start_dismiss_timer(self, request: dict[str, Any]) -> None:
        if self._timer is None or self._lifetime_timer is None or self._lifetime_progress is None:
            return
        self._timer.stop()
        self._lifetime_timer.stop()
        self._hover_paused = False
        self._dismiss_remaining_ms = request["duration"] * 1000
        self._dismiss_deadline = time.monotonic() + self._dismiss_remaining_ms / 1000
        show_lifetime = (
            bool(request.get("show_lifetime", False))
            and not request["pinned"]
            and request.get("_resolved_layout", request.get("layout")) != "badge"
        )
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
        if not self._parallel_child:
            self._desktop_capture.invalidate()
            self._reflow_parallel_cards()
        if self._current is None or self._window is None or not self._window.isVisible():
            return
        self._position(
            self._current["monitor"],
            self._current["corner"],
            self._current["edge_offset"],
        )

    def _validated_request(self, title: str, message: str, options: dict[str, Any]) -> dict[str, Any]:
        return validated_request(title, message, options, duration_seconds=self.duration_seconds, default_monitor=self.default_monitor)

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
