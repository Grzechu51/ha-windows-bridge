"""The real HA runtime exercised with dependency doubles; no HA server on Windows."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def runtime_module(monkeypatch):
    def module(name, **values):
        result = ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result
    mqtt = SimpleNamespace(async_publish=AsyncMock(), async_subscribe=AsyncMock(return_value=lambda: None))
    module("homeassistant")
    module("homeassistant.components", mqtt=mqtt)
    module("homeassistant.core", callback=lambda function: function)
    module("homeassistant.exceptions", HomeAssistantError=RuntimeError)
    module("homeassistant.helpers")
    module("homeassistant.helpers.event", async_call_later=lambda hass, delay, function: hass.loop.call_later(delay, function, None).cancel)
    path = Path(__file__).parents[1] / "custom_components/ha_windows_bridge/runtime.py"
    spec = importlib.util.spec_from_file_location("bridge_runtime_test", path)
    loaded = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, loaded)
    spec.loader.exec_module(loaded)
    return loaded


def make_runtime(module, **kwargs):
    return module.BridgeRuntime(SimpleNamespace(loop=asyncio.get_running_loop()), "pc", {"popup"}, "popup", "pc/overlay", "direct", **kwargs)


def test_direct_ack_is_correlated_and_disconnect_fails_pending(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module)
        sent = []
        owner = object()
        runtime.attach(owner, sent.append)
        task = asyncio.create_task(runtime.send("", '{"message":"hello"}', direct=True))
        await asyncio.sleep(0)
        command = sent[0]
        assert command["version"] == 2 and command["kind"] == "overlay.show"
        for bad in ({"version": 2, "id": []}, {"version": 2, "id": "other", "status": "succeeded"}):
            runtime._result(bad)
        assert not task.done()
        runtime._result({"version": 2, "id": command["id"], "status": "succeeded"})
        await task
        assert not runtime.pending
        task = asyncio.create_task(runtime.send("", '{}', direct=True))
        await asyncio.sleep(0)
        runtime.detach(object())
        assert runtime.available
        runtime.detach(owner)
        with pytest.raises(RuntimeError, match="disconnected"):
            await task
        assert not runtime.available and not runtime.pending
        runtime.close()
        runtime.close()
    asyncio.run(exercise())


def test_direct_rejects_offline_and_second_client(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module)
        with pytest.raises(RuntimeError, match="offline"):
            await runtime.send("", '{}', direct=True)
        runtime.attach(object(), lambda command: None)
        with pytest.raises(RuntimeError, match="already connected"):
            runtime.attach(object(), lambda command: None)
        runtime.close()
    asyncio.run(exercise())


def test_mqtt_creates_envelope_before_publish_and_ignores_retained_ack(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module, protocol={"command_topic": "v2/command", "result_topic": "v2/result", "routes": {"volume": {"kind": "audio.master.volume", "parser": "volume"}}})
        runtime.overlay_event_type = ""
        async def publish(hass, topic, payload, **kwargs):
            command = json.loads(payload)
            assert command["arguments"] == {"value": .42}
            assert command["id"] in runtime.pending and not kwargs["retain"]
            ack = {"version": 2, "id": command["id"], "status": "succeeded"}
            runtime._mqtt_result(SimpleNamespace(retain=True, payload=json.dumps(ack)))
            assert not runtime.pending[command["id"]].done()
            runtime._mqtt_result(SimpleNamespace(retain=False, payload=json.dumps(ack)))
        runtime_module.mqtt.async_publish.side_effect = publish
        await runtime.start()
        await runtime.send("volume", "42")
        assert not runtime.pending
        with pytest.raises(RuntimeError, match="not allowed"):
            await runtime.send("arbitrary", "42")
        runtime.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("parser,payload", [("json", "{"), ("json", "[]"), ("volume", "nan"), ("volume", "text"), ("switch", "maybe"), ("button", "delete")])
def test_wire_arguments_reject_malformed_values(runtime_module, parser, payload):
    with pytest.raises(RuntimeError):
        runtime_module.command_arguments(parser, payload)
