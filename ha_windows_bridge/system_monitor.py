from __future__ import annotations

import ctypes
import json
import math
import os
import subprocess  # nosec B404
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import win32con
import win32gui
import win32process

# Security note: subprocess is used only for fixed, trusted executable paths with shell=False.


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
    cpu_frequency_mhz: float | None = None
    cpu_temperature: float | None = None
    cpu_power_watts: float | None = None
    gpu_clock_mhz: float | None = None
    gpu_fan_rpm: float | None = None
    cpu_vendor: str = ""
    gpu_vendor: str = ""
    ram_used_gb: float | None = None
    ram_available_gb: float | None = None
    ram_total_gb: float | None = None


@dataclass(frozen=True, slots=True)
class WindowsHealth:
    battery_percent: float | None = None
    on_ac_power: bool | None = None
    pending_restart: bool = False
    power_plan: str = ""
    windows_update_status: str = "Checking"
    uptime_seconds: int = 0


@dataclass(frozen=True, slots=True)
class DiskMetrics:
    used_percent: float
    free_gb: float
    read_mb_s: float
    write_mb_s: float
    health: str = ""
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class DiskVolume:
    mountpoint: str
    device: str
    file_system: str
    total_gb: float
    used_percent: float
    free_gb: float


@dataclass(frozen=True, slots=True)
class PnpDevice:
    instance_id: str
    display_name: str
    category: str
    present: bool = True


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
        self._hardware_identity_cache: tuple[str, str] | None = None
        self._last_disk_io: tuple[float, int, int] | None = None
        self._disk_health_cache: tuple[str, float | None] = ("", None)
        self._disk_health_cache_time = 0.0
        self._pending_updates: int | None = None
        self._update_check_time = 0.0
        self._update_thread: threading.Thread | None = None

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
            monitor_left, monitor_top, monitor_right, monitor_bottom = win32gui.GetMonitorInfo(
                monitor
            )["Monitor"]
            tolerance = 2
            return (
                left <= monitor_left + tolerance
                and top <= monitor_top + tolerance
                and right >= monitor_right - tolerance
                and bottom >= monitor_bottom - tolerance
            )
        except Exception:
            return False

    def system_metrics(
        self,
        include_cpu: bool = True,
        include_gpu: bool = True,
        include_ram: bool = True,
    ) -> SystemMetrics:
        gpu: dict[str, float] = {}
        if include_gpu:
            now = time.monotonic()
            if now - self._gpu_cache_time >= 10.0:
                self._gpu_cache = self._gpu_metrics()
                self._gpu_cache_time = now
            gpu = self._gpu_cache
        optional = self._hardware_monitor_metrics() if include_cpu or include_gpu else {}
        if include_gpu:
            gpu.update(
                {
                    key: value
                    for key, value in optional.items()
                    if key.startswith("gpu_") and value is not None
                }
            )
        cpu_vendor, gpu_vendor = (
            self._hardware_identity() if include_cpu or include_gpu else ("", "")
        )
        frequency = psutil.cpu_freq() if include_cpu else None
        memory = psutil.virtual_memory() if include_ram else None
        gibibyte = 1024**3
        return SystemMetrics(
            cpu_percent=float(psutil.cpu_percent(interval=None)) if include_cpu else 0.0,
            ram_percent=float(memory.percent) if memory is not None else 0.0,
            uptime_seconds=max(0, int(time.time() - psutil.boot_time())),
            gpu_percent=gpu.get("gpu_percent"),
            gpu_temperature=gpu.get("gpu_temperature"),
            gpu_power_watts=gpu.get("gpu_power_watts"),
            gpu_memory_used_mb=gpu.get("gpu_memory_used_mb"),
            gpu_memory_total_mb=gpu.get("gpu_memory_total_mb"),
            cpu_frequency_mhz=float(frequency.current) if frequency else None,
            cpu_temperature=optional.get("cpu_temperature") if include_cpu else None,
            cpu_power_watts=optional.get("cpu_power_watts") if include_cpu else None,
            gpu_clock_mhz=gpu.get("gpu_clock_mhz"),
            gpu_fan_rpm=gpu.get("gpu_fan_rpm"),
            cpu_vendor=cpu_vendor if include_cpu else "",
            gpu_vendor=gpu_vendor if include_gpu and gpu_vendor in {"NVIDIA", "AMD"} else "",
            ram_used_gb=float(memory.used) / gibibyte if memory is not None else None,
            ram_available_gb=(
                float(memory.available) / gibibyte if memory is not None else None
            ),
            ram_total_gb=float(memory.total) / gibibyte if memory is not None else None,
        )

    def windows_health(self) -> WindowsHealth:
        self._schedule_windows_update_check()
        try:
            battery = psutil.sensors_battery()
        except (AttributeError, OSError, RuntimeError):
            battery = None
        battery_percent: float | None = None
        on_ac_power: bool | None = None
        if battery is not None:
            try:
                raw_percent = getattr(battery, "percent", None)
                if raw_percent is not None:
                    battery_percent = float(raw_percent)
                raw_power = getattr(battery, "power_plugged", None)
                if raw_power is not None:
                    on_ac_power = bool(raw_power)
            except (TypeError, ValueError):
                battery_percent = None
                on_ac_power = None
        pending_restart = self._pending_restart()
        if pending_restart:
            update_status = "Restart required"
        elif self._pending_updates is None:
            update_status = "Checking"
        elif self._pending_updates:
            update_status = f"{self._pending_updates} update(s) available"
        else:
            update_status = "Up to date"
        return WindowsHealth(
            battery_percent=battery_percent,
            on_ac_power=on_ac_power,
            pending_restart=pending_restart,
            power_plan=self._active_power_plan(),
            windows_update_status=update_status,
            uptime_seconds=max(0, int(time.time() - psutil.boot_time())),
        )

    def _schedule_windows_update_check(self) -> None:
        """Refresh Windows Update in a daemon so monitoring never blocks on the service."""
        now = time.monotonic()
        if self._update_thread is not None and self._update_thread.is_alive():
            return
        if now - self._update_check_time < 30 * 60:
            return
        self._update_check_time = now
        self._update_thread = threading.Thread(
            target=self._read_pending_windows_updates,
            name="windows-update-check",
            daemon=True,
        )
        self._update_thread.start()

    def _read_pending_windows_updates(self) -> None:
        initialized = False
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            initialized = True
            session = win32com.client.Dispatch("Microsoft.Update.Session")
            searcher = session.CreateUpdateSearcher()
            result = searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
            self._pending_updates = max(0, int(result.Updates.Count))
        except Exception:
            self._pending_updates = None
        finally:
            if initialized:
                pythoncom.CoUninitialize()

    @staticmethod
    def list_disk_volumes() -> list[DiskVolume]:
        """Return mounted fixed volumes suitable for user selection."""
        volumes: list[DiskVolume] = []
        seen: set[str] = set()
        for partition in psutil.disk_partitions(all=False):
            mountpoint = os.path.normpath(str(partition.mountpoint).strip())
            key = os.path.normcase(mountpoint)
            if not mountpoint or key in seen:
                continue
            try:
                usage = psutil.disk_usage(mountpoint)
            except (OSError, PermissionError):
                continue
            if usage.total <= 0:
                continue
            seen.add(key)
            volumes.append(
                DiskVolume(
                    mountpoint=mountpoint,
                    device=str(partition.device or mountpoint),
                    file_system=str(partition.fstype or ""),
                    total_gb=usage.total / 1_073_741_824,
                    used_percent=float(usage.percent),
                    free_gb=usage.free / 1_073_741_824,
                )
            )
        return sorted(volumes, key=lambda item: item.mountpoint.casefold())

    def disk_metrics(self, mounts: list[str] | None = None) -> DiskMetrics:
        volumes = self.list_disk_volumes()
        selected = {os.path.normcase(os.path.normpath(mount)) for mount in (mounts or []) if mount}
        if selected:
            volumes = [
                item
                for item in volumes
                if os.path.normcase(os.path.normpath(item.mountpoint)) in selected
            ]
        total = sum(item.total_gb for item in volumes)
        free = sum(item.free_gb for item in volumes)
        used = max(0.0, total - free)

        now = time.monotonic()
        io = psutil.disk_io_counters()
        read_rate = write_rate = 0.0
        if io is not None and self._last_disk_io is not None:
            previous_time, previous_read, previous_write = self._last_disk_io
            elapsed = max(0.001, now - previous_time)
            read_rate = max(0, io.read_bytes - previous_read) / elapsed / 1_048_576
            write_rate = max(0, io.write_bytes - previous_write) / elapsed / 1_048_576
        if io is not None:
            self._last_disk_io = (now, io.read_bytes, io.write_bytes)
        if now - self._disk_health_cache_time >= 60.0:
            self._disk_health_cache = self._physical_disk_health()
            self._disk_health_cache_time = now
        return DiskMetrics(
            used_percent=(used / total * 100.0) if total else 0.0,
            free_gb=free,
            read_mb_s=read_rate,
            write_mb_s=write_rate,
            health=self._disk_health_cache[0],
            temperature=self._disk_health_cache[1],
        )

    @staticmethod
    def _physical_disk_health() -> tuple[str, float | None]:
        health = ""
        temperature: float | None = None
        try:
            import win32com.client

            storage = win32com.client.GetObject(r"winmgmts:\\.\root\Microsoft\Windows\Storage")
            statuses: list[int] = []
            temperatures: list[float] = []
            for disk in storage.ExecQuery("SELECT HealthStatus,Temperature FROM MSFT_PhysicalDisk"):
                raw_status = getattr(disk, "HealthStatus", None)
                statuses.append(int(raw_status) if raw_status is not None else 5)
                raw_temperature = getattr(disk, "Temperature", None)
                if raw_temperature is not None:
                    value = float(raw_temperature)
                    if 0 < value < 150:
                        temperatures.append(value)
            if statuses:
                worst = max(statuses)
                health = {0: "Healthy", 1: "Warning", 2: "Unhealthy"}.get(worst, "Unknown")
            if temperatures:
                temperature = max(temperatures)
        # The optional Storage WMI provider is not present on every supported PC.
        except Exception:  # nosec B110
            pass
        if not health:
            try:
                import win32com.client

                wmi = win32com.client.GetObject(r"winmgmts:\\.\root\wmi")
                predictions = list(
                    wmi.ExecQuery("SELECT PredictFailure FROM MSStorageDriver_FailurePredictStatus")
                )
                if predictions:
                    health = (
                        "Warning"
                        if any(bool(getattr(item, "PredictFailure", False)) for item in predictions)
                        else "Healthy"
                    )
            # Legacy SMART WMI is also optional and driver-dependent.
            except Exception:  # nosec B110
                pass
        return health, temperature

    @classmethod
    def list_pnp_devices(cls, include_disconnected: bool = False) -> list[PnpDevice]:
        """Return physical/user-facing peripherals, optionally including device history."""
        if include_disconnected:
            historical = cls._pnp_devices_from_powershell()
            if historical:
                return cls._sorted_pnp_devices(historical)

        devices: dict[str, PnpDevice] = {}
        try:
            import win32com.client

            service = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            query = (
                "SELECT PNPDeviceID,Name,PNPClass,Present,ConfigManagerErrorCode "
                "FROM Win32_PnPEntity"
            )
            for item in service.ExecQuery(query):
                instance_id = str(getattr(item, "PNPDeviceID", "") or "").strip()
                name = str(getattr(item, "Name", "") or "").strip()
                category = str(getattr(item, "PNPClass", "") or "Device").strip()
                if not cls._is_user_facing_pnp_device(instance_id, name, category):
                    continue
                raw_present = getattr(item, "Present", None)
                present = (
                    bool(raw_present)
                    if raw_present is not None
                    else int(getattr(item, "ConfigManagerErrorCode", 0) or 0) == 0
                )
                devices[instance_id.casefold()] = PnpDevice(instance_id, name, category, present)
        except Exception:
            return []
        return cls._sorted_pnp_devices(devices)

    @classmethod
    def _pnp_devices_from_powershell(cls) -> dict[str, PnpDevice]:
        """Read connected and remembered PnP devices from Windows' signed cmdlet."""
        system_root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        powershell = system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if not powershell.is_file():
            return {}
        script = (
            "$OutputEncoding=[Console]::OutputEncoding="
            "[System.Text.UTF8Encoding]::new($false);"
            "@(Get-PnpDevice -ErrorAction Stop | Select-Object "
            "@{n='category';e={$_.Class}},@{n='name';e={$_.FriendlyName}},"
            "@{n='instance_id';e={$_.InstanceId}},@{n='present';e={[bool]$_.Present}})"
            "|ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(  # nosec B603
                [
                    str(powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                capture_output=True,
                timeout=20,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            raw_output = completed.stdout or b""
            text = (
                raw_output.decode("utf-8-sig", errors="strict")
                if isinstance(raw_output, bytes)
                else str(raw_output)
            )
            payload = json.loads(text)
        except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError):
            return {}

        rows = payload if isinstance(payload, list) else [payload]
        devices: dict[str, PnpDevice] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            instance_id = str(row.get("instance_id", "") or "").strip()
            name = str(row.get("name", "") or "").strip()
            category = str(row.get("category", "") or "Device").strip()
            if not cls._is_user_facing_pnp_device(instance_id, name, category):
                continue
            devices[instance_id.casefold()] = PnpDevice(
                instance_id,
                name,
                category,
                bool(row.get("present", False)),
            )
        return devices

    @staticmethod
    def _is_user_facing_pnp_device(instance_id: str, name: str, category: str) -> bool:
        if not instance_id or not name:
            return False
        category_key = category.casefold()
        allowed = {
            "audioendpoint",
            "battery",
            "bluetooth",
            "camera",
            "diskdrive",
            "hidclass",
            "image",
            "monitor",
            "ports",
            "printer",
            "printqueue",
            "sensor",
            "smartcardreader",
            "usb",
            "usbdevice",
            "wpd",
        }
        if category_key not in allowed:
            return False

        identity = instance_id.casefold()
        label = name.casefold().strip()
        if category_key == "bluetooth" and not identity.startswith(
            ("bthenum\\dev_", "bthle\\dev_", "usb\\vid_")
        ):
            return False

        if category_key == "hidclass":
            generic_hid_names = {
                "hid-compliant game controller",
                "hid-compliant consumer control device",
                "hid-compliant device",
                "hid-compliant system controller",
                "hid-compliant vendor-defined device",
                "usb input device",
                "kontroler gier zgodny z hid",
                "kontroler systemu zgodny z hid",
                "urządzenie hid zgodne z interfejsem xinput",
                "urządzenie hid wirtualnej struktury hid (vhf)",
                "urządzenie sterujące użytkownika zgodne z hid",
                "urządzenie zgodne z hid",
                "urządzenie wejściowe usb",
                "urządzenie zgodne ze standardem hid",
                "urządzenie zdefiniowane przez dostawcę zgodne z hid",
            }
            recognizable_hid_terms = (
                "flight stick",
                "gamepad",
                "joystick",
                "racing wheel",
                "steering wheel",
                "kierownica",
            )
            if label in generic_hid_names or not any(
                fragment in label for fragment in recognizable_hid_terms
            ):
                return False

        if category_key == "printqueue":
            virtual_printer_names = (
                "adobe pdf",
                "fax",
                "microsoft print",
                "onenote",
                "root print queue",
                "solid edge ps printer",
                "xps document writer",
                "główna kolejka wydruku",
            )
            if any(fragment in label for fragment in virtual_printer_names):
                return False

        infrastructure_names = (
            "generic usb hub",
            "host controller",
            "root hub",
            "usb composite device",
            "główny koncentrator usb",
            "kontroler hosta",
            "rodzajowy koncentrator usb",
            "urządzenie kompozytowe usb",
        )
        return not (
            category_key in {"usb", "usbdevice"}
            and (
                identity.startswith(("pci\\", "root\\", "usb\\root_hub"))
                or any(fragment in label for fragment in infrastructure_names)
            )
        )

    @staticmethod
    def _sorted_pnp_devices(devices: dict[str, PnpDevice]) -> list[PnpDevice]:
        visible: dict[tuple[str, str], PnpDevice] = {}
        collapse_by_name = {"audioendpoint", "bluetooth", "monitor"}
        for device in devices.values():
            category = device.category.casefold()
            key = (
                (category, device.display_name.casefold())
                if category in collapse_by_name
                else (category, device.instance_id.casefold())
            )
            previous = visible.get(key)
            if previous is None or (device.present and not previous.present):
                visible[key] = device
        return sorted(
            visible.values(),
            key=lambda item: (
                not item.present,
                item.category.casefold(),
                item.display_name.casefold(),
            ),
        )[:300]

    @classmethod
    def present_device_ids(cls) -> set[str]:
        return {
            device.instance_id.casefold() for device in cls.list_pnp_devices() if device.present
        }

    @staticmethod
    def _pending_restart() -> bool:
        try:
            import winreg

            keys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
            )
            for key in keys:
                try:
                    handle = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_READ)
                    winreg.CloseKey(handle)
                    return True
                except FileNotFoundError:
                    continue
        except OSError:
            pass
        return False

    @staticmethod
    def _active_power_plan() -> str:
        system_root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        powercfg = system_root / "System32/powercfg.exe"
        if not powercfg.is_file():
            return ""
        try:
            completed = subprocess.run(  # nosec B603
                [str(powercfg), "/getactivescheme"],
                capture_output=True,
                timeout=2,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            raw_output = completed.stdout or b""
            if isinstance(raw_output, bytes):
                if raw_output.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw_output:
                    text = raw_output.decode("utf-16", errors="replace").strip()
                else:
                    text = raw_output.decode("oem", errors="replace").strip()
            else:
                text = str(raw_output).strip()
            if not text:
                return ""
            if "(" in text and ")" in text:
                return text.rsplit("(", 1)[-1].split(")", 1)[0].strip()[:120]
            return text[:120]
        except (OSError, subprocess.SubprocessError):
            return ""

    def _hardware_identity(self) -> tuple[str, str]:
        if self._hardware_identity_cache is not None:
            return self._hardware_identity_cache
        cpu_vendor = gpu_vendor = ""
        try:
            import win32com.client

            service = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            processors = list(service.ExecQuery("SELECT Manufacturer FROM Win32_Processor"))
            adapters = list(service.ExecQuery("SELECT Name FROM Win32_VideoController"))
            cpu_vendor = str(getattr(processors[0], "Manufacturer", "") or "") if processors else ""
            names = " ".join(str(getattr(item, "Name", "") or "") for item in adapters).casefold()
            if "nvidia" in names:
                gpu_vendor = "NVIDIA"
            elif "amd" in names or "radeon" in names:
                gpu_vendor = "AMD"
            elif "intel" in names:
                gpu_vendor = "Intel"
        # Hardware identity is a best-effort diagnostic only.
        except Exception:  # nosec B110
            pass
        self._hardware_identity_cache = (cpu_vendor[:80], gpu_vendor)
        return self._hardware_identity_cache

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
        """Locate NVIDIA's signed utility in trusted Windows installation folders."""
        system_root = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        candidates = [system_root / "System32/nvidia-smi.exe"]
        for variable in ("ProgramW6432", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "NVIDIA Corporation/NVSMI/nvidia-smi.exe")

        seen: set[str] = set()
        for candidate in candidates:
            normalized = os.path.normcase(os.path.abspath(candidate))
            if normalized in seen:
                continue
            seen.add(normalized)
            if candidate.is_file():
                return str(candidate)
        return None

    def _gpu_metrics(self) -> dict[str, float]:
        _cpu_vendor, gpu_vendor = self._hardware_identity()
        if gpu_vendor == "AMD":
            return self._windows_gpu_metrics()
        if gpu_vendor != "NVIDIA" and not self._nvidia_smi:
            return {}
        if not self._nvidia_smi:
            return {}
        command = [
            self._nvidia_smi,
            "--query-gpu=utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,clocks.current.graphics,fan.speed",
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
            raw_values = completed.stdout.splitlines()[0].split(",")
            keys = (
                "gpu_percent",
                "gpu_temperature",
                "gpu_power_watts",
                "gpu_memory_used_mb",
                "gpu_memory_total_mb",
                "gpu_clock_mhz",
                "gpu_fan_rpm",
            )
            if len(raw_values) != len(keys):
                return {}
            metrics: dict[str, float] = {}
            for key, raw_value in zip(keys, raw_values, strict=True):
                try:
                    value = float(raw_value.strip())
                except ValueError:
                    continue
                if math.isfinite(value):
                    metrics[key] = value
            return metrics
        except (OSError, subprocess.SubprocessError, IndexError):
            return {}

    def _windows_gpu_metrics(self) -> dict[str, float]:
        """Read AMD GPU data from vendor-neutral Windows performance counters."""
        _cpu_vendor, gpu_vendor = self._hardware_identity()
        if gpu_vendor != "AMD":
            return {}
        metrics: dict[str, float] = {}
        try:
            import win32com.client

            service = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
            engines: Any = service.ExecQuery(
                "SELECT Name,UtilizationPercentage FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine"
            )
            loads = [
                float(getattr(item, "UtilizationPercentage", 0) or 0)
                for item in engines
                if "engtype_3d" in str(getattr(item, "Name", "")).casefold()
            ]
            if loads:
                metrics["gpu_percent"] = min(100.0, max(loads))
            memories: Any = service.ExecQuery(
                "SELECT DedicatedUsage FROM Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory"
            )
            used = sum(float(getattr(item, "DedicatedUsage", 0) or 0) for item in memories)
            if used > 0:
                metrics["gpu_memory_used_mb"] = used / 1_048_576
        except Exception:
            return {}
        return metrics

    @staticmethod
    def _hardware_monitor_metrics() -> dict[str, float]:
        """Read an optional Libre/OpenHardwareMonitor WMI provider when present."""
        for namespace in ("LibreHardwareMonitor", "OpenHardwareMonitor"):
            try:
                import win32com.client

                service = win32com.client.GetObject(rf"winmgmts:\\.\root\{namespace}")
                hardware = {
                    str(getattr(item, "Identifier", "")): str(
                        getattr(item, "HardwareType", "")
                    ).casefold()
                    for item in service.ExecQuery("SELECT Identifier,HardwareType FROM Hardware")
                }
                metrics: dict[str, float] = {}
                for sensor in service.ExecQuery("SELECT Name,SensorType,Value,Parent FROM Sensor"):
                    parent = str(getattr(sensor, "Parent", ""))
                    kind = hardware.get(parent, "")
                    sensor_type = str(getattr(sensor, "SensorType", "")).casefold()
                    name = str(getattr(sensor, "Name", "")).casefold()
                    try:
                        value = float(getattr(sensor, "Value", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    if not math.isfinite(value):
                        continue
                    if "cpu" in kind:
                        if sensor_type == "temperature" and (
                            "package" in name or "core max" in name
                        ):
                            metrics["cpu_temperature"] = max(
                                value, metrics.get("cpu_temperature", value)
                            )
                        elif sensor_type == "power" and ("package" in name or "cores" in name):
                            metrics["cpu_power_watts"] = max(
                                value, metrics.get("cpu_power_watts", value)
                            )
                    elif (
                        "gpuamd" in kind
                        or "gpuati" in kind
                        or (
                            "gpu" in kind
                            and any(vendor in parent.casefold() for vendor in ("amd", "ati"))
                        )
                    ):
                        if sensor_type == "load" and "core" in name:
                            metrics["gpu_percent"] = value
                        elif sensor_type == "temperature" and "core" in name:
                            metrics["gpu_temperature"] = value
                        elif sensor_type == "power" and ("core" in name or "total" in name):
                            metrics["gpu_power_watts"] = max(
                                value, metrics.get("gpu_power_watts", value)
                            )
                        elif sensor_type == "clock" and "core" in name:
                            metrics["gpu_clock_mhz"] = value
                        elif sensor_type == "fan":
                            metrics["gpu_fan_rpm"] = max(value, metrics.get("gpu_fan_rpm", value))
                        elif sensor_type in {"data", "smalldata"} and "memory used" in name:
                            metrics["gpu_memory_used_mb"] = value
                return metrics
            # Try the next optional sensor provider when this namespace is unavailable.
            except Exception:  # nosec B112
                continue
        return {}
