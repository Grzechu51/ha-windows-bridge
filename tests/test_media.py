from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

from ha_windows_bridge.audio import AudioSessionSnapshot
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.integration_protocol import integration_announcement_payload
from ha_windows_bridge.media import (
    MediaArtwork,
    MediaCapabilities,
    MediaSnapshot,
    _image_content_type,
    _playback_state,
    _read_artwork,
)
from ha_windows_bridge.media_protocol import (
    media_announcement_topic,
    media_artwork_payload,
    media_state_payload,
    media_thumbnail_topic,
    media_topics,
)

_PAYLOAD_MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ha_windows_bridge" / "media_payload.py"
)
_PAYLOAD_SPEC = importlib.util.spec_from_file_location(
    "ha_windows_bridge_media_payload", _PAYLOAD_MODULE_PATH
)
assert _PAYLOAD_SPEC is not None and _PAYLOAD_SPEC.loader is not None
_PAYLOAD_MODULE = importlib.util.module_from_spec(_PAYLOAD_SPEC)
_PAYLOAD_SPEC.loader.exec_module(_PAYLOAD_MODULE)
MAX_ARTWORK_BYTES = _PAYLOAD_MODULE.MAX_ARTWORK_BYTES
MAX_STATE_PAYLOAD = _PAYLOAD_MODULE.MAX_STATE_PAYLOAD
parse_media_artwork = _PAYLOAD_MODULE.parse_media_artwork
parse_media_state = _PAYLOAD_MODULE.parse_media_state

_ANNOUNCEMENT_MODULE_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ha_windows_bridge" / "announcement.py"
)
_ANNOUNCEMENT_SPEC = importlib.util.spec_from_file_location(
    "ha_windows_bridge_announcement", _ANNOUNCEMENT_MODULE_PATH
)
assert _ANNOUNCEMENT_SPEC is not None and _ANNOUNCEMENT_SPEC.loader is not None
_ANNOUNCEMENT_MODULE = importlib.util.module_from_spec(_ANNOUNCEMENT_SPEC)
_ANNOUNCEMENT_SPEC.loader.exec_module(_ANNOUNCEMENT_MODULE)
parse_discovery_announcement = _ANNOUNCEMENT_MODULE.parse_discovery_announcement


class NamedStatus:
    def __init__(self, name: str) -> None:
        self.name = name


def test_windows_playback_status_is_mapped_to_home_assistant_state() -> None:
    assert _playback_state(NamedStatus("PLAYING")) == "playing"
    assert _playback_state(NamedStatus("PAUSED")) == "paused"
    assert _playback_state(NamedStatus("STOPPED")) == "idle"


def test_image_content_type_is_detected_from_common_file_signatures() -> None:
    assert _image_content_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert _image_content_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert _image_content_type(b"GIF89arest") == "image/gif"
    assert _image_content_type(b"RIFF1234WEBPrest") == "image/webp"
    assert _image_content_type(b"<svg/>", "image/svg+xml") == "application/octet-stream"


def test_media_state_parser_rejects_oversized_and_invalid_messages() -> None:
    assert parse_media_state(b"not json") is None
    assert parse_media_state(b"{" + b" " * MAX_STATE_PAYLOAD + b"}") is None


def test_media_state_parser_normalizes_untrusted_values() -> None:
    payload = json.dumps(
        {
            "state": "unknown",
            "title": 123,
            "duration": "nan",
            "position": "inf",
            "volume": 7,
            "muted": "false",
            "capabilities": ["play", "delete", "play", 123],
            "supported": "false",
        }
    )

    state = parse_media_state(payload)

    assert state is not None
    assert state["state"] == "idle"
    assert state["title"] is None
    assert state["duration"] == 0
    assert state["position"] == 0
    assert state["volume"] == 1
    assert state["muted"] is None
    assert state["capabilities"] == ["play"]
    assert state["supported"] is True


def test_artwork_parser_accepts_known_raster_and_rejects_svg_or_mime_mismatch() -> None:
    png = b"\x89PNG\r\n\x1a\nthumbnail"
    accepted = parse_media_artwork(
        json.dumps({"content_type": "image/png", "data": base64.b64encode(png).decode()})
    )
    assert accepted is not None
    assert accepted[0] == png
    assert accepted[1] == "image/png"

    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    assert (
        parse_media_artwork(
            json.dumps({"content_type": "image/svg+xml", "data": base64.b64encode(svg).decode()})
        )
        is None
    )
    assert (
        parse_media_artwork(
            json.dumps({"content_type": "image/jpeg", "data": base64.b64encode(png).decode()})
        )
        is None
    )


