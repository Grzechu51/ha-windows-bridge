from __future__ import annotations

import ctypes
import os
import subprocess  # nosec B404
from collections.abc import Callable, Sequence
from pathlib import Path

POWER_ACTIONS = frozenset({"lock", "sleep", "restart", "shutdown", "cancel"})
CREATE_NO_WINDOW = 0x08000000


class WindowsPowerActions:
    """Execute a small, fixed allow-list of Windows session and power actions."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        system_root: Path | None = None,
    ) -> None:
        root = system_root or Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        self._shutdown_exe = root / "System32" / "shutdown.exe"
        self._runner = runner

    def execute(self, action: str) -> tuple[bool, str]:
        action = action.strip().lower()
        if action not in POWER_ACTIONS:
            return False, "Unsupported power action"
        if action == "lock":
            return self._lock()
        if action == "sleep":
            return self._sleep()
        if action == "cancel":
            return self._shutdown_command(("/a",), "Scheduled power action cancelled")
        if action == "restart":
            return self._shutdown_command(
                (
                    "/r",
                    "/t",
                    "30",
                    "/d",
                    "p:0:0",
                    "/c",
                    "HA Windows Bridge: restart requested from Home Assistant",
                ),
                "Restart scheduled in 30 seconds",
            )
        return self._shutdown_command(
            (
                "/s",
                "/t",
                "30",
                "/d",
                "p:0:0",
                "/c",
                "HA Windows Bridge: shutdown requested from Home Assistant",
            ),
            "Shutdown scheduled in 30 seconds",
        )

    @staticmethod
    def _lock() -> tuple[bool, str]:
        try:
            ok = bool(ctypes.windll.user32.LockWorkStation())
        except (AttributeError, OSError):
            ok = False
        return ok, "Windows locked" if ok else "Windows could not be locked"

    @staticmethod
    def _sleep() -> tuple[bool, str]:
        try:
            ok = bool(ctypes.windll.powrprof.SetSuspendState(False, True, False))
        except (AttributeError, OSError):
            ok = False
        return ok, "Sleep requested" if ok else "Sleep could not be requested"

    def _shutdown_command(
        self,
        arguments: Sequence[str],
        success_message: str,
    ) -> tuple[bool, str]:
        if not self._shutdown_exe.is_file():
            return False, "Windows shutdown tool was not found"
        try:
            result = self._runner(
                [str(self._shutdown_exe), *arguments],
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )  # nosec B603
        except (OSError, subprocess.SubprocessError):
            return False, "Windows rejected the power action"
        if result.returncode:
            return False, "Windows rejected the power action"
        return True, success_message
