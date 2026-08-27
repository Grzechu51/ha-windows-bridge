from __future__ import annotations

from types import SimpleNamespace

from ha_windows_bridge.system_monitor import WindowsSystemMonitor


def test_context_snapshot_has_safe_windows_values() -> None:
    snapshot = WindowsSystemMonitor().context_snapshot()
    assert snapshot.idle_seconds >= 0
    assert isinstance(snapshot.locked, bool)
    assert isinstance(snapshot.fullscreen, bool)


def test_missing_application_is_not_started(tmp_path) -> None:
    assert WindowsSystemMonitor.start_application(str(tmp_path / "missing.exe")) is False


def test_store_spotify_path_is_started_through_apps_folder(monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(
        WindowsSystemMonitor,
        "_shell_open",
        staticmethod(lambda target: opened.append(target) or True),
    )
    path = (
        r"C:\Program Files\WindowsApps\SpotifyAB.SpotifyMusic_1.2.3.0_x64__zpdnekdrzrea0"
        r"\Spotify.exe"
    )

    assert WindowsSystemMonitor.start_application(path, display_name="Spotify") is True
    assert opened == [r"shell:AppsFolder\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"]


def test_running_process_names_is_case_insensitive(monkeypatch) -> None:
    processes = [
        SimpleNamespace(info={"name": "Discord.exe"}),
        SimpleNamespace(info={"name": "chrome.exe"}),
    ]
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.psutil.process_iter",
        lambda _attrs: processes,
    )

    assert WindowsSystemMonitor.running_process_names(["discord.EXE"]) == {"discord.exe"}


def test_close_application_requests_graceful_close_for_matching_windows(monkeypatch) -> None:
    spotify = SimpleNamespace(info={"pid": 10, "name": "Spotify.exe"})
    chrome = SimpleNamespace(info={"pid": 20, "name": "chrome.exe"})
    posted = []
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.psutil.process_iter",
        lambda _attrs: [spotify, chrome],
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.win32gui.EnumWindows",
        lambda callback, extra: [callback(hwnd, extra) for hwnd in (100, 200)],
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.win32gui.IsWindowVisible",
        lambda _hwnd: True,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.win32process.GetWindowThreadProcessId",
        lambda hwnd: (1, 10 if hwnd == 100 else 20),
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.win32gui.PostMessage",
        lambda hwnd, message, wparam, lparam: posted.append((hwnd, message, wparam, lparam)),
    )

    assert WindowsSystemMonitor.close_application("spotify.exe") == 1
    assert len(posted) == 1
    assert posted[0][0] == 100


def test_remote_close_refuses_protected_windows_process(monkeypatch) -> None:
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.psutil.process_iter",
        lambda _attrs: (_ for _ in ()).throw(AssertionError("process list must not be scanned")),
    )

    assert WindowsSystemMonitor.close_application("explorer.exe") == -1


def test_nvidia_smi_is_found_in_system32(monkeypatch, tmp_path) -> None:
    system_root = tmp_path / "Windows"
    executable = system_root / "System32" / "nvidia-smi.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("SYSTEMROOT", str(system_root))

    assert WindowsSystemMonitor._find_nvidia_smi() == str(executable)


def test_nvidia_metrics_are_parsed(monkeypatch) -> None:
    monitor = WindowsSystemMonitor()
    monitor._nvidia_smi = "nvidia-smi"
    monkeypatch.setattr(monitor, "_hardware_identity", lambda: ("Intel", "NVIDIA"))
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="97, 71, 238.5, 6800, 8192, 2100, 1450\n"
        ),
    )

    metrics = monitor._gpu_metrics()

    assert metrics["gpu_percent"] == 97
    assert metrics["gpu_temperature"] == 71
    assert metrics["gpu_power_watts"] == 238.5
    assert metrics["gpu_memory_used_mb"] == 6800
    assert metrics["gpu_clock_mhz"] == 2100
    assert metrics["gpu_fan_rpm"] == 1450


