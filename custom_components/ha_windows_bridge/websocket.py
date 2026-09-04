"""Device-scoped WebSocket API, without an administrator-only event bus tunnel."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICE_ID, DOMAIN


class BridgeConnectionError(HomeAssistantError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def authorized_runtime(hass, connection, device_id):
    registry = er.async_get(hass)
    entries = [entry for entry in hass.config_entries.async_entries(DOMAIN)
               if entry.data.get(CONF_DEVICE_ID) == device_id]
    pending = False
    missing_popup = False
    # Preserve a separately configured Direct endpoint, but MQTT computers can
    # also use their existing popup. No second config entry is required.
    entries.sort(key=lambda entry: not bool(getattr(getattr(entry, "runtime_data", None), "overlay_event_type", "")))
    for entry in entries:
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None or runtime._closed:
            pending = True
            continue
        if runtime.device_id != device_id or not runtime.overlay_unique_id:
            pending = True
            continue
        entity_id = registry.async_get_entity_id("notify", DOMAIN, runtime.overlay_unique_id)
        entity = registry.async_get(entity_id) if entity_id else None
        if entity is None:
            pending = True
            continue
        if entity.config_entry_id != entry.entry_id or entity.disabled_by is not None:
            missing_popup = True
            continue
        if not connection.user.permissions.check_entity(entity_id, POLICY_CONTROL):
            raise Unauthorized()
        return runtime
    raise BridgeConnectionError("bridge_not_ready" if pending else "popup_unavailable" if missing_popup else "bridge_not_configured")


@callback
@websocket_api.websocket_command({vol.Required("type"): "ha_windows_bridge/connect",
                                  vol.Required("device_id"): vol.All(str, vol.Length(min=1, max=128))})
def connect(hass, connection, msg):
    try:
        runtime = authorized_runtime(hass, connection, msg["device_id"])
    except BridgeConnectionError as exc:
        connection.send_error(msg["id"], exc.code, str(exc))
        return
    if runtime.owner is not None:
        connection.send_error(msg["id"], "bridge_busy", "Another Windows Bridge is already connected")
        return
    runtime.attach(connection, lambda command: connection.send_event(msg["id"], command))
    connection.subscriptions[msg["id"]] = lambda: runtime.detach(connection)
    connection.send_result(msg["id"], {"protocol": 2})


@callback
@websocket_api.websocket_command({vol.Required("type"): "ha_windows_bridge/heartbeat",
                                  vol.Required("device_id"): vol.All(str, vol.Length(min=1, max=128))})
def heartbeat(hass, connection, msg):
    runtime = authorized_runtime(hass, connection, msg["device_id"])
    if runtime.owner is not connection:
        raise Unauthorized()
    runtime.heartbeat()
    connection.send_result(msg["id"])


@callback
@websocket_api.websocket_command({vol.Required("type"): "ha_windows_bridge/result",
                                  vol.Required("device_id"): vol.All(str, vol.Length(min=1, max=128)),
                                  vol.Required("result"): {
                                      vol.Required("version"): 2,
                                      vol.Required("id"): vol.All(str, vol.Length(min=1, max=128)),
                                      vol.Required("status"): vol.In({"succeeded", "failed", "rejected", "cancelled"}),
                                      vol.Optional("error", default=None): vol.Any(None, vol.All(str, vol.Length(max=64))),
                                      vol.Optional("data", default={}): vol.Schema({}, extra=vol.REMOVE_EXTRA),
                                  }})
def result(hass, connection, msg):
    runtime = authorized_runtime(hass, connection, msg["device_id"])
    if runtime.owner is not connection:
        raise Unauthorized()
    # Only IDs belonging to this connection's device can complete its commands.
    runtime._result(msg["result"])
    connection.send_result(msg["id"])


@callback
def async_register_commands(hass):
    for handler in (connect, heartbeat, result):
        websocket_api.async_register_command(hass, handler)
