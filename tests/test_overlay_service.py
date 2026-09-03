"""Exercise the HA action handler with API doubles on the Windows test runner."""

from __future__ import annotations

import ast
import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def service_harness(*, denied: str = ""):
    source = Path(__file__).parents[1] / "custom_components/ha_windows_bridge/__init__.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"async_setup", "_text_attribute"}
    ]
    publish = AsyncMock()
    image = AsyncMock(return_value="data:image/png;base64,TEST")
    namespace = {
        "json": json,
        "math": math,
        "DOMAIN": "ha_windows_bridge",
        "HomeAssistantError": RuntimeError,
        "POLICY_READ": "read",
        "POLICY_CONTROL": "control",
        "er": SimpleNamespace(async_get=lambda hass: hass.registry),
        "target_helpers": SimpleNamespace(
            TargetSelection=lambda data: data,
            async_extract_referenced_entity_ids=lambda *args, **kwargs: SimpleNamespace(
                referenced={"notify.pc_overlay"}, indirectly_referenced=set()
            ),
        ),
        "mqtt": SimpleNamespace(async_publish=publish),
        "_async_entity_image": image,
    }
    for action in ("SHOW", "UPDATE", "REMOVE", "CLEAR"):
        namespace[f"SERVICE_{action}_OVERLAY"] = f"{action.lower()}_overlay"
        namespace[f"_{action}_OVERLAY_SCHEMA"] = None
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    states = {
        "sensor.title": SimpleNamespace(state="Battery", attributes={}),
        "sensor.battery": SimpleNamespace(state="78", attributes={"formatted": "78%"}),
    }
    hass = SimpleNamespace(
        data={
            "ha_windows_bridge": {
                "pc": {"overlay_unique_id": "pc_overlay", "overlay_topic": "pc/overlay"}
            }
        },
        registry=SimpleNamespace(
            async_get=lambda entity_id: SimpleNamespace(
                config_entry_id="pc", unique_id="pc_overlay"
            )
        ),
        auth=SimpleNamespace(
            async_get_user=AsyncMock(
                return_value=SimpleNamespace(
                    permissions=SimpleNamespace(
                        check_entity=lambda entity_id, policy: entity_id != denied
                    )
                )
            )
        ),
        states=SimpleNamespace(get=states.get),
        services=SimpleNamespace(async_register=Mock()),
    )
    asyncio.run(namespace["async_setup"](hass, {}))
    handler = hass.services.async_register.call_args_list[0].args[2]

    def call(data: dict, action: str = "show_overlay"):
        asyncio.run(
            handler(
                SimpleNamespace(service=action, data=data, context=SimpleNamespace(user_id="user"))
            )
        )
        return json.loads(publish.call_args.args[2])

    return call, states, publish, image


@pytest.mark.parametrize("action", ["show_overlay", "update_overlay"])
def test_overlay_actions_resolve_entity_sources(action: str) -> None:
    call, _, _, _ = service_harness()
    payload = call(
        {
            "notification_id": "battery",
            "title_entity": "sensor.title",
            "message_entity": "sensor.battery",
            "message_attribute": "formatted",
            "progress_entity": "sensor.battery",
        },
        action,
    )
    assert payload["title"] == "Battery"
    assert payload["message"] == "78%"
    assert payload["data"] == {
        "progress": 78,
        "action": action.removesuffix("_overlay"),
        "id": "battery",
    }


def test_camera_can_be_shown_without_manual_text() -> None:
    call, _, _, image = service_harness()
    payload = call({"image_entity": "camera.driveway"})
    assert payload["data"]["image"] == "data:image/png;base64,TEST"
    assert payload["title"] == "Home Assistant"
    assert image.await_count == 1


@pytest.mark.parametrize(
    "field", ["title_entity", "message_entity", "progress_entity", "duration_entity"]
)
def test_source_permissions_are_enforced(field: str) -> None:
    call, _, publish, _ = service_harness(denied="sensor.battery")
    with pytest.raises(RuntimeError, match="Not authorized"):
        call({field: "sensor.battery"})
    publish.assert_not_called()


@pytest.mark.parametrize("value", ["unknown", "unavailable", "nan", "inf"])
def test_invalid_numeric_source_does_not_publish(value: str) -> None:
    call, states, publish, _ = service_harness()
    states["sensor.battery"].state = value
    with pytest.raises(RuntimeError, match="numeric value"):
        call({"progress_entity": "sensor.battery"})
    publish.assert_not_called()
