"""Exercise integration functions with HA API doubles (HA does not run on Windows)."""

from __future__ import annotations

import ast
import asyncio
import json
from collections import Counter
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def load_function(filename, name, namespace):
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ha_windows_bridge" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if getattr(item, "name", None) == name)
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_diagnostics_does_not_export_identities_topics_or_payloads():
    namespace = {"ConfigEntry": object, "HomeAssistant": object, "Any": Any, "Counter": Counter,
                 "CONF_ENTITIES": "entities", "CONF_MEDIA_PLAYER": "media_player", "CONF_TRANSPORT": "transport", "DOMAIN": "ha_windows_bridge"}
    diagnostic = load_function("diagnostics.py", "async_get_config_entry_diagnostics", namespace)
    entry = SimpleNamespace(version=1, state=SimpleNamespace(value="loaded"), entry_id="secret-id", data={
        "device_id": "secret-device", "token": "secret-token", "transport": "mqtt", "media_player": {"enabled": True},
        "entities": [{"platform": "sensor", "state_topic": "secret-topic", "name": "secret-name"}, {"platform": "secret-platform"}],
    })
    entry.runtime_data = SimpleNamespace(pending={}, notification_lifecycle=[])
    report = asyncio.run(diagnostic(SimpleNamespace(), entry))
    assert report["entity_counts"] == {"sensor": 1}
    assert report["runtime_loaded"]
    assert "secret" not in json.dumps(report)


def test_integration_translations_match_and_reconfigure_is_documented():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "ha_windows_bridge"
    english = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    assert english == json.loads((root / "translations/en.json").read_text(encoding="utf-8"))
    for language in ("en", "pl"):
        messages = json.loads((root / f"translations/{language}.json").read_text(encoding="utf-8"))
        assert "reconfigure" in messages["config"]["step"]
        assert "reconfigure_successful" in messages["config"]["abort"]


def test_reconfigure_changes_only_direct_device_name():
    class FlowBase:
        def __init_subclass__(cls, **kwargs):
            pass

        def async_update_reload_and_abort(self, entry, **kwargs):
            return kwargs

        def async_abort(self, **kwargs):
            return kwargs

    namespace = {"config_entries": SimpleNamespace(ConfigFlow=FlowBase), "DOMAIN": "ha_windows_bridge",
                 "Any": Any, "FlowResult": dict, "MqttServiceInfo": object,
                 "CONF_DEVICE": "device", "CONF_TRANSPORT": "transport", "TRANSPORT_DIRECT": "direct"}
    flow_type = load_function("config_flow.py", "ConfigFlow", namespace)
    flow = flow_type()
    entry = SimpleNamespace(data={"device_id": "unchanged", "transport": "direct", "device": {"name": "Old", "model": "PC"}})
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_known_entry=lambda key: entry))
    flow.context = {"entry_id": "entry"}
    result = asyncio.run(flow.async_step_reconfigure({"name": " New "}))
    assert result["title"] == "New"
    assert result["data_updates"] == {"device": {"name": "New", "model": "PC"}}
    assert entry.data["device_id"] == "unchanged"
    assert entry.data["device"]["name"] == "Old"
    entry.data["transport"] = "mqtt"
    assert asyncio.run(flow.async_step_reconfigure({"name": "New"})) == {"reason": "discovery_only"}


def test_entity_registers_cleanup_before_later_subscription_fails():
    class Category(Enum):
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    removed = []

    async def subscribe(_hass, topic, _callback, **kwargs):
        if topic == "state":
            raise OSError("broker disconnected during setup")
        return lambda: removed.append(topic)

    mqtt = SimpleNamespace(is_connected=lambda hass: True, async_subscribe=subscribe,
                           async_subscribe_connection_status=lambda *args: lambda: removed.append("connection"))
    namespace = {"ConfigEntry": object, "ReceiveMessage": object, "Any": Any, "mqtt": mqtt,
                 "EntityCategory": Category, "bridge_device_info": lambda entry: {}, "callback": lambda function: function}
    mixin = load_function("entity.py", "BridgeMqttEntity", namespace)

    class EntityBase:
        async def async_added_to_hass(self):
            self.cleanup = []

        def async_on_remove(self, callback):
            self.cleanup.append(callback)

        def add_to_platform_abort(self):
            for callback in self.cleanup:
                callback()
            self.cleanup.clear()

    class Entity(mixin, EntityBase):
        pass

    runtime = SimpleNamespace(setup_failed=False)
    entity = Entity(SimpleNamespace(runtime_data=runtime), {"unique_id": "same-id", "name": "Name", "availability_topic": "availability", "state_topic": "state"})
    released = []
    entity.entity_id = "sensor.name"
    entity.hass = SimpleNamespace(states=SimpleNamespace(
        get=lambda entity_id: None, async_remove=released.append))
    with pytest.raises(OSError, match="broker disconnected"):
        asyncio.run(entity.async_added_to_hass())
    for cleanup in entity.cleanup:
        cleanup()
    assert removed == ["connection", "availability"]
    assert released == ["sensor.name"]
    assert runtime.setup_failed



