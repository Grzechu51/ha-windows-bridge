from __future__ import annotations

from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.discovery import (
    all_possible_discovery_topics,
    discovery_messages,
    discovery_topics,
)


def sample_config() -> AppConfig:
    return AppConfig(
        device_name="Gaming PC",
        device_id="gaming_pc_123",
        mqtt=MqttConfig(host="broker", base_topic="hawn/gaming-pc"),
        apps=[
            AudioAppConfig(
                "Spotify.exe",
                "Spotify",
                "spotify",
                True,
                "C:/Apps/Spotify.exe",
                True,
                True,
            )
        ],
        control_active_app=True,
        publish_activity=True,
        publish_idle=True,
        publish_session_lock=True,
        publish_system_stats=True,
        publish_gpu_stats=True,
        control_microphone=True,
        control_audio_output=True,
    )


def test_discovery_creates_grouped_entities() -> None:
    messages = discovery_messages(sample_config(), ["Speakers", "Headphones"])
    topics = {message.topic for message in messages}
    assert "homeassistant/number/gaming_pc_123/spotify_volume/config" in topics
    assert "homeassistant/number/gaming_pc_123/master_volume/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/connection/config" in topics
    assert "homeassistant/number/gaming_pc_123/active_volume/config" in topics
    assert "homeassistant/switch/gaming_pc_123/master_mute/config" in topics
    assert "homeassistant/switch/gaming_pc_123/spotify_mute/config" in topics
    assert "homeassistant/button/gaming_pc_123/spotify_start/config" in topics
    assert "homeassistant/button/gaming_pc_123/spotify_close/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/active_app/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/active_window/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/fullscreen/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/idle_time/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/pc_active/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/windows_locked/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/cpu/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/gpu_temperature/config" in topics
    assert "homeassistant/number/gaming_pc_123/microphone_volume/config" in topics
    assert "homeassistant/switch/gaming_pc_123/microphone_mute/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/microphone_active/config" in topics
    assert "homeassistant/select/gaming_pc_123/audio_output/config" in topics
    spotify = next(message.payload for message in messages if "spotify_volume" in message.topic)
    assert spotify["command_topic"] == "hawn/gaming-pc/audio/spotify/volume/set"
    assert spotify["state_topic"] == "hawn/gaming-pc/audio/spotify/volume/state"
    assert spotify["availability_topic"] == "hawn/gaming-pc/status"
    assert spotify["device"]["identifiers"] == ["gaming_pc_123"]
    master = next(message.payload for message in messages if "master_volume" in message.topic)
    assert master["command_topic"] == "hawn/gaming-pc/audio/master/volume/set"
    assert master["state_topic"] == "hawn/gaming-pc/audio/master/volume/state"
    output = next(message.payload for message in messages if "/audio_output/" in message.topic)
    assert output["options"] == ["Speakers", "Headphones"]


def test_disabled_app_is_not_discovered() -> None:
    config = sample_config()
    config.apps[0].enabled = False
    assert not any("spotify" in message.topic for message in discovery_messages(config))


def test_optional_feature_entities_can_be_disabled() -> None:
    config = sample_config()
    config.publish_activity = False
    config.publish_idle = False
    config.publish_session_lock = False
    config.publish_system_stats = False
    config.control_microphone = False
    config.control_audio_output = False
    config.control_master_volume = False
    topics = {message.topic for message in discovery_messages(config)}

    assert not any("active_window" in topic or "fullscreen" in topic for topic in topics)
    assert not any("idle_time" in topic or "pc_active" in topic for topic in topics)
    assert not any("windows_locked" in topic for topic in topics)
    assert not any("/cpu/" in topic or "/gpu_" in topic for topic in topics)
    assert not any("microphone" in topic or "audio_output" in topic for topic in topics)
    assert not any("master_volume" in topic or "master_mute" in topic for topic in topics)


def test_cleanup_topics_cover_disabled_features_and_removed_default_app() -> None:
    config = AppConfig(device_id="gaming_pc_123", mqtt=MqttConfig(host="broker"), apps=[])
    stale = all_possible_discovery_topics(config) - discovery_topics(config)

    assert "homeassistant/sensor/gaming_pc_123/cpu/config" in stale
    assert "homeassistant/binary_sensor/gaming_pc_123/microphone_active/config" in stale
    assert "homeassistant/number/gaming_pc_123/youtube_music_volume/config" in stale
