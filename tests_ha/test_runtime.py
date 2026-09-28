"""Audit H02/H05: full import, discovery, real entity setup/reload/unload."""
from __future__ import annotations

import importlib
import json
import re
import shutil
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from homeassistant import bootstrap, loader
from homeassistant.components import mqtt
from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import (
    SOURCE_MQTT,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryDisabler,
    ConfigEntryState,
)
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform, translation
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
from probatio.error import MultipleInvalid

DOMAIN = "ha_windows_bridge"
ROOT = Path(__file__).parent


async def quality_direct_entry(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Quality PC", "device_id": "quality_pc"})
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    popup = er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "quality_pc_windows_overlay")
    assert popup
    return entry, popup


class MqttBoundary:
    def __init__(self):
        self.acquired = {}
        self.removed = set()
        self.sequence = 0
        self.fail_topic = None
        self.failed_owner = None

    def acquire(self, topic, callback):
        token = self.sequence
        self.sequence += 1
        self.acquired[token] = (topic, callback)
        def unsubscribe():
            assert token not in self.removed, "Subscription removed twice"
            self.removed.add(token)
        return unsubscribe

    async def subscribe(self, hass, topic, callback, **kwargs):
        if topic == self.fail_topic:
            self.failed_owner = callback.__self__
            raise OSError("injected subscribe failure")
        return self.acquire(topic, callback)

    def connection(self, hass, callback):
        return self.acquire("connection", callback)

    def emit(self, topic, payload):
        for token, (subscribed, callback) in tuple(self.acquired.items()):
            if subscribed == topic and token not in self.removed:
                callback(ReceiveMessage(topic, payload, 1, True, topic, 0.0))


@pytest.fixture
def wire(monkeypatch):
    boundary = MqttBoundary()
    monkeypatch.setattr(mqtt, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt, "is_connected", lambda hass: True)
    monkeypatch.setattr(mqtt, "async_subscribe", boundary.subscribe)
    monkeypatch.setattr(mqtt, "async_subscribe_connection_status", boundary.connection)
    return boundary


def announcement():
    return json.loads((ROOT / "fixtures/announcement-v2.json").read_text())


def mqtt_info(payload):
    return MqttServiceInfo("ha-windows-bridge/devices/phase0_pc", json.dumps(payload),
                           1, True, "ha-windows-bridge/devices/+", 0.0)


def test_all_modules_import_against_installed_ha():
    for path in (ROOT.parent / "custom_components" / DOMAIN).glob("*.py"):
        name = DOMAIN if path.stem == "__init__" else DOMAIN + "." + path.stem
        importlib.import_module("custom_components." + name)


