"""Deterministic startup races using only fake provider reads and publishers."""
from __future__ import annotations

import logging
import threading
from unittest.mock import Mock

import pytest

from ha_windows_bridge.application.providers import (
    AdaptiveProvider,
    DeviceSnapshot,
    StorageSnapshot,
    SystemProviderView,
)
from ha_windows_bridge.application.telemetry import TelemetryService
from ha_windows_bridge.audio import AudioSessionSnapshot
from ha_windows_bridge.config import AppConfig, AudioAppConfig, TrackedDeviceConfig
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.provider_errors import ProviderNotReady
from ha_windows_bridge.core.state import ComputerStateStore, StateQuality
from ha_windows_bridge.runtime.polling import PollScheduler
from ha_windows_bridge.system_monitor import PcContext, WindowsHealth
from ha_windows_bridge.windows.com import ProviderUnavailable


def make_state():
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    return state


def make_telemetry(state, **config):
    publisher = Mock(connected=True)
    return TelemetryService(
        AppConfig(**config), Mock(), SystemProviderView(Mock(), state),
        Mock(), publisher, state.events, [],
    )


@pytest.mark.parametrize(
    ("source", "read", "observe", "expected"),
    [
        ("windows_health", lambda view: view.windows_health(), WindowsHealth(uptime_seconds=42), 42),
        ("desktop_context", lambda view: view.context_snapshot(), PcContext(idle_seconds=42), 42),
        ("processes", lambda view: view.running_process_names(["player.exe"]), frozenset({"player.exe"}), {"player.exe"}),
        ("storage", lambda view: view.list_disk_volumes(), StorageSnapshot(), []),
        ("pnp", lambda view: view.present_device_ids(), DeviceSnapshot(), set()),
    ],
)
def test_registered_provider_waits_without_defaults_and_retries_immediately(
    source, read, observe, expected, caplog,
):
    state = make_state()
    assert state.register_provider(source, generation=1)
    view = SystemProviderView(Mock(), state)
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    published = []

    def publish():
        value = read(view)
        published.append(value)
        return value

    for _ in range(3):
        assert scheduler.run(source, 30, publish, "fake-default") is None
    assert published == []
    assert state.snapshot().provider(source) is None
    assert caplog.records == []
    assert state.observe_provider(source, observe, generation=1)
    result = scheduler.run(source, 30, publish)
    if source == "windows_health":
        result = result.uptime_seconds
    elif source == "desktop_context":
        result = result.idle_seconds
    assert result == expected
    assert published == [read(view)]
    assert not state.snapshot().health_for(source).awaiting_first_observation


def test_delayed_owner_read_is_pending_and_does_not_block_other_polling(caplog):
    state = make_state()
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    state.events.subscribe(
        "computer_state.changed",
        lambda event: observed.set() if event.data.provider("windows_health") else None,
    )

    def read():
        entered.set()
        assert release.wait(2)
        return WindowsHealth(uptime_seconds=42)

    provider = AdaptiveProvider("windows_health", read, state, 1, interval=60, maximum_interval=60)
    service = make_telemetry(state)
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    provider.start()
    try:
        assert entered.wait(1)
        for _ in range(3):
            scheduler.run("windows_health", 30, service._monitor_windows_health)
        service.publisher.publish.assert_not_called()
        assert scheduler.run("independent", 30, lambda: 42) == 42
        assert caplog.records == []
        release.set()
        assert observed.wait(1)
        scheduler.run("windows_health", 30, service._monitor_windows_health)
        assert service.publisher.publish.call_count >= 2
    finally:
        release.set()
        assert provider.stop()


def test_sensor_thread_polls_other_sources_and_stops_while_provider_is_pending(caplog):
    state = make_state()
    entered, release = threading.Event(), threading.Event()
    attempted, independent = threading.Event(), threading.Event()

    def read():
        entered.set()
        assert release.wait(2)
        return WindowsHealth(uptime_seconds=42)

    provider = AdaptiveProvider("windows_health", read, state, 1, interval=60, maximum_interval=60)
    service = make_telemetry(
        state, apps=[], poll_interval=0.01, publish_windows_health=True, publish_activity=True,
    )
    service._inventory_requested.clear()

    service._monitor_context = independent.set
    original_monitor = service._monitor_windows_health

    def pending_health():
        attempted.set()
        original_monitor()

    service._monitor_windows_health = pending_health
    provider.start()
    try:
        assert entered.wait(1)
        service.start()
        service._wake_event.set()
        assert attempted.wait(1)
        assert independent.wait(1)
        assert service.stop()
        assert not service._thread.is_alive()
        service.publisher.publish.assert_not_called()
        assert caplog.records == []
    finally:
        service.stop()
        release.set()
        assert provider.stop()


