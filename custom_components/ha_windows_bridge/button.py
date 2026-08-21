from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BridgeMqttEntity, entity_definitions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [BridgeButton(entry, definition) for definition in entity_definitions(entry, "button")]
    )


class BridgeButton(BridgeMqttEntity, ButtonEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._command_topic = str(definition["command_topic"])
        self._payload_press = str(definition["payload_press"])

    async def async_press(self) -> None:
        await self._async_publish(self._command_topic, self._payload_press)
