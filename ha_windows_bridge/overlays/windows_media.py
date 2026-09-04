"""Present a Windows media snapshot without depending on Qt or a network source."""
from __future__ import annotations

import base64


def windows_media_payload(snapshot, *, device_name="Windows", controls=False):
    data = {
        "layout": "media", "icon": "mdi:music-note",
        "media_source": snapshot.source_app or device_name,
        "media_position": snapshot.position, "media_duration": snapshot.duration,
        "media_playing": snapshot.state == "playing", "media_controls": controls,
        "show_lifetime": False,
    }
    artwork = snapshot.artwork
    if artwork.data and len(artwork.data) <= 512 * 1024 and artwork.content_type in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        data["image"] = f"data:{artwork.content_type};base64," + base64.b64encode(artwork.data).decode("ascii")
    return {"title": snapshot.title or "Odtwarzacz Windows",
            "message": " · ".join(part for part in (snapshot.artist, snapshot.album_title) if part),
            "data": data}
