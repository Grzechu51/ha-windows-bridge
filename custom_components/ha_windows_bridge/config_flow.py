from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .announcement import parse_discovery_announcement
from .const import CONF_DEVICE, CONF_DEVICE_ID, CONF_ENTITIES, CONF_MEDIA_PLAYER, DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle MQTT discovery for HA Windows Bridge."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._title = "HA Windows Bridge"

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> FlowResult:
        """Handle an MQTT integration announcement from the Windows application."""
        payload = parse_discovery_announcement(discovery_info.payload)
        if payload is None:
            return self.async_abort(reason="invalid_discovery")
        device_id = payload[CONF_DEVICE_ID]
        device = payload[CONF_DEVICE]
        entities = payload[CONF_ENTITIES]
        media_player = payload[CONF_MEDIA_PLAYER]
        self._title = device["name"]

        self._data = {
            CONF_DEVICE_ID: device_id,
            CONF_DEVICE: device,
            CONF_ENTITIES: entities,
            CONF_MEDIA_PLAYER: media_player,
        }
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(
            updates=self._data,
            reload_on_update=True,
        )
        if not entities and not media_player.get("enabled", False):
            return self.async_abort(reason="no_entities")

        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask the user to confirm the discovered Windows PC."""
        if user_input is not None:
            return self.async_create_entry(title=self._title, data=self._data)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._title},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """The integration is configured automatically through MQTT."""
        return self.async_abort(reason="discovery_only")