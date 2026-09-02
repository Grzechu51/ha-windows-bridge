from __future__ import annotations

import json
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DEVICE_ID,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_DIRECT,
    direct_template_command_event,
    template_dispatcher_signal,
)
from .entity import (
    BridgeMqttEntity,
    bridge_device_info,
    entity_definitions,
    message_text,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SelectEntity] = [
        BridgeSelect(entry, definition) for definition in entity_definitions(entry, "select")
    ]
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if runtime.get("overlay_unique_id"):
        entities.append(OverlayTemplateSelect(entry))
    async_add_entities(entities)


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


class OverlayTemplateSelect(SelectEntity):
    """Dynamic list of popup designs owned by one Windows bridge."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:message-draw"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_overlay_template"
        self._attr_translation_key = "overlay_template"
        self._attr_device_info = bridge_device_info(entry)
        self._attr_options: list[str] = []
        self._attr_current_option: str | None = None
        self._catalog: list[dict[str, str]] = []
        self._unsubscribe = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsubscribe = async_dispatcher_connect(
            self.hass,
            template_dispatcher_signal(self._entry.entry_id),
            self._catalog_updated,
        )
        self._catalog_updated()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await super().async_will_remove_from_hass()

    @callback
    def _catalog_updated(self) -> None:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        self._catalog = list(runtime.get("template_catalog", []))
        self._attr_options = [item["name"] for item in self._catalog]
        selected_id = str(runtime.get("selected_template_id", ""))
        self._attr_current_option = next(
            (item["name"] for item in self._catalog if item["id"] == selected_id),
            self._attr_options[0] if self._attr_options else None,
        )
        self._attr_available = bool(self._attr_options)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "template_id": next(
                (
                    item["id"]
                    for item in self._catalog
                    if item["name"] == self._attr_current_option
                ),
                "",
            ),
            "templates": {item["id"]: item["name"] for item in self._catalog},
        }

    async def async_select_option(self, option: str) -> None:
        selected = next((item for item in self._catalog if item["name"] == option), None)
        if selected is None:
            raise ValueError(f"Unsupported popup template: {option}")
        runtime = self.hass.data[DOMAIN][self._entry.entry_id]
        runtime["selected_template_id"] = selected["id"]
        self._attr_current_option = option
        self.async_write_ha_state()
        payload = json.dumps(
            {"action": "select", "template_id": selected["id"]},
            separators=(",", ":"),
        )
        if self._entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT:
            self.hass.bus.async_fire(
                direct_template_command_event(str(self._entry.data[CONF_DEVICE_ID])),
                {"action": "select", "template_id": selected["id"]},
            )
        else:
            await mqtt.async_publish(
                self.hass,
                str(runtime.get("template_command_topic", "")),
                payload,
                qos=1,
                retain=False,
            )