async def test_mqtt_discovery_all_platforms_reload_and_unload(hass, wire):
    payload = announcement()
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    assert flow["type"] == "form" and flow["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["type"] == "create_entry"
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    registry = er.async_get(hass)
    assert {item["platform"] for item in payload["entities"]} == {
        "binary_sensor", "button", "media_player", "notify", "number", "select", "sensor", "switch"}
    for definition in payload["entities"]:
        entity_id = registry.async_get_entity_id(definition["platform"], DOMAIN, definition["unique_id"])
        assert entity_id is not None, definition
        assert hass.states.get(entity_id) is not None, definition
    active_id = registry.async_get_entity_id("media_player", DOMAIN, "phase0_pc_media_player")
    assert active_id is not None and hass.states.get(active_id) is not None
    app = next(item for item in payload["entities"] if item["platform"] == "media_player")
    wire.emit(app["availability_topic"], "online")
    wire.emit(app["state_topic"], "ON")
    wire.emit(app["volume_state_topic"], "80")
    wire.emit(app["mute_state_topic"], "ON")
    entity_id = registry.async_get_entity_id("media_player", DOMAIN, app["unique_id"])
    state = hass.states.get(entity_id)
    assert state.state == "idle"
    assert state.attributes["volume_level"] == .8
    assert state.attributes["is_volume_muted"] is True
    before_reload = set(wire.acquired)
    old_runtime = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert old_runtime._closed and before_reload <= wire.removed
    assert entry.state == ConfigEntryState.LOADED
    assert registry.async_get_entity_id("media_player", DOMAIN, app["unique_id"]) == entity_id
    current_runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert set(wire.acquired) == wire.removed
    assert current_runtime._closed and not current_runtime.pending


@pytest.mark.parametrize("active_player", [False, True])
async def test_partial_subscribe_failure_uses_real_ha_cleanup(hass, wire, active_player):
    from custom_components.ha_windows_bridge.announcement import parse_discovery_announcement
    payload = announcement()
    app = next(item for item in payload["entities"] if item["platform"] == "media_player")
    payload["entities"] = [] if active_player else [app]
    payload["media_player"]["enabled"] = active_player
    wire.fail_topic = payload["media_player"]["thumbnail_topic"] if active_player else app["mute_state_topic"]
    entry = ConfigEntry(domain=DOMAIN, title="Phase 0", version=1, minor_version=1,
                        source=SOURCE_MQTT, unique_id="phase0_pc", options={}, discovery_keys=MappingProxyType({}),
                        subentries_data=None, data=parse_discovery_announcement(json.dumps(payload)))
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    assert wire.failed_owner is not None
    partial_tokens = {token for token, (_, callback) in wire.acquired.items()
                      if getattr(callback, "__self__", None) is wire.failed_owner}
    assert partial_tokens and partial_tokens <= wire.removed
    assert wire.failed_owner not in hass.data[DATA_COMPONENT].entities
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert set(wire.acquired) == wire.removed


async def test_direct_config_flow_and_setup_without_mqtt(hass, wire):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert flow["type"] == "form" and flow["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"name": "Direct PC", "device_id": "direct_pc"})
    assert result["type"] == "create_entry"
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    assert not wire.acquired
    entity_id = er.async_get(hass).async_get_entity_id("notify", DOMAIN, "direct_pc_windows_overlay")
    assert entity_id and hass.states.get(entity_id) is not None
    current_runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert current_runtime._closed



async def test_repeated_reload_releases_old_platform_references(hass, wire):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Direct PC", "device_id": "direct_pc"})
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED

    def owned_platforms():
        return [platform for platform in entity_platform.async_get_platforms(hass, DOMAIN)
                if platform.config_entry is entry]

    for _ in range(3):
        old = owned_platforms()
        assert len(old) == 8
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state == ConfigEntryState.LOADED
        current = owned_platforms()
        assert len(current) == len(old)
        assert not any(platform in current for platform in old)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not owned_platforms()


async def test_capability_disappearance_and_return_preserves_entity_registry(hass, wire):
    payload = announcement()
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED

    definition = next(item for item in payload["entities"] if item["platform"] == "switch")
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, definition["unique_id"])
    assert entity_id is not None
    registry.async_update_entity(entity_id, name="My custom switch")

    original_entities = entry.data["entities"]
    without_switch = dict(entry.data)
    without_switch["entities"] = [
        item for item in entry.data["entities"]
        if item["unique_id"] != definition["unique_id"]
    ]
    hass.config_entries.async_update_entry(entry, data=without_switch)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("switch", DOMAIN, definition["unique_id"]) == entity_id
    assert registry.async_get(entity_id).name == "My custom switch"
    disappeared_state = hass.states.get(entity_id)
    assert disappeared_state is None or disappeared_state.state == "unavailable"

    restored = dict(entry.data)
    restored["entities"] = original_entities
    hass.config_entries.async_update_entry(entry, data=restored)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("switch", DOMAIN, definition["unique_id"]) == entity_id
    assert registry.async_get(entity_id).name == "My custom switch"
    assert hass.states.get(entity_id) is not None


async def test_registry_disabled_entity_is_not_a_setup_failure(hass, wire):
    payload = announcement()
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED

    definition = next(item for item in payload["entities"] if item["platform"] == "switch")
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, definition["unique_id"])
    registry.async_update_entity(entity_id, disabled_by=RegistryEntryDisabler.USER)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    assert registry.async_get(entity_id).disabled_by is RegistryEntryDisabler.USER


async def test_forward_failure_after_notify_loaded_rolls_back(hass, wire, monkeypatch):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER})
    original_forward = hass.config_entries.async_forward_entry_setups
    loaded = []

    async def fail_after_first(manager, entry, platforms):
        await original_forward(entry, [Platform.NOTIFY])
        entity_id = er.async_get(hass).async_get_entity_id(
            "notify", DOMAIN, "direct_pc_windows_overlay")
        loaded.append(entity_id)
        raise OSError("injected failure after notify setup")

    monkeypatch.setattr(
        type(hass.config_entries), "async_forward_entry_setups", fail_after_first)
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Direct PC", "device_id": "direct_pc"})
    entry = result["result"]
    await hass.async_block_till_done()
    assert loaded and loaded[0] is not None
    assert entry.runtime_data is None
    state = hass.states.get(loaded[0])
    assert state is None or state.state == "unavailable"



async def test_swallowed_platform_setup_failure_destroys_failed_platform(hass, wire, monkeypatch):
    from homeassistant import loader

    integration = await loader.async_get_integration(hass, DOMAIN)
    switch_platform = await integration.async_get_platform(Platform.SWITCH)

    async def fail_switch_setup(*_args):
        raise OSError("injected switch platform failure")

    original_setup = switch_platform.async_setup_entry
    monkeypatch.setattr(switch_platform, "async_setup_entry", fail_switch_setup)
    payload = announcement()
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()

    assert entry.state != ConfigEntryState.LOADED
    assert entry.runtime_data is None
    assert set(wire.acquired) == wire.removed
    assert not [platform for platform in entity_platform.async_get_platforms(hass, DOMAIN)
                if platform.config_entry is entry]

    monkeypatch.setattr(switch_platform, "async_setup_entry", original_setup)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert set(wire.acquired) == wire.removed


