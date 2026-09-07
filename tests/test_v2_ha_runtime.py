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
    directory = Path(__file__).parents[1] / "custom_components/ha_windows_bridge"
    package = module("bridge_runtime_test")
    package.__path__ = [str(directory)]
    protocol_spec = importlib.util.spec_from_file_location(
        "bridge_runtime_test.protocol", directory / "protocol.py"
    )
    protocol_module = importlib.util.module_from_spec(protocol_spec)
    monkeypatch.setitem(sys.modules, protocol_spec.name, protocol_module)
    protocol_spec.loader.exec_module(protocol_module)
    path = directory / "runtime.py"
    spec = importlib.util.spec_from_file_location("bridge_runtime_test.runtime", path)
    loaded = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, loaded)
    spec.loader.exec_module(loaded)
    return loaded


def make_runtime(module, **kwargs):
    return module.BridgeRuntime(SimpleNamespace(loop=asyncio.get_running_loop()), "pc", {"popup"}, "popup", "pc/overlay", "direct", **kwargs)


def protocol(routes):
    return {"version": 3, "session": "mqtt-session", "command_topic": "v3/command",
            "result_topic": "v3/result", "capabilities_topic": "v3/capabilities",
            "snapshot_topic": "v3/snapshot", "routes": routes}


def result(command, status="succeeded", *, session=None):
    return {"version": 3, "type": "result", "id": command["id"],
            "session": session or command["session"], "device_id": "pc",
            "status": status, "code": "", "data": {}}


def test_direct_ack_is_correlated_and_disconnect_fails_pending(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module)
        sent = []
        owner = object()
        runtime.attach(owner, sent.append)
        task = asyncio.create_task(runtime.send("", '{"message":"hello"}', direct=True))
        await asyncio.sleep(0)
        command = sent[0]
        assert command["version"] == 3 and command["kind"] == "overlay.show"
        for bad in ({"version": 3, "id": []}, result({**command, "id": "other"}),
                    result(command, session="stale-session")):
            runtime._result(bad)
        assert not task.done()
        runtime._result(result(command))
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
        runtime = make_runtime(runtime_module, protocol=protocol(
            {"volume": {"kind": "audio.master.volume", "parser": "volume"}}))
        runtime.overlay_event_type = ""
        async def publish(hass, topic, payload, **kwargs):
            command = json.loads(payload)
            assert command["arguments"] == {"value": .42}
            assert command["id"] in runtime.pending and not kwargs["retain"]
            ack = result(command)
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


def test_mqtt_computer_uses_direct_for_popup_but_keeps_audio_and_acks_independent(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module, protocol=protocol(
            {"volume": {"kind": "audio.master.volume", "parser": "volume"},
             "pc/overlay": {"kind": "overlay.show", "parser": "json"}}))
        runtime.overlay_event_type = ""
        owner, direct_sent = object(), []
        runtime.attach(owner, direct_sent.append)
        audio = asyncio.create_task(runtime.send("volume", "42"))
        popup = asyncio.create_task(runtime.send("pc/overlay", '{"message":"Direct from MQTT entry"}'))
        await asyncio.sleep(0)
        assert direct_sent[0]["kind"] == "overlay.show"
        assert direct_sent[0]["arguments"]["message"] == "Direct from MQTT entry"
        published = runtime_module.mqtt.async_publish.call_args.args
        audio_command = json.loads(published[2])
        assert audio_command["kind"] == "audio.master.volume"
        assert runtime_module.mqtt.async_publish.call_count == 1
        runtime.detach(owner)
        with pytest.raises(RuntimeError, match="disconnected"):
            await popup
        assert not audio.done()  # Direct must never fail an independent MQTT ACK.
        runtime._result(result(audio_command))
        await audio
        assert not runtime.pending and not runtime._direct_pending
        # With Direct gone, future popup commands use MQTT again.
        fallback = asyncio.create_task(runtime.send("pc/overlay", '{"message":"MQTT fallback"}'))
        await asyncio.sleep(0)
        command = json.loads(runtime_module.mqtt.async_publish.call_args.args[2])
        assert command["kind"] == "overlay.show"
        assert len(direct_sent) == 1
        runtime._result(result(command))
        await fallback
        runtime.close()
    asyncio.run(exercise())