@pytest.mark.parametrize("failure", [ProviderUnavailable("WMI unavailable"), OSError("read failed")])
def test_first_failed_read_is_visible_and_later_success_recovers(failure, caplog):
    state = make_state()
    failed = threading.Event()
    state.events.subscribe(
        "computer_state.changed",
        lambda event: failed.set()
        if (event.data.health_for("windows_health") is not None
            and event.data.health_for("windows_health").detail == str(failure)) else None,
    )
    outcomes = iter([failure, WindowsHealth(uptime_seconds=42)])

    def read():
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    provider = AdaptiveProvider("windows_health", read, state, 1, interval=60, maximum_interval=60)
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    view = SystemProviderView(Mock(), state)
    provider.start()
    try:
        assert failed.wait(1)
        assert not state.snapshot().health_for("windows_health").awaiting_first_observation
        with pytest.raises(ProviderUnavailable, match=str(failure)) as caught:
            view.windows_health()
        assert not isinstance(caught.value, ProviderNotReady)
        caplog.clear()
        assert scheduler.run("windows_health", 0, view.windows_health) is None
        assert len(caplog.records) == 1
        assert "Windows source failed" in caplog.records[0].message
        assert provider.refresh_now()
        assert scheduler.run("windows_health", 0, view.windows_health).uptime_seconds == 42
    finally:
        assert provider.stop()


def test_new_generation_clears_samples_but_retained_success_cannot_mask_failure():
    state = make_state()
    view = SystemProviderView(Mock(), state)
    state.observe_provider("windows_health", WindowsHealth(uptime_seconds=42), generation=1)
    last_success = state.snapshot().health_for("windows_health").last_success_at
    state.fail_provider("windows_health", StateQuality.ERROR, "read failed", generation=1)
    with pytest.raises(ProviderUnavailable, match="read failed"):
        view.windows_health()
    state.begin_generation(2)
    health = state.snapshot().health_for("windows_health")
    assert health.last_success_at == last_success
    with pytest.raises(ProviderNotReady):
        view.windows_health()
    state.fail_provider("windows_health", StateQuality.ERROR, "first read failed", generation=2)
    state.register_provider("windows_health", generation=2)
    with pytest.raises(ProviderUnavailable, match="first read failed") as caught:
        view.windows_health()
    assert not isinstance(caught.value, ProviderNotReady)
    assert state.snapshot().provider("windows_health") is None
    assert state.snapshot().health_for("windows_health").last_success_at == last_success


def test_unregistered_or_stopped_provider_is_unavailable_not_pending():
    state = make_state()
    view = SystemProviderView(Mock(), state)
    for detail in (None, "provider_stopped", "shutdown_timeout", "sampling_paused"):
        if detail is not None:
            state.fail_provider("windows_health", StateQuality.ERROR, detail, generation=1)
            state.register_provider("windows_health", generation=1)
        with pytest.raises(ProviderUnavailable) as caught:
            view.windows_health()
        assert not isinstance(caught.value, ProviderNotReady)
    assert not state.register_provider("new", generation=0)
    assert state.snapshot().health_for("new") is None


@pytest.mark.parametrize("detail", ["stopping", "reconnecting", "suspended", "shutdown"])
def test_stopping_generation_is_unavailable_instead_of_startup_pending(detail):
    state = make_state()
    state.observe_provider("windows_health", WindowsHealth(uptime_seconds=42), generation=1)
    state.begin_generation(2, detail=detail)
    assert not state.snapshot().health_for("windows_health").awaiting_first_observation
    with pytest.raises(ProviderUnavailable, match=detail) as caught:
        SystemProviderView(Mock(), state).windows_health()
    assert not isinstance(caught.value, ProviderNotReady)


def test_pending_poll_clears_old_cached_value_without_suppressing_next_failure(caplog):
    state = make_state()
    state.observe_provider("windows_health", WindowsHealth(uptime_seconds=42), generation=1)
    view = SystemProviderView(Mock(), state)
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    assert scheduler.run("windows_health", 0, view.windows_health).uptime_seconds == 42
    state.begin_generation(2)
    assert scheduler.run("windows_health", 0, view.windows_health, "fake-default") is None
    state.fail_provider("windows_health", StateQuality.UNAVAILABLE, "first failure", generation=2)
    assert scheduler.run("windows_health", 0, view.windows_health) is None
    assert len(caplog.records) == 1


