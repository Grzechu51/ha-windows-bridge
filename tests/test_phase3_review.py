from __future__ import annotations

import asyncio
import ctypes
import threading
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.application.commands import CommandRouter
from ha_windows_bridge.application.master_audio import MasterAudioProvider
from ha_windows_bridge.application.providers import (
    AdaptiveProvider,
    DeviceSnapshot,
    MediaProvider,
    StorageSnapshot,
    SystemProviderView,
    stable_system_sample_key,
)
from ha_windows_bridge.application.telemetry import TelemetryService
from ha_windows_bridge.application.windows_commands import WindowsCommands
from ha_windows_bridge.audio import (
    AudioApplication,
    AudioProviderSnapshot,
    AudioSessionSnapshot,
    _AudioEventSubscription,
    _ExistingSessionEvents,
)
from ha_windows_bridge.communication.mqtt import MqttTransport
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.core.commands import Command
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ComputerStateStore, StateQuality
from ha_windows_bridge.discovery import discovery_messages
from ha_windows_bridge.media import (
    MediaSnapshot,
    WindowsMediaService,
    _AsyncRunner,
)
from ha_windows_bridge.system_monitor import (
    DiskMetrics,
    DiskVolume,
    PnpDevice,
    SystemMetrics,
    WindowsHealth,
    WindowsSystemMonitor,
)
from ha_windows_bridge.windows.com import ProviderUnavailable
from ha_windows_bridge.windows.native import WindowsEventBridge


def test_r1_system_view_requires_only_requested_available_providers() -> None:
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    state.observe_provider(
        "cpu_ram",
        SystemMetrics(7.0, 42.0, 10, ram_total_gb=32.0),
        generation=1,
    )
    state.observe_provider(
        "windows_health",
        WindowsHealth(power_plan="Balanced"),
        generation=1,
    )
    view = SystemProviderView(Mock(), state)

    ram = view.system_metrics(
        include_cpu=False,
        include_gpu=False,
        include_ram=True,
    )
    assert ram.ram_percent == 42.0
    assert not any(item.startswith("gpu:") for item in ram.provider_errors)
    assert view.windows_health().windows_update_status == "Unavailable"

    gpu_state = ComputerStateStore(EventBus())
    gpu_state.begin_generation(1)
    gpu_state.observe_provider(
        "gpu",
        SystemMetrics(0.0, 0.0, 11, gpu_percent=55.0),
        generation=1,
    )
    gpu = SystemProviderView(Mock(), gpu_state).system_metrics(
        include_cpu=False,
        include_gpu=True,
        include_ram=False,
    )
    assert gpu.gpu_percent == 55.0
    assert not any(item.startswith("cpu_ram:") for item in gpu.provider_errors)

    publisher = Mock(connected=True)
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        publish_gpu_stats=True,
        publish_disk_stats=True,
    )
    telemetry = TelemetryService(
        config,
        Mock(),
        SystemProviderView(Mock(), gpu_state),
        Mock(),
        publisher,
        EventBus(),
        ["Monitor"],
    )
    assert telemetry.publish_discovery() > 0


class _BarrierState(ComputerStateStore):
    def __init__(self, events: EventBus, method: str) -> None:
        super().__init__(events)
        self.method = method
        self.entered = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()

    def observe_provider(self, source, value, **kwargs):
        if self.method == "provider":
            self.entered.set()
            assert self.release.wait(2)
        result = super().observe_provider(source, value, **kwargs)
        self.returned.set()
        return result

    def observe_audio_provider(self, value, master, **kwargs):
        if self.method == "audio":
            self.entered.set()
            assert self.release.wait(2)
        result = super().observe_audio_provider(value, master, **kwargs)
        self.returned.set()
        return result


def test_r2_pause_epoch_and_state_commit_are_atomic() -> None:
    state = _BarrierState(EventBus(), "provider")
    state.begin_generation(1)
    provider = AdaptiveProvider(
        "pnp",
        lambda: DeviceSnapshot((PnpDevice("id", "Device", "USB"),)),
        state,
        1,
        interval=60,
        maximum_interval=60,
    )
    provider.start()
    assert state.entered.wait(1)
    provider.pause(True)
    state.release.set()
    assert state.returned.wait(1)
    assert state.snapshot().provider("pnp") is None
    assert state.snapshot().health_for("pnp").quality == StateQuality.PAUSED
    assert provider.stop()


