from __future__ import annotations

import subprocess

from ha_windows_bridge.system_actions import WindowsPowerActions


def test_restart_uses_fixed_windows_tool_and_safe_arguments(tmp_path) -> None:
    shutdown = tmp_path / "System32" / "shutdown.exe"
    shutdown.parent.mkdir(parents=True)
    shutdown.write_bytes(b"MZ")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    actions = WindowsPowerActions(runner=runner, system_root=tmp_path)

    ok, detail = actions.execute("restart")

    assert ok is True
    assert detail == "Restart scheduled in 30 seconds"
    assert calls[0][0][0] == str(shutdown)
    assert calls[0][0][1:4] == ["/r", "/t", "30"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 5


def test_unknown_power_action_is_never_executed(tmp_path) -> None:
    calls = []
    actions = WindowsPowerActions(
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        system_root=tmp_path,
    )

    ok, detail = actions.execute("format-drive")

    assert ok is False
    assert detail == "Unsupported power action"
    assert calls == []


def test_shutdown_action_fails_when_windows_tool_is_missing(tmp_path) -> None:
    actions = WindowsPowerActions(system_root=tmp_path)

    ok, detail = actions.execute("shutdown")

    assert ok is False
    assert detail == "Windows shutdown tool was not found"