def test_artwork_parser_rejects_decoded_image_over_limit() -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * MAX_ARTWORK_BYTES
    payload = json.dumps(
        {"content_type": "image/png", "data": base64.b64encode(oversized).decode()}
    )
    assert parse_media_artwork(payload) is None


def test_media_protocol_uses_stable_device_and_base_topics() -> None:
    config = AppConfig(
        device_name="Gaming PC",
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="ha-windows-bridge/gaming-pc"),
        media_player_enabled=True,
    )

    announcement = integration_announcement_payload(config)

    assert media_announcement_topic(config) == "ha-windows-bridge/devices/gaming_pc_123"
    assert media_topics(config) == (
        "ha-windows-bridge/gaming-pc/media_player/command",
        "ha-windows-bridge/gaming-pc/media_player/state",
    )
    assert announcement["schema"] == 2
    assert announcement["device_id"] == "gaming_pc_123"
    assert announcement["device"]["name"] == "Gaming PC"
    assert announcement["media_player"]["enabled"] is True
    assert {entity["platform"] for entity in announcement["entities"]} >= {
        "binary_sensor",
        "number",
        "switch",
    }
    assert announcement["media_player"]["availability_topic"].endswith("/status")
    assert announcement["media_player"]["thumbnail_topic"] == media_thumbnail_topic(config)


def test_discovery_announcement_parser_accepts_bridge_payload() -> None:
    config = AppConfig(
        device_name="Gaming PC",
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="ha-windows-bridge/gaming-pc"),
        media_player_enabled=True,
    )

    parsed = parse_discovery_announcement(json.dumps(integration_announcement_payload(config)))

    assert parsed is not None
    assert parsed["device_id"] == "gaming_pc_123"
    assert parsed["media_player"]["enabled"] is True
    assert len(parsed["entities"]) >= 3


def test_discovery_announcement_parser_rejects_wildcards_and_invalid_identifiers() -> None:
    config = AppConfig(
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="ha-windows-bridge/gaming-pc"),
        media_player_enabled=True,
    )
    announcement = integration_announcement_payload(config)
    announcement["media_player"]["state_topic"] = "untrusted/#"
    assert parse_discovery_announcement(json.dumps(announcement)) is None

    announcement = integration_announcement_payload(config)
    announcement["device_id"] = "../../invalid"
    assert parse_discovery_announcement(json.dumps(announcement)) is None


def test_discovery_announcement_rejects_topics_outside_bridge_scope_and_duplicates() -> None:
    config = AppConfig(
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="ha-windows-bridge/gaming-pc"),
        media_player_enabled=True,
    )
    announcement = integration_announcement_payload(config)
    announcement["entities"][0]["state_topic"] = "another-device/status"
    assert parse_discovery_announcement(json.dumps(announcement)) is None

    announcement = integration_announcement_payload(config)
    announcement["entities"].append(dict(announcement["entities"][0]))
    assert parse_discovery_announcement(json.dumps(announcement)) is None


def test_legacy_schema_one_announcement_remains_readable_during_migration() -> None:
    config = AppConfig(
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="ha-windows-bridge/gaming-pc"),
        media_player_enabled=True,
    )
    announcement = integration_announcement_payload(config)
    announcement["schema"] = 1
    announcement.pop("entities")

    parsed = parse_discovery_announcement(json.dumps(announcement))

    assert parsed is not None
    assert parsed["entities"] == []


def test_media_state_contains_metadata_controls_and_master_volume() -> None:
    snapshot = MediaSnapshot(
        state="playing",
        title="Track",
        artist="Artist",
        album_title="Album",
        album_artist="Album Artist",
        source_app="Spotify.exe",
        duration=241.5,
        position=42.25,
        capabilities=MediaCapabilities(play=True, pause=True, next=True, seek=True),
    )

    payload = media_state_payload(snapshot, AudioSessionSnapshot(0.65, True))

    assert payload == {
        "state": "playing",
        "title": "Track",
        "artist": "Artist",
        "album_title": "Album",
        "album_artist": "Album Artist",
        "source_app": "Spotify.exe",
        "duration": 241.5,
        "position": 42.25,
        "volume": 0.65,
        "muted": True,
        "capabilities": ["play", "pause", "next", "seek"],
        "supported": True,
    }


def test_artwork_is_encoded_separately_from_small_state_payload() -> None:
    data = b"\x89PNG\r\n\x1a\nthumbnail"
    digest = hashlib.sha256(data).hexdigest()
    snapshot = MediaSnapshot(artwork=MediaArtwork(data, "image/png", digest))

    payload = media_artwork_payload(snapshot)

    assert payload is not None
    assert payload["hash"] == digest
    assert payload["content_type"] == "image/png"
    assert payload["data"] == "iVBORw0KGgp0aHVtYm5haWw="


