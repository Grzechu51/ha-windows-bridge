from __future__ import annotations

import json
from typing import Any

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import BridgeMqttEntity, entity_definitions

MAX_NOTIFICATION_TITLE = 128
MAX_NOTIFICATION_MESSAGE = 2048


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            BridgeWindowsNotify(entry, definition)
            for definition in entity_definitions(entry, "notify")
        ]
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
