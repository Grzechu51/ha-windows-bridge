from __future__ import annotations

import base64
from typing import Any

from .audio import AudioSessionSnapshot
from .config import AppConfig
from .media import MediaSnapshot


def media_announcement_topic(config: AppConfig) -> str:
    return f"ha-windows-bridge/devices/{config.device_id}"


def media_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/media_player"
    return f"{root}/command", f"{root}/state"


def media_thumbnail_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/media_player/thumbnail"


def media_state_payload(
    snapshot: MediaSnapshot,
    master: AudioSessionSnapshot | None,
) -> dict[str, Any]:
    return {
        "state": snapshot.state,
        "title": snapshot.title or None,
        "artist": snapshot.artist or None,
        "album_title": snapshot.album_title or None,
        "album_artist": snapshot.album_artist or None,
        "source_app": snapshot.source_app or None,
        "duration": snapshot.duration,
        "position": snapshot.position,
        "volume": master.volume if master is not None else None,
        "muted": master.muted if master is not None else None,
        "capabilities": snapshot.capabilities.enabled_names(),
        "supported": snapshot.supported,
    }


def media_artwork_payload(snapshot: MediaSnapshot) -> dict[str, str] | None:
    artwork = snapshot.artwork
    if not artwork.data or not artwork.digest:
        return None
    return {
        "hash": artwork.digest,
        "content_type": artwork.content_type,
        "data": base64.b64encode(artwork.data).decode("ascii"),
    }