async def test_swallowed_entity_subscription_failure_rolls_back_all_platforms(hass, wire):
    payload = announcement()
    switch = next(item for item in payload["entities"] if item["platform"] == "switch")
    wire.fail_topic = switch["state_topic"]
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()

    assert wire.failed_owner is not None
    assert entry.state != ConfigEntryState.LOADED
    assert entry.runtime_data is None
    assert set(wire.acquired) == wire.removed
    for definition in payload["entities"]:
        entity_id = er.async_get(hass).async_get_entity_id(
            definition["platform"], DOMAIN, definition["unique_id"])
        if entity_id:
            state = hass.states.get(entity_id)
            assert state is None or state.state == "unavailable"

    wire.fail_topic = None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    switch_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, switch["unique_id"])
    assert switch_id and hass.states.get(switch_id) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert set(wire.acquired) == wire.removed



def legacy_direct_data(device_id):
    return {
        "device_id": device_id,
        "transport": "direct",
        "device": {"name": "Legacy Direct PC", "manufacturer": "HA Windows Bridge",
                   "model": "Direct overlay bridge", "sw_version": ""},
        "entities": [{"platform": "notify", "unique_id": f"{device_id}_overlay",
                      "name": "Overlay", "command_topic": f"direct://{device_id}/overlay"}],
        "media_player": {"enabled": False},
    }


async def test_direct_only_discovery_keeps_one_entry_device_and_popup(hass, wire):
    device_id = "phase0_pc"
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "My Direct PC", "device_id": device_id})
    entry = result["result"]
    await hass.async_block_till_done()
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0]
    assert entry.unique_id == device_id
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, f"{device_id}_windows_overlay") is not None

    discovery = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    await hass.async_block_till_done()
    assert discovery["type"] == "abort"
    assert entry.title == "My Direct PC"
    assert entry.unique_id == device_id
    assert [item for item in hass.config_entries.async_entries(DOMAIN)
            if item.data.get("device_id") == device_id] == [entry]
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1 and devices[0].id == old_device.id
    assert (DOMAIN, device_id) in devices[0].identifiers
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("notify", DOMAIN, f"{device_id}_overlay") is None
    popup_id = registry.async_get_entity_id("notify", DOMAIN, f"{device_id}_windows_overlay")
    assert popup_id and registry.async_get(popup_id).config_entry_id == entry.entry_id


async def test_existing_pair_retires_legacy_records_after_canonical_ready(hass, wire):
    device_id = "phase0_pc"
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    canonical = result["result"]
    await hass.async_block_till_done()
    primary = dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)[0]

    source = ConfigEntry(
        domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id=f"{device_id}_direct", options={},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data(device_id))
    await hass.config_entries.async_add(source)
    await hass.async_block_till_done()
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), source.entry_id)[0]
    assert old_device.id != primary.id
    registry = er.async_get(hass)
    old_popup = registry.async_get_entity_id("notify", DOMAIN, f"{device_id}_overlay")
    registry.async_update_entity(old_popup, name="My legacy popup")
    dr.async_get(hass).async_update_device(old_device.id, name_by_user="My legacy device")

    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)
    assert len(devices) == 1 and devices[0].id == primary.id
    assert devices[0].name_by_user == "My legacy device"
    assert dr.async_get(hass).async_get(old_device.id) is None
    assert registry.async_get(old_popup) is None
    popup_id = registry.async_get_entity_id("notify", DOMAIN, f"{device_id}_windows_overlay")
    assert popup_id and registry.async_get(popup_id).config_entry_id == canonical.entry_id
    assert registry.async_get(popup_id).name == "My legacy popup"
    assert "migration_journal" not in canonical.data


async def test_legacy_direct_v1_migrates_to_canonical_popup(hass, wire):
    device_id = "phase0_pc"
    old = ConfigEntry(
        domain=DOMAIN, title="My Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id=f"{device_id}_direct", options={"keep": True},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data(device_id))
    await hass.config_entries.async_add(old)
    await hass.async_block_till_done()
    assert old.state == ConfigEntryState.LOADED
    assert old.version == 2 and old.unique_id == device_id
    assert old.title == "My Direct PC" and old.options == {"keep": True}
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), old.entry_id)) == 1
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("notify", DOMAIN, f"{device_id}_overlay") is None
    assert registry.async_get_entity_id(
        "notify", DOMAIN, f"{device_id}_windows_overlay") is not None
    assert "migration_journal" not in old.data


async def test_direct_flow_refuses_existing_mqtt_owner(hass, wire):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    await hass.async_block_till_done()
    direct_flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        direct_flow["flow_id"], {"name": "Duplicate", "device_id": "phase0_pc"})
    assert result["type"] == "abort"
    assert len([entry for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.data.get("device_id") == "phase0_pc"]) == 1


async def test_failed_canonical_setup_keeps_legacy_source_until_retry(hass, wire, monkeypatch):
    from homeassistant import loader

    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    source = ConfigEntry(
        domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id="phase0_pc_direct", options={},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data("phase0_pc"))
    await hass.config_entries.async_add(source)
    await hass.async_block_till_done()
    old_id = er.async_get(hass).async_get_entity_id("notify", DOMAIN, "phase0_pc_overlay")
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), source.entry_id)[0]

    integration = await loader.async_get_integration(hass, DOMAIN)
    switch_platform = await integration.async_get_platform(Platform.SWITCH)
    original_setup = switch_platform.async_setup_entry

    async def fail_setup(*_args):
        raise OSError("injected canonical setup failure")

    monkeypatch.setattr(switch_platform, "async_setup_entry", fail_setup)
    assert not await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state != ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(source.entry_id) is source
    assert source.state == ConfigEntryState.LOADED
    assert er.async_get(hass).async_get(old_id) is not None
    assert dr.async_get(hass).async_get(old_device.id) is not None
    assert "migration_journal" in canonical.data

    monkeypatch.setattr(switch_platform, "async_setup_entry", original_setup)
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert er.async_get(hass).async_get(old_id) is None
    assert dr.async_get(hass).async_get(old_device.id) is None
    assert "migration_journal" not in canonical.data