def test_r2_shutdown_epoch_rejects_delayed_audio_bundle() -> None:
    state = _BarrierState(EventBus(), "audio")
    state.begin_generation(1)
    adapter = SimpleNamespace(
        provider_snapshot=lambda **_kwargs: AudioProviderSnapshot(
            master=AudioSessionSnapshot(0.8, False)
        )
    )
    provider = MasterAudioProvider(adapter, state, 1, poll_interval=60)
    provider.start()
    assert state.entered.wait(1)

    stopped = threading.Event()

    def stop() -> None:
        provider.stop()
        stopped.set()

    thread = threading.Thread(target=stop)
    stop_waiting = threading.Event()
    owner_thread = provider._thread
    assert owner_thread is not None
    original_join = owner_thread.join

    def joined(timeout=None):
        stop_waiting.set()
        return original_join(timeout)

    owner_thread.join = joined
    thread.start()
    assert stop_waiting.wait(1)
    state.release.set()
    assert stopped.wait(2)
    thread.join(timeout=1)
    snapshot = state.snapshot()
    assert snapshot.provider("audio") is None
    assert snapshot.master_audio is None
    assert snapshot.health_for("audio").quality == StateQuality.STOPPED
    assert snapshot.health_for("master_audio").quality == StateQuality.STOPPED


def test_r3_media_target_is_bound_before_command_queue() -> None:
    blocker_entered = threading.Event()
    blocker_release = threading.Event()
    result_ready = threading.Event()
    results = []

    class Media:
        def __init__(self) -> None:
            self.current = "gsmtc:a"
            self.calls = []

        def snapshot(self):
            return MediaSnapshot(session_id=self.current)

        def execute(self, action, value=None, *, session_id=""):
            self.calls.append((action, value, session_id, self.current))
            return session_id == self.current

    media = Media()
    config = AppConfig(media_player_enabled=True)
    router = CommandRouter()
    router.register(
        "test.block",
        lambda _command: (
            blocker_entered.set(),
            blocker_release.wait(2),
            {},
        )[-1],
    )
    WindowsCommands(
        config,
        Mock(),
        Mock(),
        media,
        Mock(),
        EventBus(),
        ["Monitor"],
        master_audio=Mock(),
    ).install(router)
    try:
        blocker = Command(
            "block",
            "test.block",
            "",
            {},
            time.time() + 10,
        )
        assert router.submit(blocker, lambda _result: None).status == "accepted"
        assert blocker_entered.wait(1)
        command = Command(
            "media",
            "media.control",
            "",
            {"action": "pause"},
            time.time() + 10,
        )
        receipt = router.submit(
            command,
            lambda result: (results.append(result), result_ready.set()),
        )
        assert receipt.status == "accepted"
        media.current = "gsmtc:b"
        assert router.submit(command, lambda _result: None).status == "pending"
        blocker_release.set()
        assert result_ready.wait(2)
        assert results[-1].status == "failed"
        assert media.calls == [("pause", None, "gsmtc:a", "gsmtc:b")]
    finally:
        blocker_release.set()
        assert router.stop()


def test_r3_gsmtc_identity_distinguishes_same_aumid_instances() -> None:
    service = WindowsMediaService()
    first = SimpleNamespace(source_app_user_model_id="Spotify")
    second = SimpleNamespace(source_app_user_model_id="Spotify")

    first_id = service._stable_session_identity(first)
    second_id = service._stable_session_identity(second)

    assert first_id.startswith("gsmtc:")
    assert first_id != second_id


def test_r4_gsmtc_callback_runs_on_owner_and_is_stale_after_shutdown() -> None:
    callback_thread = []
    manager_threads = []
    changed = threading.Event()

    class Session:
        def add_media_properties_changed(self, callback):
            self.media_changed = callback
            return "media"

        def add_playback_info_changed(self, callback):
            self.playback_changed = callback
            return "playback"

        def add_timeline_properties_changed(self, callback):
            self.timeline_changed = callback
            return "timeline"

        def remove_media_properties_changed(self, _token):
            return None

        def remove_playback_info_changed(self, _token):
            return None

        def remove_timeline_properties_changed(self, _token):
            return None

    class Manager:
        def __init__(self) -> None:
            self.session = Session()

        def get_current_session(self):
            manager_threads.append(threading.get_ident())
            return self.session

        def add_current_session_changed(self, callback):
            self.current_changed = callback
            return "current"

        def add_sessions_changed(self, callback):
            self.sessions_changed = callback
            return "sessions"

        def remove_current_session_changed(self, _token):
            return None

        def remove_sessions_changed(self, _token):
            return None

    manager = Manager()
    service = WindowsMediaService()
    service._runner = _AsyncRunner()

    async def get_manager():
        service._manager = manager
        return manager

    service._manager_async = get_manager
    unsubscribe = service.subscribe(lambda: changed.set())
    saved = manager.current_changed

    def fire() -> None:
        callback_thread.append(threading.get_ident())
        saved(manager, None)

    foreign = threading.Thread(target=fire)
    foreign.start()
    foreign.join(timeout=1)
    assert changed.wait(1)
    assert manager_threads[-1] == service._runner._thread.ident
    assert manager_threads[-1] != callback_thread[-1]

    changed.clear()
    unsubscribe()
    saved(manager, None)
    assert not changed.is_set()
    assert service.close()


