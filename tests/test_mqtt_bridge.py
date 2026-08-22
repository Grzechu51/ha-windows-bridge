from __future__ import annotations

import hashlib
import json

import pytest

from ha_windows_bridge.audio import AudioSessionSnapshot, MicrophoneSnapshot
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.discovery import (
    active_app_topic,
    active_window_topic,
    app_close_topic,
    app_mute_topics,
    app_start_topic,
    app_volume_topics,
    audio_output_topics,
    fullscreen_topic,
    idle_topic,
    master_mute_topics,
    master_volume_topics,
    microphone_mute_topics,
    microphone_volume_topics,
    pc_active_topic,
    session_locked_topic,
    system_metric_topic,
)
from ha_windows_bridge.media import MediaArtwork, MediaCapabilities, MediaSnapshot
from ha_windows_bridge.media_protocol import (
    media_announcement_topic,
    media_thumbnail_topic,
    media_topics,
)
from ha_windows_bridge.mqtt_bridge import MAX_COMMAND_PAYLOAD, MqttBridge
from ha_windows_bridge.system_monitor import PcContext, SystemMetrics


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("50", 0.5),
        (b"0.5", 0.5),
        ("1", 0.01),
        ("1.0", 1.0),
        ("100", 1.0),
        ("150", 1.0),
        ("-3", 0.0),
    ],
)
def test_parse_volume_accepts_percentage_and_fraction(payload, expected) -> None:
    assert MqttBridge.parse_volume(payload) == expected


def test_parse_volume_rejects_text() -> None:
    with pytest.raises(ValueError):
        MqttBridge.parse_volume("loud")


@pytest.mark.parametrize("payload", ["nan", "inf", "-inf", "1e9999"])
def test_parse_volume_rejects_non_finite_numbers(payload) -> None:
    with pytest.raises(ValueError):
        MqttBridge.parse_volume(payload)


class FakeAudio:
    def __init__(self):
        self.volume = 0.25
        self.master_volume = 0.3
        self.master_mute = False
        self.microphone_volume = 0.6
        self.microphone_mute = False
        self.set_calls = []
        self.master_set_calls = []
        self.mute_calls = []
        self.master_mute_calls = []
        self.microphone_volume_calls = []
        self.microphone_mute_calls = []
        self.output_calls = []

    def get_volume(self, process_name):
        return self.volume

    def set_volume(self, process_name, volume):
        self.set_calls.append((process_name, volume))
        self.volume = volume
        return True

    def get_master_volume(self):
        return self.master_volume

    def get_master_snapshot(self):
        return AudioSessionSnapshot(self.master_volume, self.master_mute)

    def set_master_volume(self, volume):
        self.master_set_calls.append(volume)
        self.master_volume = volume
        return True

    def set_mute(self, process_name, muted):
        self.mute_calls.append((process_name, muted))
        return True

    def set_master_mute(self, muted):
        self.master_mute_calls.append(muted)
        self.master_mute = muted
        return True

    def set_microphone_volume(self, volume):
        self.microphone_volume_calls.append(volume)
        self.microphone_volume = volume
        return True

    def set_microphone_mute(self, muted):
        self.microphone_mute_calls.append(muted)
        self.microphone_mute = muted
        return True

    def set_output_device(self, name):
        self.output_calls.append(name)
        return True


class FakeSystem:
    def __init__(self):
        self.started = []
        self.closed = []

    def start_application(self, path, _process_name="", _display_name=""):
        self.started.append(path)
        return True

    def running_process_names(self, process_names):
        return {name.casefold() for name in process_names}

    def close_application(self, process_name):
        self.closed.append(process_name)
        return 1

    def context_snapshot(self):
        return PcContext("Cyberpunk2077.exe", "Cyberpunk 2077", True, 12, False)

    def system_metrics(self, _include_gpu):
        return SystemMetrics(18.5, 43.2, 3600, 97.0, 71.0, 238.0, 6800.0, 8192.0)


class FakeMedia:
    def __init__(self):
        self.commands = []

    def snapshot(self):
        artwork_data = b"\x89PNG\r\n\x1a\ncover"
        return MediaSnapshot(
            state="playing",
            title="Test track",
            artist="Test artist",
            duration=180.0,
            position=12.0,
            capabilities=MediaCapabilities(play=True, pause=True, next=True, seek=True),
            artwork=MediaArtwork(
                artwork_data,
                "image/png",
                hashlib.sha256(artwork_data).hexdigest(),
            ),
        )

    def execute(self, action, value=None):
        self.commands.append((action, value))
        return True

    def close(self):
        return None


class FakePublishResult:
    def wait_for_publish(self, _timeout=None):
        return None


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakePublishResult()


class FakeMessage:
    def __init__(self, topic, payload, retain):
        self.topic = topic
        self.payload = payload
        self.retain = retain


def test_retained_command_never_changes_windows_volume() -> None:
    app = AudioAppConfig("Spotify.exe", "Spotify", "spotify", True)
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    audio = FakeAudio()
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()
    command, _ = app_volume_topics(config, app)

    bridge._on_message(None, None, FakeMessage(command, b"80", True))

    assert audio.set_calls == []
    assert bridge.messages_processed == 1


