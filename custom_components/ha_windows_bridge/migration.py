"""Replayable consolidation of legacy Direct entries into one bridge identity."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICE_ID, CONF_ENTITIES, CONF_TRANSPORT, DOMAIN, TRANSPORT_DIRECT

_LOGGER = logging.getLogger(__name__)
_JOURNAL = "migration_journal"


def canonical_popup_uid(device_id: str) -> str:
    return f"{device_id}_windows_overlay"


def legacy_popup_uid(device_id: str) -> str:
    return f"{device_id}_overlay"


def canonical_direct_entities(device_id: str) -> list[dict[str, str]]:
    return [{"platform": "notify", "unique_id": canonical_popup_uid(device_id),
             "name": "Overlay", "command_topic": f"direct://{device_id}/overlay"}]


def legacy_sources(hass, canonical: ConfigEntry) -> list[ConfigEntry]:
    return [entry for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != canonical.entry_id
            and entry.data.get(CONF_DEVICE_ID) == canonical.data[CONF_DEVICE_ID]
            and entry.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT]


def direct_in_place_journal(hass, entry: ConfigEntry) -> dict[str, Any]:
    """Record the exact old popup before replacing its definition."""
    uid = legacy_popup_uid(str(entry.data[CONF_DEVICE_ID]))
    registry = er.async_get(hass)
    old_id = registry.async_get_entity_id("notify", DOMAIN, uid)
    return {"mode": "direct_in_place", "old_popup_uid": uid,
            "old_entity_id": old_id}


def _source_journal(hass, canonical: ConfigEntry, source: ConfigEntry) -> dict[str, Any]:
    """Preflight one known Direct popup/device; never guess what to delete."""
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    old_uid = legacy_popup_uid(str(canonical.data[CONF_DEVICE_ID]))
    source_entities = er.async_entries_for_config_entry(registry, source.entry_id)
    if any(item.domain != "notify" or item.platform != DOMAIN
           or item.unique_id != old_uid for item in source_entities):
        raise ConfigEntryNotReady("Unexpected Direct entities require manual review")
    source_devices = dr.async_entries_for_config_entry(devices, source.entry_id)
    if len(source_devices) > 1:
        raise ConfigEntryNotReady("Multiple Direct devices require manual review")
    return {"mode": "remove_source", "source_entry_id": source.entry_id,
            "source_entity_ids": [item.entity_id for item in source_entities],
            "source_device_ids": [item.id for item in source_devices]}


async def async_prepare_migration(hass, canonical: ConfigEntry) -> None:
    """Persist a cleanup plan without touching old working records."""
    sources = legacy_sources(hass, canonical)
    journal = canonical.data.get(_JOURNAL)
    if len(sources) > 1 or (journal and journal["mode"] == "remove_source"
                            and sources and sources[0].entry_id != journal["source_entry_id"]):
        raise ConfigEntryNotReady("Multiple Direct endpoints require manual review")
    if journal and journal["mode"] == "direct_in_place":
        registry = er.async_get(hass)
        old = registry.async_get(journal["old_entity_id"]) if journal["old_entity_id"] else None
        if old and old.disabled_by is not None and registry.async_get_entity_id(
            "notify", DOMAIN, canonical_popup_uid(str(canonical.data[CONF_DEVICE_ID]))
        ) is None:
            registry.async_get_or_create(
                "notify", DOMAIN, canonical_popup_uid(str(canonical.data[CONF_DEVICE_ID])),
                config_entry=canonical, device_id=old.device_id,
                disabled_by=old.disabled_by)
    if journal or not sources or canonical.data.get(CONF_TRANSPORT) == TRANSPORT_DIRECT:
        return
    journal = _source_journal(hass, canonical, sources[0])
    data = {**canonical.data, _JOURNAL: journal,
            "direct_popup_enabled": True}
    if not any(item.get("platform") == "notify" and
               item.get("unique_id") == canonical_popup_uid(str(data[CONF_DEVICE_ID]))
               for item in data.get(CONF_ENTITIES, ())):
        data[CONF_ENTITIES] = [*data.get(CONF_ENTITIES, ()),
                               *canonical_direct_entities(str(data[CONF_DEVICE_ID]))]
    hass.config_entries.async_update_entry(canonical, data=data)


def _verify_canonical(hass, entry: ConfigEntry) -> tuple[dr.DeviceEntry, er.RegistryEntry]:
    """Require the new popup and ordinary device before legacy cleanup."""
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    identifier = (DOMAIN, str(entry.data[CONF_DEVICE_ID]))
    if len(devices) != 1 or identifier not in devices[0].identifiers:
        raise ConfigEntryNotReady("Canonical Windows Bridge device is not ready")
    registry = er.async_get(hass)
    popup_id = registry.async_get_entity_id(
        "notify", DOMAIN, canonical_popup_uid(str(entry.data[CONF_DEVICE_ID])))
    popup = registry.async_get(popup_id) if popup_id else None
    if popup is None or popup.config_entry_id != entry.entry_id or popup.device_id != devices[0].id:
        raise ConfigEntryNotReady("Canonical Windows Bridge popup is not ready")
    if popup.disabled_by is None and hass.states.get(popup.entity_id) is None:
        raise ConfigEntryNotReady("Canonical Windows Bridge popup is not live")
    return devices[0], popup


def _fill_missing_user_settings(hass, target_device, target_popup, old_device, old_popup):
    """Canonical MQTT choices win; carry only unset user preferences."""
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    if old_device:
        changes = {}
        for field in ("name_by_user", "area_id"):
            if getattr(target_device, field) is None and getattr(old_device, field) is not None:
                changes[field] = getattr(old_device, field)
        if not target_device.labels and old_device.labels:
            changes["labels"] = old_device.labels
        if changes:
            devices.async_update_device(target_device.id, **changes)
    if old_popup:
        changes = {}
        for field in ("name", "area_id"):
            if getattr(target_popup, field) is None and getattr(old_popup, field) is not None:
                changes[field] = getattr(old_popup, field)
        if not target_popup.labels and old_popup.labels:
            changes["labels"] = old_popup.labels
        if changes:
            registry.async_update_entity(target_popup.entity_id, **changes)


def _validate_source_records(hass, journal: dict[str, Any]) -> None:
    """Recheck ownership and the exact deletion set after every await."""
    source_id = journal["source_entry_id"]
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    if (set(journal["source_entity_ids"]) !=
            {item.entity_id for item in er.async_entries_for_config_entry(registry, source_id)}
            or set(journal["source_device_ids"]) !=
            {item.id for item in dr.async_entries_for_config_entry(devices, source_id)}):
        raise ConfigEntryNotReady("Legacy Direct registry records changed")


def _remove_owned_orphans(hass, journal: dict[str, Any]) -> None:
    """Finish an interrupted HA removal using only journaled, still-owned IDs."""
    source_id = journal["source_entry_id"]
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    for entity_id in journal["source_entity_ids"]:
        item = registry.async_get(entity_id)
        if item:
            if item.config_entry_id != source_id:
                raise ConfigEntryNotReady("Legacy popup changed ownership after source removal")
            registry.async_remove(entity_id)
    for device_id in journal["source_device_ids"]:
        item = devices.async_get(device_id)
        if item:
            if item.config_entry_id != source_id or er.async_entries_for_device(
                registry, device_id, include_disabled_entities=True
            ):
                raise ConfigEntryNotReady("Legacy device changed after source removal")
            devices.async_remove_device(device_id)


async def async_finish_migration(hass, canonical: ConfigEntry) -> None:
    """Delete exact old records only after canonical setup and registry readiness."""
    journal = canonical.data.get(_JOURNAL)
    if not journal:
        return
    target_device, target_popup = _verify_canonical(hass, canonical)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    if journal["mode"] == "direct_in_place":
        old_id = journal["old_entity_id"]
        old_popup = registry.async_get(old_id) if old_id else None
        if old_popup:
            if (old_popup.config_entry_id != canonical.entry_id
                    or old_popup.unique_id != journal["old_popup_uid"]):
                raise ConfigEntryNotReady("Legacy popup changed ownership during migration")
            _fill_missing_user_settings(hass, target_device, target_popup, None, old_popup)
            registry.async_remove(old_id)
    elif journal["mode"] == "remove_source":
        source_id = journal["source_entry_id"]
        source = hass.config_entries.async_get_entry(source_id)
        old_popups = [registry.async_get(item) for item in journal["source_entity_ids"]]
        old_devices = [devices.async_get(item) for item in journal["source_device_ids"]]
        if source:
            if source.data.get(CONF_DEVICE_ID) != canonical.data[CONF_DEVICE_ID]:
                raise ConfigEntryNotReady("Legacy Direct source changed identity")
            if any(item and item.config_entry_id != source_id for item in old_popups + old_devices):
                raise ConfigEntryNotReady("Legacy Direct registry ownership changed")
            _validate_source_records(hass, journal)
            _fill_missing_user_settings(
                hass, target_device, target_popup,
                old_devices[0] if old_devices else None,
                old_popups[0] if old_popups else None)
            if (source.state is ConfigEntryState.LOADED
                    and not await hass.config_entries.async_unload(source_id)):
                raise ConfigEntryNotReady("Legacy Direct endpoint could not be unloaded")
            _validate_source_records(hass, journal)
            result = await hass.config_entries.async_remove(source_id)
            if result.get("require_restart"):
                raise ConfigEntryNotReady("Legacy Direct endpoint removal was incomplete")
        _remove_owned_orphans(hass, journal)
        if any(registry.async_get(item) for item in journal["source_entity_ids"]):
            raise ConfigEntryNotReady("Legacy Direct popup cleanup was incomplete")
        if any(devices.async_get(item) for item in journal["source_device_ids"]):
            raise ConfigEntryNotReady("Legacy Direct device cleanup was incomplete")
    else:
        raise ConfigEntryNotReady("Unknown Windows Bridge migration plan")
    data = dict(canonical.data)
    data.pop(_JOURNAL, None)
    hass.config_entries.async_update_entry(canonical, data=data)
    _LOGGER.info("Completed Windows Bridge identity consolidation")
