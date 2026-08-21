from __future__ import annotations

import ctypes
import os
import subprocess  # nosec B404
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import win32con
import win32gui
import win32process

# Security note: subprocess is used only for a fixed nvidia-smi path with shell=False.


@dataclass(frozen=True, slots=True)
class PcContext:
    process_name: str = ""
    window_title: str = ""
    fullscreen: bool = False
    idle_seconds: int = 0
    locked: bool = False


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    cpu_percent: float
    ram_percent: float
    uptime_seconds: int
    gpu_percent: float | None = None
    gpu_temperature: float | None = None
    gpu_power_watts: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None


class _LastInputInfo(ctypes.Structure):
    _fields_ = (("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint))


class WindowsSystemMonitor:
    """Reads user activity and lightweight system telemetry from Windows."""

    _PROTECTED_PROCESSES = frozenset(
        {
            "csrss.exe",
            "dwm.exe",
            "explorer.exe",
            "lsass.exe",
            "services.exe",
            "smss.exe",
            "svchost.exe",
            "wininit.exe",
            "winlogon.exe",
        }
    )

    def __init__(self) -> None:
        self._nvidia_smi = self._find_nvidia_smi()
        self._gpu_cache: dict[str, float] = {}
        self._gpu_cache_time = 0.0

    def context_snapshot(self) -> PcContext:
        process_name = ""
        window_title = ""
        fullscreen = False
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                window_title = win32gui.GetWindowText(hwnd).strip()
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process_name = psutil.Process(pid).name()
                fullscreen = self._is_fullscreen(hwnd)
        except (psutil.Error, OSError):
            pass
        return PcContext(
            process_name=process_name,
            window_title=window_title,
            fullscreen=fullscreen,
            idle_seconds=self.idle_seconds(),
            locked=self.is_locked(),
        )

    @staticmethod
    def idle_seconds() -> int:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        tick_count = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        elapsed_ms = (tick_count - info.dwTime) & 0xFFFFFFFF
        return max(0, elapsed_ms // 1000)

    @staticmethod
    def is_locked() -> bool:
        desktop = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            return True
        try:
            return not bool(ctypes.windll.user32.SwitchDesktop(desktop))
        finally:
            ctypes.windll.user32.CloseDesktop(desktop)

    @staticmethod
    def _is_fullscreen(hwnd: int) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return False
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            monitor = win32gui.MonitorFromWindow(hwnd, 2)
            monitor_left, monitor_top, monitor_right, monitor_bottom = win32gui.GetMonitorInfo(monitor)[
                "Monitor"
            ]
            tolerance = 2
            return (
                left <= monitor_left + tolerance
                and top <= monitor_top + tolerance
                and right >= monitor_right - tolerance
                and bottom >= monitor_bottom - tolerance
            )
        except Exception:
            return False

    def system_metrics(self, include_gpu: bool = True) -> SystemMetrics:
        gpu: dict[str, float] = {}
        if include_gpu:
            now = time.monotonic()
            if now - self._gpu_cache_time >= 10.0:
                self._gpu_cache = self._gpu_metrics()
                self._gpu_cache_time = now
            gpu = self._gpu_cache
        return SystemMetrics(
            cpu_percent=float(psutil.cpu_percent(interval=None)),
            ram_percent=float(psutil.virtual_memory().percent),
            uptime_seconds=max(0, int(time.time() - psutil.boot_time())),
            gpu_percent=gpu.get("gpu_percent"),
            gpu_temperature=gpu.get("gpu_temperature"),
            gpu_power_watts=gpu.get("gpu_power_watts"),
            gpu_memory_used_mb=gpu.get("gpu_memory_used_mb"),
            gpu_memory_total_mb=gpu.get("gpu_memory_total_mb"),
        )

    @staticmethod
    def running_process_names(process_names: list[str]) -> set[str]:
        """Return matching process names without relying on an audio session."""
        targets = {name.casefold() for name in process_names if name}
        if not targets:
            return set()
        running: set[str] = set()
        for process in psutil.process_iter(("name",)):
            try:
                name = (process.info.get("name") or "").casefold()
                if name in targets:
                    running.add(name)
            except (psutil.Error, KeyError, OSError, TypeError, ValueError):
                continue
        return running

    @staticmethod
    def _windows_apps_shell_target(executable_path: str) -> str:
        """Translate a protected Microsoft Store path into an AppsFolder target."""
        path = Path(executable_path)
        parts = path.parent.name.split("_")
        if "windowsapps" not in executable_path.casefold() or len(parts) < 5:
            return ""
        package_family = f"{parts[0]}_{parts[-1]}"
        app_id = path.stem
        return rf"shell:AppsFolder\{package_family}!{app_id}"

    @staticmethod
    def _shell_open(target: str) -> bool:
        try:
            result = ctypes.windll.shell32.ShellExecuteW(None, "open", target, None, None, 1)
            return int(result) > 32
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    @classmethod
    def start_application(
        cls,
        executable_path: str,
        process_name: str = "",
        display_name: str = "",
    ) -> bool:
        """Launch regular executables and packaged Microsoft Store applications."""
        if process_name and process_name.casefold() in cls.running_process_names([process_name]):
            return True

        package_target = cls._windows_apps_shell_target(executable_path)
        if package_target and cls._shell_open(package_target):
            return True

        path = Path(executable_path)
        if path.is_file() and cls._shell_open(str(path)):
            return True

        # Spotify installed from Microsoft Store registers this protocol even though
        # its executable lives in a directory that regular applications cannot open.
        return (
            "spotify" in f"{process_name} {display_name} {executable_path}".casefold()
            and cls._shell_open("spotify:")
        )

    @staticmethod
    def close_application(process_name: str) -> int:
        """Ask visible top-level windows owned by the application to close.

        WM_CLOSE gives the application a chance to save data or ask the user for
        confirmation.  Deliberately do not fall back to TerminateProcess here.
        """
        target = process_name.casefold()
        if target in WindowsSystemMonitor._PROTECTED_PROCESSES:
            return -1

        target_pids: set[int] = set()
        for process in psutil.process_iter(("pid", "name")):
            try:
                if (process.info.get("name") or "").casefold() != target:
                    continue
                target_pids.add(int(process.info["pid"]))
            except (psutil.Error, KeyError, OSError, TypeError, ValueError):
                continue

        notified_pids: set[int] = set()

        def request_close(hwnd: int, _extra: object) -> bool:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in target_pids:
                    return True
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                notified_pids.add(pid)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
            return True

        if target_pids:
            try:
                win32gui.EnumWindows(request_close, None)
            except (OSError, RuntimeError):
                return 0
        return len(notified_pids)

    @staticmethod
    def _find_nvidia_smi() -> str | None:
        fallback = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / (
            "NVIDIA Corporation/NVSMI/nvidia-smi.exe"
        )
        return str(fallback) if fallback.is_file() else None

    def _gpu_metrics(self) -> dict[str, float]:
        if not self._nvidia_smi:
            return {}
        command = [
            self._nvidia_smi,
            "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            # The executable path is fixed and this call never invokes a shell.
            completed = subprocess.run(  # nosec B603
                command,
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
                creationflags=flags,
            )
            values = [float(value.strip()) for value in completed.stdout.splitlines()[0].split(",")]
            if len(values) != 5:
                return {}
            return dict(
                zip(
                    (
                        "gpu_percent",
                        "gpu_temperature",
                        "gpu_power_watts",
                        "gpu_memory_used_mb",
                        "gpu_memory_total_mb",
                    ),
                    values,
                    strict=True,
                )
            )
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return {}
