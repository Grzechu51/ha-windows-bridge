from types import SimpleNamespace

import pytest
from test_ha_lifecycle import load_function


def test_websocket_scope_requires_control_permission_for_exact_device():
    runtime = SimpleNamespace(device_id="pc", overlay_event_type="direct", overlay_unique_id="popup")
    registry = SimpleNamespace(async_get_entity_id=lambda platform, domain, identity: "notify.pc_popup" if identity == "popup" else None)
    namespace = {"DOMAIN": "ha_windows_bridge", "POLICY_CONTROL": "control", "Unauthorized": PermissionError,
                 "HomeAssistantError": RuntimeError, "er": SimpleNamespace(async_get=lambda hass: registry)}
    authorize = load_function("websocket.py", "authorized_runtime", namespace)
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda domain: [SimpleNamespace(runtime_data=runtime)]))
    checked = []
    connection = SimpleNamespace(user=SimpleNamespace(permissions=SimpleNamespace(check_entity=lambda entity, policy: checked.append((entity, policy)) or True)))
    assert authorize(hass, connection, "pc") is runtime
    assert checked == [("notify.pc_popup", "control")]
    with pytest.raises(RuntimeError):
        authorize(hass, connection, "another-pc")
    connection.user.permissions.check_entity = lambda *args: False
    with pytest.raises(PermissionError):
        authorize(hass, connection, "pc")


def test_another_socket_cannot_complete_command_or_extend_lease():
    # HA dispatch decorators only attach schemas; test the handler authorization itself.
    import ast
    from pathlib import Path
    source = Path(__file__).parents[1] / "custom_components/ha_windows_bridge/websocket.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    runtime = SimpleNamespace(owner=object())
    namespace = {"authorized_runtime": lambda *args: runtime, "Unauthorized": PermissionError}
    for name in ("result", "heartbeat"):
        node = next(item for item in tree.body if getattr(item, "name", None) == name)
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)  # noqa: S102
        with pytest.raises(PermissionError):
            namespace[name](object(), object(), {"device_id": "pc"})