def _setup_namespace(*, fail_forward=False, unload_ok=True, platform_failure=False):
    events = []
    registered = SimpleNamespace(entity_id="sensor.custom_name", unique_id="old-capability")
    registry = SimpleNamespace(
        async_remove=lambda entity_id: events.append(("remove", entity_id)),
        async_get_entity_id=lambda platform, domain, unique_id:
            "notify.popup" if (platform, unique_id) == ("notify", "popup") else None,
        async_get=lambda entity_id: SimpleNamespace(
            config_entry_id="entry", disabled_by=None) if entity_id == "notify.popup" else None,
    )
    class Runtime:
        def __init__(self, **kwargs):
            self.protocol = kwargs["protocol"]
            self._closed = False
            self.setup_failed = False
            events.append(("runtime", self))
        async def start(self):
            events.append(("start", self))
        def close(self):
            if not self._closed:
                self._closed = True
                events.append(("close", self))
        async def async_close(self):
            self.close()
    async def forward(entry, platforms):
        events.append(("forward", tuple(platforms)))
        if fail_forward:
            raise OSError("platform forwarding failed")
    async def unload(entry, platforms):
        events.append(("unload", tuple(platforms)))
        return unload_ok
    class FakeNotReady(RuntimeError):
        def __init__(self, message, **translation):
            super().__init__(message)
            self.translation_key = translation.get("translation_key")

    namespace = {
        "HomeAssistant": object, "ConfigEntry": object,
        "CONF_TRANSPORT": "transport", "TRANSPORT_DIRECT": "direct",
        "CONF_ENTITIES": "entities", "CONF_MEDIA_PLAYER": "media_player",
        "CONF_DEVICE_ID": "device_id", "PLATFORMS": ["sensor", "notify"],
        "DOMAIN": "ha_windows_bridge", "ConfigEntryNotReady": FakeNotReady,
        "Platform": SimpleNamespace(NOTIFY=SimpleNamespace(value="notify")),
        "er": SimpleNamespace(async_get=lambda hass: registry,
                              async_entries_for_config_entry=lambda registry, entry_id: [registered]),
        "entity_platform": SimpleNamespace(async_get_platforms=lambda hass, domain: platforms),
        "BridgeRuntime": Runtime,
        "direct_overlay_event": lambda device: "direct-event",
        "async_prepare_migration": lambda hass, entry: asyncio.sleep(0),
        "async_finish_migration": lambda hass, entry: asyncio.sleep(0),
        "migration_conflict": lambda hass, entry: None,
        "migration_cleanup_pending": lambda hass, entry: None,
        "clear_migration_conflict": lambda hass, entry: None,
        "clear_migration_issues": lambda hass, entry: None,
        "_LOGGER": SimpleNamespace(exception=lambda *args: None),
    }
    entry = SimpleNamespace(
        data={"transport": "direct", "device_id": "pc",
              "entities": [{"platform": "notify", "unique_id": "popup",
                            "command_topic": "direct://pc"}],
              "protocol": {"session": "initial"}},
        entry_id="entry", runtime_data=None,
        async_on_unload=lambda callback: events.append(("on_unload", callback)),
    )
    async def destroy(platform):
        events.append(("destroy", platform.domain))
    platforms = [
        SimpleNamespace(config_entry=entry, domain="sensor", _setup_complete=True,
                        entities={}, async_destroy=lambda: destroy(platforms[0])),
        SimpleNamespace(config_entry=entry, domain="notify",
                        _setup_complete=not platform_failure,
                        entities={"notify.popup": object()} if not platform_failure else {},
                        async_destroy=lambda: destroy(platforms[1])),
    ]
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_forward_entry_setups=forward, async_unload_platforms=unload))
    return namespace, hass, entry, events


def test_failed_platform_forward_unloads_partial_platforms_and_clears_runtime():
    namespace, hass, entry, events = _setup_namespace(fail_forward=True)
    for name in ("_entry_platforms", "_forwarded_entities_ready", "_async_rollback_platforms"):
        load_function("__init__.py", name, namespace)
    setup = load_function("__init__.py", "async_setup_entry", namespace)
    with pytest.raises(OSError, match="platform forwarding failed"):
        asyncio.run(setup(hass, entry))
    assert [event[0] for event in events] == [
        "runtime", "start", "forward", "unload", "destroy", "destroy", "close"]
    assert entry.runtime_data is None
    assert not any(event[0] == "remove" for event in events)


def test_unload_clears_runtime_only_after_platform_cleanup():
    namespace, hass, entry, events = _setup_namespace(unload_ok=False)
    for name in ("_entry_platforms", "_forwarded_entities_ready", "_async_rollback_platforms"):
        load_function("__init__.py", name, namespace)
    setup = load_function("__init__.py", "async_setup_entry", namespace)
    unload = load_function("__init__.py", "async_unload_entry", namespace)
    async def exercise():
        assert await setup(hass, entry)
        runtime = entry.runtime_data
        assert not await unload(hass, entry)
        assert entry.runtime_data is runtime and not runtime._closed
        hass.config_entries.async_unload_platforms = async_success
        assert await unload(hass, entry)
        assert entry.runtime_data is None and runtime._closed
    async def async_success(entry, platforms):
        return True
    asyncio.run(exercise())
    assert not any(event[0] == "remove" for event in events)



def test_swallowed_platform_failure_destroys_failed_platform_and_unloads_loaded_one():
    namespace, hass, entry, events = _setup_namespace(platform_failure=True)
    for name in ("_entry_platforms", "_forwarded_entities_ready", "_async_rollback_platforms"):
        load_function("__init__.py", name, namespace)
    setup = load_function("__init__.py", "async_setup_entry", namespace)
    with pytest.raises(RuntimeError, match="entity setup did not complete"):
        asyncio.run(setup(hass, entry))
    assert [event[0] for event in events] == [
        "runtime", "start", "forward", "unload", "destroy", "destroy", "close"]
    assert next(event[1] for event in events if event[0] == "unload") == ("sensor", "notify")
    assert entry.runtime_data is None