def test_r4_gsmtc_partial_registration_rolls_back() -> None:
    removed = []

    class Manager:
        def add_current_session_changed(self, _callback):
            return "current"

        def add_sessions_changed(self, _callback):
            raise RuntimeError("second registration failed")

        def remove_current_session_changed(self, token):
            removed.append(token)

        def remove_sessions_changed(self, _token):
            raise AssertionError("was never registered")

    service = WindowsMediaService()

    async def get_manager():
        service._manager = Manager()
        return service._manager

    service._manager_async = get_manager
    with pytest.raises(RuntimeError, match="second registration"):
        asyncio.run(service._subscribe_async(lambda: None))
    assert removed == ["current"]
    assert service._manager_event_tokens == []


def test_r4_gsmtc_unsubscribe_failure_is_reported() -> None:
    class Session:
        def add_media_properties_changed(self, _callback):
            return "media"

        def add_playback_info_changed(self, _callback):
            return "playback"

        def add_timeline_properties_changed(self, _callback):
            return "timeline"

        def remove_media_properties_changed(self, _token):
            raise RuntimeError("unsubscribe failed")

        def remove_playback_info_changed(self, _token):
            return None

        def remove_timeline_properties_changed(self, _token):
            return None

    class Manager:
        def __init__(self):
            self.session = Session()

        def get_current_session(self):
            return self.session

        def add_current_session_changed(self, _callback):
            return "current"

        def add_sessions_changed(self, _callback):
            return "sessions"

        def remove_current_session_changed(self, _token):
            return None

        def remove_sessions_changed(self, _token):
            return None

    service = WindowsMediaService()

    async def get_manager():
        service._manager = Manager()
        return service._manager

    service._manager_async = get_manager

    def callback():
        return None

    asyncio.run(service._subscribe_async(callback))
    with pytest.raises(RuntimeError, match="callback cleanup"):
        asyncio.run(service._unsubscribe_async(callback))


class _AudioEndpoint:
    def __init__(self, *, cleanup_error: bool = False) -> None:
        self.registered = 0
        self.unregistered = 0
        self.cleanup_error = cleanup_error

    def RegisterControlChangeNotify(self, _callback):
        self.registered += 1

    def UnregisterControlChangeNotify(self, _callback):
        self.unregistered += 1
        if self.cleanup_error:
            raise RuntimeError("endpoint cleanup")


class _SessionEnumerator:
    def GetCount(self):
        return 0


class _AudioManager:
    def __init__(self, *, setup_error: bool = False) -> None:
        self.registered = 0
        self.unregistered = 0
        self.setup_error = setup_error

    def RegisterSessionNotification(self, _callback):
        self.registered += 1
        if self.setup_error:
            raise RuntimeError("manager setup")

    def UnregisterSessionNotification(self, _callback):
        self.unregistered += 1

    def GetSessionEnumerator(self):
        return _SessionEnumerator()


def test_r5_audio_endpoint_change_moves_all_subscriptions(monkeypatch) -> None:
    endpoint_a, endpoint_b = _AudioEndpoint(), _AudioEndpoint()
    manager_a, manager_b = _AudioManager(), _AudioManager()
    devices = [
        SimpleNamespace(
            id="a",
            EndpointVolume=endpoint_a,
            AudioSessionManager=manager_a,
        ),
        SimpleNamespace(
            id="b",
            EndpointVolume=endpoint_b,
            AudioSessionManager=manager_b,
        ),
    ]
    current = [0]
    enumerator = SimpleNamespace(
        RegisterEndpointNotificationCallback=lambda _callback: None,
        UnregisterEndpointNotificationCallback=lambda _callback: None,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetDeviceEnumerator",
        lambda: enumerator,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetSpeakers",
        lambda: devices[current[0]],
    )

    subscription = _AudioEventSubscription(lambda: None)
    current[0] = 1
    subscription.refresh_endpoint()

    assert endpoint_a.unregistered == 1
    assert manager_a.unregistered == 1
    assert endpoint_b.registered == 1
    assert manager_b.registered == 1
    assert subscription.close()


