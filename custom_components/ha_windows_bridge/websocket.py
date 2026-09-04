"""Device-scoped WebSocket API, without an administrator-only event bus tunnel."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components import websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


def authorized_runtime(hass, connection, device_id):
    registry = er.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None or runtime.device_id != device_id or not runtime.overlay_event_type:
            continue
        entity_id = registry.async_get_entity_id("notify", DOMAIN, runtime.overlay_unique_id)
        if not entity_id or not connection.user.permissions.check_entity(entity_id, POLICY_CONTROL):
            raise Unauthorized()
        return runtime
    raise HomeAssistantError("Configure this Direct Windows Bridge in Home Assistant first")


@callback
@websocket_api.websocket_command({vol.Required("type"): "ha_windows_bridge/connect",
                                  vol.Required("device_id"): vol.All(str, vol.Length(min=1, max=128))})
def connect(hass, connection, msg):
    runtime = authorized_runtime(hass, connection, msg["device_id"])
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
