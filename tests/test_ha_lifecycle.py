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
    entry.runtime_data = SimpleNamespace(pending={})
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

    class Entity(mixin, EntityBase):
        pass

    entity = Entity(SimpleNamespace(), {"unique_id": "same-id", "name": "Name", "availability_topic": "availability", "state_topic": "state"})
    entity.hass = object()
    with pytest.raises(OSError, match="broker disconnected"):
        asyncio.run(entity.async_added_to_hass())
    for cleanup in entity.cleanup:
        cleanup()
    assert removed == ["connection", "availability"]
