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
    return {
        "entry_version": entry.version,
        "entry_state": entry.state.value,
        "transport": "direct" if entry.data.get(CONF_TRANSPORT) == "direct" else "mqtt",
        "entity_counts": dict(counts),
        "media_player_enabled": bool(entry.data.get(CONF_MEDIA_PLAYER, {}).get("enabled")),
        "runtime_loaded": getattr(entry, "runtime_data", None) is not None,
        "direct_delivery_acknowledged": True,
        "pending_commands": len(entry.runtime_data.pending) if getattr(entry, "runtime_data", None) else 0,
    }
