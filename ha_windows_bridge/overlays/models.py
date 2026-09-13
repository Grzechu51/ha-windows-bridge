from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .constants import _CORNERS, _ID_RE, _PRESET_COLORS, _PRIORITIES


class NotificationAction(StrEnum):
    SHOW = "show"
    UPDATE = "update"
    REMOVE = "remove"
    CLEAR = "clear"


class DeliveryDisposition(StrEnum):
    ACCEPTED = "accepted"
    DISPLAYED = "displayed"
    REJECTED = "rejected"
    CLOSED = "closed"
    DROPPED = "dropped"


class LifecycleReason(StrEnum):
    QUEUED = "queued"
    DISPLAYED = "displayed"
    QUEUE_FULL = "queue_full"
    PINNED_LIMIT = "pinned_limit"
    NOT_FOUND = "not_found"
    REPLACED = "replaced"
    UPDATED = "updated"
    EXPIRED = "expired"
    USER = "user"
    LOCKED = "locked"
    SUSPENDED = "suspended"
    FULLSCREEN = "fullscreen"
    DISPLAY_REMOVED = "display_removed"
    NO_SPACE = "no_space"
    RENDER_ERROR = "render_error"
    STOPPING = "stopping"


@dataclass(frozen=True)
class NotificationContent:
    title: str
    message: str
    icon: str = ""
    image: str = ""
    qr: str = ""
    progress: int | None = None


@dataclass(frozen=True)
class NotificationPresentation:
    layout: str
    display_mode: str
    corner: str
    monitor_id: str
    values: MappingProxyType


@dataclass(frozen=True)
class NotificationLifetime:
    duration: int
    pinned: bool
    pause_on_hover: bool


@dataclass(frozen=True)
class NotificationPolicy:
    source: str
    priority: int
    session: str = ""
    device_id: str = ""


@dataclass(frozen=True)
class NotificationCommand:
    action: NotificationAction
    notification_id: str
    content: NotificationContent | None
    presentation: NotificationPresentation | None
    lifetime: NotificationLifetime | None
    policy: NotificationPolicy | None
    provided: frozenset[str]
    patch: MappingProxyType
    command_id: str = ""

    @classmethod
    def parse(cls, payload: dict[str, Any], *, source: str = "remote",
              command_id: str = "", session: str = "", device_id: str = "",
              default_monitor: int = 0) -> NotificationCommand:
        if not isinstance(payload, dict):
            raise ValueError("Notification payload must be an object")
        raw_data = payload.get("data", {})
        if not isinstance(raw_data, dict):
            raise ValueError("Notification options must be an object")
        try:
            action = NotificationAction(raw_data.get("action", "show"))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid notification action") from exc
        raw_id = raw_data.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise ValueError("Invalid notification ID")
        if action in {NotificationAction.UPDATE, NotificationAction.REMOVE} and not raw_id:
            raise ValueError("Notification ID is required")
        provided = frozenset(raw_data) | frozenset(key for key in ("title", "message") if key in payload)
        if action in {NotificationAction.REMOVE, NotificationAction.CLEAR}:
            return cls(action, raw_id or "", None, None, None,
                       NotificationPolicy(source[:64] or "remote", 0, session, device_id), provided,
                       MappingProxyType(dict(raw_data)), command_id)
        if action is NotificationAction.UPDATE:
            patch = dict(raw_data)
            patch.pop("action", None)
            patch.pop("id", None)
            if "title" in payload:
                patch["title"] = payload["title"]
            if "message" in payload:
                patch["message"] = payload["message"]
            return cls(action, raw_id, None, None, None,
                       NotificationPolicy(source[:64] or "remote", 0, session, device_id), provided,
                       MappingProxyType(patch), command_id)
        normalized = validated_request(payload.get("title", ""), payload.get("message", ""), raw_data,
                                       default_monitor=default_monitor)
        owned = MappingProxyType(dict(normalized))
        return cls(
            action, normalized["id"],
            NotificationContent(normalized["title"], normalized["message"], normalized["icon"],
                                normalized["image"], normalized["qr"], normalized["progress"]),
            NotificationPresentation(normalized["layout"], normalized["display_mode"], normalized["corner"],
                                     str(raw_data.get("monitor_id", normalized["monitor"])), owned),
            NotificationLifetime(normalized["duration"], normalized["pinned"], normalized["pause_on_hover"]),
            NotificationPolicy(source[:64] or "remote", normalized["priority"], session, device_id),
            provided, MappingProxyType({}), command_id,
        )

    def options(self) -> dict[str, Any]:
        return dict(self.presentation.values) if self.presentation else {}


@dataclass(frozen=True)
class EngineResult:
    disposition: DeliveryDisposition
    notification_id: str = ""
    reason: LifecycleReason = LifecycleReason.QUEUED
    token: int = 0
    command_id: str = ""
    transport: str = ""
    session: str = ""
    device_id: str = ""

    @property
    def accepted(self) -> bool:
        return self.disposition is not DeliveryDisposition.REJECTED

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
        "monitor_id": str(options.get("monitor_id", "")).strip()[:128],
        "edge_offset": edge_offset,
        "media_position": media_position,
        "media_duration": media_duration,
        "media_playing": bool(options.get("media_playing", False)),
        "media_controls": bool(options.get("media_controls", False)),
        "media_live": bool(options.get("media_live", False)),
    }


def finite_number(value: Any, default: float) -> float:
    number = float(value)
    return number if math.isfinite(number) else default
