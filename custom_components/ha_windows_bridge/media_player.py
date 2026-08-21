from __future__ import annotations

import json
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
from .entity import bridge_device_info, message_text
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
    """Create the discovered Windows media player when the feature is enabled."""
    if entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled", False):
        async_add_entities([HAWindowsMediaPlayer(entry)])


class HAWindowsMediaPlayer(MediaPlayerEntity):
    """Active Windows System Media Transport session exposed through MQTT."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = True
    _attr_media_content_type = MediaType.MUSIC
    _attr_should_poll = False
    _attr_translation_key = "media_player"

    def __init__(self, entry: ConfigEntry) -> None:
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

    async def async_will_remove_from_hass(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        await super().async_will_remove_from_hass()

    @callback
    def _availability_received(self, message: ReceiveMessage) -> None:
        self._bridge_online = message_text(message).strip().lower() == "online"
        self._attr_available = self._bridge_online and self._media_supported
        self.async_write_ha_state()

    @callback
    def _state_received(self, message: ReceiveMessage) -> None:
        payload = parse_media_state(message.payload)
        if payload is None:
            return
        self._media_supported = payload["supported"]
        self._attr_available = self._bridge_online and self._media_supported
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
        await mqtt.async_publish(
            self.hass,
            self._command_topic,
            json.dumps({"action": action, "value": value}, separators=(",", ":")),
            qos=1,
            retain=False,
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
