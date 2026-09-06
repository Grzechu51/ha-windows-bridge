from __future__ import annotations

import copy
import threading
import time
from types import SimpleNamespace

import pytest

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.application.master_audio import MasterAudioProvider
from ha_windows_bridge.communication.publishing import StatePublisher
from ha_windows_bridge.communication.state_outbox import StateOutbox
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ComputerStateStore, StateQuality
from ha_windows_bridge.discovery import master_volume_topics


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return bool(predicate())


def test_computer_state_tracks_health_freshness_and_rejects_stale_generation():
    wall = [100.0]
    monotonic = [10.0]
    events = EventBus()
    store = ComputerStateStore(
        events,
        wall_clock=lambda: wall[0],
        monotonic_clock=lambda: monotonic[0],
    )
    seen = []
    events.subscribe("computer_state.changed", lambda event: seen.append(event.data))

    initial = store.begin_generation(1)
    assert initial.generation == 1
    assert store.observe_master_audio(.25, False, generation=1)
    current = store.snapshot(stale_after=5)
    assert current.revision > initial.revision
    assert current.master_audio.volume == .25
    assert current.master_audio.quality == StateQuality.GOOD
    assert current.health_for("master_audio").last_success_at == 100

    monotonic[0] = 16
    stale = store.snapshot(stale_after=5)
    assert stale.master_audio.quality == StateQuality.STALE
    assert stale.health_for("master_audio").quality == StateQuality.STALE

    store.begin_generation(2, detail="reconfigure")
    revision = store.snapshot().revision
    assert not store.observe_master_audio(.9, True, generation=1)
    assert store.snapshot().revision == revision
    assert store.snapshot().master_audio is None
    assert len(seen) == 3


def test_computer_state_keeps_last_value_when_provider_health_degrades():
    store = ComputerStateStore(EventBus())
    store.begin_generation(1)
    store.observe_master_audio(.4, False, generation=1)
    last_success = store.snapshot().health_for("master_audio").last_success_at

    assert store.fail_master_audio(
        StateQuality.UNAVAILABLE,
        "endpoint_unavailable",
        generation=1,
    )
    state = store.snapshot()
    assert state.master_audio.volume == .4
    assert state.master_audio.quality == StateQuality.UNAVAILABLE
    assert state.health_for("master_audio").last_success_at == last_success


def test_state_outbox_separates_observed_and_delivered_and_replays_latest():
    outbox = StateOutbox(capacity=2, generation=4)
    assert outbox.observe("volume", "20", generation=4, revision=1)
    assert not outbox.flush(lambda _item: False)
    assert [item.payload for item in outbox.observed()] == ["20"]
    assert outbox.delivered() == ()

    assert outbox.observe("volume", "80", generation=4, revision=2)
    sent = []
    assert outbox.flush(lambda item: sent.append(item.payload) or True)
    assert sent == ["80"]
    assert outbox.delivered()[0].revision == 2

    outbox.request_replay()
    assert [item.payload for item in outbox.pending()] == ["80"]
    assert outbox.flush(lambda item: sent.append(item.payload) or True)
    assert sent == ["80", "80"]


def test_state_outbox_generation_prevents_late_delivery_ack():
    outbox = StateOutbox(generation=1)
    outbox.observe("volume", "20", generation=1, revision=1)
    entered = threading.Event()
    release = threading.Event()

    def delayed_send(_item):
        entered.set()
        assert release.wait(2)
        return True

    worker = threading.Thread(target=lambda: outbox.flush(delayed_send), daemon=True)
    worker.start()
    assert entered.wait(1)
    outbox.begin_generation(2)
    outbox.observe("volume", "80", generation=2, revision=2)
    release.set()
    worker.join(1)

    assert not worker.is_alive()
    assert outbox.delivered() == ()
    assert [item.payload for item in outbox.pending()] == ["80"]


def test_state_outbox_has_an_explicit_key_bound():
    outbox = StateOutbox(capacity=1)
    outbox.observe("one", "1", revision=1)
    assert not outbox.observe("one", "different", revision=1)
    with pytest.raises(OverflowError):
        outbox.observe("two", "2")


class FakeAudio:
    def __init__(self):
        self.volume = .2
        self.muted = False
        self.threads = []

    def _record(self):
        self.threads.append(threading.get_ident())

    def get_master_snapshot(self):
        self._record()
        return SimpleNamespace(volume=self.volume, muted=self.muted)

    def set_master_volume(self, value):
        self._record()
        self.volume = value
        return True

    def set_master_mute(self, value):
        self._record()
        self.muted = value
        return True

    def get_master_balance(self):
        self._record()
        return 0.0

    def set_master_balance(self, _value):
        self._record()
        return True

    def list_audio_applications(self, **_kwargs):
        return []


