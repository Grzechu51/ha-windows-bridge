from __future__ import annotations

from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.select import SelectEntity
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
        [BridgeSelect(entry, definition) for definition in entity_definitions(entry, "select")]
    )


class BridgeSelect(BridgeMqttEntity, SelectEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._command_topic = str(definition["command_topic"])
        self._attr_options = list(definition["options"])
        self._attr_current_option: str | None = None

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload not in self._attr_options:
            return
        self._attr_current_option = payload
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise ValueError(f"Unsupported option: {option}")
        await self._async_publish(self._command_topic, option)
