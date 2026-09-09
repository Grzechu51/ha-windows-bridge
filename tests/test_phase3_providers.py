from __future__ import annotations

import asyncio
import queue
import threading
from ctypes import addressof, wintypes
from types import SimpleNamespace

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.application.master_audio import MasterAudioProvider
from ha_windows_bridge.application.providers import (
    AdaptiveProvider,
    MediaProvider,
    StorageSnapshot,
)
from ha_windows_bridge.audio import (
    AudioApplication,
    AudioOutputDevice,
    AudioProviderSnapshot,
    AudioSessionSnapshot,
)
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ComputerStateStore, StateQuality
from ha_windows_bridge.media import MediaSnapshot, WindowsMediaService
from ha_windows_bridge.system_monitor import DiskMetrics, DiskVolume
from ha_windows_bridge.windows.com import ProviderUnavailable
from ha_windows_bridge.windows.native import WindowsEventBridge


def provider_events(events: EventBus, source: str):
    received: queue.Queue = queue.Queue()

    def changed(event):
        if event.data.provider(source) is not None:
            received.put(event.data)

    events.subscribe("computer_state.changed", changed)
    return received


class FakeAudioOwner:
    def __init__(self) -> None:
        self.changed = None
        self.threads: list[int] = []
        self.unsubscribed_on = None
        self.reads: queue.Queue = queue.Queue()
        self.snapshot = AudioProviderSnapshot(
            endpoint_id="endpoint-a",
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
                    "C:/Player.exe",
                    0.4,
                    False,
                    ("session-a",),
                ),
            ),
            outputs=(AudioOutputDevice("endpoint-a", "Speakers", True),),
            active_process="player.exe",
        )

    def subscribe(self, callback):
        self.threads.append(threading.get_ident())
        self.changed = callback

        def unsubscribe():
            self.unsubscribed_on = threading.get_ident()

        unsubscribe.refresh = lambda: None
        return unsubscribe

    def provider_snapshot(self, **_kwargs):
        self.threads.append(threading.get_ident())
        self.reads.put(None)
        return self.snapshot

    def set_volume(self, _process_name, _volume):
        self.threads.append(threading.get_ident())
        return True

    def get_master_snapshot(self):
        return self.snapshot.master

    def set_master_volume(self, _volume):
        self.threads.append(threading.get_ident())
        return True

    def set_master_mute(self, _muted):
        self.threads.append(threading.get_ident())
        return True

    def get_master_balance(self):
        self.threads.append(threading.get_ident())
        return 0.0

    def set_master_balance(self, _balance):
        self.threads.append(threading.get_ident())
        return True


def test_audio_owner_handles_endpoint_and_session_disappearance_from_one_thread():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    adapter = FakeAudioOwner()
    provider = MasterAudioProvider(
        adapter,
        state,
        1,
        poll_interval=60,
        process_names=("player.exe",),
        include_sessions=True,
        include_outputs=True,
    )
    provider.start()
    try:
        adapter.reads.get(timeout=1)
        first = state.snapshot().provider("audio").value
        assert first.endpoint_id == "endpoint-a"
        assert first.sessions[0][1].session_ids == ("session-a",)
        assert provider.list_audio_applications()[0].session_ids == ("session-a",)

        adapter.snapshot = AudioProviderSnapshot(errors=("master",))
        adapter.changed()
        adapter.reads.get(timeout=1)
        assert state.snapshot().health_for("audio").quality == StateQuality.UNAVAILABLE
        assert state.snapshot().master_audio.quality == StateQuality.UNAVAILABLE

        adapter.snapshot = AudioProviderSnapshot(
            endpoint_id="endpoint-b",
            master=AudioSessionSnapshot(0.8, False),
            outputs=(AudioOutputDevice("endpoint-b", "Headset", True),),
        )
        adapter.changed()
        adapter.reads.get(timeout=1)
        current = state.snapshot().provider("audio").value
        assert current.endpoint_id == "endpoint-b"
        assert current.sessions == ()
        assert provider.session_snapshot(["player.exe"]) == {}
        assert provider.set_volume("player.exe", 0.5)
        assert set(adapter.threads) == {provider.thread_ident}
    finally:
        assert provider.stop()
    assert adapter.unsubscribed_on == provider.thread_ident


