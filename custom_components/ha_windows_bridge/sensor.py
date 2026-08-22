from __future__ import annotations

import math
from contextlib import suppress
from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
        [BridgeSensor(entry, definition) for definition in entity_definitions(entry, "sensor")]
    )


class BridgeSensor(BridgeMqttEntity, SensorEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._attr_native_unit_of_measurement = definition.get("unit_of_measurement")
        self._numeric = bool(self._attr_native_unit_of_measurement or definition.get("state_class"))
        device_class = definition.get("device_class")
        if isinstance(device_class, str):
            with suppress(ValueError):
                self._attr_device_class = SensorDeviceClass(device_class)
        state_class = definition.get("state_class")
        if isinstance(state_class, str):
            with suppress(ValueError):
                self._attr_state_class = SensorStateClass(state_class)
        self._attr_native_value: str | int | float | None = None

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if self._numeric:
            try:
                value = float(payload)
            except ValueError:
                return
            if not math.isfinite(value):
                return
            self._attr_native_value = int(value) if value.is_integer() else value
        else:
            self._attr_native_value = payload[:1024]
        self.async_write_ha_state()
