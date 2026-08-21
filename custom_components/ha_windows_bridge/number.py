from __future__ import annotations

import math
from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.number import NumberEntity, NumberMode
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
        [BridgeNumber(entry, definition) for definition in entity_definitions(entry, "number")]
    )


class BridgeNumber(BridgeMqttEntity, NumberEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._command_topic = str(definition["command_topic"])
        self._attr_native_min_value = float(definition["min"])
        self._attr_native_max_value = float(definition["max"])
        self._attr_native_step = float(definition["step"])
        self._attr_mode = (
            NumberMode.BOX if definition.get("mode") == NumberMode.BOX.value else NumberMode.SLIDER
        )
        self._attr_native_value: float | None = None

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        try:
            value = float(message_text(message).strip())
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        self._attr_native_value = max(
            self._attr_native_min_value,
            min(self._attr_native_max_value, value),
        )
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        value = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        await self._async_publish(self._command_topic, f"{value:g}")