def test_audio_callback_burst_is_coalesced_while_read_is_inflight():
    class BlockingAudio(FakeAudioOwner):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.entered = threading.Event()
            self.release = threading.Event()
            self.follow_up = threading.Event()

        def provider_snapshot(self, **kwargs):
            self.count += 1
            if self.count == 2:
                self.entered.set()
                assert self.release.wait(1)
            if self.count == 3:
                self.follow_up.set()
            return super().provider_snapshot(**kwargs)

    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    adapter = BlockingAudio()
    provider = MasterAudioProvider(adapter, state, 1, poll_interval=60)
    provider.start()
    try:
        adapter.reads.get(timeout=1)
        adapter.changed()
        assert adapter.entered.wait(1)
        for _index in range(50):
            adapter.changed()
        adapter.release.set()
        assert adapter.follow_up.wait(1)
        assert adapter.count == 3
    finally:
        adapter.release.set()
        assert provider.stop()


def test_provider_distinguishes_failure_from_successful_empty_hotplug_result():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    changed = provider_events(events, "storage")
    values: queue.Queue = queue.Queue()
    volume = DiskVolume("C:\\", "disk0", "NTFS", 100.0, 20.0, 80.0)
    values.put(StorageSnapshot((volume,), DiskMetrics(20.0, 80.0, 0.0, 0.0)))

    def read():
        value = values.get(timeout=1)
        if isinstance(value, BaseException):
            raise value
        return value

    provider = AdaptiveProvider(
        "storage",
        read,
        state,
        1,
        interval=60,
        maximum_interval=60,
    )
    provider.start()
    try:
        changed.get(timeout=1)
        values.put(ProviderUnavailable("WMI unavailable"))
        provider.request_refresh()
        degraded = changed.get(timeout=1)
        sample = degraded.provider("storage")
        assert sample.value.volumes == (volume,)
        assert sample.quality == StateQuality.UNAVAILABLE

        values.put(StorageSnapshot())
        provider.request_refresh()
        recovered = changed.get(timeout=1)
        assert recovered.provider("storage").value.volumes == ()
        assert recovered.health_for("storage").quality == StateQuality.GOOD
    finally:
        assert provider.stop()


def test_slow_windows_update_does_not_block_an_independent_provider():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    entered = threading.Event()
    release = threading.Event()
    fast_observed = threading.Event()

    def slow_wua():
        entered.set()
        assert release.wait(2)
        return 0

    events.subscribe(
        "computer_state.changed",
        lambda event: fast_observed.set()
        if event.data.provider("cpu_ram") is not None
        else None,
    )
    slow = AdaptiveProvider(
        "windows_update",
        slow_wua,
        state,
        1,
        interval=1800,
        maximum_interval=1800,
    )
    fast = AdaptiveProvider(
        "cpu_ram",
        lambda: {"cpu": 10},
        state,
        1,
        interval=60,
        maximum_interval=60,
    )
    slow.start()
    assert entered.wait(1)
    fast.start()
    try:
        assert fast_observed.wait(1)
        assert state.snapshot().provider("windows_update") is None
    finally:
        release.set()
        assert fast.stop()
        assert slow.stop()


def test_windows_update_shutdown_timeout_is_reported_and_fences_late_result():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    timed_out = threading.Event()
    events.subscribe(
        "computer_state.changed",
        lambda event: timed_out.set()
        if (
            event.data.health_for("windows_update") is not None
            and event.data.health_for("windows_update").detail == "read_timeout"
        )
        else None,
    )

    def blocked():
        entered.set()
        assert release.wait(2)
        finished.set()
        return 4

    provider = AdaptiveProvider(
        "windows_update",
        blocked,
        state,
        1,
        interval=1800,
        maximum_interval=1800,
        stop_timeout=0.01,
        read_timeout=0.01,
    )
    provider.start()
    assert entered.wait(1)
    assert timed_out.wait(1)
    assert state.snapshot().health_for("windows_update").detail == "read_timeout"
    assert provider.stop() is False
    assert state.snapshot().health_for("windows_update").detail == "shutdown_timeout"
    release.set()
    assert finished.wait(1)
    provider._thread.join(timeout=1)
    provider._io_thread.join(timeout=1)
    assert not provider.is_alive
    assert state.snapshot().provider("windows_update") is None


