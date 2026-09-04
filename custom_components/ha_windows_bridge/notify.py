from __future__ import annotations

import json
from typing import Any

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_TRANSPORT, TRANSPORT_DIRECT, direct_overlay_event
from .entity import BridgeMqttEntity, bridge_device_info, entity_definitions

MAX_NOTIFICATION_TITLE = 128
MAX_NOTIFICATION_MESSAGE = 2048


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entity_type = BridgeDirectNotify if entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT else BridgeWindowsNotify
    async_add_entities([entity_type(entry, definition) for definition in entity_definitions(entry, "notify")])


class BridgeDirectNotify(NotifyEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_available = False
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        self._entry = entry
        self._attr_unique_id = str(definition["unique_id"])
        self._attr_name = str(definition["name"])
        self._attr_device_info = bridge_device_info(entry)
        self._event_type = direct_overlay_event(str(entry.data[CONF_DEVICE_ID]))

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        runtime = self._entry.runtime_data
        runtime.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: runtime.listeners.discard(self.async_write_ha_state))

    @property
    def available(self):
        return self._entry.runtime_data.available

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        clean_message = message.strip()
        clean_title = (title or "Home Assistant").strip()
        if not clean_message:
            raise HomeAssistantError("Notification message cannot be empty")
        if len(clean_message) > MAX_NOTIFICATION_MESSAGE or len(clean_title) > MAX_NOTIFICATION_TITLE:
            raise HomeAssistantError("Notification content is too long")
        await self._entry.runtime_data.send(
            "", json.dumps({"title": clean_title, "message": clean_message, "data": {}}), direct=True,
        )


class BridgeWindowsNotify(BridgeMqttEntity, NotifyEntity):
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._command_topic = str(definition["command_topic"])

    async def async_send_message(
        self,
        message: str,
        title: str | None = None,
    ) -> None:
        clean_message = message.strip()
        clean_title = (title or "Home Assistant").strip()
        if not clean_message:
            raise HomeAssistantError("Notification message cannot be empty")
        if len(clean_message) > MAX_NOTIFICATION_MESSAGE:
            raise HomeAssistantError("Notification message is too long")
        if len(clean_title) > MAX_NOTIFICATION_TITLE:
            raise HomeAssistantError("Notification title is too long")
        await self._async_publish(
            self._command_topic,
            json.dumps(
                {"title": clean_title, "message": clean_message},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