async def test_cleanup_failure_after_source_removal_replays_without_orphans(hass, wire, monkeypatch):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    source = ConfigEntry(
        domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id="phase0_pc_direct", options={},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data("phase0_pc"))
    await hass.config_entries.async_add(source)
    await hass.async_block_till_done()
    old_id = er.async_get(hass).async_get_entity_id("notify", DOMAIN, "phase0_pc_overlay")
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), source.entry_id)[0]
    original_update = type(hass.config_entries).async_update_entry

    def fail_journal_clear(manager, entry, **kwargs):
        data = kwargs.get("data")
        if entry is canonical and data is not None and (
            "migration_journal" in entry.data and "migration_journal" not in data
        ):
            raise OSError("injected journal-clear failure")
        return original_update(manager, entry, **kwargs)

    monkeypatch.setattr(type(hass.config_entries), "async_update_entry", fail_journal_clear)
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert canonical.runtime_data.migration_incomplete
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert er.async_get(hass).async_get(old_id) is None
    assert dr.async_get(hass).async_get(old_device.id) is None
    assert "migration_journal" in canonical.data

    monkeypatch.setattr(type(hass.config_entries), "async_update_entry", original_update)
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert "migration_journal" not in canonical.data
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)
    assert len(devices) == 1
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay") is not None


async def test_disabled_direct_entry_stays_disabled_during_discovery(hass, wire):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Disabled Direct", "device_id": "phase0_pc"}))["result"]
    await hass.async_block_till_done()
    assert await hass.config_entries.async_set_disabled_by(
        entry.entry_id, ConfigEntryDisabler.USER)
    discovery = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    assert discovery["type"] == "abort"
    assert entry.disabled_by is ConfigEntryDisabler.USER
    assert len([item for item in hass.config_entries.async_entries(DOMAIN)
                if item.data.get("device_id") == "phase0_pc"]) == 1


@pytest.mark.parametrize("schema", [1, 2])
async def test_legacy_announcement_without_popup_keeps_one_direct_fallback(hass, wire, schema):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Direct PC", "device_id": "phase0_pc"}))["result"]
    await hass.async_block_till_done()
    payload = announcement()
    payload["schema"] = schema
    payload["entities"] = [item for item in payload["entities"]
                           if item.get("unique_id") != "phase0_pc_windows_overlay"]
    discovery = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    await hass.async_block_till_done()
    assert discovery["type"] == "abort"
    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data.overlay_event_type
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 1
    popup = er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay")
    assert popup and er.async_get(hass).async_get(popup).config_entry_id == entry.entry_id
    assert er.async_get(hass).async_get_entity_id("notify", DOMAIN, "phase0_pc_overlay") is None
    assert sum(item.get("unique_id") == "phase0_pc_windows_overlay"
               for item in entry.data["entities"]) == 1


async def test_existing_pair_without_mqtt_popup_gets_one_direct_fallback(hass, wire):
    payload = announcement()
    payload["entities"] = [item for item in payload["entities"]
                           if item.get("unique_id") != "phase0_pc_windows_overlay"]
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay") is None
    source = ConfigEntry(
        domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id="phase0_pc_direct", options={},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data("phase0_pc"))
    await hass.config_entries.async_add(source)
    await hass.async_block_till_done()
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), source.entry_id)[0]
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert canonical.runtime_data.overlay_event_type
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert dr.async_get(hass).async_get(old_device.id) is None
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)) == 1
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("notify", DOMAIN, "phase0_pc_overlay") is None
    popup_id = registry.async_get_entity_id("notify", DOMAIN, "phase0_pc_windows_overlay")
    assert popup_id and registry.async_get(popup_id).config_entry_id == canonical.entry_id


async def test_direct_popup_intent_survives_present_absent_present_discovery(hass, wire):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Direct PC", "device_id": "phase0_pc"}))["result"]
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    popup_id = registry.async_get_entity_id("notify", DOMAIN, "phase0_pc_windows_overlay")
    assert popup_id

    for has_mqtt_popup in (True, False, True):
        payload = announcement()
        if not has_mqtt_popup:
            payload["entities"] = [item for item in payload["entities"]
                                   if item.get("unique_id") != "phase0_pc_windows_overlay"]
        discovery = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
        await hass.async_block_till_done()
        assert discovery["type"] == "abort"
        assert entry.state == ConfigEntryState.LOADED
        assert entry.data["direct_popup_enabled"]
        assert registry.async_get_entity_id(
            "notify", DOMAIN, "phase0_pc_windows_overlay") == popup_id
        assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 1
        assert len([item for item in entry.data["entities"]
                    if item.get("unique_id") == "phase0_pc_windows_overlay"]) == 1
        assert bool(entry.runtime_data.overlay_event_type) is (not has_mqtt_popup)


