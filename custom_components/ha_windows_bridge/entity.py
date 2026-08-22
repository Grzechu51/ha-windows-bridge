from __future__ import annotations

from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_DEVICE, CONF_DEVICE_ID, CONF_ENTITIES, DOMAIN


def entity_definitions(entry: ConfigEntry, platform: str) -> list[dict[str, Any]]:
    return [
        definition
        for definition in entry.data.get(CONF_ENTITIES, [])
        if definition.get("platform") == platform
    ]


def bridge_device_info(entry: ConfigEntry) -> DeviceInfo:
    device_id = str(entry.data[CONF_DEVICE_ID])
    device = entry.data[CONF_DEVICE]
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=str(device.get("name", "Windows PC")),
        manufacturer=str(device.get("manufacturer", "HA Windows Bridge")),
        model=str(device.get("model", "Windows bridge")),
        sw_version=str(device.get("sw_version", "")),
    )


def message_text(message: ReceiveMessage) -> str:
    payload = message.payload
    return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)


class BridgeMqttEntity:
    """Shared MQTT subscription and availability behavior for bridge entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        self._definition = definition
        self._attr_unique_id = str(definition["unique_id"])
        self._attr_name = str(definition["name"])
        self._attr_icon = definition.get("icon")
        self._attr_device_info = bridge_device_info(entry)
        category = definition.get("entity_category")
        if category in {EntityCategory.CONFIG.value, EntityCategory.DIAGNOSTIC.value}:
            self._attr_entity_category = EntityCategory(category)
        self._state_topic = str(definition.get("state_topic", ""))
        self._availability_topic = str(definition.get("availability_topic", ""))
        self._payload_available = str(definition.get("payload_available", "online"))
        self._payload_not_available = str(definition.get("payload_not_available", "offline"))
        self._bridge_online = not bool(self._availability_topic)
        self._mqtt_connected = False
        self._attr_available = False
        self._unsubscribers: list[Any] = []

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._mqtt_connected = mqtt.is_connected(self.hass)
        self._unsubscribers.append(
            mqtt.async_subscribe_connection_status(
                self.hass,
                self._mqtt_connection_received,
            )
        )
        if self._availability_topic:
            self._unsubscribers.append(
                await mqtt.async_subscribe(
                    self.hass,
                    self._availability_topic,
                    self._availability_received,
                    qos=1,
                )
            )
        if self._state_topic:
            self._unsubscribers.append(
                await mqtt.async_subscribe(
                    self.hass,
                    self._state_topic,
                    self._state_received,
                    qos=1,
                )
            )

        self._update_availability()

    async def async_will_remove_from_hass(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        await super().async_will_remove_from_hass()

    @callback
    def _availability_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload == self._payload_available:
            self._bridge_online = True
        elif payload == self._payload_not_available:
            self._bridge_online = False
        self._update_availability()

    @callback
    def _mqtt_connection_received(self, connected: bool) -> None:
        self._mqtt_connected = connected
        self._update_availability()

    @callback
    def _update_availability(self) -> None:
        self._attr_available = self._mqtt_connected and self._bridge_online
        self.async_write_ha_state()

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        raise NotImplementedError

    async def _async_publish(self, topic: str, payload: str) -> None:
        await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=False)
