from __future__ import annotations

from ha_windows_bridge.config import (
    AppConfig,
    AudioAppConfig,
    MqttConfig,
    TrackedDeviceConfig,
)
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
        publish_ram_stats=True,
        publish_cpu_stats=True,
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
    assert "homeassistant/sensor/gaming_pc_123/ram/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/ram_available/config" in topics
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
    config.publish_ram_stats = False
    config.publish_cpu_stats = False
    config.publish_gpu_stats = False
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
    assert "homeassistant/select/gaming_pc_123/audio_profile/config" in stale


def test_cleanup_topics_include_legacy_aggregate_disk_entities() -> None:
    config = AppConfig(device_id="gaming_pc_123", mqtt=MqttConfig(host="broker"))

    stale = all_possible_discovery_topics(config) - discovery_topics(config)

    assert "homeassistant/sensor/gaming_pc_123/disk_used/config" in stale
    assert "homeassistant/sensor/gaming_pc_123/disk_free/config" in stale


def test_power_actions_and_windows_notifications_are_discovered() -> None:
    config = sample_config()
    config.allow_power_actions = True
    config.enable_windows_notifications = True

    messages = discovery_messages(config)
    topics = {message.topic for message in messages}

    assert "homeassistant/button/gaming_pc_123/power_lock/config" in topics
    assert "homeassistant/button/gaming_pc_123/power_shutdown/config" in topics
    assert "homeassistant/button/gaming_pc_123/power_cancel/config" in topics
    assert "homeassistant/notify/gaming_pc_123/windows_notification/config" in topics
    notification = next(message.payload for message in messages if "/notify/" in message.topic)
    assert notification["command_topic"] == "hawn/gaming-pc/notification/show/set"
    assert notification["unique_id"] == "gaming_pc_123_windows_notification"


def test_modular_system_audio_device_and_overlay_entities_are_capability_filtered() -> None:
    config = sample_config()
    config.publish_windows_health = True
    config.publish_disk_stats = True
    config.disk_mounts = ["C:\\", "D:\\"]
    config.publish_cpu_stats = True
    config.publish_gpu_stats = True
    config.audio_enhancements_enabled = True
    config.control_channel_balance = True
    config.publish_audio_sessions = True
    config.publish_devices = True
    config.tracked_devices = [TrackedDeviceConfig("USB\\PAD", "Controller", "HIDClass")]
    config.overlay_enabled = True

    capabilities = {
        "cpu_frequency",
        "cpu_vendor",
        "gpu_usage",
        "gpu_vendor",
        "pending_restart",
        "power_plan",
        "windows_update",
        "uptime",
        "disk_c_used",
        "disk_c_free",
        "disk_d_used",
        "disk_d_free",
        "disk_read",
        "disk_write",
        "disk_health",
    }
    topics = {message.topic for message in discovery_messages(config, ["Speakers"], capabilities)}

    assert "homeassistant/number/gaming_pc_123/master_balance/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/spotify_sessions/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/audio_sessions/config" in topics
    assert "homeassistant/select/gaming_pc_123/audio_profile/config" not in topics
    assert "homeassistant/sensor/gaming_pc_123/disk_health/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/disk_c_used/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/disk_d_free/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/pending_restart/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/windows_update/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/uptime/config" in topics
    assert "homeassistant/binary_sensor/gaming_pc_123/device_controller/config" in topics
    assert "homeassistant/notify/gaming_pc_123/windows_overlay/config" in topics
    assert "homeassistant/select/gaming_pc_123/overlay_monitor/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/gpu_usage/config" in topics
    assert "homeassistant/sensor/gaming_pc_123/gpu_temperature/config" not in topics
    assert "homeassistant/sensor/gaming_pc_123/battery/config" not in topics