async def test_journal_replays_orphan_registry_cleanup_after_source_disappears(
    hass, wire, monkeypatch,
):
    from custom_components.ha_windows_bridge import migration

    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    source = ConfigEntry(
        domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id="phase0_pc_direct", options={},
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data("phase0_pc"))
    await hass.config_entries.async_add(source)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    old_popup = registry.async_get_entity_id("notify", DOMAIN, "phase0_pc_overlay")
    old_device = dr.async_entries_for_config_entry(dr.async_get(hass), source.entry_id)[0]
    original_cleanup = type(hass.config_entries)._async_clean_up
    original_orphans = migration._remove_owned_orphans

    def leave_registry_records(manager, removed):
        if removed is not source:
            original_cleanup(manager, removed)

    def fail_orphan_cleanup(*_args):
        raise OSError("injected interrupted registry cleanup")

    monkeypatch.setattr(type(hass.config_entries), "_async_clean_up", leave_registry_records)
    monkeypatch.setattr(migration, "_remove_owned_orphans", fail_orphan_cleanup)
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(source.entry_id) is None
    assert registry.async_get(old_popup) is not None
    assert dr.async_get(hass).async_get(old_device.id) is not None
    assert "migration_journal" in canonical.data

    monkeypatch.setattr(migration, "_remove_owned_orphans", original_orphans)
    monkeypatch.setattr(type(hass.config_entries), "_async_clean_up", original_cleanup)
    assert await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state == ConfigEntryState.LOADED
    assert registry.async_get(old_popup) is None
    assert dr.async_get(hass).async_get(old_device.id) is None
    assert "migration_journal" not in canonical.data


async def test_seeded_v1_direct_registry_migrates_without_orphan_and_keeps_user_disable(hass, wire):
    old = ConfigEntry(
        domain=DOMAIN, title="My Direct PC", version=1, minor_version=1,
        source=SOURCE_USER, unique_id="phase0_pc_direct", options={"keep": True},
        disabled_by=ConfigEntryDisabler.USER,
        discovery_keys=MappingProxyType({}), subentries_data=None,
        data=legacy_direct_data("phase0_pc"))
    await hass.config_entries.async_add(old)
    await hass.async_block_till_done()
    assert old.state != ConfigEntryState.LOADED
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    seeded_device = devices.async_get_or_create(
        config_entry_id=old.entry_id, identifiers={(DOMAIN, "phase0_pc")},
        name="Original device")
    seeded_popup = registry.async_get_or_create(
        "notify", DOMAIN, "phase0_pc_overlay", config_entry=old,
        device_id=seeded_device.id, disabled_by=RegistryEntryDisabler.USER)
    registry.async_update_entity(seeded_popup.entity_id, name="My popup")
    assert await hass.config_entries.async_set_disabled_by(old.entry_id, None)
    await hass.async_block_till_done()
    assert old.state == ConfigEntryState.LOADED
    assert old.version == 2 and old.unique_id == "phase0_pc"
    assert old.options == {"keep": True} and old.title == "My Direct PC"
    assert registry.async_get(seeded_popup.entity_id) is None
    canonical_id = registry.async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay")
    canonical = registry.async_get(canonical_id)
    assert canonical and canonical.disabled_by is RegistryEntryDisabler.USER
    assert canonical.name == "My popup"
    owned_devices = dr.async_entries_for_config_entry(devices, old.entry_id)
    assert len(owned_devices) == 1 and owned_devices[0].id == seeded_device.id
    assert "migration_journal" not in old.data


async def test_manual_direct_adds_popup_to_existing_mqtt_entry_without_one(hass, wire):
    payload = announcement()
    payload["entities"] = [item for item in payload["entities"]
                           if item.get("unique_id") != "phase0_pc_windows_overlay"]
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay") is None
    direct_flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        direct_flow["flow_id"], {"name": "Direct popup", "device_id": "phase0_pc"})
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert canonical.state == ConfigEntryState.LOADED
    assert canonical.data["direct_popup_enabled"]
    assert canonical.runtime_data.overlay_event_type
    assert len([entry for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.data.get("device_id") == "phase0_pc"]) == 1
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)) == 1
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay") is not None


async def test_manual_direct_intent_with_mqtt_popup_survives_later_omission(hass, wire):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    popup_id = er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay")
    direct_flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        direct_flow["flow_id"], {"name": "Direct popup", "device_id": "phase0_pc"})
    assert result["type"] == "abort"
    assert canonical.data["direct_popup_enabled"]
    assert not canonical.runtime_data.overlay_event_type
    payload = announcement()
    payload["entities"] = [item for item in payload["entities"]
                           if item.get("unique_id") != "phase0_pc_windows_overlay"]
    discovery = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    await hass.async_block_till_done()
    assert discovery["type"] == "abort"
    assert canonical.state == ConfigEntryState.LOADED
    assert canonical.runtime_data.overlay_event_type
    assert er.async_get(hass).async_get_entity_id(
        "notify", DOMAIN, "phase0_pc_windows_overlay") == popup_id
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), canonical.entry_id)) == 1