def test_winrt_thumbnail_stream_can_be_read() -> None:
    from winrt.windows.storage.streams import (
        DataWriter,
        InMemoryRandomAccessStream,
        RandomAccessStreamReference,
    )

    source = b"\x89PNG\r\n\x1a\nthumbnail"

    async def read() -> MediaArtwork:
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(source)
            await writer.store_async()
            writer.detach_stream()
            reference = RandomAccessStreamReference.create_from_stream(stream)
            return await _read_artwork(reference)
        finally:
            writer.close()
            stream.close()

    artwork = asyncio.run(read())

    assert artwork.data == source
    assert artwork.content_type == "image/png"
    assert artwork.digest == hashlib.sha256(source).hexdigest()


def test_home_assistant_integration_files_are_valid_json() -> None:
    project_root = Path(__file__).parents[1]
    root = project_root / "custom_components" / "ha_windows_bridge"
    for path in (
        root / "manifest.json",
        root / "translations" / "en.json",
        root / "translations" / "pl.json",
    ):
        assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["after_dependencies"] == ["mqtt"]
    assert manifest["mqtt"] == ["ha-windows-bridge/devices/+"]
    from ha_windows_bridge import __version__

    assert manifest["version"] == __version__
    assert manifest["codeowners"] == ["@Grzechu51"]
    assert manifest["documentation"] == "https://github.com/Grzechu51/ha-windows-bridge"
    assert manifest["issue_tracker"].endswith("/Grzechu51/ha-windows-bridge/issues")
    for brand_file in ("icon.png", "dark_icon.png", "logo.png", "dark_logo.png"):
        assert (root / "brand" / brand_file).read_bytes().startswith(b"\x89PNG")


def test_overlay_service_form_uses_single_booleans_and_native_icon_selector() -> None:
    project_root = Path(__file__).parents[1]
    root = project_root / "custom_components" / "ha_windows_bridge"
    services = (root / "services.yaml").read_text(encoding="utf-8")
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))

    assert "media:\n          selector:\n            constant:\n              value: true" in services
    assert "pinned:\n          selector:\n            constant:\n              value: true" in services
    assert (
        "show_close_button:\n          selector:\n            constant:\n              value: true"
        in services
    )
    assert "icon:\n          selector:\n            icon:" in services
    assert "min: 0\n              max: 1" in services
    assert "glass:" not in services
    assert services.count("background_effect:") == 2
    assert services.count("translation_key: overlay_background_effect") == 2
    assert services.count("edge_offset:") == 2
    assert services.count("media_player_entity:") == 3
    assert services.count("domain: media_player") == 3
    assert "visible:" not in services
    assert services.count("translation_key: overlay_size_mode") == 2
    assert services.count("display_mode:") == 2
    assert services.count("translation_key: overlay_display_mode") == 2
    assert "channel:" not in services
    assert "translation_key: overlay_channel" not in services
    assert services.count("image_entity:") == 1
    assert "- camera\n                - image" in services
    assert services.count("image_url:") == 1
    assert (
        strings["services"]["show_overlay"]["fields"]["background_effect"]["name"]
        == "Background effect"
    )
    assert (
        strings["services"]["show_overlay"]["fields"]["edge_offset"]["name"]
        == "Edge offset"
    )
    show_service = services.split("update_overlay:", 1)[0]
    update_service = services.split("update_overlay:", 1)[1]
    assert show_service.index("background_effect:") < show_service.index("opacity:")
    assert update_service.index("background_effect:") < update_service.index("opacity:")
    assert (
        strings["services"]["show_overlay"]["fields"]["media_player_entity"]["name"]
        == "Home Assistant media player"
    )
    saved_fields = strings["services"]["show_saved_overlay"]["fields"]
    assert saved_fields["image_entity"]["name"] == "Camera or image entity"
    assert saved_fields["image_url"]["name"] == "Image URL"
    assert "channel" not in strings["services"]["show_overlay"]["fields"]
    assert "channel" not in strings["services"]["update_overlay"]["fields"]
    assert "fields" not in strings["services"]["clear_overlay"]
    assert "overlay_channel" not in strings["selector"]
    assert set(strings["selector"]["overlay_style"]["options"]) == {
        "success",
        "warning",
        "error",
        "info",
    }
    assert set(strings["selector"]["overlay_size_mode"]["options"]) == {
        "auto",
        "manual",
    }
    assert set(strings["selector"]["overlay_background_effect"]["options"]) == {
        "none",
        "blur",
        "liquid",
    }
    assert set(strings["selector"]["overlay_layout"]["options"]) == {
        "auto",
        "compact",
        "status",
        "badge",
        "standard",
        "media",
        "camera",
    }
    assert set(strings["selector"]["overlay_display_mode"]["options"]) == {
        "queue",
        "parallel",
    }