def test_r5_audio_partial_setup_rolls_back_and_session_events_wake(monkeypatch) -> None:
    endpoint_a, endpoint_b = _AudioEndpoint(), _AudioEndpoint()
    manager_a = _AudioManager()
    manager_b = _AudioManager(setup_error=True)
    devices = [
        SimpleNamespace(
            id="a",
            EndpointVolume=endpoint_a,
            AudioSessionManager=manager_a,
        ),
        SimpleNamespace(
            id="b",
            EndpointVolume=endpoint_b,
            AudioSessionManager=manager_b,
        ),
    ]
    current = [0]
    enumerator = SimpleNamespace(
        RegisterEndpointNotificationCallback=lambda _callback: None,
        UnregisterEndpointNotificationCallback=lambda _callback: None,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetDeviceEnumerator",
        lambda: enumerator,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetSpeakers",
        lambda: devices[current[0]],
    )
    woke = []
    subscription = _AudioEventSubscription(lambda: woke.append(True))
    current[0] = 1

    with pytest.raises(RuntimeError, match="manager setup"):
        subscription.refresh_endpoint()
    assert endpoint_b.unregistered == 1
    assert subscription.endpoint_id == "a"
    events = _ExistingSessionEvents(lambda: woke.append(True))
    events.on_simple_volume_changed(0.2, False, None)
    events.on_state_changed("Active", 1)
    assert len(woke) == 2

    class Existing:
        InstanceIdentifier = "existing"

        def register_notification(self, callback):
            self.callback = callback

        def unregister_notification(self):
            return None

    existing = Existing()
    monkeypatch.setattr(
        subscription,
        "_enumerate_sessions",
        lambda _manager: [existing],
    )
    registered = subscription._register_existing_sessions(manager_a)
    registered["existing"][1].on_simple_volume_changed(0.5, False, None)
    assert len(woke) == 3
    assert subscription.close()


def test_r5_audio_cleanup_failure_is_explicit(monkeypatch) -> None:
    endpoint = _AudioEndpoint(cleanup_error=True)
    manager = _AudioManager()
    enumerator = SimpleNamespace(
        RegisterEndpointNotificationCallback=lambda _callback: None,
        UnregisterEndpointNotificationCallback=lambda _callback: None,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetDeviceEnumerator",
        lambda: enumerator,
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetSpeakers",
        lambda: SimpleNamespace(
            id="a",
            EndpointVolume=endpoint,
            AudioSessionManager=manager,
        ),
    )
    subscription = _AudioEventSubscription(lambda: None)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        subscription.close()


def test_r6_degraded_pnp_media_and_wua_are_visible() -> None:
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    state.observe_provider(
        "pnp",
        DeviceSnapshot((PnpDevice("id", "Pad", "HIDClass"),)),
        generation=1,
    )
    state.fail_provider(
        "pnp",
        StateQuality.ERROR,
        "pnp_failed",
        generation=1,
    )
    with pytest.raises(ProviderUnavailable, match="pnp_failed"):
        SystemProviderView(Mock(), state).present_device_ids()

    state.observe_provider(
        "media",
        MediaSnapshot(
            state="playing",
            session_id="gsmtc:a",
            title="Old",
        ),
        generation=1,
    )
    state.fail_provider(
        "media",
        StateQuality.UNAVAILABLE,
        "WinRT lost",
        generation=1,
    )
    media = MediaProvider(Mock(), state, 1, interval=60).snapshot()
    assert media.supported is False
    assert media.state == "idle"
    assert media.error == "WinRT lost"

    state.observe_provider(
        "windows_health",
        WindowsHealth(windows_update_status="Checking"),
        generation=1,
    )
    state.observe_provider("windows_update", 0, generation=1)
    state.fail_provider(
        "windows_update",
        StateQuality.ERROR,
        "read_timeout",
        generation=1,
    )
    assert (
        SystemProviderView(Mock(), state).windows_health().windows_update_status
        == "Unavailable"
    )


