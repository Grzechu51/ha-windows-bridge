from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import target as target_helpers
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE_ID,
    CONF_ENTITIES,
    CONF_MEDIA_PLAYER,
    DOMAIN,
    SERVICE_CLEAR_OVERLAY,
    SERVICE_REMOVE_OVERLAY,
    SERVICE_SHOW_OVERLAY,
    SERVICE_UPDATE_OVERLAY,
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

_OVERLAY_ID = vol.All(cv.string, vol.Length(min=1, max=64), vol.Match(r"^[A-Za-z0-9_.:-]+$"))
_OVERLAY_OPTIONS = {
    vol.Optional("icon"): vol.All(cv.string, vol.Length(max=8)),
    vol.Optional("image"): vol.All(cv.string, vol.Length(max=700 * 1024)),
    vol.Optional("qr"): vol.All(cv.string, vol.Length(max=512)),
    vol.Optional("progress"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=2, max=60)),
    vol.Optional("pinned"): cv.boolean,
    vol.Optional("corner"): vol.In(
        {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
    ),
    vol.Optional("monitor"): vol.All(vol.Coerce(int), vol.Range(min=0, max=15)),
    vol.Optional("size"): vol.In({"small", "medium", "large"}),
    vol.Optional("opacity"): vol.All(
        vol.Coerce(float), vol.Range(min=0.35, max=1.0)
    ),
    vol.Optional("preset"): vol.In(
        {"default", "success", "warning", "error", "info"}
    ),
}
_SHOW_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=2048)),
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=128)),
        vol.Optional("notification_id"): _OVERLAY_ID,
        **_OVERLAY_OPTIONS,
    }
)
_UPDATE_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required("notification_id"): _OVERLAY_ID,
        vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=2048)),
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=128)),
        **_OVERLAY_OPTIONS,
    }
)
_REMOVE_OVERLAY_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("notification_id"): _OVERLAY_ID}
)
_CLEAR_OVERLAY_SCHEMA = cv.make_entity_service_schema({})


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register validated actions shared by all configured Windows bridges."""

    async def publish_overlay(call: ServiceCall) -> None:
        action = {
            SERVICE_SHOW_OVERLAY: "show",
            SERVICE_UPDATE_OVERLAY: "update",
            SERVICE_REMOVE_OVERLAY: "remove",
            SERVICE_CLEAR_OVERLAY: "clear",
        }[call.service]
        registry = er.async_get(hass)
        selected = target_helpers.TargetSelection(call.data)
        referenced = target_helpers.async_extract_referenced_entity_ids(
            hass, selected, expand_group=True
        )
        entity_ids = referenced.referenced | referenced.indirectly_referenced
        topics: set[str] = set()
        for entity_id in entity_ids:
            if call.context.user_id:
                user = await hass.auth.async_get_user(call.context.user_id)
                if user is None or not user.permissions.check_entity(entity_id, POLICY_CONTROL):
                    raise HomeAssistantError("Not authorized to control this overlay entity")
            registered = registry.async_get(entity_id)
            if registered is None or registered.config_entry_id is None:
                continue
            runtime = hass.data.get(DOMAIN, {}).get(registered.config_entry_id, {})
            if registered.unique_id != runtime.get("overlay_unique_id"):
                continue
            if topic := runtime.get("overlay_topic"):
                topics.add(str(topic))
        if not topics:
            raise HomeAssistantError("Select an enabled HA Windows Bridge overlay entity")

        options: dict[str, Any] = {
            key: value
            for key, value in call.data.items()
            if key not in {"entity_id", "device_id", "area_id", "floor_id", "label_id"}
            and key not in {"title", "message", "notification_id"}
        }
        options["action"] = action
        if notification_id := call.data.get("notification_id"):
            options["id"] = notification_id
        payload = json.dumps(
            {
                "title": call.data.get(
                    "title", "Home Assistant" if action == "show" else ""
                ),
                "message": call.data.get("message", ""),
                "data": options,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > 768 * 1024:
            raise HomeAssistantError("Overlay payload is too large")
        for topic in topics:
            await mqtt.async_publish(hass, topic, payload, qos=1, retain=False)

    hass.services.async_register(
        DOMAIN, SERVICE_SHOW_OVERLAY, publish_overlay, schema=_SHOW_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_OVERLAY, publish_overlay, schema=_UPDATE_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_OVERLAY, publish_overlay, schema=_REMOVE_OVERLAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_OVERLAY, publish_overlay, schema=_CLEAR_OVERLAY_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up every entity announced by one Windows bridge."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("Configure and enable the Home Assistant MQTT integration first")

    valid_unique_ids = {
        str(definition["unique_id"])
        for definition in entry.data.get(CONF_ENTITIES, [])
        if isinstance(definition, dict) and definition.get("unique_id")
    }
    if entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled", False):
        valid_unique_ids.add(f"{entry.data[CONF_DEVICE_ID]}_media_player")

    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id not in valid_unique_ids:
            registry.async_remove(registered.entity_id)

    overlay_definition = next(
        (
            definition
            for definition in entry.data.get(CONF_ENTITIES, [])
            if isinstance(definition, dict)
            and definition.get("platform") == Platform.NOTIFY.value
            and str(definition.get("command_topic", "")).endswith("/overlay/show/set")
        ),
        {},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "unique_ids": valid_unique_ids,
        "overlay_unique_id": overlay_definition.get("unique_id", ""),
        "overlay_topic": overlay_definition.get("command_topic", ""),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA Windows Bridge."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