async def test_direct_handshake_capability_is_independent_of_retained_mqtt_manifest(hass, wire):
    from custom_components.ha_windows_bridge.protocol import CapabilitiesMessage, Capability
    from custom_components.ha_windows_bridge.websocket import connect

    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    entry = (await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"name": "Direct PC", "device_id": "phase0_pc"}))["result"]
    await hass.async_block_till_done()
    payload = announcement()
    payload["entities"] = [item for item in payload["entities"]
                           if item.get("unique_id") != "phase0_pc_windows_overlay"]
    payload["protocol"].update(
        version=3, session="mqtt-session", command_topic="phase0/pc/v3/command",
        result_topic="phase0/pc/v3/result", capabilities_topic="phase0/pc/v3/capabilities",
        snapshot_topic="phase0/pc/v3/snapshot", legacy_command_topic="phase0/pc/v2/command")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload))
    await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    runtime = entry.runtime_data
    assert runtime.overlay_event_type and runtime.protocol["version"] == 3
    # This retained MQTT manifest came from an older Windows profile without popup.
    manifest = CapabilitiesMessage(
        "manifest-1", "mqtt-session", "phase0_pc", 1,
        (Capability("audio.master.volume", ("mqtt",)),))
    runtime._mqtt_capabilities(SimpleNamespace(payload=manifest.encode()))

    sent, errors = [], []
    def direct_send(command):
        sent.append(command)
        runtime._result({
            "version": 3, "type": "result", "id": command["id"],
            "session": command["session"], "device_id": "phase0_pc",
            "status": "succeeded", "code": "", "data": {},
        }, direct=True)
    connection = SimpleNamespace(
        subscriptions={}, user=SimpleNamespace(permissions=SimpleNamespace(
            check_entity=lambda *_args: True)),
        send_error=lambda *_args: errors.append(_args), send_result=lambda *_args: None,
        send_event=lambda _id, command: direct_send(command))
    handshake = {"id": 1, "device_id": "phase0_pc", "session": "direct-session"}
    connect(hass, connection, {**handshake, "capabilities": [
        {"name": "audio.master.volume", "transports": ["direct"]}]})
    assert errors and runtime.owner is None
    connect(hass, connection, {**handshake, "id": 2, "capabilities": [
        {"name": "overlay.show", "transports": ["direct"]}]})
    assert runtime.owner is connection and runtime._direct_capabilities == {"overlay.show"}
    await runtime.send("", '{"message":"working Direct"}', direct=True)
    assert len(sent) == 1 and sent[0]["kind"] == "overlay.show"
    # The Direct handshake must not weaken the MQTT manifest guard.
    route = "phase0/pc/overlay/show/set"
    assert runtime.protocol["routes"][route]["kind"] == "overlay.show"
    with pytest.raises(HomeAssistantError) as error:
        await runtime.send(route, '{"message":"MQTT disallowed"}')
    assert error.value.translation_key == "capability_unavailable"
    assert len(sent) == 1


async def test_overlay_service_rejects_nonfinite_and_overflow_sources(hass, wire):
    entry, popup = await quality_direct_entry(hass)
    assert hass.services.has_service(DOMAIN, "show_overlay")
    hass.states.async_set("sensor.quality_value", "42", {"huge": 10**400})

    async def show(**data):
        await hass.services.async_call(
            DOMAIN, "show_overlay", {"entity_id": popup, "message": "test", **data},
            blocking=True)

    for field in ("progress_min", "progress_max"):
        for value in ("nan", "inf", "-inf"):
            with pytest.raises(ServiceValidationError) as error:
                await show(progress_entity="sensor.quality_value", **{field: value})
            assert error.value.translation_key == "number_must_be_finite"
    with pytest.raises(ServiceValidationError) as error:
        await show(progress_entity="sensor.quality_value", progress_attribute="huge")
    assert error.value.translation_key == "source_not_numeric"
    hass.states.async_set("sensor.quality_value", "1e308")
    with pytest.raises(ServiceValidationError) as error:
        await show(progress_entity="sensor.quality_value",
                   progress_min=-1e308, progress_max=1e308)
    assert error.value.translation_key == "progress_range_invalid"

    # Invalid HA media numbers must be sanitized before JSON serialization.
    hass.states.async_set("media_player.quality", "playing", {
        "media_title": "Track", "media_duration": float("inf"),
        "media_position": 10**400})
    sent = []
    async def record_send(_topic, payload, **_kwargs):
        sent.append(json.loads(payload))
    entry.runtime_data.send = record_send
    await show(media_player_entity="media_player.quality")
    assert sent and sent[-1]["data"]["media_duration"] == 0
    assert sent[-1]["data"]["media_position"] == 0