def test_r7_master_audio_public_reads_only_accepted_computer_state() -> None:
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    accepted = AudioProviderSnapshot(
        master=AudioSessionSnapshot(0.2, False),
        balance=-0.2,
        sessions=(("a.exe", AudioSessionSnapshot(0.3, False)),),
        applications=(AudioApplication("a.exe", "A"),),
        active_process="a.exe",
    )
    state.observe_audio_provider(
        accepted,
        (0.2, False),
        generation=1,
    )
    provider = MasterAudioProvider(
        SimpleNamespace(
            provider_snapshot=lambda **_kwargs: AudioProviderSnapshot(
                master=AudioSessionSnapshot(0.9, False),
                balance=0.9,
                active_process="rejected.exe",
            )
        ),
        state,
        0,
        poll_interval=60,
    )
    provider._stopping = False

    assert provider._sample() is False
    assert provider.master_balance_snapshot() == -0.2
    assert provider.get_volume("a.exe") == 0.3
    assert provider.get_active_process_name() == "a.exe"
    assert provider.list_audio_applications()[0].display_name == "A"


def test_r8_partial_audio_session_failure_preserves_last_known_good() -> None:
    previous = AudioProviderSnapshot(
        master=AudioSessionSnapshot(0.2, False),
        sessions=(
            (
                "player.exe",
                AudioSessionSnapshot(0.4, False, 1, ("session-a",)),
            ),
        ),
        applications=(
            AudioApplication(
                "player.exe",
                "Player",
                volume=0.4,
                muted=False,
                session_ids=("session-a",),
            ),
        ),
    )
    current = AudioProviderSnapshot(
        master=AudioSessionSnapshot(0.2, False),
        errors=("sessions",),
        session_failures=(("player.exe", "session-a"),),
    )

    merged = MasterAudioProvider._preserve_partial_snapshot(current, previous)

    assert merged.sessions == previous.sessions
    assert merged.applications == previous.applications
    assert merged.errors == ("sessions",)


def test_r8_audio_adapter_marks_session_read_failure(monkeypatch) -> None:
    from ha_windows_bridge.audio import WindowsAudioService

    class Endpoint:
        def GetMasterVolumeLevelScalar(self):
            return 0.2

        def GetMute(self):
            return False

        def GetChannelCount(self):
            return 0

    class Process:
        def name(self):
            return "player.exe"

        def exe(self):
            return "C:/Player.exe"

    class Control:
        def GetMasterVolume(self):
            raise RuntimeError("session disappeared during read")

    session = SimpleNamespace(
        Process=Process(),
        InstanceIdentifier="session-a",
        Identifier="identifier-a",
        ProcessId=10,
        _ctl=SimpleNamespace(QueryInterface=lambda _interface: Control()),
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.com_scope",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetSpeakers",
        lambda: SimpleNamespace(id="endpoint", EndpointVolume=Endpoint()),
    )
    monkeypatch.setattr(
        "ha_windows_bridge.audio.AudioUtilities.GetAllSessions",
        lambda: [session],
    )
    monkeypatch.setattr(
        WindowsAudioService,
        "get_active_process_name",
        staticmethod(lambda: None),
    )

    snapshot = WindowsAudioService().provider_snapshot(
        include_sessions=True,
    )

    assert snapshot.sessions == ()
    assert snapshot.session_failures == (("player.exe", "session-a"),)
    assert "sessions" in snapshot.errors


def test_r9_inventory_refreshes_owned_provider_without_parallel_enumeration() -> None:
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    volume = DiskVolume("C:\\", "C:\\", "NTFS", 100, 20, 80)
    raw = SimpleNamespace(
        list_disk_volumes=lambda: (_ for _ in ()).throw(
            AssertionError("raw inventory must not run")
        ),
    )

    class Provider:
        source = "storage"
        is_alive = True

        def __init__(self) -> None:
            self.refreshes = 0

        def refresh_now(self):
            self.refreshes += 1
            return state.observe_provider(
                "storage",
                StorageSnapshot(
                    (volume,),
                    DiskMetrics(20, 80, 0, 0),
                ),
                generation=1,
            )

    provider = Provider()
    app = Application.__new__(Application)
    app._closed = False
    app.events = events
    app.computer_state = state
    app._system_providers = [provider]
    app._master_audio = None
    app.system = raw
    app.log = Mock()
    app._query_once = lambda _key, callback: (callback(), True)[1]
    received = []
    events.subscribe("inventory.disks", lambda event: received.append(event.data))

    assert app.request_inventory("disks")
    assert provider.refreshes == 1
    assert received == [[volume]]


