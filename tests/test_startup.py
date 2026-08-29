from __future__ import annotations

import sys

from ha_windows_bridge.startup import WindowsStartupManager


def test_windows_startup_marks_launch_as_autostart(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\HA Windows Bridge\app.exe")

    command = WindowsStartupManager.command()

    assert '"C:\\Program Files\\HA Windows Bridge\\app.exe"' in command
    assert "--autostart" in command
    assert "--minimized" not in command