def test_generation_change_rejects_delayed_wmi_result():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()

    def delayed():
        entered.set()
        assert release.wait(1)
        returned.set()
        return ("stale-device",)

    provider = AdaptiveProvider(
        "pnp",
        delayed,
        state,
        1,
        interval=60,
        maximum_interval=60,
    )
    provider.start()
    assert entered.wait(1)
    state.begin_generation(2)
    release.set()
    assert returned.wait(1)
    assert provider.stop()
    assert state.snapshot().generation == 2
    assert state.snapshot().provider("pnp") is None


def test_gpu_unavailable_has_health_instead_of_an_empty_success():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    observed = threading.Event()
    events.subscribe(
        "computer_state.changed",
        lambda event: observed.set()
        if (
            event.data.health_for("gpu") is not None
            and event.data.health_for("gpu").quality == StateQuality.UNAVAILABLE
        )
        else None,
    )
    provider = AdaptiveProvider(
        "gpu",
        lambda: (_ for _ in ()).throw(ProviderUnavailable("GPU API unavailable")),
        state,
        1,
        interval=60,
        maximum_interval=60,
    )
    provider.start()
    try:
        assert observed.wait(1)
        assert state.snapshot().provider("gpu") is None
    finally:
        assert provider.stop()


class FakeMediaOwner:
    def __init__(self) -> None:
        self.current = MediaSnapshot(
            state="playing",
            title="A",
            source_app="Player",
            session_id="session-a",
        )
        self.changed = None
        self.reads: queue.Queue = queue.Queue()
        self.commands = []

    def reopen(self):
        return None

    def close(self):
        return True

    def subscribe(self, callback):
        self.changed = callback
        return lambda: None

    def snapshot(self):
        self.reads.put(None)
        return self.current

    def execute(self, action, value=None, *, session_id=""):
        self.commands.append((action, value, session_id))
        return session_id == self.current.session_id


def test_gsmtc_registers_and_releases_manager_and_session_events():
    removed = []

    class Session:
        def add_media_properties_changed(self, callback):
            self.media_changed = callback
            return "media-token"

        def add_playback_info_changed(self, callback):
            self.playback_changed = callback
            return "playback-token"

        def add_timeline_properties_changed(self, callback):
            self.timeline_changed = callback
            return "timeline-token"

        def remove_media_properties_changed(self, token):
            removed.append(token)

        def remove_playback_info_changed(self, token):
            removed.append(token)

        def remove_timeline_properties_changed(self, token):
            removed.append(token)

    class Manager:
        def __init__(self):
            self.session = Session()

        def get_current_session(self):
            return self.session

        def add_current_session_changed(self, callback):
            self.current_changed = callback
            return "current-token"

        def add_sessions_changed(self, callback):
            self.sessions_changed = callback
            return "sessions-token"

        def remove_current_session_changed(self, token):
            removed.append(token)

        def remove_sessions_changed(self, token):
            removed.append(token)

    manager = Manager()
    service = WindowsMediaService()

    async def get_manager():
        service._manager = manager
        return manager

    service._manager_async = get_manager
    changed = []

    def callback():
        changed.append("changed")

    asyncio.run(service._subscribe_async(callback))
    service._runner = SimpleNamespace(schedule=lambda action: action())
    manager.session.playback_changed(None, None)
    manager.current_changed(manager, None)
    assert changed == ["changed", "changed"]
    asyncio.run(service._unsubscribe_async(callback))
    assert set(removed) == {
        "media-token",
        "playback-token",
        "timeline-token",
        "current-token",
        "sessions-token",
    }


def test_media_events_track_session_change_disappearance_and_target_commands():
    events = EventBus()
    state = ComputerStateStore(events)
    state.begin_generation(1)
    adapter = FakeMediaOwner()
    provider = MediaProvider(adapter, state, 1, interval=60)
    changed = provider_events(events, "media")

    def wait_session(session_id):
        while state.snapshot().provider("media") is None or (
            state.snapshot().provider("media").value.session_id != session_id
        ):
            changed.get(timeout=1)

    provider.start()
    try:
        wait_session("session-a")
        assert provider.execute("pause")
        assert adapter.commands[-1] == ("pause", None, "session-a")

        # Session changes between observation and execution: stale target is
        # rejected by the WinRT adapter instead of controlling the new player.
        adapter.current = MediaSnapshot(
            state="playing",
            title="B",
            source_app="Other",
            session_id="session-b",
        )
        assert provider.execute("pause") is False
        assert adapter.commands[-1][2] == "session-a"

        adapter.changed()
        wait_session("session-b")
        assert provider.snapshot().session_id == "session-b"
        assert provider.execute("pause")

        adapter.current = MediaSnapshot(supported=False, error="WinRT lost")
        adapter.changed()
        while state.snapshot().health_for("media").detail != "WinRT lost":
            changed.get(timeout=1)
        assert provider.snapshot().session_id == "session-b"

        adapter.current = MediaSnapshot()
        adapter.changed()
        wait_session("")
        assert provider.snapshot().session_id == ""
        assert provider.execute("play") is False
    finally:
        assert provider.stop()


