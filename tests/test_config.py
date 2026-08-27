from __future__ import annotations

import json
import math

import pytest

from ha_windows_bridge.config import (
    AppConfig,
    AudioAppConfig,
    DpapiSecretBackend,
    MqttConfig,
    SettingsStore,
    default_apps,
    slugify,
)


class FakeSecrets:
    def __init__(self):
        self.value = ""

    def load(self) -> str:
        return self.value

    def save(self, value: str) -> None:
        self.value = value


def test_slugify_is_mqtt_safe() -> None:
    assert slugify("YouTube Music Desktop App.exe") == "youtube_music_desktop_app"
    assert slugify("  Łódź / PC  ") == "lodz_pc"


def test_settings_round_trip_keeps_password_out_of_json(tmp_path) -> None:
    secrets = FakeSecrets()
    store = SettingsStore(tmp_path, secrets)
    config = AppConfig(
        device_name="Gaming PC",
        theme="light",
        mqtt=MqttConfig(host="192.168.1.2", password="super-secret"),
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
    )

    store.save(config)
    saved_text = store.config_path.read_text(encoding="utf-8")
    assert "super-secret" not in saved_text
    assert json.loads(saved_text)["mqtt"]["host"] == "192.168.1.2"
    assert store.load().mqtt.password == "super-secret"
    assert store.load().apps[0].executable_path == "C:/Apps/Spotify.exe"
    assert store.load().apps[0].allow_remote_start is True
    assert store.load().apps[0].allow_remote_close is True
    assert store.load().theme == "light"


def test_duplicate_enabled_slugs_are_rejected() -> None:
    config = AppConfig(
        mqtt=MqttConfig(host="broker"),
        apps=[
            AudioAppConfig("one.exe", "One", "same", True),
            AudioAppConfig("two.exe", "Two", "same", True),
        ],
    )
    with pytest.raises(ValueError, match="unikalne"):
        SettingsStore.__new__(SettingsStore).save(config)


def test_non_finite_poll_interval_and_invalid_mqtt_topics_are_rejected() -> None:
    config = AppConfig(
        mqtt=MqttConfig(host="broker", base_topic="bridge/\x00bad", discovery_prefix="bad/#"),
        poll_interval=math.nan,
    )

    errors = config.validation_errors()

    assert any("Base topic" in error for error in errors)
    assert any("Discovery prefix" in error for error in errors)
    assert any("Interwał" in error for error in errors)


def test_dpapi_secret_round_trip(tmp_path) -> None:
    backend = DpapiSecretBackend(tmp_path / "credentials.dat")
    backend.save("mqtt-test-secret")
    assert backend.load() == "mqtt-test-secret"
    assert b"mqtt-test-secret" not in (tmp_path / "credentials.dat").read_bytes()


def test_first_run_defaults_are_user_friendly() -> None:
    config = AppConfig(device_name="Gaming PC")
    assert config.mqtt.base_topic == "ha-windows-bridge/gaming_pc"
    assert config.start_with_windows is True
    assert config.start_minimized is True
    assert config.minimize_to_tray is True
    assert config.auto_connect is True
    assert config.language == "pl"
    assert config.theme == "dark"
    assert config.control_master_volume is True
    assert config.control_active_app is False
    assert config.publish_initial_state is True
    assert config.publish_activity is False
    assert config.publish_idle is False
    assert config.idle_threshold == 300
    assert config.publish_session_lock is False
    assert config.publish_system_stats is False
    assert config.publish_cpu_stats is False
    assert config.publish_gpu_stats is False
    assert config.ducking_sensitivity == 50
    assert config.control_microphone is False
    assert config.control_audio_output is False
    assert config.media_player_enabled is False
    assert {app.display_name for app in default_apps()} == {"Chrome", "Discord", "Spotify"}


def test_unused_legacy_youtube_music_default_is_removed_but_user_entry_is_preserved() -> None:
    unused = {
        "process_name": "YouTube Music Desktop App.exe",
        "display_name": "YouTube Music",
        "slug": "youtube_music",
        "enabled": False,
    }
    used = {**unused, "enabled": True}

    assert AppConfig.from_dict({"schema_version": 2, "apps": [unused]}).apps == []
    assert AppConfig.from_dict({"schema_version": 2, "apps": [used]}).apps[0].enabled is True


def test_mqtt_topic_history_is_merged_and_can_be_cleared(tmp_path) -> None:
    store = SettingsStore(data_dir=tmp_path, secrets=FakeSecrets())

    store.remember_mqtt_topics({"old/device/status", "homeassistant/sensor/old/config"})
    store.remember_mqtt_topics({"new/device/status", "old/device/status"})

    assert store.load_mqtt_topic_history() == {
        "old/device/status",
        "new/device/status",
        "homeassistant/sensor/old/config",
    }
    store.clear_mqtt_topic_history()
    assert store.load_mqtt_topic_history() == set()


def test_oversized_configuration_is_rejected_before_json_parsing(tmp_path) -> None:
    store = SettingsStore(data_dir=tmp_path, secrets=FakeSecrets())
    store.config_path.write_bytes(b" " * (2 * 1024 * 1024 + 1))

    with pytest.raises(RuntimeError, match="zbyt duży"):
        store.load()


def test_version_04_optional_features_are_disabled_during_migration() -> None:
    legacy = AppConfig.from_dict(
        {
            "schema_version": 1,
            "mqtt": {"host": "broker"},
            "control_active_app": True,
            "publish_activity": True,
            "publish_idle": True,
            "publish_session_lock": True,
            "publish_system_stats": True,
            "publish_gpu_stats": True,
            "control_microphone": True,
            "control_audio_output": True,
        }
    )

    assert legacy.schema_version == 8
    assert legacy.control_active_app is False
    assert legacy.publish_activity is False
    assert legacy.publish_idle is False
    assert legacy.publish_session_lock is False
    assert legacy.publish_system_stats is False
    assert legacy.publish_gpu_stats is False
    assert legacy.control_microphone is False
    assert legacy.control_audio_output is False


def test_version_12_hardware_telemetry_is_migrated_to_cpu_and_gpu() -> None:
    migrated = AppConfig.from_dict(
        {
            "schema_version": 7,
            "publish_hardware_stats": True,
            "publish_gpu_stats": False,
        }
    )

    assert migrated.schema_version == 8
    assert migrated.publish_cpu_stats is True
    assert migrated.publish_gpu_stats is True