def test_nvidia_metrics_keep_supported_values_when_one_field_is_unavailable(monkeypatch) -> None:
    monitor = WindowsSystemMonitor()
    monitor._nvidia_smi = "nvidia-smi"
    monkeypatch.setattr(monitor, "_hardware_identity", lambda: ("AMD", "NVIDIA"))
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="42, 65, [N/A], 1024, 8192, 1800, [N/A]\n"
        ),
    )

    metrics = monitor._gpu_metrics()

    assert metrics["gpu_percent"] == 42
    assert metrics["gpu_temperature"] == 65
    assert "gpu_power_watts" not in metrics


def test_gpu_metrics_are_cached_for_ten_seconds(monkeypatch) -> None:
    monitor = WindowsSystemMonitor()
    calls = []
    monkeypatch.setattr(
        monitor,
        "_gpu_metrics",
        lambda: calls.append(True) or {"gpu_percent": 42.0},
    )
    moments = iter([20.0, 25.0, 31.0])
    monkeypatch.setattr("ha_windows_bridge.system_monitor.time.monotonic", lambda: next(moments))

    assert monitor.system_metrics().gpu_percent == 42.0
    assert monitor.system_metrics().gpu_percent == 42.0
    assert monitor.system_metrics().gpu_percent == 42.0
    assert len(calls) == 2


def test_windows_update_status_is_derived_without_blocking(monkeypatch) -> None:
    monitor = WindowsSystemMonitor()
    monkeypatch.setattr(monitor, "_schedule_windows_update_check", lambda: None)
    monkeypatch.setattr(monitor, "_pending_restart", lambda: False)
    monkeypatch.setattr(monitor, "_active_power_plan", lambda: "Balanced")
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.psutil.sensors_battery",
        lambda: None,
    )
    monitor._pending_updates = 3

    health = monitor.windows_health()

    assert health.windows_update_status == "3 update(s) available"
    assert health.pending_restart is False
    assert health.power_plan == "Balanced"


def test_active_power_plan_handles_missing_command_output(monkeypatch, tmp_path) -> None:
    system_root = tmp_path / "Windows"
    executable = system_root / "System32" / "powercfg.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("SYSTEMROOT", str(system_root))
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=None),
    )

    assert WindowsSystemMonitor._active_power_plan() == ""


def test_active_power_plan_decodes_windows_oem_output(monkeypatch, tmp_path) -> None:
    system_root = tmp_path / "Windows"
    executable = system_root / "System32" / "powercfg.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MZ")
    monkeypatch.setenv("SYSTEMROOT", str(system_root))
    output = (
        b"Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  "
        b"(Wysoka wydajno\x98\x86)"
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )

    assert WindowsSystemMonitor._active_power_plan() == "Wysoka wydajność"


def test_zero_physical_disk_health_status_means_healthy(monkeypatch) -> None:
    import win32com.client

    storage = SimpleNamespace(
        ExecQuery=lambda _query: [SimpleNamespace(HealthStatus=0, Temperature=42)]
    )
    monkeypatch.setattr(win32com.client, "GetObject", lambda _path: storage)

    assert WindowsSystemMonitor._physical_disk_health() == ("Healthy", 42.0)


def test_pnp_presence_uses_windows_present_property(monkeypatch) -> None:
    import win32com.client

    service = SimpleNamespace(
        ExecQuery=lambda _query: [
            SimpleNamespace(
                PNPDeviceID=r"USB\VID_1234&PID_5678",
                Name="USB controller",
                PNPClass="USBDevice",
                Present=False,
                ConfigManagerErrorCode=0,
            )
        ]
    )
    monkeypatch.setattr(win32com.client, "GetObject", lambda _path: service)

    devices = WindowsSystemMonitor.list_pnp_devices()

    assert len(devices) == 1
    assert devices[0].present is False
    assert WindowsSystemMonitor.present_device_ids() == set()
