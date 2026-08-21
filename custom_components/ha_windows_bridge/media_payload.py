from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Any

MAX_STATE_PAYLOAD = 64 * 1024
MAX_ARTWORK_BYTES = 1024 * 1024
MAX_ARTWORK_PAYLOAD = ((MAX_ARTWORK_BYTES + 2) // 3) * 4 + 1024

_ALLOWED_STATES = frozenset({"playing", "paused", "idle", "off"})
_ALLOWED_CAPABILITIES = frozenset({"play", "pause", "stop", "next", "previous", "seek"})


def _raw_size(raw: str | bytes) -> int:
    return len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)


def _load_json_object(raw: str | bytes, limit: int) -> dict[str, Any] | None:
    if not isinstance(raw, (str, bytes)):
        return None
    if _raw_size(raw) > limit:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:limit]


def _finite_number(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return minimum
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return minimum
    if not math.isfinite(number):
        return minimum
    return max(minimum, min(maximum, number))


def parse_media_state(raw: str | bytes) -> dict[str, Any] | None:
    """Validate and normalize an untrusted MQTT media-state payload."""
    payload = _load_json_object(raw, MAX_STATE_PAYLOAD)
    if payload is None:
        return None

    state = payload.get("state")
    state = state if isinstance(state, str) and state in _ALLOWED_STATES else "idle"
    duration = _finite_number(payload.get("duration"), minimum=0.0, maximum=31_536_000.0)
    position = _finite_number(payload.get("position"), minimum=0.0, maximum=31_536_000.0)
    if duration:
        position = min(position, duration)

    volume = payload.get("volume")
    normalized_volume = (
        None if volume is None else _finite_number(volume, minimum=0.0, maximum=1.0)
    )
    muted = payload.get("muted")
    capabilities = payload.get("capabilities")
    normalized_capabilities: list[str] = []
    if isinstance(capabilities, list):
        normalized_capabilities = list(
            dict.fromkeys(
                value
                for value in capabilities[:32]
                if isinstance(value, str) and value in _ALLOWED_CAPABILITIES
            )
        )

    return {
        "supported": payload.get("supported") if isinstance(payload.get("supported"), bool) else True,
        "state": state,
        "title": _text(payload.get("title"), 1024),
        "artist": _text(payload.get("artist"), 1024),
        "album_title": _text(payload.get("album_title"), 1024),
        "album_artist": _text(payload.get("album_artist"), 1024),
        "source_app": _text(payload.get("source_app"), 512),
        "duration": duration,
        "position": position,
        "volume": normalized_volume,
        "muted": muted if isinstance(muted, bool) else None,
        "capabilities": normalized_capabilities,
    }


def _detected_content_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def parse_media_artwork(raw: str | bytes) -> tuple[bytes, str, str] | None:
    """Decode only small raster images with matching MIME type and file signature."""
    payload = _load_json_object(raw, MAX_ARTWORK_PAYLOAD)
    if payload is None:
        return None
    encoded = payload.get("data")
    declared_type = payload.get("content_type")
    if not isinstance(encoded, str) or not isinstance(declared_type, str):
        return None
    if len(encoded) > MAX_ARTWORK_PAYLOAD:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not data or len(data) > MAX_ARTWORK_BYTES:
        return None

    content_type = _detected_content_type(data)
    normalized_declared = declared_type.strip().lower()
    if normalized_declared == "image/jpg":
        normalized_declared = "image/jpeg"
    if not content_type or normalized_declared != content_type:
        return None
    return data, content_type, hashlib.sha256(data).hexdigest()
