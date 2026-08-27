from __future__ import annotations

import copy
from typing import Any

from . import __version__
from .config import AppConfig
from .discovery import discovery_messages, status_topic
from .media_protocol import media_thumbnail_topic, media_topics


def integration_entity_definitions(
    config: AppConfig,
    audio_outputs: list[str] | None = None,
    hardware_metrics: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the platform-neutral entity inventory consumed by the HA integration."""
    prefix = f"{config.mqtt.discovery_prefix}/"
    entities: list[dict[str, Any]] = []
    for message in discovery_messages(config, audio_outputs, hardware_metrics):
        if not message.topic.startswith(prefix):
            continue
        platform = message.topic[len(prefix) :].split("/", 1)[0]
        payload = copy.deepcopy(message.payload)
        payload.pop("device", None)
        payload.pop("origin", None)
        payload["platform"] = platform
        entities.append(payload)
    return entities


def integration_announcement_payload(
    config: AppConfig,
    audio_outputs: list[str] | None = None,
    hardware_metrics: set[str] | None = None,
) -> dict[str, Any]:
    """Describe one Windows bridge and every entity owned by its HA integration."""
    command_topic, state_topic = media_topics(config)
    return {
        "schema": 2,
        "device_id": config.device_id,
        "device": {
            "name": config.device_name,
            "manufacturer": "HA Windows Bridge",
            "model": "Windows bridge",
            "sw_version": __version__,
        },
        "entities": integration_entity_definitions(config, audio_outputs, hardware_metrics),
        "media_player": {
            "enabled": config.media_player_enabled,
            "command_topic": command_topic,
            "state_topic": state_topic,
            "thumbnail_topic": media_thumbnail_topic(config),
            "availability_topic": status_topic(config),
        },
    }
