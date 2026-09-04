from __future__ import annotations

import math
import uuid
from typing import Any

from .constants import _CORNERS, _ID_RE, _PRESET_COLORS, _PRIORITIES


def validated_request(
    title: str, message: str, options: dict[str, Any], *, duration_seconds: int = 8, default_monitor: int = 0
) -> dict[str, Any]:
    options = options if isinstance(options, dict) else {}
    action = str(options.get("action", "show")).strip().lower()
    if action not in {"show", "update", "remove", "clear"}:
        action = "show"
    message_id = str(options.get("id", "default" if action != "show" else "")).strip()
    if message_id and not _ID_RE.fullmatch(message_id):
        message_id = ""
    if not message_id:
        message_id = f"message-{uuid.uuid4().hex}"
    preset = str(options.get("preset", "default")).strip().lower()
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
    try:
        width = max(240, min(1200, int(options.get("width", 400))))
    except (TypeError, ValueError, OverflowError):
        width = 400
    try:
        height = max(90, min(900, int(options.get("height", 160))))
    except (TypeError, ValueError, OverflowError):
        height = 160
    layout = str(options.get("layout", "default")).strip().lower()
    if layout == "auto":
        layout = "default"
    if layout not in {
        "default",
        "compact",
        "status",
        "badge",
        "standard",
        "media",
        "camera",
    }:
        layout = "default"
    display_mode = str(options.get("display_mode", "queue")).strip().lower()
    if display_mode not in {"queue", "parallel"}:
        display_mode = "queue"
    progress = options.get("progress")
    try:
        progress = max(0, min(100, round(float(progress)))) if progress is not None else None
    except (TypeError, ValueError, OverflowError):
        progress = None
    try:
        duration = max(2, min(60, int(options.get("duration", duration_seconds))))
    except (TypeError, ValueError, OverflowError):
        duration = duration_seconds
    try:
        opacity = max(0.0, min(1.0, finite_number(options.get("opacity", 0.94), 0.94)))
    except (TypeError, ValueError, OverflowError):
        opacity = 0.94
    raw_effect = options.get("background_effect")
    background_effect = (
        "none" if raw_effect is None else str(raw_effect).strip().lower()
    )
    if background_effect not in {"none", "blur", "liquid"}:
        background_effect = "none"
    try:
        monitor = max(0, min(15, int(options.get("monitor", default_monitor))))
    except (TypeError, ValueError, OverflowError):
        monitor = 0
    try:
        edge_offset = max(0, min(240, int(options.get("edge_offset", 0))))
    except (TypeError, ValueError, OverflowError):
        edge_offset = 0
    try:
        media_position = max(0.0, finite_number(options.get("media_position", 0.0), 0.0))
    except (TypeError, ValueError, OverflowError):
        media_position = 0.0
    try:
        media_duration = max(0.0, finite_number(options.get("media_duration", 0.0), 0.0))
    except (TypeError, ValueError, OverflowError):
        media_duration = 0.0
    if media_duration:
        media_position = min(media_position, media_duration)
        progress = round(media_position / media_duration * 100)
    return {
        "action": action,
        "id": message_id,
        "title": str(title).strip()[:128] or ("" if layout == "badge" else "Home Assistant"),
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
        "display_mode": display_mode,
        "camera": bool(options.get("camera", False)) or layout == "camera",
        "media_source": str(options.get("media_source", "")).strip()[:128],
        "opacity": opacity,
        "background_effect": background_effect,
        "glass": background_effect != "none",
        "preset": preset,
        "priority": priority,
        "priority_name": priority_name,
        "monitor": monitor,
        "edge_offset": edge_offset,
        "media_position": media_position,
        "media_duration": media_duration,
        "media_playing": bool(options.get("media_playing", False)),
        "media_controls": bool(options.get("media_controls", False)),
    }


def finite_number(value: Any, default: float) -> float:
    number = float(value)
    return number if math.isfinite(number) else default
