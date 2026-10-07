from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from .announcement import parse_discovery_announcement
from .const import (
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_ENTITIES,
    CONF_MEDIA_PLAYER,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_DIRECT,
)
from .migration import canonical_direct_entities, direct_in_place_journal


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle MQTT discovery for HA Windows Bridge."""

    VERSION = 2

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
            "protocol": payload.get("protocol", {}),
        }
        await self.async_set_unique_id(device_id)
        configured = [entry for entry in self.hass.config_entries.async_entries(DOMAIN)
                      if entry.data.get(CONF_DEVICE_ID) == device_id]
        canonical = next((entry for entry in configured if entry.unique_id == device_id), None)
        # An old Direct-only entry becomes the MQTT owner in place. Its old popup
        # remains registered until the new canonical popup is live.
        if canonical is None and len(configured) == 1 and configured[0].data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT:
            canonical = configured[0]
            self._data["migration_journal"] = direct_in_place_journal(self.hass, canonical)
            self._data["direct_popup_enabled"] = True
            self._data[CONF_DEVICE] = {**device, "name": canonical.data[CONF_DEVICE]["name"]}
        elif canonical:
            if "migration_journal" in canonical.data:
                self._data["migration_journal"] = canonical.data["migration_journal"]
            if canonical.data.get("direct_popup_enabled"):
                self._data["direct_popup_enabled"] = True
        if not any(item.get("platform") == "notify" and
                   item.get("unique_id") == f"{device_id}_windows_overlay"
                   for item in self._data[CONF_ENTITIES]):
            has_direct_fallback = any(
                entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT
                or entry.data.get("direct_popup_enabled") or any(
                    item.get("platform") == "notify" and
                    str(item.get("command_topic", "")).startswith("direct://")
                    for item in entry.data.get(CONF_ENTITIES, ()))
                for entry in configured)
            if has_direct_fallback:
                self._data[CONF_ENTITIES] = [*self._data[CONF_ENTITIES],
                                             *canonical_direct_entities(device_id)]
        if canonical:
            title = canonical.title if canonical.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT else self._title
            runtime = getattr(canonical, "runtime_data", None)
            if (canonical.data == self._data and canonical.unique_id == device_id
                    and canonical.title == title and canonical.version == self.VERSION
                    and canonical.state == config_entries.ConfigEntryState.LOADED
                    and runtime is not None and not getattr(runtime, "migration_incomplete", False)):
                # A retained reannouncement must not discard a live Direct lease.
                return self.async_abort(reason="already_configured")
            self.hass.config_entries.async_update_entry(
                canonical, data=self._data, unique_id=device_id,
                title=title,
                version=self.VERSION)
            await self.hass.config_entries.async_reload(canonical.entry_id)
            return self.async_abort(reason="already_configured")
        if not entities and not media_player.get("enabled", False):
            return self.async_abort(reason="no_entities")

        self.context["title_placeholders"] = {"name": self._title}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Ask the user to confirm the discovered Windows PC."""
        if user_input is not None:
            return self.async_create_entry(title=self._title, data=self._data)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._title},
            last_step=True,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Rename a direct endpoint without changing its device/entity identities."""
        entry = self.hass.config_entries.async_get_known_entry(self.context["entry_id"])
        if entry.data.get(CONF_TRANSPORT) != TRANSPORT_DIRECT:
            return self.async_abort(reason="discovery_only")
        if user_input is not None:
            name = str(user_input["name"]).strip()
            if name:
                return self.async_update_reload_and_abort(
                    entry,
                    title=name,
                    data_updates={CONF_DEVICE: {**entry.data[CONF_DEVICE], "name": name}},
                    reason="reconfigure_successful",
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required("name", default=entry.data[CONF_DEVICE]["name"]): vol.All(str, vol.Length(min=1, max=128))}),
            errors={"base": "invalid_name"} if user_input is not None else {},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Create a local direct-overlay endpoint without requiring MQTT."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("name", default="Windows PC"): str,
                        vol.Required(CONF_DEVICE_ID): vol.All(
                            str, vol.Match(r"^[a-z0-9_]{1,128}$")
                        ),
                    }
                ),
            )
        device_id = str(user_input[CONF_DEVICE_ID]).strip()
        name = str(user_input["name"]).strip() or "Windows PC"
        await self.async_set_unique_id(device_id)
        configured = [entry for entry in self.hass.config_entries.async_entries(DOMAIN)
                      if entry.data.get(CONF_DEVICE_ID) == device_id]
        if len(configured) == 1 and configured[0].unique_id == device_id:
            existing = configured[0]
            has_popup = any(item.get("platform") == "notify" and
                            item.get("unique_id") == f"{device_id}_windows_overlay"
                            for item in existing.data.get(CONF_ENTITIES, ()))
            if not existing.data.get("direct_popup_enabled") or not has_popup:
                data = {**existing.data, "direct_popup_enabled": True}
                if not has_popup:
                    data[CONF_ENTITIES] = [*existing.data.get(CONF_ENTITIES, ()),
                                           *canonical_direct_entities(device_id)]
                self.hass.config_entries.async_update_entry(existing, data=data)
                if not has_popup:
                    await self.hass.config_entries.async_reload(existing.entry_id)
            return self.async_abort(reason="already_configured")
        if configured:
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=name,
            data={
                CONF_DEVICE_ID: device_id,
                CONF_TRANSPORT: TRANSPORT_DIRECT,
                CONF_DEVICE: {
                    "name": name,
                    "manufacturer": "HA Windows Bridge",
                    "model": "Direct overlay bridge",
                    "sw_version": "",
                },
                CONF_ENTITIES: canonical_direct_entities(device_id),
                CONF_MEDIA_PLAYER: {"enabled": False},
                "direct_popup_enabled": True,
            },
        )