def test_r9_inventory_without_first_sample_is_pending_not_fake_zero() -> None:
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    provider = SimpleNamespace(
        source="storage",
        is_alive=True,
        refresh_now=lambda: False,
    )
    app = Application.__new__(Application)
    app._closed = False
    app.events = events
    app.computer_state = state
    app._system_providers = [provider]
    app._master_audio = None
    app.system = Mock()
    app.log = Mock()
    app._query_once = lambda _key, callback: (callback(), True)[1]
    inventory, errors = [], []
    events.subscribe("inventory.disks", lambda event: inventory.append(event.data))
    events.subscribe("application.error", lambda event: errors.append(event.data))

    assert app.request_inventory("disks")
    assert inventory == []
    assert errors
    app.system.list_disk_volumes.assert_not_called()


def test_r10_disk_health_maps_selected_volume_to_physical_disk(
    monkeypatch,
) -> None:
    volumes = [
        DiskVolume("C:\\", "C:\\", "NTFS", 100, 20, 80),
        DiskVolume("D:\\", "D:\\", "NTFS", 100, 20, 80),
    ]

    def query(_service, statement):
        if "ASSOCIATORS" in statement:
            return [
                SimpleNamespace(
                    DiskIndex=0 if "C:" in statement else 1
                )
            ]
        if "MSFT_PhysicalDisk" in statement:
            return [
                SimpleNamespace(DeviceId="0", HealthStatus=0),
                SimpleNamespace(DeviceId="1", HealthStatus=2),
            ]
        if "MSFT_StorageReliabilityCounter" in statement:
            return [
                SimpleNamespace(DeviceId="0", Temperature=35),
                SimpleNamespace(DeviceId="1", Temperature=85),
            ]
        return []

    monkeypatch.setattr("ha_windows_bridge.system_monitor.query_wmi", query)
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.psutil.disk_io_counters",
        lambda: SimpleNamespace(read_bytes=0, write_bytes=0),
    )
    monitor = WindowsSystemMonitor()

    metrics = monitor.disk_metrics(["C:\\"], volumes=volumes)

    assert metrics.health == "Healthy"
    assert metrics.temperature == 35
    assert monitor._volume_disk_cache
    monitor.invalidate_storage_mapping()
    assert monitor._volume_disk_cache == {}


def test_r11_nvidia_selection_is_stable_across_row_permutations(
    monkeypatch,
) -> None:
    monitor = WindowsSystemMonitor()
    monitor._nvidia_smi = "nvidia-smi"
    monkeypatch.setattr(
        monitor,
        "_hardware_identity",
        lambda: ("Intel", "NVIDIA"),
    )
    outputs = iter(
        [
            "GPU-B,90,80,200,2,8,1900,70\nGPU-A,10,40,50,1,8,900,20\n",
            "GPU-A,10,40,50,1,8,900,20\nGPU-B,90,80,200,2,8,1900,70\n",
        ]
    )
    monkeypatch.setattr(
        "ha_windows_bridge.system_monitor.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=next(outputs)),
    )

    first = monitor._gpu_metrics()
    second = monitor._gpu_metrics()

    assert monitor._selected_nvidia_uuid == "GPU-A"
    assert first == second
    assert first["gpu_percent"] == 10


def test_r12_gpu_fan_percent_has_new_identity_and_legacy_rpm_contract() -> None:
    config = AppConfig(
        device_id="pc",
        mqtt=MqttConfig(host="broker"),
        publish_gpu_stats=True,
    )
    messages = discovery_messages(
        config,
        hardware_metrics={"gpu_fan", "gpu_fan_percent"},
    )
    payloads = {
        message.payload["state_topic"].rsplit("/", 2)[-2]: message.payload
        for message in messages
        if "/gpu_fan/" in message.payload.get("state_topic", "")
        or "/gpu_fan_percent/" in message.payload.get("state_topic", "")
    }

    assert payloads["gpu_fan"]["unit_of_measurement"] == "rpm"
    assert payloads["gpu_fan_percent"]["unit_of_measurement"] == "%"
    assert (
        payloads["gpu_fan"]["unique_id"]
        != payloads["gpu_fan_percent"]["unique_id"]
    )