def test_oversized_command_never_changes_windows_volume() -> None:
    app = AudioAppConfig("Spotify.exe", "Spotify", "spotify", True)
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    audio = FakeAudio()
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()
    command, _ = app_volume_topics(config, app)

    bridge._on_message(
        None,
        None,
        FakeMessage(command, b"9" * (MAX_COMMAND_PAYLOAD + 1), False),
    )

    assert audio.set_calls == []
    assert bridge.messages_processed == 1


def test_non_retained_command_sets_volume_and_publishes_state() -> None:
    app = AudioAppConfig("Spotify.exe", "Spotify", "spotify", True)
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    audio = FakeAudio()
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()
    command, state = app_volume_topics(config, app)

    bridge._on_message(None, None, FakeMessage(command, b"80", False))

    assert audio.set_calls == [("Spotify.exe", 0.8)]
    assert (state, "80", 1, True) in bridge.client.published
    assert bridge.messages_processed == 1


def test_master_volume_command_controls_windows_endpoint() -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[])
    audio = FakeAudio()
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()
    command, state = master_volume_topics(config)

    bridge._on_message(None, None, FakeMessage(command, b"80", False))

    assert audio.master_set_calls == [0.8]
    assert (state, "80", 1, True) in bridge.client.published


def test_mute_microphone_and_audio_output_commands() -> None:
    app = AudioAppConfig("Discord.exe", "Discord", "discord", True)
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    audio = FakeAudio()
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()

    master_command, master_state = master_mute_topics(config)
    app_command, app_state = app_mute_topics(config, app)
    mic_volume_command, mic_volume_state = microphone_volume_topics(config)
    mic_mute_command, mic_mute_state = microphone_mute_topics(config)
    output_command, output_state = audio_output_topics(config)
    bridge._on_message(None, None, FakeMessage(master_command, b"ON", False))
    bridge._on_message(None, None, FakeMessage(app_command, b"ON", False))
    bridge._on_message(None, None, FakeMessage(mic_volume_command, b"55", False))
    bridge._on_message(None, None, FakeMessage(mic_mute_command, b"ON", False))
    bridge._on_message(None, None, FakeMessage(output_command, b"Headphones", False))

    assert audio.master_mute_calls == [True]
    assert audio.mute_calls == [("Discord.exe", True)]
    assert audio.microphone_volume_calls == [0.55]
    assert audio.microphone_mute_calls == [True]
    assert audio.output_calls == ["Headphones"]
    assert (master_state, "ON", 1, True) in bridge.client.published
    assert (app_state, "ON", 1, True) in bridge.client.published
    assert (mic_volume_state, "55", 1, True) in bridge.client.published
    assert (mic_mute_state, "ON", 1, True) in bridge.client.published
    assert (output_state, "Headphones", 1, True) in bridge.client.published


def test_pc_context_and_system_metrics_are_published() -> None:
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        apps=[],
        idle_threshold=300,
        publish_activity=True,
        publish_idle=True,
        publish_session_lock=True,
        publish_system_stats=True,
        publish_gpu_stats=True,
    )
    bridge = MqttBridge(config, audio=FakeAudio(), system_monitor=FakeSystem())
    bridge.client = FakeClient()
    bridge._connected.set()

    bridge._monitor_context()
    bridge._monitor_system()

    published = bridge.client.published
    assert (active_app_topic(config), "Cyberpunk2077.exe", 1, True) in published
    assert (active_window_topic(config), "Cyberpunk 2077", 1, True) in published
    assert (fullscreen_topic(config), "ON", 1, True) in published
    assert (idle_topic(config), "12", 1, True) in published
    assert (pc_active_topic(config), "ON", 1, True) in published
    assert (session_locked_topic(config), "OFF", 1, True) in published
    assert (system_metric_topic(config, "cpu"), "18.5", 1, True) in published
    assert (system_metric_topic(config, "gpu_temperature"), "71.0", 1, True) in published


def test_remote_app_actions_require_enabled_configuration() -> None:
    app = AudioAppConfig(
        "Spotify.exe",
        "Spotify",
        "spotify",
        True,
        "C:/Apps/Spotify.exe",
        True,
        True,
    )
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    system = FakeSystem()
    bridge = MqttBridge(config, audio=FakeAudio(), system_monitor=system)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()

    bridge._on_message(None, None, FakeMessage(app_start_topic(config, app), b"PRESS", False))
    bridge._on_message(None, None, FakeMessage(app_close_topic(config, app), b"PRESS", False))

    assert system.started == ["C:/Apps/Spotify.exe"]
    assert system.closed == ["Spotify.exe"]


def test_running_state_uses_process_even_without_audio_session() -> None:
    app = AudioAppConfig("Discord.exe", "Discord", "discord", True)
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[app])
    bridge = MqttBridge(config, audio=FakeAudio(), system_monitor=FakeSystem())
    bridge.client = FakeClient()
    bridge._connected.set()

    bridge._monitor_apps([app], {}, {"discord.exe"})

    assert any(
        topic.endswith("/app/discord/running") and payload == "ON"
        for topic, payload, *_ in bridge.client.published
    )


