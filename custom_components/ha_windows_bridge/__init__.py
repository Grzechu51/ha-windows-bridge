from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICE_ID, CONF_ENTITIES, CONF_MEDIA_PLAYER, DOMAIN

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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"unique_ids": valid_unique_ids}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload HA Windows Bridge."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
