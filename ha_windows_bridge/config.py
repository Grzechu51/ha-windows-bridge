from __future__ import annotations

import base64
import json
import math
import os
import platform
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

APP_NAME = "HA Windows Bridge"
CONFIG_SCHEMA_VERSION = 9
_SLUG_RE = re.compile(r"[^a-z0-9]+")
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_SECRET_BYTES = 64 * 1024
MAX_MQTT_HISTORY_BYTES = 4 * 1024 * 1024
MAX_REMEMBERED_TOPICS = 20_000


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().lower().replace(".exe", "")
    value = value.translate(str.maketrans({"ł": "l", "đ": "d", "ø": "o"}))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = _SLUG_RE.sub("_", value).strip("_")
    return value or fallback


def default_device_id() -> str:
    hostname = slugify(platform.node(), "windows_pc")
    hardware = f"{uuid.getnode():012x}"[-6:]
    return f"{hostname}_{hardware}"


@dataclass(slots=True)
class AudioAppConfig:
    process_name: str
    display_name: str
    slug: str = ""
    enabled: bool = True
    executable_path: str = ""
    allow_remote_start: bool = False
    allow_remote_close: bool = False

    def __post_init__(self) -> None:
        self.process_name = self.process_name.strip()
        self.display_name = self.display_name.strip() or self.process_name.removesuffix(".exe")
        self.slug = slugify(self.slug or self.display_name or self.process_name)
        self.executable_path = self.executable_path.strip()

    @classmethod
    def from_dict(cls, data: dict) -> AudioAppConfig:
        return cls(
            process_name=str(data.get("process_name", "")),
            display_name=str(data.get("display_name", "")),
            slug=str(data.get("slug", "")),
            enabled=bool(data.get("enabled", True)),
            executable_path=str(data.get("executable_path", "")),
            allow_remote_start=bool(data.get("allow_remote_start", False)),
            allow_remote_close=bool(data.get("allow_remote_close", False)),
        )