def test_microphone_activity_is_held_long_enough_to_be_visible(monkeypatch) -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[], control_microphone=True)
    audio = FakeAudio()
    snapshots = iter(
        [
            MicrophoneSnapshot(0.6, False, True),
            MicrophoneSnapshot(0.6, False, False),
            MicrophoneSnapshot(0.6, False, False),
        ]
    )
    audio.get_microphone_snapshot = lambda: next(snapshots)
    bridge = MqttBridge(config, audio=audio)
    bridge.client = FakeClient()
    bridge._connected.set()
    moments = iter([10.0, 10.5, 11.5])
    monkeypatch.setattr("ha_windows_bridge.mqtt_bridge.time.monotonic", lambda: next(moments))

    bridge._monitor_microphone()
    bridge._monitor_microphone()
    bridge._monitor_microphone()

    active_states = [
        payload
        for topic, payload, *_ in bridge.client.published
        if topic.endswith("/microphone/active")
    ]
    assert active_states == ["ON", "OFF"]


def test_discovery_can_be_republished_and_reports_entity_count() -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[])
    bridge = MqttBridge(config, audio=FakeAudio())
    bridge.client = FakeClient()
    bridge._connected.set()

    count = bridge.publish_discovery()

    announcements = [
        item for item in bridge.client.published if item[0] == media_announcement_topic(config)
    ]
    assert len(announcements) == 1
    payload = json.loads(announcements[0][1])
    assert count == len(payload["entities"])
    assert count >= 3
    assert len(bridge.client.published) == 3
    assert all(not item[1] for item in bridge.client.published[1:])
    assert all(qos == 1 and retain for _topic, _payload, qos, retain in bridge.client.published)


def test_discovery_cleanup_publishes_empty_retained_definitions() -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[])
    bridge = MqttBridge(config, audio=FakeAudio())
    bridge.client = FakeClient()
    bridge._connected.set()

    assert bridge.remove_discovery(["homeassistant/sensor/pc/cpu/config"]) is True
    assert bridge.client.published == [("homeassistant/sensor/pc/cpu/config", "", 1, True)]


def test_media_player_command_is_dispatched_and_retained_command_is_ignored() -> None:
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        apps=[],
        media_player_enabled=True,
    )
    media = FakeMedia()
    bridge = MqttBridge(config, audio=FakeAudio(), media_service=media)
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()
    command, _ = media_topics(config)

    bridge._on_message(
        None,
        None,
        FakeMessage(command, b'{"action":"seek","value":45.5}', False),
    )
    bridge._on_message(
        None,
        None,
        FakeMessage(command, b'{"action":"pause","value":null}', True),
    )

    assert media.commands == [("seek", 45.5)]


def test_media_player_publishes_announcement_and_changed_state() -> None:
    config = AppConfig(
        device_id="pc_123",
        mqtt=MqttConfig(host="broker", base_topic="hawn/pc"),
        apps=[],
        media_player_enabled=True,
    )
    bridge = MqttBridge(config, audio=FakeAudio(), media_service=FakeMedia())
    bridge.client = FakeClient()
    bridge._connected.set()

    bridge.publish_media_announcement()
    bridge._monitor_media()
    bridge._monitor_media()

    announcement = [
        item for item in bridge.client.published if item[0] == media_announcement_topic(config)
    ]
    _, state_topic = media_topics(config)
    states = [item for item in bridge.client.published if item[0] == state_topic]
    thumbnails = [
        item for item in bridge.client.published if item[0] == media_thumbnail_topic(config)
    ]
    assert len(announcement) == 1
    assert len(states) == 1
    assert len(thumbnails) == 1
    assert json.loads(announcement[0][1])["media_player"]["enabled"] is True
    assert json.loads(states[0][1])["title"] == "Test track"
    assert json.loads(thumbnails[0][1])["content_type"] == "image/png"


def test_power_action_and_notification_commands_are_dispatched() -> None:
    from ha_windows_bridge.discovery import power_action_topic, windows_notification_topic

    class FakePowerActions:
        def __init__(self):
            self.actions = []

        def execute(self, action):
            self.actions.append(action)
            return True, "Action accepted"

    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        apps=[],
        allow_power_actions=True,
        enable_windows_notifications=True,
    )
    power = FakePowerActions()
    notifications = []
    bridge = MqttBridge(
        config,
        audio=FakeAudio(),
        power_actions=power,
        notification_callback=lambda title, message: notifications.append((title, message)),
    )
    bridge.client = FakeClient()
    bridge._connected.set()
    bridge._build_command_map()

    bridge._on_message(
        None,
        None,
        FakeMessage(power_action_topic(config, "restart"), b"", False),
    )

    bridge._on_message(
        None,
        None,
        FakeMessage(power_action_topic(config, "restart"), b"PRESS", False),
    )
    bridge._on_message(
        None,
        None,
        FakeMessage(
            windows_notification_topic(config),
            b'{"title":"HA","message":"Front door is open"}',
            False,
        ),
    )
