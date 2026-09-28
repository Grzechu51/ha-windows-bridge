"""Allowlisted diagnostics: never export topics, identities or sensor contents."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTITIES, CONF_MEDIA_PLAYER, CONF_TRANSPORT


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return only structural information safe to attach to an issue."""
    counts = Counter(
        definition["platform"]
        for definition in entry.data.get(CONF_ENTITIES, [])
        if isinstance(definition, dict) and definition.get("platform") in {
            "sensor", "binary_sensor", "button", "number", "switch", "select", "notify", "media_player"
        }
    )
    runtime = getattr(entry, "runtime_data", None)
    protocol = entry.data.get("protocol", {})
    protocol_version = protocol.get("version") if isinstance(protocol, dict) else None
    capabilities = getattr(runtime, "capabilities", None)
    capability_items = getattr(capabilities, "capabilities", ()) if capabilities else ()
    return {
        "entry_version": entry.version,
        "entry_state": entry.state.value,
        "transport": "direct" if entry.data.get(CONF_TRANSPORT) == "direct" else "mqtt",
        "entity_counts": dict(counts),
        "media_player_enabled": bool(entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled")),
        "runtime_loaded": runtime is not None,
        "protocol_version": protocol_version if protocol_version in {2, 3} else None,
        "direct_endpoint_configured": bool(
            entry.data.get("direct_popup_enabled")
            or entry.data.get(CONF_TRANSPORT) == "direct"
        ),
        "direct_connection_active": bool(
            runtime and getattr(runtime, "owner", None) is not None
            and getattr(runtime, "available", False)
        ),
        "capability_count": len(capability_items),
        "snapshot_available": bool(runtime and getattr(runtime, "snapshot", None)),
        "pending_commands": len(runtime.pending) if runtime else 0,
        "lifecycle_event_count": len(runtime.notification_lifecycle) if runtime else 0,
        "migration_pending": "migration_journal" in entry.data,
        "migration_incomplete": bool(runtime and getattr(runtime, "migration_incomplete", False)),
    }
