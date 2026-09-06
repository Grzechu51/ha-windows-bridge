"""Audit P07/P08: apartment ownership, provider failure and correct disk query."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pythoncom
import win32com.client
from test_phase0_publishing import telemetry

from ha_windows_bridge.config import TrackedDeviceConfig
from ha_windows_bridge.system_monitor import WindowsSystemMonitor
from ha_windows_bridge.windows.com import ProviderUnavailable, com_apartment, query_wmi


def test_p07_query_owns_com_and_releases_proxies_before_uninitialize(monkeypatch):
    calls = []
    owner = []
    class Row:
        Manufacturer = "CPU"
        def __del__(self):
            calls.append("release_row")
    class Service:
        def ExecQuery(self, query):
            calls.append("query")
            assert threading.get_ident() == owner[0]
            return [Row()]
        def __del__(self):
            calls.append("release_service")
    def initialize(mode):
        owner.append(threading.get_ident())
        calls.append("init")
        assert mode == pythoncom.COINIT_MULTITHREADED
    monkeypatch.setattr(pythoncom, "CoInitializeEx", initialize)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: calls.append("uninit"))
    monkeypatch.setattr(win32com.client, "GetObject", lambda _: Service())
    result = []
    thread = threading.Thread(target=lambda: result.extend(query_wmi("namespace", "SELECT Manufacturer FROM Win32_Processor")))
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert result[0].Manufacturer == "CPU"
    assert calls[0] == "init" and calls[-1] == "uninit"
    assert "release_row" in calls and "release_service" in calls
    assert owner[0] != threading.get_ident()


def test_com_borrowed_sta_is_not_uninitialized(monkeypatch):
    def changed_mode(_):
        raise pythoncom.com_error(-2147417850, "existing STA", None, None)
    monkeypatch.setattr(pythoncom, "CoInitializeEx", changed_mode)
    cleanup = Mock()
    monkeypatch.setattr(pythoncom, "CoUninitialize", cleanup)
    with com_apartment():
        pass
    cleanup.assert_not_called()


@pytest.mark.parametrize("stage", ["init", "query"])
def test_provider_failure_is_explicit_and_com_cleanup_is_balanced(monkeypatch, stage):
    cleanup = Mock()
    monkeypatch.setattr(pythoncom, "CoUninitialize", cleanup)
    def initialize(_):
        if stage == "init":
            raise pythoncom.com_error(-2147467259, "failure", None, None)
    monkeypatch.setattr(pythoncom, "CoInitializeEx", initialize)
    monkeypatch.setattr(win32com.client, "GetObject", Mock(side_effect=OSError("WMI failed")))
    with pytest.raises(ProviderUnavailable):
        query_wmi("namespace", "SELECT Name FROM Win32_Processor")
    assert cleanup.call_count == (stage == "query")


def test_failed_hardware_identity_is_retried_not_cached_as_empty(monkeypatch):
    monitor = WindowsSystemMonitor()
    monkeypatch.setattr(win32com.client, "GetObject", Mock(side_effect=OSError("WMI failed")))
    with pytest.raises(ProviderUnavailable):
        monitor._hardware_identity()
    assert monitor._hardware_identity_cache is None
    service = SimpleNamespace(ExecQuery=lambda q: [SimpleNamespace(Manufacturer="Intel", Name="NVIDIA")])
    monkeypatch.setattr(win32com.client, "GetObject", lambda _: service)
    assert monitor._hardware_identity() == ("Intel", "NVIDIA")


def test_failed_pnp_does_not_publish_disconnected_and_recovers(monkeypatch):
    service, publisher = telemetry(Mock())
    service.config.tracked_devices = [TrackedDeviceConfig("USB-1", "Device", "device")]
    service.system = WindowsSystemMonitor()
    monkeypatch.setattr(win32com.client, "GetObject", Mock(side_effect=OSError("WMI failed")))
    with pytest.raises(ProviderUnavailable):
        service.system.present_device_ids()
    events = []
    service.events.subscribe("provider.health", lambda event: events.append(event.data))
    service._monitor_devices()
    assert events[-1]["errors"]
    assert any(call.args[1] == "unavailable" for call in publisher.transport.publish.call_args_list)
    assert not any(call.args[1] == "OFF" for call in publisher.transport.publish.call_args_list)
    monkeypatch.setattr(service.system, "present_device_ids", lambda: set())
    service._monitor_devices()
    assert not events[-1]["errors"]
    assert publisher.transport.publish.call_args_list[-1].args[1] == "OFF"


def test_p08_physical_health_and_reliability_temperature_use_distinct_queries(monkeypatch):
    queries = []
    def query(value):
        queries.append(value)
        if value == "SELECT HealthStatus FROM MSFT_PhysicalDisk":
            return [SimpleNamespace(HealthStatus=0)]
        if value == "SELECT Temperature FROM MSFT_StorageReliabilityCounter":
            return [SimpleNamespace(Temperature=42)]
        raise AssertionError(value)
    monkeypatch.setattr(win32com.client, "GetObject", lambda _: SimpleNamespace(ExecQuery=query))
    assert WindowsSystemMonitor._physical_disk_health() == ("Healthy", 42)
    assert len(queries) == 2


def test_optional_provider_failures_keep_cpu_ram_and_report_health(monkeypatch):
    monitor = WindowsSystemMonitor()
    unavailable = Mock(side_effect=ProviderUnavailable("missing"))
    monkeypatch.setattr(monitor, "_hardware_identity", unavailable)
    monkeypatch.setattr(monitor, "_hardware_monitor_metrics", unavailable)
    result = monitor.system_metrics(include_gpu=False)
    assert result.cpu_percent >= 0 and result.ram_total_gb > 0
    assert set(result.provider_errors) == {"hardware_monitor", "hardware_identity"}


def test_disk_health_failure_is_not_cached_as_a_success(monkeypatch):
    monitor = WindowsSystemMonitor()
    monkeypatch.setattr(monitor, "list_disk_volumes", lambda: [])
    monkeypatch.setattr("ha_windows_bridge.system_monitor.psutil.disk_io_counters", lambda: None)
    monkeypatch.setattr("ha_windows_bridge.system_monitor.time.monotonic", lambda: 100.)
    read = Mock(side_effect=[ProviderUnavailable("missing"), ("Healthy", 42)])
    monkeypatch.setattr(monitor, "_physical_disk_health", read)
    result = monitor.disk_metrics()
    assert result.provider_errors == ("disk_health",)
    assert result.health == "" and result.temperature is None
    assert monitor._disk_health_cache_time == 0
    recovered = monitor.disk_metrics()
    assert not recovered.provider_errors
    assert recovered.health == "Healthy" and recovered.temperature == 42
    assert read.call_count == 2


def test_windows_update_failure_has_explicit_health_error_and_releases_com(monkeypatch):
    monitor = WindowsSystemMonitor()
    monkeypatch.setattr(pythoncom, "CoInitializeEx", lambda _: None)
    cleanup = Mock()
    monkeypatch.setattr(pythoncom, "CoUninitialize", cleanup)
    monkeypatch.setattr(win32com.client, "Dispatch", Mock(side_effect=OSError("WUA failed")))
    monitor._read_pending_windows_updates()
    cleanup.assert_called_once_with()
    monkeypatch.setattr(monitor, "_schedule_windows_update_check", lambda: None)
    monkeypatch.setattr(monitor, "_pending_restart", lambda: False)
    monkeypatch.setattr(monitor, "_active_power_plan", lambda: "Balanced")
    assert monitor.windows_health().windows_update_status == "Unavailable"


def test_nvidia_execution_failure_reports_unavailable(monkeypatch):
    monitor = WindowsSystemMonitor()
    monitor._nvidia_smi = "nvidia-smi"
    monkeypatch.setattr(monitor, "_hardware_identity", lambda: ("CPU", "NVIDIA"))
    monkeypatch.setattr("ha_windows_bridge.system_monitor.subprocess.run", Mock(side_effect=OSError("missing")))
    with pytest.raises(ProviderUnavailable, match="NVIDIA"):
        monitor._gpu_metrics()