def test_master_audio_provider_owns_reads_commands_and_confirming_sample():
    adapter = FakeAudio()
    state = ComputerStateStore(EventBus())
    state.begin_generation(1)
    provider = MasterAudioProvider(adapter, state, 1, poll_interval=10)
    provider.start()
    try:
        assert wait_until(lambda: state.snapshot().master_audio is not None)
        assert provider.set_master_volume(.65)
        assert provider.set_master_mute(True)
        assert state.snapshot().master_audio.volume == .65
        assert state.snapshot().master_audio.muted is True
        assert set(adapter.threads) == {provider.thread_ident}
    finally:
        assert provider.stop()
    assert not provider.is_alive


class FakeTransport:
    def __init__(self):
        self.connected = True
        self.sent = []

    def publish(self, topic, payload, **kwargs):
        self.sent.append((topic, payload, kwargs))
        return True


class FakeGateway:
    instances = []
    stop_result = True

    def __init__(self, _config, router, events):
        self.router = router
        self.transport = FakeTransport()
        self.publisher = StatePublisher(self.transport, events)
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        return self.stop_result


class FakeMedia:
    def __init__(self):
        self.running = False

    def reopen(self):
        self.running = True

    def close(self):
        self.running = False
        return True


def application(gateway=FakeGateway):
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        control_master_volume=True,
        poll_interval=.2,
    )
    store = SimpleNamespace(saved=copy.deepcopy(config))
    store.save = lambda candidate: setattr(store, "saved", copy.deepcopy(candidate))
    startup = SimpleNamespace(
        enabled=False,
        is_enabled=lambda: startup.enabled,
        set_enabled=lambda enabled: setattr(startup, "enabled", enabled),
    )
    return Application(
        config,
        store,
        startup,
        FakeAudio(),
        object(),
        FakeMedia(),
        object(),
        mqtt_factory=gateway,
        events=EventBus(),
    )


def test_application_reuses_one_owner_and_subscription_set_across_cycles():
    FakeGateway.instances.clear()
    app = application()
    base_subscriptions = len(app.events._listeners)
    expected_running_subscriptions = None
    try:
        for _index in range(2):
            assert app.start()
            assert app.start()
            assert wait_until(lambda: app.computer_snapshot().master_audio is not None)
            assert len(
                [
                    thread
                    for thread in threading.enumerate()
                    if thread.name.startswith("master-audio-")
                ]
            ) == 1
            running_subscriptions = len(app.events._listeners)
            if expected_running_subscriptions is None:
                expected_running_subscriptions = running_subscriptions
            assert running_subscriptions == expected_running_subscriptions
            assert running_subscriptions > base_subscriptions
            assert app.stop()
            assert wait_until(lambda: not app.supervisor.active)
            assert len(app.events._listeners) == base_subscriptions

        assert app.start()
        assert wait_until(lambda: app.computer_snapshot().master_audio is not None)
        changed = copy.deepcopy(app.config)
        changed.mqtt.host = "new-broker"
        assert app.apply_configuration(changed)
        assert wait_until(lambda: app.config.mqtt.host == "new-broker")
        assert len(app.events._listeners) == expected_running_subscriptions
        assert len(
            [
                thread
                for thread in threading.enumerate()
                if thread.name.startswith("master-audio-")
            ]
        ) == 1
    finally:
        assert app.shutdown()
    assert not any(
        thread.name.startswith("master-audio-") for thread in threading.enumerate()
    )


def test_master_audio_command_confirms_computer_state_and_ha_projection():
    FakeGateway.instances.clear()
    app = application()
    try:
        assert app.start()
        assert wait_until(lambda: app.computer_snapshot().master_audio is not None)
        result = app.command("audio.master.volume", {"value": .73})
        assert result.status == "accepted"
        topic = master_volume_topics(app.config)[1]
        assert wait_until(lambda: app.computer_snapshot().master_audio.volume == .73)
        assert wait_until(
            lambda: any(
                sent_topic == topic and payload == "73"
                for sent_topic, payload, _kwargs in FakeGateway.instances[-1].transport.sent
            )
        )
    finally:
        assert app.shutdown()


def test_shutdown_report_names_owner_that_did_not_stop():
    class StuckGateway(FakeGateway):
        stop_result = False

    app = application(StuckGateway)
    assert app.start()
    assert wait_until(lambda: bool(app.supervisor.active))
    assert not app.shutdown()
    assert "mqtt" in app.last_shutdown_report.unfinished
    result = next(
        item for item in app.last_shutdown_report.results if item.owner == "mqtt"
    )
    assert result.outcome.value == "timeout"
    assert not app.shutdown()
