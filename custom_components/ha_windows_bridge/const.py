from __future__ import annotations

DOMAIN = "ha_windows_bridge"

CONF_DEVICE_ID = "device_id"
CONF_DEVICE = "device"
CONF_ENTITIES = "entities"
CONF_MEDIA_PLAYER = "media_player"
CONF_TRANSPORT = "transport"

TRANSPORT_MQTT = "mqtt"
TRANSPORT_DIRECT = "direct"


def direct_overlay_event(device_id: str) -> str:
    return f"ha_windows_bridge_overlay_{device_id}"


def direct_template_catalog_event(device_id: str) -> str:
    return f"ha_windows_bridge_templates_{device_id}"


def direct_template_command_event(device_id: str) -> str:
    return f"ha_windows_bridge_template_command_{device_id}"


def template_dispatcher_signal(entry_id: str) -> str:
    return f"ha_windows_bridge_template_catalog_{entry_id}"

SERVICE_SHOW_OVERLAY = "show_overlay"
SERVICE_SHOW_SAVED_OVERLAY = "show_saved_overlay"
SERVICE_UPDATE_OVERLAY = "update_overlay"
SERVICE_REMOVE_OVERLAY = "remove_overlay"
SERVICE_CLEAR_OVERLAY = "clear_overlay"