def test_mqtt_retry_reuses_command_id_after_lost_result(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module, protocol=protocol(
            {"volume": {"kind": "audio.master.volume", "parser": "volume"}}))
        runtime.overlay_event_type = ""
        runtime.command_attempt_timeout = 0.001
        sent = []

        async def publish(_hass, _topic, payload, **_kwargs):
            sent.append(json.loads(payload))
            if len(sent) == 2:
                runtime._result(result(sent[-1]))

        runtime_module.mqtt.async_publish.side_effect = publish
        await runtime.start()
        await runtime.send("volume", "42")
        assert len(sent) == 2
        assert sent[0] == sent[1]
        runtime.close()

    asyncio.run(exercise())


def test_ha_runtime_accepts_current_capabilities_and_monotonic_snapshot(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module, protocol=protocol({}))
        runtime.overlay_event_type = ""
        await runtime.start()
        capability = runtime_module.CapabilitiesMessage(
            "capabilities-new", "new-session", "pc", 2,
            (sys.modules["bridge_runtime_test.protocol"].Capability(
                "overlay.show", ("mqtt", "direct")
            ),),
        )
        runtime._mqtt_capabilities(SimpleNamespace(payload=capability.encode(), retain=True))
        assert runtime.protocol["session"] == "new-session"
        current = runtime_module.SnapshotMessage(
            "snapshot-4", "new-session", "pc", 4, 10.0,
            {"master_audio": {"volume": 0.7, "muted": False}}, {},
        )
        runtime._mqtt_snapshot(SimpleNamespace(payload=current.encode(), retain=True))
        stale = runtime_module.SnapshotMessage(
            "snapshot-3", "new-session", "pc", 3, 9.0,
            {"master_audio": {"volume": 0.2, "muted": False}}, {},
        )
        runtime._mqtt_snapshot(SimpleNamespace(payload=stale.encode(), retain=True))
        assert runtime.snapshot.revision == 4
        assert runtime.snapshot.state["master_audio"]["volume"] == 0.7
        runtime.close()

    asyncio.run(exercise())


def test_p2_r11_mqtt_result_uses_shared_utf8_byte_limit(runtime_module):
    async def exercise():
        runtime = make_runtime(runtime_module, protocol=protocol({}))

        large = {
            "version": 3,
            "type": "result",
            "id": "large-result",
            "session": "mqtt-session",
            "device_id": "pc",
            "status": "succeeded",
            "code": "",
            "data": {"text": "ą" * 4600},
        }
        encoded_large = json.dumps(
            large, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        assert len(encoded_large) > 9_000
        large_future = asyncio.get_running_loop().create_future()
        runtime.pending["large-result"] = large_future
        runtime._mqtt_result(SimpleNamespace(retain=False, payload=encoded_large))
        assert large_future.done()

        boundary = {**large, "id": "boundary-result", "data": {}}
        raw = json.dumps(boundary, separators=(",", ":")).encode()
        exact = raw + b" " * (runtime_module.MAX_CONTROL_BYTES - len(raw))
        assert len(exact) == runtime_module.MAX_CONTROL_BYTES
        boundary_future = asyncio.get_running_loop().create_future()
        runtime.pending["boundary-result"] = boundary_future
        runtime._mqtt_result(SimpleNamespace(retain=False, payload=exact + b" "))
        assert not boundary_future.done()
        runtime._mqtt_result(SimpleNamespace(retain=False, payload=exact))
        assert boundary_future.done()
        runtime.close()

    asyncio.run(exercise())
