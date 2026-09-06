from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any

from . import __version__
from .config import AppConfig
from .discovery import discovery_messages, status_topic
from .media_protocol import media_thumbnail_topic, media_topics


def integration_entity_definitions(
    config: AppConfig,
    audio_outputs: list[str] | None = None,
    hardware_metrics: set[str] | None = None,
    overlay_monitors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the platform-neutral entity inventory consumed by the HA integration."""
    prefix = f"{config.mqtt.discovery_prefix}/"
    entities: list[dict[str, Any]] = []
    for message in discovery_messages(config, audio_outputs, hardware_metrics, overlay_monitors):
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
    overlay_monitors: list[str] | None = None,
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
        "entities": integration_entity_definitions(
            config, audio_outputs, hardware_metrics, overlay_monitors
        ),
        "media_player": {
            "enabled": config.media_player_enabled,
            "command_topic": command_topic,
            "state_topic": state_topic,
            "thumbnail_topic": media_thumbnail_topic(config),
            "availability_topic": status_topic(config),
        },
    }


# Keep these v2 wire limits aligned with the HA decoder (contract-tested).
MAX_ENTITIES = 256
MAX_ANNOUNCEMENT_PAYLOAD = 256 * 1024
MAX_ROUTES = 512


def inventory_budget_errors(config: AppConfig) -> list[str]:
    """Reserve all configured optional entities, without reading any hardware."""
    from .communication.protocol import TopicProtocol

    payload = integration_announcement_payload(config)
    protocol = TopicProtocol(config)
    routes = {topic: asdict(route) for topic, route in protocol.routes.items()}
    payload.update(schema=3, protocol={"version": 2, "command_topic": protocol.command_topic,
                                      "result_topic": protocol.result_topic, "routes": routes})
    errors = []
    if len(payload["entities"]) > MAX_ENTITIES:
        errors.append(f"Inventory exceeds the Home Assistant limit of {MAX_ENTITIES} entities.")
    if len(routes) > MAX_ROUTES:
        errors.append(f"Inventory exceeds the Home Assistant limit of {MAX_ROUTES} command routes.")
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_ANNOUNCEMENT_PAYLOAD:
        errors.append("Inventory exceeds the Home Assistant payload limit of 256 KiB.")
    return errors
