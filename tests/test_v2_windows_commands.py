from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ha_windows_bridge.application.commands import CommandRouter
from ha_windows_bridge.application.telemetry import TelemetryService
from ha_windows_bridge.application.windows_commands import WindowsCommands
from ha_windows_bridge.communication.protocol import TopicProtocol, legacy_volume
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.core.commands import Command, CommandError
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.discovery import master_volume_topics, overlay_notification_topic
from ha_windows_bridge.media import MediaSnapshot
from ha_windows_bridge.system_monitor import PcContext, SystemMetrics


@pytest.mark.parametrize("payload,expected", [("50", .5), ("0.5", .5), ("1", .01), ("1.0", 1), ("100", 1)])
def test_entity_volume_formats(payload, expected):
    assert legacy_volume(payload) == expected


@pytest.mark.parametrize("value", ["nan", "inf", "1e9999", "loud", "150", "-3"])
def test_volume_rejects_invalid_or_out_of_range_values(value):
    with pytest.raises(CommandError):
        legacy_volume(value)


def test_protocol_rejects_retain_unknown_topics_and_nonfinite_json():
    config = AppConfig(overlay_enabled=True)
    protocol = TopicProtocol(config)
    for topic, payload, retain in [(master_volume_topics(config)[0], b"42", True), ("unknown", b"42", False), (overlay_notification_topic(config), b'{"data":{"progress":NaN}}', False)]:
        with pytest.raises(CommandError):
            protocol.decode(topic, payload, retain)


def test_remote_actions_are_allowlisted_and_target_bound():
    config = AppConfig(apps=[AudioAppConfig("test.exe", "Test", "test", True)], control_microphone=True)
    audio, system = Mock(), Mock()
    events = EventBus()
    router = CommandRouter()
    WindowsCommands(config, audio, system, Mock(), Mock(), events, ["Monitor"]).install(router)
    results = []
    def execute(kind, arguments, target=""):
        complete = threading.Event()
        command = Command(str(len(results)), kind, target, arguments, time.time() + 10)
        receipt = router.submit(command, lambda result: (results.append(result), complete.set()))
        if receipt.status == "accepted":
            assert complete.wait(2)
            return results[-1]
        results.append(receipt)
        return receipt
    try:
        assert execute("audio.master.volume", {"value": .42}).status == "succeeded"
        audio.set_master_volume.assert_called_once_with(.42)
        assert execute("audio.microphone.mute", {"value": True}).status == "succeeded"
        audio.set_microphone_mute.assert_called_once_with(True)
        assert execute("application.start", {}, "test").code == "not_allowed"
        assert execute("application.volume", {"value": .5}, "unknown").code == "unknown_application"
        assert execute("application.mute", {"value": "false"}, "test").code == "invalid_boolean"
        assert execute("power.shutdown", {}).code == "not_allowed"
        assert execute("shell.run", {"value": "calc.exe"}).code == "not_allowed"
        system.start_application.assert_not_called()
        system.close_application.assert_not_called()
    finally:
        assert router.stop()


def test_overlay_remote_media_cannot_control_unrelated_windows_player():
    events, delivered = EventBus(), []
    events.subscribe("overlay.show", lambda event: delivered.append(event.data))
    config = AppConfig(overlay_enabled=True, media_player_enabled=True)
    system = SimpleNamespace(context_snapshot=lambda: PcContext())
    media = SimpleNamespace(snapshot=lambda: MediaSnapshot())
    service = WindowsCommands(config, Mock(), system, media, Mock(), events, ["Monitor"])
    command = Command("popup", "overlay.show", "", {"message": "TV", "data": {"layout": "media", "media_controls": True}}, time.time() + 10)
    assert service.execute(command)["delivery"] == "queued_for_presentation"
    assert not delivered[0]["data"]["media_controls"]
    system.context_snapshot = lambda: PcContext(fullscreen=True)
    with pytest.raises(CommandError, match="presentation_suppressed"):
        service.execute(command)


def test_sensor_aggregation_and_v2_inventory_are_separate_from_transport():
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[], publish_ram_stats=True, publish_cpu_stats=True, publish_activity=True)
    publisher = Mock(connected=True)
    system = Mock()
    system.system_metrics.return_value = SystemMetrics(18.5, 43.2, 3600, ram_used_gb=13.5, ram_total_gb=32)
    system.context_snapshot.return_value = PcContext("test.exe", "Window", False, 12, False)
    service = TelemetryService(config, Mock(), system, Mock(), publisher, EventBus(), ["Monitor"])
    service._monitor_system()
    service._monitor_context()
    values = {call.args[0]: call.args[1] for call in publisher.publish.call_args_list}
    assert any(value == "18.5" for value in values.values())
    assert any(value == "43.2" for value in values.values())
    assert any(value == "test.exe" for value in values.values())
    publisher.reset_mock()
    service.publish_discovery()
    announcements = [json.loads(call.args[1]) for call in publisher.publish.call_args_list if str(call.args[1]).startswith('{')]
    assert announcements[0]["schema"] == 3
    assert announcements[0]["protocol"]["version"] == 2