def test_shutdown_during_first_read_does_not_accept_late_success():
    state = make_state()
    entered, release = threading.Event(), threading.Event()

    def read():
        entered.set()
        assert release.wait(2)
        return WindowsHealth(uptime_seconds=42)

    provider = AdaptiveProvider(
        "windows_health", read, state, 1, interval=60, maximum_interval=60, stop_timeout=0.01,
    )
    provider.start()
    try:
        assert entered.wait(1)
        assert not provider.stop()
        with pytest.raises(ProviderUnavailable, match="shutdown_timeout") as caught:
            SystemProviderView(Mock(), state).windows_health()
        assert not isinstance(caught.value, ProviderNotReady)
    finally:
        release.set()
        # Joining here is test cleanup, without another state transition.
        provider._thread.join(timeout=1)
        assert not provider.is_alive
        assert state.snapshot().provider("windows_health") is None
        assert state.snapshot().health_for("windows_health").detail == "shutdown_timeout"


def test_process_startup_skips_false_off_but_audio_evidence_can_publish_on():
    state = make_state()
    state.register_provider("processes", generation=1)
    app = AudioAppConfig("player.exe", "Player")
    service = make_telemetry(state, apps=[app])
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    running = scheduler.run("processes", 2, lambda: service.system.running_process_names([app.process_name]))
    service._monitor_apps([app], {}, running)
    service.publisher.publish.assert_not_called()
    service._monitor_apps([app], {"player.exe": AudioSessionSnapshot(0.5, False)}, running)
    assert any(call.args[1] == "ON" for call in service.publisher.publish.call_args_list)
    service.publisher.reset_mock()
    state.observe_provider("processes", frozenset(), generation=1)
    running = scheduler.run("processes", 2, lambda: service.system.running_process_names([app.process_name]))
    service._monitor_apps([app], {}, running)
    assert any(call.args[1] == "OFF" for call in service.publisher.publish.call_args_list)


def test_pnp_startup_skips_publication_but_actual_failure_publishes_unavailable():
    state = make_state()
    state.register_provider("pnp", generation=1)
    service = make_telemetry(state, tracked_devices=[TrackedDeviceConfig("device-id", "Device")])
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    scheduler.run("devices", 10, service._monitor_devices)
    service.publisher.publish.assert_not_called()
    state.fail_provider("pnp", StateQuality.ERROR, "pnp_failed", generation=1)
    scheduler.run("devices", 10, service._monitor_devices)
    service.publisher.publish.assert_called_once()
    assert service.publisher.publish.call_args.args[1] == "unavailable"


def test_pending_optional_metrics_remain_quality_flagged_and_updates_unavailable():
    state = make_state()
    for source in ("cpu_ram", "cpu_hardware", "gpu", "windows_update"):
        state.register_provider(source, generation=1)
    service = make_telemetry(state, publish_cpu_stats=True, publish_ram_stats=True, publish_gpu_stats=True)
    service._monitor_system()
    assert service.publisher.publish.call_count > 0
    assert all(call.args[1] == "unavailable" for call in service.publisher.publish.call_args_list)
    state.observe_provider("windows_health", WindowsHealth(uptime_seconds=42), generation=1)
    assert service.system.windows_health().windows_update_status == "Unavailable"


@pytest.mark.parametrize(
    ("source", "config", "value"),
    [
        ("windows_health", {"publish_windows_health": True}, WindowsHealth(battery_percent=50)),
        ("storage", {"publish_disk_stats": True}, StorageSnapshot()),
    ],
)
def test_discovery_waits_for_requested_provider_and_retries_without_losing_inventory(
    source, config, value,
):
    state = make_state()
    state.register_provider(source, generation=1)
    service = make_telemetry(
        state, publish_cpu_stats=False, publish_ram_stats=False, publish_gpu_stats=False,
        **config,
    )
    scheduler = PollScheduler(logging.getLogger("startup-test"), lambda: 100)
    assert scheduler.run("inventory", 5, service.publish_discovery, 0) is None
    assert service._inventory_requested.is_set()
    service.publisher.publish.assert_not_called()
    state.observe_provider(source, value, generation=1)
    assert scheduler.run("inventory", 5, service.publish_discovery, 0) > 0
    service.publisher.publish.assert_called()


def test_unrequested_pending_provider_does_not_delay_discovery():
    state = make_state()
    state.register_provider("storage", generation=1)
    service = make_telemetry(
        state, publish_disk_stats=False, publish_windows_health=False,
        publish_cpu_stats=False, publish_gpu_stats=False,
    )
    assert service.publish_discovery() > 0