def test_provider_freshness_is_derived_without_mutating_observed_snapshot():
    wall = [100.0]
    monotonic = [10.0]
    state = ComputerStateStore(
        EventBus(),
        wall_clock=lambda: wall[0],
        monotonic_clock=lambda: monotonic[0],
    )
    state.begin_generation(1)
    assert state.observe_provider(
        "desktop_context",
        SimpleNamespace(locked=False),
        generation=1,
    )
    monotonic[0] = 20.0
    stale = state.snapshot(stale_after=5.0)
    assert stale.provider("desktop_context").quality == StateQuality.STALE
    assert stale.health_for("desktop_context").quality == StateQuality.STALE
    assert state.snapshot().provider("desktop_context").quality == StateQuality.GOOD


def test_native_windows_callbacks_only_emit_wake_events_for_provider_owners():
    events = EventBus()
    received = []
    for topic in (
        "windows.device_changed",
        "windows.network_changed",
        "windows.display_changed",
        "windows.locked",
        "windows.power_changed",
    ):
        events.subscribe(topic, lambda event: received.append((event.topic, event.data)))
    application = SimpleNamespace(
        events=events,
        suspend=lambda: received.append(("suspend", None)),
        resume=lambda: received.append(("resume", None)),
    )
    bridge = WindowsEventBridge.__new__(WindowsEventBridge)
    bridge.application = application
    bridge.hwnd = 42
    bridge._enabled = True
    bridge._taskbar_message = 0

    def dispatch(message, wparam=0):
        record = wintypes.MSG()
        record.hWnd = 42
        record.message = message
        record.wParam = wparam
        assert bridge.nativeEventFilter("", addressof(record)) == (False, 0)

    dispatch(0x0219)  # WM_DEVICECHANGE
    dispatch(0x007E)  # WM_DISPLAYCHANGE
    dispatch(0x02B1, 7)  # WTS_SESSION_LOCK
    dispatch(0x0218, 4)  # PBT_APMSUSPEND

    assert ("windows.device_changed", None) in received
    assert ("windows.network_changed", None) not in received
    assert ("windows.display_changed", None) in received
    assert ("windows.locked", True) in received
    assert ("windows.power_changed", "suspend") in received
    assert ("suspend", None) in received


def test_disabled_system_capabilities_create_no_pollers_and_enabled_sources_split():
    app = Application.__new__(Application)
    app.events = EventBus()
    app.computer_state = ComputerStateStore(app.events)
    app.computer_state.begin_generation(1)
    app._generation = 1
    app.log = SimpleNamespace()
    app.system = SimpleNamespace(
        context_snapshot=lambda: None,
        running_process_names=lambda _names: set(),
        cpu_ram_metrics=lambda: None,
        gpu_metrics_snapshot=lambda **_kwargs: None,
        windows_health_snapshot=lambda: None,
        pending_windows_updates=lambda: 0,
        list_disk_volumes=lambda: [],
        disk_metrics=lambda *_args, **_kwargs: DiskMetrics(0, 0, 0, 0),
        list_pnp_devices=lambda: [],
    )
    app.config = AppConfig(
        mqtt=MqttConfig(),
        apps=[],
        control_master_volume=False,
    )
    assert app._create_system_providers(()) == []

    app.config.publish_activity = True
    app.config.publish_cpu_stats = True
    app.config.publish_gpu_stats = True
    app.config.publish_windows_health = True
    app.config.publish_disk_stats = True
    app.config.publish_devices = True
    sources = {
        provider.source for provider in app._create_system_providers(("player.exe",))
    }
    assert sources == {
        "desktop_context",
        "processes",
        "cpu_ram",
        "gpu",
        "windows_health",
        "windows_update",
        "storage",
        "pnp",
    }
