from __future__ import annotations

import json
import math
import re
from typing import Any

MAX_ANNOUNCEMENT_PAYLOAD = 256 * 1024
MAX_ENTITIES = 256
_DEVICE_ID = re.compile(r"[a-z0-9_]{1,128}")
_UNIQUE_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")
_PLATFORMS = frozenset(
    {
        "binary_sensor",
        "button",
        "media_player",
        "notify",
        "number",
        "select",
        "sensor",
        "switch",
    }
)
_TOPIC_FIELDS = frozenset(
    {
        "availability_topic",
        "command_topic",
        "mute_command_topic",
        "mute_state_topic",
        "state_topic",
        "volume_command_topic",
        "volume_state_topic",
    }
)
_TEXT_FIELDS = frozenset(
    {
        "device_class",
        "entity_category",
        "icon",
        "mode",
        "name",
        "payload_available",
        "payload_not_available",
        "payload_off",
        "payload_on",
        "payload_press",
        "state_class",
        "state_off",
        "state_on",
        "unit_of_measurement",
    }
)
_REQUIRED_FIELDS = {
    "binary_sensor": frozenset({"state_topic", "payload_on", "payload_off"}),
    "button": frozenset({"command_topic", "payload_press"}),
    "media_player": frozenset(
        {
            "state_topic",
            "volume_command_topic",
            "volume_state_topic",
            "mute_command_topic",
            "mute_state_topic",
            "state_on",
            "state_off",
        }
    ),
    "notify": frozenset({"command_topic"}),
    "number": frozenset({"state_topic", "command_topic", "min", "max", "step"}),
    "select": frozenset({"state_topic", "command_topic", "options"}),
    "sensor": frozenset({"state_topic"}),
    "switch": frozenset(
        {"state_topic", "command_topic", "payload_on", "payload_off", "state_on", "state_off"}
    ),
}


def _text(value: Any, *, maximum: int, required: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > maximum or (required and not value):
        return None
    return value


def _topic(value: Any, *, required: bool = True) -> str | None:
    topic = _text(value, maximum=65_535, required=required)
    if topic is None or any(character in topic for character in "\x00+#"):
        return None
    return topic


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _entity(raw: Any, topic_prefix: str, bridge_status_topic: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    platform = raw.get("platform")
    unique_id = raw.get("unique_id")
    if platform not in _PLATFORMS:
        return None
    if not isinstance(unique_id, str) or _UNIQUE_ID.fullmatch(unique_id) is None:
        return None
    name = _text(raw.get("name"), maximum=128, required=True)
    if name is None or not _REQUIRED_FIELDS[platform].issubset(raw):
        return None

    normalized: dict[str, Any] = {
        "platform": platform,
        "unique_id": unique_id,
        "name": name,
    }
    for field in _TOPIC_FIELDS:
        if field not in raw:
            continue
        topic = _topic(raw[field], required=True)
        if topic is None:
            return None
        if topic != bridge_status_topic and not topic.startswith(topic_prefix):
            return None
        normalized[field] = topic
    for field in _TEXT_FIELDS - {"name"}:
        if field not in raw:
            continue
        value = _text(raw[field], maximum=128, required=True)
        if value is None:
            return None
        normalized[field] = value

    if platform == "number":
        minimum = _finite(raw.get("min"))
        maximum = _finite(raw.get("max"))
        step = _finite(raw.get("step"))
        if minimum is None or maximum is None or step is None:
            return None
        if minimum >= maximum or step <= 0 or step > maximum - minimum:
            return None
        normalized.update({"min": minimum, "max": maximum, "step": step})
    if platform == "select":
        options = raw.get("options")
        if not isinstance(options, list) or not 1 <= len(options) <= 128:
            return None
        normalized_options: list[str] = []
        for option in options:
            value = _text(option, maximum=256, required=True)
            if value is None or value in normalized_options:
                return None
            normalized_options.append(value)
        normalized["options"] = normalized_options
    return normalized


def parse_discovery_announcement(raw: str | bytes) -> dict[str, Any] | None:
    """Validate an untrusted MQTT integration announcement before creating a flow."""
    if not isinstance(raw, (str, bytes)):
        return None
    size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if size > MAX_ANNOUNCEMENT_PAYLOAD:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or type(payload.get("schema")) is not int:
        return None
    if payload["schema"] not in {1, 2}:
        return None

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or _DEVICE_ID.fullmatch(device_id) is None:
        return None
    raw_device = payload.get("device")
    raw_media = payload.get("media_player")
    if not isinstance(raw_device, dict) or not isinstance(raw_media, dict):
        return None

    name = _text(raw_device.get("name"), maximum=128, required=True)
    manufacturer = _text(raw_device.get("manufacturer"), maximum=128)
    model = _text(raw_device.get("model"), maximum=128)
    sw_version = _text(raw_device.get("sw_version"), maximum=64)
    enabled = raw_media.get("enabled")
    if name is None or not isinstance(enabled, bool):
        return None

    command_topic = _topic(raw_media.get("command_topic"))
    state_topic = _topic(raw_media.get("state_topic"))
    availability_topic = _topic(raw_media.get("availability_topic"))
    thumbnail_topic = _topic(raw_media.get("thumbnail_topic", ""), required=False)
    if None in (command_topic, state_topic, availability_topic, thumbnail_topic):
        return None
    if not availability_topic.endswith("/status"):
        return None
    topic_prefix = availability_topic[: -len("status")]
    if not command_topic.startswith(topic_prefix) or not state_topic.startswith(topic_prefix):
        return None
    if thumbnail_topic and not thumbnail_topic.startswith(topic_prefix):
        return None

    raw_entities = payload.get("entities", []) if payload["schema"] == 2 else []
    if not isinstance(raw_entities, list) or len(raw_entities) > MAX_ENTITIES:
        return None
    entities: list[dict[str, Any]] = []
    unique_ids: set[str] = set()
    for raw_entity in raw_entities:
        entity = _entity(raw_entity, topic_prefix, availability_topic)
        if entity is None or entity["unique_id"] in unique_ids:
            return None
        unique_ids.add(entity["unique_id"])
        entities.append(entity)

    return {
        "device_id": device_id,
        "device": {
            "name": name,
            "manufacturer": manufacturer or "HA Windows Bridge",
            "model": model or "Windows bridge",
            "sw_version": sw_version or "",
        },
        "entities": entities,
        "media_player": {
            "enabled": enabled,
            "command_topic": command_topic,
            "state_topic": state_topic,
            "thumbnail_topic": thumbnail_topic,
            "availability_topic": availability_topic,
        },
    }