def test_r13_adaptive_key_ignores_uptime_and_disabled_gpu_is_never_called() -> None:
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    values = iter(
        [
            SystemMetrics(10, 20, 100),
            SystemMetrics(10, 20, 101),
        ]
    )
    provider = AdaptiveProvider(
        "cpu_ram",
        lambda: next(values),
        state,
        1,
        interval=5,
        maximum_interval=30,
        comparison_key=stable_system_sample_key,
    )
    provider._stopping = False
    assert provider._sample(0)
    assert provider._sample(0)
    assert provider._current_interval == 7.5

    calls = {"cpu": 0, "gpu": 0}
    app = Application.__new__(Application)
    app.events = EventBus()
    app.computer_state = state
    app._generation = 1
    app.log = Mock()
    app.system = SimpleNamespace(
        cpu_ram_metrics=lambda: SystemMetrics(1, 2, 3),
        cpu_hardware_snapshot=lambda: (
            calls.__setitem__("cpu", calls["cpu"] + 1)
            or SystemMetrics(0, 0, 3)
        ),
        gpu_metrics_snapshot=lambda **_kwargs: calls.__setitem__(
            "gpu",
            calls["gpu"] + 1,
        ),
    )
    app.config = AppConfig(
        publish_cpu_stats=True,
        publish_gpu_stats=False,
        publish_ram_stats=False,
    )
    providers = app._create_system_providers(())
    assert "gpu" not in {item.source for item in providers}
    next(item for item in providers if item.source == "cpu_hardware").read()
    assert calls == {"cpu": 1, "gpu": 0}


class _MqttClient:
    def __init__(self) -> None:
        self.disconnects = 0
        self.socket_closes = 0

    def max_queued_messages_set(self, _value):
        return None

    def max_inflight_messages_set(self, _value):
        return None

    def will_set(self, *_args, **_kwargs):
        return None

    def disconnect(self):
        self.disconnects += 1

    def _sock_close(self):
        self.socket_closes += 1


def test_r14_network_wake_coalesces_and_shutdown_cancels_pending() -> None:
    scheduled = []
    cancelled = []

    def scheduler(_delay, callback):
        scheduled.append(callback)

        def cancel():
            cancelled.append(True)

        return cancel

    client = _MqttClient()
    transport = MqttTransport(
        MqttConfig(host="broker"),
        "pc",
        EventBus(),
        lambda *_args: None,
        set(),
        client_factory=lambda *_args, **_kwargs: client,
        network_delay=lambda: 0.1,
        network_scheduler=scheduler,
    )
    assert transport.network_changed()
    assert not transport.network_changed()
    assert len(scheduled) == 1
    assert client.disconnects == 0
    assert client.socket_closes == 0
    scheduled[0]()
    assert transport._network_wake.is_set()

    other = MqttTransport(
        MqttConfig(host="broker"),
        "pc",
        EventBus(),
        lambda *_args: None,
        set(),
        client_factory=lambda *_args, **_kwargs: _MqttClient(),
        network_delay=lambda: 0.1,
        network_scheduler=scheduler,
    )
    assert other.network_changed()
    assert other.stop()
    assert cancelled


def test_r14_native_ip_interface_callback_only_emits_wake(monkeypatch) -> None:
    callbacks = []
    cancelled = []

    class IpHelper:
        def NotifyIpInterfaceChange(
            self,
            _family,
            callback,
            _context,
            _initial,
            _handle,
        ):
            callbacks.append(callback)
            return 0

        def CancelMibChangeNotify2(self, _handle):
            cancelled.append(True)

    monkeypatch.setattr(
        "ha_windows_bridge.windows.native.ctypes.windll",
        SimpleNamespace(iphlpapi=IpHelper()),
    )
    events = EventBus()
    received = []
    events.subscribe(
        "windows.network_changed",
        lambda event: received.append(event.topic),
    )
    bridge = WindowsEventBridge.__new__(WindowsEventBridge)
    bridge.application = SimpleNamespace(events=events)
    bridge._network_registered = False
    bridge._network_handle = ctypes.wintypes.HANDLE()
    bridge._network_callback = None
    bridge._enabled = False
    bridge._registered = False

    bridge._register_network_notifications()
    callbacks[0](None, None, 0)
    assert received == ["windows.network_changed"]
    bridge.close()
    assert cancelled == [True]
