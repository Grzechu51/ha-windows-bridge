from __future__ import annotations

from contextlib import suppress
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BridgeMqttEntity, entity_definitions, message_text


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            BridgeBinarySensor(entry, definition)
            for definition in entity_definitions(entry, "binary_sensor")
        ]
    )


class BridgeBinarySensor(BridgeMqttEntity, BinarySensorEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._payload_on = str(definition["payload_on"])
        self._payload_off = str(definition["payload_off"])
        self._attr_is_on: bool | None = None
        device_class = definition.get("device_class")
        if isinstance(device_class, str):
            with suppress(ValueError):
                self._attr_device_class = BinarySensorDeviceClass(device_class)

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload == self._payload_on:
            self._attr_is_on = True
        elif payload == self._payload_off:
            self._attr_is_on = False
        else:
            return
        self.async_write_ha_state()