@dataclass(slots=True)
class TrackedDeviceConfig:
    """A Windows Plug and Play device selected for Home Assistant."""

    instance_id: str
    display_name: str
    category: str = "Device"
    slug: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        self.instance_id = self.instance_id.strip()
        self.display_name = self.display_name.strip() or self.instance_id
        self.category = self.category.strip() or "Device"
        self.slug = slugify(self.slug or self.display_name or self.instance_id)

    @classmethod
    def from_dict(cls, data: dict) -> TrackedDeviceConfig:
        return cls(
            instance_id=str(data.get("instance_id", "")),
            display_name=str(data.get("display_name", "")),
            category=str(data.get("category", "Device")),
            slug=str(data.get("slug", "")),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(slots=True)
class AudioProfileConfig:
    name: str
    slug: str = ""
    master_volume: int = 50
    output_device: str = ""
    app_volumes: dict[str, int] = field(default_factory=dict)
    trigger_process: str = ""
    trigger_processes: list[str] = field(default_factory=list)
    enabled: bool = True

    def __post_init__(self) -> None:
        self.name = self.name.strip() or "Audio profile"
        self.slug = slugify(self.slug or self.name)
        self.master_volume = max(0, min(100, int(self.master_volume)))
        self.output_device = self.output_device.strip()
        self.trigger_process = self.trigger_process.strip()
        normalized_triggers: list[str] = []
        seen_triggers: set[str] = set()
        for process in ([self.trigger_process] if self.trigger_process else []) + list(
            self.trigger_processes
        ):
            process = process.strip()
            key = process.casefold()
            if not process or key in seen_triggers:
                continue
            seen_triggers.add(key)
            normalized_triggers.append(process)
        self.trigger_processes = normalized_triggers
        self.trigger_process = self.trigger_processes[0] if self.trigger_processes else ""
        self.app_volumes = {
            str(process).strip(): max(0, min(100, int(volume)))
            for process, volume in self.app_volumes.items()
            if str(process).strip()
        }

    @classmethod
    def from_dict(cls, data: dict) -> AudioProfileConfig:
        volumes = data.get("app_volumes", {})
        return cls(
            name=str(data.get("name", "")),
            slug=str(data.get("slug", "")),
            master_volume=int(data.get("master_volume", 50)),
            output_device=str(data.get("output_device", "")),
            app_volumes=dict(volumes) if isinstance(volumes, dict) else {},
            trigger_process=str(data.get("trigger_process", "")),
            trigger_processes=[
                str(process)
                for process in data.get("trigger_processes", [])
                if str(process).strip()
            ],
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(slots=True)
class MqttConfig:
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = field(default="", repr=False)
    keepalive: int = 10
    tls: bool = False
    base_topic: str = ""
    discovery_prefix: str = "homeassistant"

    @classmethod
    def from_dict(cls, data: dict) -> MqttConfig:
        return cls(
            host=str(data.get("host", "")),
            port=int(data.get("port", 1883)),
            username=str(data.get("username", "")),
            keepalive=int(data.get("keepalive", 10)),
            tls=bool(data.get("tls", False)),
            base_topic=str(data.get("base_topic", "")),
            discovery_prefix=str(data.get("discovery_prefix", "homeassistant")),
        )


def default_apps() -> list[AudioAppConfig]:
    return [
        AudioAppConfig("chrome.exe", "Chrome", "chrome", False),
        AudioAppConfig("Discord.exe", "Discord", "discord", False),
        AudioAppConfig("Spotify.exe", "Spotify", "spotify", False),
    ]


def _remove_unused_legacy_defaults(apps: list[AudioAppConfig]) -> list[AudioAppConfig]:
    """Drop defaults removed from the product without deleting user-enabled entries."""
    return [
        app
        for app in apps
        if not (
            app.process_name.casefold() == "youtube music desktop app.exe"
            and app.slug == "youtube_music"
            and not app.enabled
            and not app.allow_remote_start
            and not app.allow_remote_close
        )
    ]


@dataclass(slots=True)
class AppConfig:
    schema_version: int = CONFIG_SCHEMA_VERSION
    device_name: str = field(default_factory=lambda: platform.node() or "Windows PC")
    device_id: str = field(default_factory=default_device_id)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    apps: list[AudioAppConfig] = field(default_factory=default_apps)
    start_with_windows: bool = True
    start_minimized: bool = True
    minimize_to_tray: bool = True
    auto_connect: bool = True
    language: str = "pl"
    control_master_volume: bool = True
    theme: str = "dark"
    control_active_app: bool = False
    publish_initial_state: bool = True
    poll_interval: float = 0.5
    publish_activity: bool = False
    publish_idle: bool = False
    idle_threshold: int = 300
    publish_session_lock: bool = False
    publish_system_stats: bool = False
    publish_cpu_stats: bool = False
    publish_gpu_stats: bool = False
    control_microphone: bool = False
    control_audio_output: bool = False
    media_player_enabled: bool = False
    allow_power_actions: bool = False
    enable_windows_notifications: bool = False
    auto_check_updates: bool = True
    publish_windows_health: bool = False
    publish_disk_stats: bool = False
    disk_mounts: list[str] = field(default_factory=list)
    audio_enhancements_enabled: bool = False
    control_channel_balance: bool = False
    automatic_ducking: bool = False
    ducking_volume: int = 35
    ducking_sensitivity: int = 50
    publish_audio_sessions: bool = False
    audio_profiles_enabled: bool = False
    automatic_audio_profiles: bool = False
    audio_profiles: list[AudioProfileConfig] = field(default_factory=list)
    publish_devices: bool = False
    tracked_devices: list[TrackedDeviceConfig] = field(default_factory=list)
    overlay_enabled: bool = False
    overlay_allow_fullscreen: bool = False
    overlay_duration: int = 8
    overlay_monitor: int = 0

    def __post_init__(self) -> None:
        self.language = self.language.strip().lower()
        if self.language not in {"pl", "en"}:
            self.language = "pl"
        self.device_name = self.device_name.strip() or "Windows PC"
        self.theme = self.theme.strip().lower()
        if self.theme not in {"dark", "light"}:
            self.theme = "dark"
        self.device_id = slugify(self.device_id, default_device_id())
        self.mqtt.base_topic = self.mqtt.base_topic.strip().strip("/")
        if not self.mqtt.base_topic:
            self.mqtt.base_topic = f"ha-windows-bridge/{slugify(self.device_name, 'windows_pc')}"
        self.mqtt.discovery_prefix = (
            self.mqtt.discovery_prefix.strip().strip("/") or "homeassistant"
        )
        self.disk_mounts = list(
            dict.fromkeys(
                os.path.normpath(str(mount).strip())
                for mount in self.disk_mounts
                if str(mount).strip()
            )
        )
        self.overlay_monitor = max(0, min(15, int(self.overlay_monitor)))

    @classmethod
    def from_dict(cls, data: dict) -> AppConfig:
        stored_schema = int(data.get("schema_version", 1))
        reset_legacy_optional_features = stored_schema < 2
        raw_apps = data.get("apps")
        apps = _remove_unused_legacy_defaults(
            [AudioAppConfig.from_dict(item) for item in raw_apps]
            if isinstance(raw_apps, list)
            else default_apps()
        )
        return cls(
            schema_version=CONFIG_SCHEMA_VERSION,
            device_name=str(data.get("device_name", platform.node() or "Windows PC")),
            device_id=str(data.get("device_id", default_device_id())),
            mqtt=MqttConfig.from_dict(data.get("mqtt", {})),
            apps=apps,
            start_with_windows=bool(data.get("start_with_windows", True)),
            start_minimized=bool(data.get("start_minimized", True)),
            minimize_to_tray=bool(data.get("minimize_to_tray", True)),
            auto_connect=bool(data.get("auto_connect", True)),
            language=str(data.get("language", "pl")),
            theme=str(data.get("theme", "dark")),
            control_master_volume=bool(data.get("control_master_volume", True)),
            control_active_app=(
                False
                if reset_legacy_optional_features
                else bool(data.get("control_active_app", False))
            ),
            publish_initial_state=bool(data.get("publish_initial_state", True)),
            poll_interval=float(data.get("poll_interval", 0.5)),
            publish_activity=(
                False
                if reset_legacy_optional_features
                else bool(data.get("publish_activity", False))
            ),
            publish_idle=(
                False if reset_legacy_optional_features else bool(data.get("publish_idle", False))
            ),
            idle_threshold=int(data.get("idle_threshold", 300)),
            publish_session_lock=(
                False
                if reset_legacy_optional_features
                else bool(data.get("publish_session_lock", False))
            ),
            publish_system_stats=(
                False
                if reset_legacy_optional_features
                else bool(data.get("publish_system_stats", False))
            ),
            publish_cpu_stats=(
                False
                if reset_legacy_optional_features
                else bool(data.get("publish_cpu_stats", data.get("publish_hardware_stats", False)))
            ),
            publish_gpu_stats=(
                False
                if reset_legacy_optional_features
                else bool(
                    data.get("publish_gpu_stats", False)
                    or data.get("publish_hardware_stats", False)
                )
            ),
            control_microphone=(
                False
                if reset_legacy_optional_features
                else bool(data.get("control_microphone", False))
            ),
            control_audio_output=(
                False
                if reset_legacy_optional_features
                else bool(data.get("control_audio_output", False))
            ),
            media_player_enabled=bool(data.get("media_player_enabled", False)),
            allow_power_actions=bool(data.get("allow_power_actions", False)),
            enable_windows_notifications=bool(data.get("enable_windows_notifications", False)),
            auto_check_updates=bool(data.get("auto_check_updates", True)),
            publish_windows_health=bool(data.get("publish_windows_health", False)),
            publish_disk_stats=bool(data.get("publish_disk_stats", False)),
            disk_mounts=[str(mount) for mount in data.get("disk_mounts", []) if str(mount).strip()],
            audio_enhancements_enabled=bool(data.get("audio_enhancements_enabled", False)),
            control_channel_balance=bool(data.get("control_channel_balance", False)),
            automatic_ducking=bool(data.get("automatic_ducking", False)),
            ducking_volume=int(data.get("ducking_volume", 35)),
            ducking_sensitivity=int(data.get("ducking_sensitivity", 50)),
            publish_audio_sessions=bool(data.get("publish_audio_sessions", False)),
            audio_profiles_enabled=bool(data.get("audio_profiles_enabled", False)),
            automatic_audio_profiles=bool(data.get("automatic_audio_profiles", False)),
            audio_profiles=[
                AudioProfileConfig.from_dict(item)
                for item in data.get("audio_profiles", [])
                if isinstance(item, dict)
            ],
            publish_devices=bool(data.get("publish_devices", False)),
            tracked_devices=[
                TrackedDeviceConfig.from_dict(item)
                for item in data.get("tracked_devices", [])
                if isinstance(item, dict)
            ],
            overlay_enabled=bool(data.get("overlay_enabled", False)),
            overlay_allow_fullscreen=bool(data.get("overlay_allow_fullscreen", False)),
            overlay_duration=int(data.get("overlay_duration", 8)),
            overlay_monitor=int(data.get("overlay_monitor", 0)),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["mqtt"].pop("password", None)
        return data

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.device_name:
            errors.append("Podaj nazwę urządzenia.")
        if not self.mqtt.host:
            errors.append("Podaj adres brokera MQTT.")
        elif len(self.mqtt.host) > 255 or "\x00" in self.mqtt.host:
            errors.append("Adres brokera MQTT jest nieprawidłowy.")
        if not 1 <= self.mqtt.port <= 65535:
            errors.append("Port MQTT musi mieścić się w zakresie 1–65535.")
        if not 5 <= self.mqtt.keepalive <= 3600:
            errors.append("Keepalive musi mieścić się w zakresie 5–3600 sekund.")
        if (
            any(char in self.mqtt.base_topic for char in "\x00+#")
            or len(self.mqtt.base_topic.encode("utf-8")) > 65_535
        ):
            errors.append("Base topic zawiera niedozwolony znak lub jest zbyt długi.")
        if (
            any(char in self.mqtt.discovery_prefix for char in "\x00+#")
            or len(self.mqtt.discovery_prefix.encode("utf-8")) > 1024
        ):
            errors.append("Discovery prefix zawiera niedozwolony znak lub jest zbyt długi.")
        if not math.isfinite(self.poll_interval) or not 0.2 <= self.poll_interval <= 10:
            errors.append("Interwał odczytu musi mieścić się w zakresie 0,2–10 sekund.")
        if not 30 <= self.idle_threshold <= 7200:
            errors.append("Próg bezczynności musi mieścić się w zakresie 30–7200 sekund.")
        if not 1 <= self.ducking_volume <= 100:
            errors.append("Poziom wyciszenia rozmowy musi mieścić się w zakresie 1–100%.")
        if not 1 <= self.ducking_sensitivity <= 100:
            errors.append("Czułość mikrofonu musi mieścić się w zakresie 1–100%.")
        if not 2 <= self.overlay_duration <= 60:
            errors.append("Czas nakładki musi mieścić się w zakresie 2–60 sekund.")
        if self.publish_disk_stats and not self.disk_mounts:
            errors.append("Wybierz co najmniej jeden dysk do monitorowania.")

        enabled = [app for app in self.apps if app.enabled]
        slugs = [app.slug for app in enabled]
        if len(slugs) != len(set(slugs)):
            errors.append("Identyfikatory topiców aktywnych aplikacji muszą być unikalne.")
        for app in enabled:
            if not app.process_name:
                errors.append(f"Aplikacja „{app.display_name}” nie ma nazwy procesu.")
        devices = [device for device in self.tracked_devices if device.enabled]
        device_slugs = [device.slug for device in devices]
        if len(device_slugs) != len(set(device_slugs)):
            errors.append("Identyfikatory aktywnych urządzeń muszą być unikalne.")
        for device in devices:
            if not device.instance_id:
                errors.append(f"Urządzenie „{device.display_name}” nie ma identyfikatora Windows.")
        profiles = [profile for profile in self.audio_profiles if profile.enabled]
        profile_slugs = [profile.slug for profile in profiles]
        if len(profile_slugs) != len(set(profile_slugs)):
            errors.append("Identyfikatory profili audio muszą być unikalne.")
        return errors


class SecretBackend(Protocol):
    def load(self) -> str: ...

    def save(self, value: str) -> None: ...


class DpapiSecretBackend:
    """Stores the MQTT password encrypted for the current Windows user."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> str:
        if not self.path.exists():
            return ""
        try:
            if self.path.stat().st_size > MAX_SECRET_BYTES:
                return ""
            import win32crypt

            encrypted = base64.b64decode(self.path.read_bytes())
            _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
            return decrypted.decode("utf-8")
        except Exception:
            return ""

    def save(self, value: str) -> None:
        if not value:
            self.path.unlink(missing_ok=True)
            return
        import win32crypt

        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = win32crypt.CryptProtectData(
            value.encode("utf-8"),
            f"{APP_NAME} MQTT password",
            None,
            None,
            None,
            0,
        )
        self.path.write_bytes(base64.b64encode(encrypted))


def default_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "HAWindowsBridge"


class SettingsStore:
    def __init__(self, data_dir: Path | None = None, secrets: SecretBackend | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.config_path = self.data_dir / "config.json"
        self.mqtt_history_path = self.data_dir / "mqtt_topics.json"
        self.secrets = secrets or DpapiSecretBackend(self.data_dir / "credentials.dat")

    def load(self) -> AppConfig:
        if not self.config_path.exists():
            config = AppConfig()
        else:
            try:
                if self.config_path.stat().st_size > MAX_CONFIG_BYTES:
                    raise ValueError("plik konfiguracji jest zbyt duży")
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                config = AppConfig.from_dict(data)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Nie można odczytać konfiguracji: {exc}") from exc
        config.mqtt.password = self.secrets.load()
        return config

    def save(self, config: AppConfig) -> None:
        errors = config.validation_errors()
        if errors:
            raise ValueError("\n".join(errors))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.config_path)
        self.secrets.save(config.mqtt.password)

    def load_mqtt_topic_history(self) -> set[str]:
        if not self.mqtt_history_path.exists():
            return set()
        try:
            if self.mqtt_history_path.stat().st_size > MAX_MQTT_HISTORY_BYTES:
                return set()
            data = json.loads(self.mqtt_history_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return set()
        if not isinstance(data, list):
            return set()
        return {
            topic.strip()
            for topic in data[:MAX_REMEMBERED_TOPICS]
            if isinstance(topic, str) and topic.strip()
        }

    def remember_mqtt_topics(self, topics: Iterable[str]) -> None:
        remembered = self.load_mqtt_topic_history()
        remembered.update(
            topic.strip() for topic in topics if isinstance(topic, str) and topic.strip()
        )
        if len(remembered) > MAX_REMEMBERED_TOPICS:
            raise OSError("Historia MQTT przekroczyła bezpieczny limit topiców.")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.mqtt_history_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(sorted(remembered), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.mqtt_history_path)

    def clear_mqtt_topic_history(self) -> None:
        self.mqtt_history_path.unlink(missing_ok=True)