async def test_overlay_service_rejects_disabled_and_unauthorized_targets(hass, wire, monkeypatch):
    entry, popup = await quality_direct_entry(hass)
    registry = er.async_get(hass)
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "show_overlay", {"entity_id": popup, "message": "test"},
            blocking=True, context=Context(user_id="missing-user"))
    assert error.value.translation_key == "not_authorized_control"
    monkeypatch.setattr(hass.auth, "async_get_user", AsyncMock(return_value=SimpleNamespace(
        permissions=SimpleNamespace(check_entity=lambda entity_id, _policy: entity_id == popup))))
    hass.states.async_set("sensor.private", "7")
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "show_overlay", {"entity_id": popup, "message": "test",
                                     "progress_entity": "sensor.private"},
            blocking=True, context=Context(user_id="limited-user"))
    assert error.value.translation_key == "not_authorized_read_source"
    registry.async_update_entity(popup, disabled_by=RegistryEntryDisabler.USER)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN, "show_overlay", {"entity_id": popup, "message": "test"},
            blocking=True)
    assert error.value.translation_key == "popup_required"
    registry.async_update_entity(popup, disabled_by=None)
    async def fail_send(*_args, **_kwargs):
        raise HomeAssistantError("injected")
    entry.runtime_data.send = fail_send
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "show_overlay", {"entity_id": popup, "message": "test"},
            blocking=True)
    assert error.value.translation_key == "targets_unconfirmed"
    assert error.value.translation_placeholders == {"count": "1"}


async def test_overlay_update_remove_clear_use_real_service_schemas(hass, wire):
    _entry, popup = await quality_direct_entry(hass)
    sent = []
    async def record_send(_topic, payload, **_kwargs):
        sent.append(json.loads(payload))
    _entry.runtime_data.send = record_send
    with pytest.raises(MultipleInvalid, match="notification_id"):
        await hass.services.async_call(
            DOMAIN, "update_overlay", {"entity_id": popup, "message": "patch"},
            blocking=True)
    for action, data in (
        ("update_overlay", {"notification_id": "stable", "message": "patch"}),
        ("remove_overlay", {"notification_id": "stable"}),
        ("clear_overlay", {}),
    ):
        await hass.services.async_call(
            DOMAIN, action, {"entity_id": popup, **data}, blocking=True)
    assert [item["data"]["action"] for item in sent] == ["update", "remove", "clear"]
    assert sent[0]["data"]["id"] == sent[1]["data"]["id"] == "stable"


async def test_quality_translations_load_for_en_and_pl(hass):
    source = json.loads((ROOT.parent / "custom_components" / DOMAIN / "strings.json").read_text())
    service_yaml = yaml.safe_load(
        (ROOT.parent / "custom_components" / DOMAIN / "services.yaml").read_text())
    def leaf_fields(fields):
        for key, definition in fields.items():
            if "fields" in definition:
                yield from leaf_fields(definition["fields"])
            else:
                yield key
    for language in ("en", "pl"):
        for category in ("exceptions", "issues", "config", "services", "selector"):
            translated = await translation.async_get_translations(
                hass, language, category, integrations={DOMAIN})
            assert translated, (language, category)
            if category in ("exceptions", "issues"):
                for key, fields in source[category].items():
                    for field, value in fields.items():
                        lookup = f"component.{DOMAIN}.{category}.{key}.{field}"
                        assert lookup in translated, (language, lookup)
                        assert set(re.findall(r"\{([^{}]+)\}", value)) == set(
                            re.findall(r"\{([^{}]+)\}", translated[lookup]))
            if category == "config":
                for section in ("error", "abort"):
                    for key in source["config"][section]:
                        assert f"component.{DOMAIN}.config.{section}.{key}" in translated
            if category == "services":
                for service, definition in service_yaml.items():
                    fields = source["services"][service].get("fields", {})
                    for key in leaf_fields(definition.get("fields", {})):
                        assert key in fields, (language, service, key)
                        assert f"component.{DOMAIN}.services.{service}.fields.{key}.name" in translated
            if category == "selector":
                for selector, definition in source["selector"].items():
                    for option in definition["options"]:
                        assert (f"component.{DOMAIN}.selector.{selector}.options."
                                f"{option}") in translated


async def test_migration_repairs_create_retry_and_remove(hass, wire, monkeypatch):
    import custom_components.ha_windows_bridge as integration

    entry, _popup = await quality_direct_entry(hass)
    issues = ir.async_get(hass)
    original_prepare = integration.async_prepare_migration
    original_finish = integration.async_finish_migration

    async def conflict(*_args):
        raise ValueError("injected migration conflict")
    monkeypatch.setattr(integration, "async_prepare_migration", conflict)
    assert not await hass.config_entries.async_reload(entry.entry_id)
    issue = issues.async_get_issue(DOMAIN, f"migration_conflict_{entry.entry_id}")
    assert issue and issue.translation_placeholders == {"name": entry.title}
    monkeypatch.setattr(integration, "async_prepare_migration", original_prepare)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, f"migration_conflict_{entry.entry_id}") is None

    async def cleanup_pending(*_args):
        raise OSError("injected cleanup failure")
    monkeypatch.setattr(integration, "async_finish_migration", cleanup_pending)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state == ConfigEntryState.LOADED
    issue = issues.async_get_issue(DOMAIN, f"migration_cleanup_pending_{entry.entry_id}")
    assert issue and issue.translation_placeholders == {"name": entry.title}
    monkeypatch.setattr(integration, "async_finish_migration", original_finish)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, f"migration_cleanup_pending_{entry.entry_id}") is None
    integration.migration_conflict(hass, entry)
    assert await hass.config_entries.async_remove(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, f"migration_conflict_{entry.entry_id}") is None


