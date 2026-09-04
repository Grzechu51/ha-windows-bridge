from __future__ import annotations

import json
import math
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.const import MediaType
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_DEVICE_ID, CONF_MEDIA_PLAYER
from .entity import BridgeMqttEntity, bridge_device_info, entity_definitions, message_text
from .media_payload import parse_media_artwork, parse_media_state

_STATE_MAP = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "idle": MediaPlayerState.IDLE,
    "off": MediaPlayerState.OFF,
}

_CAPABILITY_FEATURES = {
    "play": MediaPlayerEntityFeature.PLAY,
    "pause": MediaPlayerEntityFeature.PAUSE,
    "stop": MediaPlayerEntityFeature.STOP,
    "next": MediaPlayerEntityFeature.NEXT_TRACK,
    "previous": MediaPlayerEntityFeature.PREVIOUS_TRACK,
    "seek": MediaPlayerEntityFeature.SEEK,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the active-session player and per-application volume players."""
    entities: list[MediaPlayerEntity] = [
        HAWindowsAppVolumePlayer(entry, definition)
        for definition in entity_definitions(entry, "media_player")
    ]
    if entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled", False):
        entities.append(HAWindowsMediaPlayer(entry))
    async_add_entities(entities)


class HAWindowsAppVolumePlayer(BridgeMqttEntity, MediaPlayerEntity):
    """One Windows application audio session exposed as a volume-only player."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, entry: ConfigEntry, definition: dict[str, Any]) -> None:
        BridgeMqttEntity.__init__(self, entry, definition)
        self._volume_command_topic = str(definition["volume_command_topic"])
        self._volume_state_topic = str(definition["volume_state_topic"])
        self._mute_command_topic = str(definition["mute_command_topic"])
        self._mute_state_topic = str(definition["mute_state_topic"])
        self._state_on = str(definition.get("state_on", "ON"))
        self._state_off = str(definition.get("state_off", "OFF"))
        self._attr_state = MediaPlayerState.OFF
        self._attr_volume_level = None
        self._attr_is_volume_muted = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsubscribers.extend(
            (
                await mqtt.async_subscribe(
                    self.hass, self._volume_state_topic, self._volume_received, qos=1
                ),
                await mqtt.async_subscribe(
                    self.hass, self._mute_state_topic, self._mute_received, qos=1
                ),
            )
        )

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload == self._state_on:
            self._attr_state = MediaPlayerState.IDLE
        elif payload == self._state_off:
            self._attr_state = MediaPlayerState.OFF
        else:
            return
        self.async_write_ha_state()

    @callback
    def _volume_received(self, message: ReceiveMessage) -> None:
        try:
            percentage = float(message_text(message).strip())
        except (TypeError, ValueError):
            return
        if not math.isfinite(percentage):
            return
        self._attr_volume_level = max(0.0, min(1.0, percentage / 100.0))
        self.async_write_ha_state()

    @callback
    def _mute_received(self, message: ReceiveMessage) -> None:
        payload = message_text(message).strip()
        if payload == self._state_on:
            self._attr_is_volume_muted = True
        elif payload == self._state_off:
            self._attr_is_volume_muted = False
        else:
            return
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        percentage = max(0.0, min(1.0, volume)) * 100.0
        await self._async_publish(self._volume_command_topic, f"{percentage:g}")

    async def async_mute_volume(self, mute: bool) -> None:
        await self._async_publish(
            self._mute_command_topic,
            self._state_on if mute else self._state_off,
        )


class HAWindowsMediaPlayer(MediaPlayerEntity):
    """Active Windows System Media Transport session exposed through MQTT."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = True
    _attr_media_content_type = MediaType.MUSIC
    _attr_should_poll = False
    _attr_translation_key = "media_player"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        device_id = str(entry.data[CONF_DEVICE_ID])
        media = entry.data[CONF_MEDIA_PLAYER]
        self._attr_unique_id = f"{device_id}_media_player"
        self._attr_device_info = bridge_device_info(entry)
        self._command_topic = str(media["command_topic"])
        self._state_topic = str(media["state_topic"])
        self._thumbnail_topic = str(media.get("thumbnail_topic", ""))
        self._availability_topic = str(media["availability_topic"])
        self._attr_available = False
        self._attr_state = MediaPlayerState.IDLE
        self._bridge_online = False
        self._mqtt_connected = False
        self._media_supported = True
        self._media_image: bytes | None = None
        self._media_image_content_type: str | None = None
        self._attr_media_image_hash = None
        self._capabilities: set[str] = set()
        self._unsubscribers: list[Any] = []

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE
        for capability in self._capabilities:
            features |= _CAPABILITY_FEATURES.get(capability, MediaPlayerEntityFeature(0))
        return features

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._mqtt_connected = mqtt.is_connected(self.hass)
        self._unsubscribers.append(
            mqtt.async_subscribe_connection_status(
                self.hass,
                self._mqtt_connection_received,
            )
        )
        self._unsubscribers.extend(
            (
                await mqtt.async_subscribe(
                    self.hass, self._state_topic, self._state_received, qos=1
                ),
                await mqtt.async_subscribe(
                    self.hass, self._availability_topic, self._availability_received, qos=1
                ),
            )
        )
        if self._thumbnail_topic:
            self._unsubscribers.append(
                await mqtt.async_subscribe(
                    self.hass, self._thumbnail_topic, self._thumbnail_received, qos=1
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
        self._bridge_online = message_text(message).strip().lower() == "online"
        self._update_availability()

    @callback
    def _mqtt_connection_received(self, connected: bool) -> None:
        self._mqtt_connected = connected
        self._update_availability()

    @callback
    def _update_availability(self) -> None:
        self._attr_available = (
            self._mqtt_connected and self._bridge_online and self._media_supported
        )
        self.async_write_ha_state()

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = parse_media_state(message.payload)
        if payload is None:
            return
        self._media_supported = payload["supported"]
        self._update_availability()
        self._attr_state = _STATE_MAP[payload["state"]]
        self._attr_media_title = payload["title"]
        self._attr_media_artist = payload["artist"]
        self._attr_media_album_name = payload["album_title"]
        self._attr_media_album_artist = payload["album_artist"]
        self._attr_app_name = payload["source_app"]
        self._attr_media_duration = payload["duration"]
        self._attr_media_position = payload["position"]
        self._attr_media_position_updated_at = dt_util.utcnow()
        self._attr_volume_level = payload["volume"]
        self._attr_is_volume_muted = payload["muted"]
        self._capabilities = set(payload["capabilities"])
        self.async_write_ha_state()

    @callback
    def _thumbnail_received(self, message: ReceiveMessage) -> None:
        if not message.payload:
            self._clear_artwork()
            self.async_write_ha_state()
            return
        parsed = parse_media_artwork(message.payload)
        if parsed is None:
            return
        data, content_type, digest = parsed
        self._media_image = data
        self._media_image_content_type = content_type
        self._attr_media_image_hash = digest
        self.async_write_ha_state()

    def _clear_artwork(self) -> None:
        self._media_image = None
        self._media_image_content_type = None
        self._attr_media_image_hash = None

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Return the cached Windows media artwork through the HA image proxy."""
        return self._media_image, self._media_image_content_type

    async def _send_command(self, action: str, value: Any = None) -> None:
        await self._entry.runtime_data.send(
            self._command_topic,
            json.dumps({"action": action, "value": value}, separators=(",", ":")),
        )

    async def async_media_play(self) -> None:
        await self._send_command("play")

    async def async_media_pause(self) -> None:
        await self._send_command("pause")

    async def async_media_stop(self) -> None:
        await self._send_command("stop")

    async def async_media_next_track(self) -> None:
        await self._send_command("next")

    async def async_media_previous_track(self) -> None:
        await self._send_command("previous")

    async def async_media_seek(self, position: float) -> None:
        await self._send_command("seek", position)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._send_command("set_volume", max(0.0, min(1.0, volume)))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._send_command("mute", mute)
