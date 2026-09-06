"""Audit H02/H05: full import, discovery, real entity setup/reload/unload."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt
from homeassistant.components.media_player import DATA_COMPONENT
from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER, ConfigEntry, ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

DOMAIN = "ha_windows_bridge"
ROOT = Path(__file__).parent


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
    entity_id = er.async_get(hass).async_get_entity_id("notify", DOMAIN, "direct_pc_overlay")
    assert entity_id and hass.states.get(entity_id) is not None
    current_runtime = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert current_runtime._closed