async def test_diagnostics_allowlist_loaded_and_unloaded(hass, wire):
    from custom_components.ha_windows_bridge.diagnostics import async_get_config_entry_diagnostics

    entry, popup = await quality_direct_entry(hass)
    runtime = entry.runtime_data
    runtime.notification_lifecycle.append({"secret": "PRIVATE_LIFECYCLE"})
    runtime.snapshot = {"secret": "PRIVATE_SNAPSHOT"}
    runtime.protocol["secret"] = "PRIVATE_PROTOCOL"
    loaded = await async_get_config_entry_diagnostics(hass, entry)
    assert loaded["runtime_loaded"] and loaded["lifecycle_event_count"] == 1
    assert loaded["snapshot_available"]
    assert loaded["entity_counts"] == {"notify": 1}
    assert not any(secret in json.dumps(loaded) for secret in (
        "PRIVATE_LIFECYCLE", "PRIVATE_SNAPSHOT", "PRIVATE_PROTOCOL", "quality_pc", popup))
    assert await hass.config_entries.async_unload(entry.entry_id)
    unloaded = await async_get_config_entry_diagnostics(hass, entry)
    assert not unloaded["runtime_loaded"] and unloaded["lifecycle_event_count"] == 0
    assert unloaded["pending_commands"] == 0


async def test_orderly_restart_keeps_one_entry_device_and_popup_after_consolidation(
    tmp_path, wire,
):
    source_dir = ROOT.parent / "custom_components" / DOMAIN
    shutil.copytree(source_dir, tmp_path / "custom_components" / DOMAIN,
                    ignore=shutil.ignore_patterns("__pycache__"))
    config = {"homeassistant": {"name": "Phase 0", "latitude": 52.0,
                                "longitude": 21.0, "elevation": 100,
                                "unit_system": "metric", "time_zone": "UTC",
                                "country": "PL"},
              "http": {"server_host": "127.0.0.1"}}

    async def start():
        instance = HomeAssistant(str(tmp_path))
        loader.async_setup(instance)
        assert await bootstrap.async_from_config_dict(config, instance) is instance
        return instance

    first = await start()
    second = None
    try:
        flow = await first.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
        canonical = (await first.config_entries.flow.async_configure(
            flow["flow_id"], {}))["result"]
        await first.async_block_till_done()
        old = ConfigEntry(
            domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
            source=SOURCE_USER, unique_id="phase0_pc_direct", options={},
            discovery_keys=MappingProxyType({}), subentries_data=None,
            data=legacy_direct_data("phase0_pc"))
        await first.config_entries.async_add(old)
        await first.async_block_till_done()
        old_device = dr.async_entries_for_config_entry(dr.async_get(first), old.entry_id)[0]
        old_popup_id = er.async_get(first).async_get_entity_id(
            "notify", DOMAIN, "phase0_pc_overlay")
        assert await first.config_entries.async_reload(canonical.entry_id)
        await first.async_block_till_done()
        assert first.config_entries.async_get_entry(old.entry_id) is None
        await first.async_stop(force=True)
        await first.async_block_till_done()

        second = await start()
        await second.async_block_till_done()
        entries = [entry for entry in second.config_entries.async_entries(DOMAIN)
                   if entry.data.get("device_id") == "phase0_pc"]
        assert len(entries) == 1
        restored = entries[0]
        assert restored.entry_id == canonical.entry_id
        assert restored.state == ConfigEntryState.LOADED
        assert "migration_journal" not in restored.data
        devices = dr.async_entries_for_config_entry(dr.async_get(second), restored.entry_id)
        assert len(devices) == 1
        assert dr.async_get(second).async_get(old_device.id) is None
        registry = er.async_get(second)
        assert registry.async_get(old_popup_id) is None
        popup_id = registry.async_get_entity_id(
            "notify", DOMAIN, "phase0_pc_windows_overlay")
        assert popup_id and registry.async_get(popup_id).config_entry_id == restored.entry_id
    finally:
        if second is not None:
            await second.async_stop(force=True)
            await second.async_block_till_done()
        else:
            await first.async_stop(force=True)
            await first.async_block_till_done()


async def test_multiple_legacy_sources_block_cleanup_without_deleting_either(hass, wire):
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(announcement()))
    canonical = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    sources = []
    for suffix in ("direct", "direct_duplicate"):
        source = ConfigEntry(
            domain=DOMAIN, title="Legacy Direct PC", version=1, minor_version=1,
            source=SOURCE_USER, unique_id=f"phase0_pc_{suffix}", options={},
            disabled_by=ConfigEntryDisabler.USER,
            discovery_keys=MappingProxyType({}), subentries_data=None,
            data=legacy_direct_data("phase0_pc"))
        await hass.config_entries.async_add(source)
        sources.append(source)
    await hass.async_block_till_done()
    assert not await hass.config_entries.async_reload(canonical.entry_id)
    await hass.async_block_till_done()
    assert canonical.state != ConfigEntryState.LOADED
    assert "migration_journal" not in canonical.data
    assert all(hass.config_entries.async_get_entry(source.entry_id) is source
               for source in sources)
