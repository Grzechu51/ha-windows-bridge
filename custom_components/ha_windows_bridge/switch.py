from __future__ import annotations

from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.switch import SwitchEntity
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
        [BridgeSwitch(entry, definition) for definition in entity_definitions(entry, "switch")]
    )


class BridgeSwitch(BridgeMqttEntity, SwitchEntity):
    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._command_topic = str(definition["command_topic"])
        self._payload_on = str(definition["payload_on"])
        self._payload_off = str(definition["payload_off"])
        self._state_on = str(definition["state_on"])
        self._state_off = str(definition["state_off"])
        self._attr_is_on: bool | None = None

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload == self._state_on:
            self._attr_is_on = True
        elif payload == self._state_off:
            self._attr_is_on = False
        else:
            return
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_publish(self._command_topic, self._payload_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_publish(self._command_topic, self._payload_off)
