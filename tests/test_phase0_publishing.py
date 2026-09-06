"""Audit P01/P02/P06: real publisher, gateway and controlled thread interleavings."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ha_windows_bridge.application.telemetry import TelemetryService
from ha_windows_bridge.communication.gateway import MqttGateway
from ha_windows_bridge.communication.publishing import StatePublisher
from ha_windows_bridge.communication.state import ConnectionMachine
from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.discovery import master_volume_topics


def telemetry(transport):
    config = AppConfig()
    audio = SimpleNamespace(get_master_snapshot=lambda: SimpleNamespace(volume=.2, muted=False))
    publisher = StatePublisher(transport, EventBus())
    return TelemetryService(config, audio, Mock(), Mock(), publisher, EventBus(), []), publisher


@pytest.mark.parametrize("failure", [False, OSError("send failed")])
def test_p01_latest_sample_survives_failed_send_and_reconnect(failure):
    sent = []
    transport = Mock(connected=True)
    transport.publish.side_effect = lambda topic, value, **kw: sent.append((topic, value)) or True
    service, publisher = telemetry(transport)
    topic = master_volume_topics(service.config)[1]
    service._monitor_master()
    assert (topic, "20") in sent
    transport.publish.side_effect = failure if isinstance(failure, Exception) else lambda *a, **k: False
    service.audio.get_master_snapshot = lambda: SimpleNamespace(volume=.8, muted=False)
    service._monitor_master()
    transport.publish.side_effect = lambda topic, value, **kw: sent.append((topic, value)) or True
    publisher.replay()
    service._monitor_master()
    assert [value for key, value in sent if key == topic] == ["20", "80"]


def test_p01_offline_observation_is_cached_and_failed_replay_is_retried():
    transport = Mock(connected=False)
    transport.publish.return_value = False
    service, publisher = telemetry(transport)
    service._monitor_master()
    publisher.replay()
    transport.connected = True
    transport.publish.return_value = True
    assert publisher.flush()
    assert any(call.args[1] == "20" for call in transport.publish.call_args_list)
    transport.publish.reset_mock()
    assert publisher.flush()
    transport.publish.assert_not_called()


def test_p06_gateway_reconnect_and_publish_finish_in_controlled_interleaving(monkeypatch):
    bus = EventBus()
    gateway = MqttGateway(AppConfig(), Mock(), bus)
    machine = gateway.transport.machine
    epoch = machine.begin()
    in_send, connected, sent = threading.Event(), threading.Event(), threading.Event()
    failures = []

    def send(*args, **kwargs):
        in_send.set()
        if not connected.wait(2):
            failures.append("connection callback blocked")
            return False
        result = gateway.transport.connected  # Actual ConnectionMachine lock acquisition.
        sent.set()
        return result

    def callback(event):
        if event.data.state == "connected":
            connected.set()
            gateway._connection_changed(event)
            if not sent.wait(2):
                failures.append("publisher blocked by state callback")

    monkeypatch.setattr(gateway.transport, "publish", send)
    unsubscribe = bus.subscribe("connection.changed", callback)
    publishing = threading.Thread(target=lambda: gateway.publisher.publish("state", "80"), daemon=True)
    connecting = threading.Thread(target=lambda: machine.connected(epoch), daemon=True)
    try:
        publishing.start()
        assert in_send.wait(2)
        connecting.start()
        publishing.join(3)
        connecting.join(3)
        assert not publishing.is_alive() and not connecting.is_alive()
        assert not failures
        assert gateway.publisher.flush()  # Reconnect during send must leave a replay pending.
    finally:
        connected.set()
        unsubscribe()


@pytest.mark.parametrize("transport", ["mqtt", "home_assistant"])
def test_every_connection_transition_emits_outside_state_lock(transport):
    bus = EventBus()
    machine = ConnectionMachine(transport, bus)
    failures = []
    readers = []
    def callback(event):
        done = threading.Event()
        def read():
            _ = machine.status
            done.set()
        thread = threading.Thread(target=read, daemon=True)
        readers.append(thread)
        thread.start()
        if not done.wait(1):
            failures.append(event.data.state)
    bus.subscribe("connection.changed", callback)
    epoch = machine.begin()
    machine.connected(epoch)
    machine.failed(epoch, "network")
    machine.retry(epoch)
    machine.stop()
    epoch = machine.begin()
    machine.failed(epoch, "auth", authentication=True)
    machine.stop(suspended=True)
    for thread in readers:
        thread.join(1)
    assert not failures


def test_concurrent_observation_and_replay_do_not_wait_for_io_or_lose_new_value():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def send(topic, value, **kwargs):
        calls.append(value)
        if value == "20":
            entered.set()
            assert release.wait(2)
        return True
    publisher = StatePublisher(SimpleNamespace(publish=send), EventBus())
    first = threading.Thread(target=lambda: publisher.publish("state", "20"), daemon=True)
    first.start()
    try:
        assert entered.wait(2)
        assert not publisher.publish("state", "80")
        publisher.request_replay()
    finally:
        release.set()
        first.join(2)
    assert not first.is_alive()
    assert publisher.flush()
    assert calls == ["20", "80"]


def test_replay_preserves_qos_and_retained_deletion_and_never_replays_commands():
    transport = Mock()
    transport.publish.return_value = True
    publisher = StatePublisher(transport, EventBus())
    publisher.publish("state", "", qos=2)
    publisher.publish("result", "done", retain=False)
    transport.publish.reset_mock()
    publisher.replay()
    transport.publish.assert_called_once_with("state", "", qos=2, retain=True)


def test_p02_first_output_and_hotplug_request_inventory_without_io():
    service, _ = telemetry(Mock())
    service._inventory_requested.clear()
    service.audio.list_output_devices = lambda: [SimpleNamespace(name="Speakers", is_default=True)]
    service._monitor_audio_output()
    assert service._inventory_requested.is_set()
    service._inventory_requested.clear()
    service._monitor_audio_output()
    assert not service._inventory_requested.is_set()
    service.audio.list_output_devices = lambda: [SimpleNamespace(name="Headset", is_default=True)]
    service._monitor_audio_output()
    assert service._inventory_requested.is_set()
