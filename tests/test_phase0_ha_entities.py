"""Whole HA platform modules with API doubles; real HA tests live in tests_ha.

These local tests deliberately do not extract classes from AST (audit P04).
"""
import asyncio
import importlib.util
import sys
from enum import IntFlag, StrEnum
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def ha_platforms(monkeypatch):
    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)
        return value
    class Entity:
        async def async_added_to_hass(self):
            self.cleanup = []
        def async_on_remove(self, callback):
            self.cleanup.append(callback)
        def add_to_platform_abort(self):
            while self.cleanup:
                self.cleanup.pop()()
        def async_write_ha_state(self):
            pass
    class Features(IntFlag):
        VOLUME_SET = 1
        VOLUME_MUTE = 2
        PLAY = 4
        PAUSE = 8
        STOP = 16
        NEXT_TRACK = 32
        PREVIOUS_TRACK = 64
        SEEK = 128
    class Category(StrEnum):
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"
    mqtt = SimpleNamespace(is_connected=lambda hass: True)
    module("homeassistant")
    module("homeassistant.components", mqtt=mqtt)
    module("homeassistant.components.mqtt", **vars(mqtt))
    module("homeassistant.components.mqtt.models", ReceiveMessage=object)
    module("homeassistant.config_entries", ConfigEntry=object)
    module("homeassistant.const", EntityCategory=Category)
    module("homeassistant.core", HomeAssistant=object, callback=lambda fn: fn)
    module("homeassistant.helpers")
    module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.util", dt=SimpleNamespace(utcnow=lambda: None))
    module("homeassistant.components.media_player", MediaPlayerEntity=Entity,
           MediaPlayerEntityFeature=Features, MediaPlayerDeviceClass=SimpleNamespace(SPEAKER="speaker"),
           MediaPlayerState=SimpleNamespace(IDLE="idle", OFF="off", PLAYING="playing", PAUSED="paused"))
    module("homeassistant.components.media_player.const", MediaType=SimpleNamespace(MUSIC="music"))
    module("homeassistant.components.sensor", SensorDeviceClass=Category, SensorStateClass=Category, SensorEntity=Entity)
    module("homeassistant.components.binary_sensor", BinarySensorDeviceClass=Category, BinarySensorEntity=Entity)
    package = module("phase0_ha")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components/ha_windows_bridge")]
    modules = {}
    for name in ("const", "entity", "media_payload", "media_player", "sensor", "binary_sensor"):
        spec = importlib.util.spec_from_file_location("phase0_ha." + name, Path(package.__path__[0]) / (name + ".py"))
        modules[name] = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, modules[name])
        spec.loader.exec_module(modules[name])
    yield SimpleNamespace(**modules, mqtt=mqtt)
    for name in modules:
        sys.modules.pop("phase0_ha." + name, None)


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("fail_at", [None, "state", "availability", "volume", "mute", "thumbnail"])
def test_p04_whole_media_platform_registers_cleanup_immediately(ha_platforms, active, fail_at):
    platform = ha_platforms.media_player
    acquired, removed, subscriptions = [], [], {}
    def cleanup(topic):
        acquired.append(topic)
        return lambda: removed.append(topic)
    async def subscribe(hass, topic, callback, **kwargs):
        if topic == fail_at:
            raise OSError("partial setup")
        subscriptions[topic] = callback
        return cleanup(topic)
    ha_platforms.mqtt.async_subscribe = subscribe
    ha_platforms.mqtt.async_subscribe_connection_status = lambda *args: cleanup("connection")
    definition = {"unique_id": "pc_app", "name": "App", "platform": "media_player",
                  "state_topic": "state", "availability_topic": "availability",
                  "volume_state_topic": "volume", "mute_state_topic": "mute",
                  "volume_command_topic": "volume/set", "mute_command_topic": "mute/set"}
    entry = SimpleNamespace(data={"device_id": "pc", "device": {}, "entities": [] if active else [definition],
                                 "media_player": {"enabled": active, "command_topic": "command", "state_topic": "state",
                                                  "availability_topic": "availability", "thumbnail_topic": "thumbnail"}})
    entities = []
    asyncio.run(platform.async_setup_entry(object(), entry, entities.extend))
    assert len(entities) == 1
    entity = entities[0]
    entity.hass = object()
    relevant = {"state", "availability", "thumbnail"} if active else {"state", "availability", "volume", "mute"}
    if fail_at in relevant:
        with pytest.raises(OSError, match="partial setup"):
            asyncio.run(entity.async_added_to_hass())
        assert sorted(removed) == sorted(acquired)
        assert not entity.cleanup
    else:
        asyncio.run(entity.async_added_to_hass())
        if not active:
            subscriptions["volume"](SimpleNamespace(payload="80"))
            subscriptions["mute"](SimpleNamespace(payload="ON"))
            assert entity._attr_volume_level == .8
            assert entity._attr_is_volume_muted is True
    for remove in entity.cleanup:
        remove()
    assert sorted(removed) == sorted(acquired)
    assert len(removed) == len(set(removed))


@pytest.mark.parametrize("binary", [False, True])
def test_provider_unavailable_is_not_a_valid_empty_or_off_sample(ha_platforms, binary):
    definition = {"unique_id": "metric", "name": "Metric", "state_topic": "state", "payload_on": "ON", "payload_off": "OFF"}
    cls = ha_platforms.binary_sensor.BridgeBinarySensor if binary else ha_platforms.sensor.BridgeSensor
    entity = cls(SimpleNamespace(data={"device_id": "pc", "device": {}}), definition)
    entity._mqtt_connected = True
    entity._state_received(SimpleNamespace(payload="ON" if binary else "20"))
    assert entity._attr_available
    entity._state_received(SimpleNamespace(payload="unavailable"))
    assert not entity._attr_available
    entity._state_received(SimpleNamespace(payload="OFF" if binary else "80"))
    assert entity._attr_available
