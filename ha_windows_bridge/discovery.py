from __future__ import annotations

import copy
from dataclasses import dataclass

from . import __version__
from .config import AppConfig, AudioAppConfig, slugify
from .media_protocol import media_announcement_topic, media_thumbnail_topic, media_topics


@dataclass(frozen=True, slots=True)
class DiscoveryMessage:
    topic: str
    payload: dict


def status_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/status"


def app_volume_topics(config: AppConfig, app: AudioAppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/{app.slug}/volume"
    return f"{root}/set", f"{root}/state"


def app_running_topic(config: AppConfig, app: AudioAppConfig) -> str:
    return f"{config.mqtt.base_topic}/app/{app.slug}/running"


def app_mute_topics(config: AppConfig, app: AudioAppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/{app.slug}/mute"
    return f"{root}/set", f"{root}/state"


def app_start_topic(config: AppConfig, app: AudioAppConfig) -> str:
    return f"{config.mqtt.base_topic}/app/{app.slug}/start"


def app_close_topic(config: AppConfig, app: AudioAppConfig) -> str:
    return f"{config.mqtt.base_topic}/app/{app.slug}/close"


def active_volume_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/active/volume"
    return f"{root}/set", f"{root}/state"


def master_volume_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/master/volume"
    return f"{root}/set", f"{root}/state"


def master_mute_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/master/mute"
    return f"{root}/set", f"{root}/state"


def microphone_volume_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/microphone/volume"
    return f"{root}/set", f"{root}/state"


def microphone_mute_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/microphone/mute"
    return f"{root}/set", f"{root}/state"


def microphone_active_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/audio/microphone/active"


def audio_output_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/output"
    return f"{root}/set", f"{root}/state"


def active_app_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/app/active/state"


def active_window_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/activity/window/state"


def fullscreen_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/activity/fullscreen/state"


def idle_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/activity/idle/state"


def pc_active_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/activity/active/state"


def session_locked_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/session/locked/state"


def system_metric_topic(config: AppConfig, metric: str) -> str:
    return f"{config.mqtt.base_topic}/system/{metric}/state"


def disk_volume_metric(mountpoint: str, measurement: str) -> str:
    volume = slugify(mountpoint, "volume")
    return f"disk_{volume}_{measurement}"


def disk_volume_name(mountpoint: str) -> str:
    value = mountpoint.strip().rstrip("\\/") or mountpoint.strip()
    return value or "Volume"


def power_action_topic(config: AppConfig, action: str) -> str:
    return f"{config.mqtt.base_topic}/system/power/{action}/set"


def windows_notification_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/notification/show/set"


def master_balance_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/master/balance"
    return f"{root}/set", f"{root}/state"


def app_session_count_topic(config: AppConfig, app: AudioAppConfig) -> str:
    return f"{config.mqtt.base_topic}/audio/{app.slug}/sessions/state"


def total_audio_session_count_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/audio/sessions/state"


def tracked_device_topic(config: AppConfig, slug: str) -> str:
    return f"{config.mqtt.base_topic}/device/{slug}/connected/state"


def overlay_notification_topic(config: AppConfig) -> str:
    return f"{config.mqtt.base_topic}/overlay/show/set"


def overlay_monitor_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/overlay/monitor"
    return f"{root}/set", f"{root}/state"


def audio_profile_topics(config: AppConfig) -> tuple[str, str]:
    root = f"{config.mqtt.base_topic}/audio/profile"
    return f"{root}/set", f"{root}/state"


def _device(config: AppConfig) -> dict:
    return {
        "identifiers": [config.device_id],
        "name": config.device_name,
        "manufacturer": "HA Windows Bridge",
        "model": "Windows audio bridge",
        "sw_version": __version__,
    }


def _origin() -> dict:
    return {
        "name": "HA Windows Bridge",
        "sw_version": __version__,
    }


def _base_entity(config: AppConfig, unique_id: str) -> dict:
    return {
        "unique_id": unique_id,
        "availability_topic": status_topic(config),
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": _device(config),
        "origin": _origin(),
    }


def discovery_messages(
    config: AppConfig,
    audio_outputs: list[str] | None = None,
    hardware_metrics: set[str] | None = None,
    overlay_monitors: list[str] | None = None,
) -> list[DiscoveryMessage]:
    prefix = config.mqtt.discovery_prefix
    object_root = slugify(config.device_id)
    messages: list[DiscoveryMessage] = []

    connection_id = f"{object_root}_connection"
    messages.append(
        DiscoveryMessage(
            f"{prefix}/binary_sensor/{object_root}/connection/config",
            {
                "name": "Connection",
                "unique_id": connection_id,
                "state_topic": status_topic(config),
                "payload_on": "online",
                "payload_off": "offline",
                "device_class": "connectivity",
                "entity_category": "diagnostic",
                "device": _device(config),
                "origin": _origin(),
            },
        )
    )

    if config.control_master_volume:
        master_command, master_state = master_volume_topics(config)
        master_payload = _base_entity(config, f"{object_root}_master_volume")
        master_payload.update(
            {
                "name": "Master Volume",
                "command_topic": master_command,
                "state_topic": master_state,
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:volume-high",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/number/{object_root}/master_volume/config",
                master_payload,
            )
        )

        master_mute_command, master_mute_state = master_mute_topics(config)
        master_mute_payload = _base_entity(config, f"{object_root}_master_mute")
        master_mute_payload.update(
            {
                "name": "Master Mute",
                "command_topic": master_mute_command,
                "state_topic": master_mute_state,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "icon": "mdi:volume-mute",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/switch/{object_root}/master_mute/config",
                master_mute_payload,
            )
        )

        if config.audio_enhancements_enabled and config.control_channel_balance:
            balance_command, balance_state = master_balance_topics(config)
            balance_payload = _base_entity(config, f"{object_root}_master_balance")
            balance_payload.update(
                {
                    "name": "Audio Balance",
                    "command_topic": balance_command,
                    "state_topic": balance_state,
                    "min": -100,
                    "max": 100,
                    "step": 1,
                    "mode": "slider",
                    "icon": "mdi:surround-sound",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/number/{object_root}/master_balance/config",
                    balance_payload,
                )
            )

    for app in config.apps:
        if not app.enabled:
            continue
        command_topic, state = app_volume_topics(config, app)
        unique_root = f"{object_root}_{app.slug}"
        payload = _base_entity(config, f"{unique_root}_volume")
        payload.update(
            {
                "name": f"{app.display_name} Volume",
                "command_topic": command_topic,
                "state_topic": state,
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:volume-high",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/number/{object_root}/{app.slug}_volume/config",
                payload,
            )
        )

        mute_command, mute_state = app_mute_topics(config, app)
        mute_payload = _base_entity(config, f"{unique_root}_mute")
        mute_payload.update(
            {
                "name": f"{app.display_name} Mute",
                "command_topic": mute_command,
                "state_topic": mute_state,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "icon": "mdi:volume-mute",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/switch/{object_root}/{app.slug}_mute/config",
                mute_payload,
            )
        )

        running_payload = _base_entity(config, f"{unique_root}_running")
        running_payload.update(
            {
                "name": f"{app.display_name} Running",
                "state_topic": app_running_topic(config, app),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:application",
                "entity_category": "diagnostic",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/binary_sensor/{object_root}/{app.slug}_running/config",
                running_payload,
            )
        )

        if config.audio_enhancements_enabled and config.publish_audio_sessions:
            sessions_payload = _base_entity(config, f"{unique_root}_sessions")
            sessions_payload.update(
                {
                    "name": f"{app.display_name} Audio Sessions",
                    "state_topic": app_session_count_topic(config, app),
                    "icon": "mdi:waveform",
                    "state_class": "measurement",
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/{app.slug}_sessions/config",
                    sessions_payload,
                )
            )

        if app.allow_remote_start and app.executable_path:
            start_payload = _base_entity(config, f"{unique_root}_start")
            start_payload.update(
                {
                    "name": f"Start {app.display_name}",
                    "command_topic": app_start_topic(config, app),
                    "payload_press": "PRESS",
                    "icon": "mdi:play",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/button/{object_root}/{app.slug}_start/config",
                    start_payload,
                )
            )

        if app.allow_remote_close:
            close_payload = _base_entity(config, f"{unique_root}_close")
            close_payload.update(
                {
                    "name": f"Close {app.display_name}",
                    "command_topic": app_close_topic(config, app),
                    "payload_press": "PRESS",
                    "icon": "mdi:stop",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/button/{object_root}/{app.slug}_close/config",
                    close_payload,
                )
            )

    if config.audio_enhancements_enabled and config.publish_audio_sessions:
        sessions_payload = _base_entity(config, f"{object_root}_audio_sessions")
        sessions_payload.update(
            {
                "name": "Windows Audio Sessions",
                "state_topic": total_audio_session_count_topic(config),
                "icon": "mdi:waveform",
                "state_class": "measurement",
                "entity_category": "diagnostic",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/sensor/{object_root}/audio_sessions/config",
                sessions_payload,
            )
        )

    if config.control_active_app:
        command_topic, state = active_volume_topics(config)
        active_payload = _base_entity(config, f"{object_root}_active_volume")
        active_payload.update(
            {
                "name": "Active Application Volume",
                "command_topic": command_topic,
                "state_topic": state,
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:volume-source",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/number/{object_root}/active_volume/config",
                active_payload,
            )
        )

    if config.publish_activity:
        activity_entities = (
            (
                "active_app",
                "Active Application",
                active_app_topic(config),
                "mdi:application-brackets-outline",
            ),
            (
                "active_window",
                "Active Window",
                active_window_topic(config),
                "mdi:application-edit-outline",
            ),
        )
        for object_id, name, state, icon in activity_entities:
            activity_payload = _base_entity(config, f"{object_root}_{object_id}")
            activity_payload.update(
                {
                    "name": name,
                    "state_topic": state,
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/{object_id}/config",
                    activity_payload,
                )
            )

        fullscreen_payload = _base_entity(config, f"{object_root}_fullscreen")
        fullscreen_payload.update(
            {
                "name": "Fullscreen Application",
                "state_topic": fullscreen_topic(config),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:fullscreen",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/binary_sensor/{object_root}/fullscreen/config",
                fullscreen_payload,
            )
        )

    if config.publish_idle:
        idle_payload = _base_entity(config, f"{object_root}_idle_seconds")
        idle_payload.update(
            {
                "name": "Idle Time",
                "state_topic": idle_topic(config),
                "device_class": "duration",
                "unit_of_measurement": "s",
                "state_class": "measurement",
                "icon": "mdi:timer-outline",
                "entity_category": "diagnostic",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/sensor/{object_root}/idle_time/config",
                idle_payload,
            )
        )
        active_payload = _base_entity(config, f"{object_root}_pc_active")
        active_payload.update(
            {
                "name": "PC Active",
                "state_topic": pc_active_topic(config),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:account-check",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/binary_sensor/{object_root}/pc_active/config",
                active_payload,
            )
        )

    if config.publish_session_lock:
        locked_payload = _base_entity(config, f"{object_root}_session_locked")
        locked_payload.update(
            {
                "name": "Windows Locked",
                "state_topic": session_locked_topic(config),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:lock",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/binary_sensor/{object_root}/windows_locked/config",
                locked_payload,
            )
        )

    if config.publish_system_stats or config.publish_cpu_stats:
        system_entities = []
        if config.publish_system_stats or config.publish_cpu_stats:
            system_entities.append(("cpu", "CPU Usage", "%", "mdi:cpu-64-bit", "measurement"))
        if config.publish_system_stats:
            system_entities.extend(
                (
                    ("ram", "RAM Usage", "%", "mdi:memory", "measurement"),
                    (
                        "uptime",
                        "System Uptime",
                        "s",
                        "mdi:clock-outline",
                        "total_increasing",
                    ),
                )
            )
        for metric, name, unit, icon, state_class in system_entities:
            metric_payload = _base_entity(config, f"{object_root}_{metric}")
            metric_payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "unit_of_measurement": unit,
                    "state_class": state_class,
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/{metric}/config",
                    metric_payload,
                )
            )

    if config.publish_gpu_stats:
        gpu_entities = (
            ("gpu_usage", "GPU Usage", "%", "mdi:expansion-card", "measurement"),
            ("gpu_temperature", "GPU Temperature", "°C", "mdi:thermometer", "measurement"),
            ("gpu_power", "GPU Power", "W", "mdi:lightning-bolt", "measurement"),
            ("gpu_memory", "GPU Memory Used", "MiB", "mdi:memory", "measurement"),
            ("gpu_vendor", "GPU Vendor", None, "mdi:expansion-card", None),
            ("gpu_clock", "GPU Clock", "MHz", "mdi:speedometer", "measurement"),
            ("gpu_fan", "GPU Fan", "rpm", "mdi:fan", "measurement"),
        )
        for metric, name, unit, icon, state_class in gpu_entities:
            if hardware_metrics is not None and metric not in hardware_metrics:
                continue
            gpu_payload = _base_entity(config, f"{object_root}_{metric}")
            gpu_payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            if unit:
                gpu_payload["unit_of_measurement"] = unit
            if state_class:
                gpu_payload["state_class"] = state_class
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/{metric}/config",
                    gpu_payload,
                )
            )

    if config.publish_cpu_stats:
        cpu_entities = (
            ("cpu_frequency", "CPU Frequency", "MHz", "mdi:speedometer", "measurement"),
            ("cpu_temperature", "CPU Temperature", "°C", "mdi:thermometer", "measurement"),
            ("cpu_power", "CPU Power", "W", "mdi:lightning-bolt", "measurement"),
            ("cpu_vendor", "CPU Vendor", None, "mdi:cpu-64-bit", None),
        )
        for metric, name, unit, icon, state_class in cpu_entities:
            if hardware_metrics is not None and metric not in hardware_metrics:
                continue
            payload = _base_entity(config, f"{object_root}_{metric}")
            payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            if unit:
                payload["unit_of_measurement"] = unit
            if state_class:
                payload["state_class"] = state_class
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/{metric}/config",
                    payload,
                )
            )

    if config.publish_windows_health:
        health_entities = (
            ("battery", "Battery", "%", "mdi:battery", "measurement"),
            ("power_plan", "Windows Power Plan", None, "mdi:power-settings", None),
            ("windows_update", "Windows Update", None, "mdi:update", None),
        )
        for metric, name, unit, icon, state_class in health_entities:
            if hardware_metrics is not None and metric not in hardware_metrics:
                continue
            payload = _base_entity(config, f"{object_root}_{metric}")
            payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            if unit:
                payload["unit_of_measurement"] = unit
            if state_class:
                payload["state_class"] = state_class
            messages.append(
                DiscoveryMessage(f"{prefix}/sensor/{object_root}/{metric}/config", payload)
            )
        for metric, name, icon in (
            ("ac_power", "AC Power", "mdi:power-plug"),
            ("pending_restart", "Restart Required", "mdi:restart-alert"),
        ):
            if hardware_metrics is not None and metric not in hardware_metrics:
                continue
            payload = _base_entity(config, f"{object_root}_{metric}")
            payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/binary_sensor/{object_root}/{metric}/config",
                    payload,
                )
            )

    if config.publish_disk_stats:
        for mountpoint in config.disk_mounts:
            name = disk_volume_name(mountpoint)
            for measurement, label, unit, icon in (
                ("used", "Used", "%", "mdi:harddisk"),
                ("free", "Free", "GiB", "mdi:harddisk-plus"),
            ):
                metric = disk_volume_metric(mountpoint, measurement)
                if hardware_metrics is not None and metric not in hardware_metrics:
                    continue
                payload = _base_entity(config, f"{object_root}_{metric}")
                payload.update(
                    {
                        "name": f"Disk {name} {label}",
                        "state_topic": system_metric_topic(config, metric),
                        "unit_of_measurement": unit,
                        "state_class": "measurement",
                        "icon": icon,
                        "entity_category": "diagnostic",
                    }
                )
                messages.append(
                    DiscoveryMessage(f"{prefix}/sensor/{object_root}/{metric}/config", payload)
                )
        disk_entities = (
            ("disk_read", "All Disks Read", "MiB/s", "mdi:download", "measurement"),
            ("disk_write", "All Disks Write", "MiB/s", "mdi:upload", "measurement"),
            (
                "disk_temperature",
                "Physical Disks Temperature",
                "°C",
                "mdi:thermometer",
                "measurement",
            ),
        )
        for metric, name, unit, icon, state_class in disk_entities:
            if hardware_metrics is not None and metric not in hardware_metrics:
                continue
            payload = _base_entity(config, f"{object_root}_{metric}")
            payload.update(
                {
                    "name": name,
                    "state_topic": system_metric_topic(config, metric),
                    "unit_of_measurement": unit,
                    "state_class": state_class,
                    "icon": icon,
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(f"{prefix}/sensor/{object_root}/{metric}/config", payload)
            )
        if hardware_metrics is None or "disk_health" in hardware_metrics:
            payload = _base_entity(config, f"{object_root}_disk_health")
            payload.update(
                {
                    "name": "Physical Disks Health",
                    "state_topic": system_metric_topic(config, "disk_health"),
                    "icon": "mdi:harddisk-check",
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/sensor/{object_root}/disk_health/config",
                    payload,
                )
            )
    if config.control_microphone:
        mic_volume_command, mic_volume_state = microphone_volume_topics(config)
        mic_volume_payload = _base_entity(config, f"{object_root}_microphone_volume")
        mic_volume_payload.update(
            {
                "name": "Microphone Volume",
                "command_topic": mic_volume_command,
                "state_topic": mic_volume_state,
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "slider",
                "icon": "mdi:microphone",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/number/{object_root}/microphone_volume/config",
                mic_volume_payload,
            )
        )

        mic_mute_command, mic_mute_state = microphone_mute_topics(config)
        mic_mute_payload = _base_entity(config, f"{object_root}_microphone_mute")
        mic_mute_payload.update(
            {
                "name": "Microphone Mute",
                "command_topic": mic_mute_command,
                "state_topic": mic_mute_state,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "icon": "mdi:microphone-off",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/switch/{object_root}/microphone_mute/config",
                mic_mute_payload,
            )
        )

        mic_active_payload = _base_entity(config, f"{object_root}_microphone_active")
        mic_active_payload.update(
            {
                "name": "Microphone Active",
                "state_topic": microphone_active_topic(config),
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:microphone-message",
                "entity_category": "diagnostic",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/binary_sensor/{object_root}/microphone_active/config",
                mic_active_payload,
            )
        )

    if config.control_audio_output:
        output_command, output_state = audio_output_topics(config)
        output_payload = _base_entity(config, f"{object_root}_audio_output")
        output_payload.update(
            {
                "name": "Audio Output",
                "command_topic": output_command,
                "state_topic": output_state,
                "options": audio_outputs or ["Brak urządzeń"],
                "icon": "mdi:speaker-multiple",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/select/{object_root}/audio_output/config",
                output_payload,
            )
        )

    if config.allow_power_actions:
        power_buttons = (
            ("lock", "Lock Windows", "mdi:lock"),
            ("sleep", "Sleep PC", "mdi:power-sleep"),
            ("restart", "Restart PC", "mdi:restart-alert"),
            ("shutdown", "Shut Down PC", "mdi:power"),
            ("cancel", "Cancel Power Action", "mdi:cancel"),
        )
        for action, name, icon in power_buttons:
            power_payload = _base_entity(config, f"{object_root}_power_{action}")
            power_payload.update(
                {
                    "name": name,
                    "command_topic": power_action_topic(config, action),
                    "payload_press": "PRESS",
                    "icon": icon,
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/button/{object_root}/power_{action}/config",
                    power_payload,
                )
            )

    if config.enable_windows_notifications:
        notification_payload = _base_entity(
            config,
            f"{object_root}_windows_notification",
        )
        notification_payload.update(
            {
                "name": "Windows Notification",
                "command_topic": windows_notification_topic(config),
                "icon": "mdi:message-badge-outline",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/notify/{object_root}/windows_notification/config",
                notification_payload,
            )
        )

    profiles = [profile for profile in config.audio_profiles if profile.enabled]
    if config.audio_enhancements_enabled and config.audio_profiles_enabled and profiles:
        profile_command, profile_state = audio_profile_topics(config)
        profile_payload = _base_entity(config, f"{object_root}_audio_profile")
        profile_payload.update(
            {
                "name": "Audio Profile",
                "command_topic": profile_command,
                "state_topic": profile_state,
                "options": [profile.name for profile in profiles],
                "icon": "mdi:tune-variant",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/select/{object_root}/audio_profile/config",
                profile_payload,
            )
        )

    if config.publish_devices:
        for device in config.tracked_devices:
            if not device.enabled:
                continue
            payload = _base_entity(config, f"{object_root}_device_{device.slug}")
            payload.update(
                {
                    "name": device.display_name,
                    "state_topic": tracked_device_topic(config, device.slug),
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "icon": "mdi:devices",
                    "entity_category": "diagnostic",
                }
            )
            messages.append(
                DiscoveryMessage(
                    f"{prefix}/binary_sensor/{object_root}/device_{device.slug}/config",
                    payload,
                )
            )

    if config.overlay_enabled:
        payload = _base_entity(config, f"{object_root}_windows_overlay")
        payload.update(
            {
                "name": "Windows Overlay",
                "command_topic": overlay_notification_topic(config),
                "icon": "mdi:message-text-fast-outline",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/notify/{object_root}/windows_overlay/config",
                payload,
            )
        )
        monitors = overlay_monitors or ["1: Monitor"]
        monitor_command, monitor_state = overlay_monitor_topics(config)
        monitor_payload = _base_entity(config, f"{object_root}_overlay_monitor")
        monitor_payload.update(
            {
                "name": "Overlay Monitor",
                "command_topic": monitor_command,
                "state_topic": monitor_state,
                "options": monitors[:16],
                "icon": "mdi:monitor-multiple",
                "entity_category": "config",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/select/{object_root}/overlay_monitor/config",
                monitor_payload,
            )
        )
    return messages


def discovery_topics(config: AppConfig) -> set[str]:
    return {message.topic for message in discovery_messages(config)}


def all_possible_discovery_messages(config: AppConfig) -> list[DiscoveryMessage]:
    """Return every Discovery definition this device could have published.

    This is used to remove retained definitions left by older versions or by
    options that were disabled while the bridge was offline.
    """
    expanded = copy.deepcopy(config)
    expanded.control_master_volume = True
    expanded.control_active_app = True
    expanded.publish_activity = True
    expanded.publish_idle = True
    expanded.publish_session_lock = True
    expanded.publish_system_stats = True
    expanded.publish_cpu_stats = True
    expanded.publish_gpu_stats = True
    expanded.publish_windows_health = True
    expanded.publish_disk_stats = True
    expanded.audio_enhancements_enabled = True
    expanded.control_channel_balance = True
    expanded.publish_audio_sessions = True
    expanded.audio_profiles_enabled = True
    expanded.publish_devices = True
    expanded.overlay_enabled = True
    expanded.allow_power_actions = True
    expanded.enable_windows_notifications = True
    expanded.control_microphone = True
    expanded.control_audio_output = True
    if not any(app.slug == "youtube_music" for app in expanded.apps):
        expanded.apps.append(
            AudioAppConfig(
                "YouTube Music Desktop App.exe",
                "YouTube Music",
                "youtube_music",
                True,
                "__discovery_cleanup__.exe",
                True,
                True,
            )
        )
    for app in expanded.apps:
        app.enabled = True
        app.allow_remote_start = True
        app.allow_remote_close = True
        if not app.executable_path:
            app.executable_path = "__discovery_cleanup__.exe"
    messages = discovery_messages(expanded)

    # Releases through 1.2.x exposed one aggregate disk_used/disk_free pair.
    # Keep those definitions in the cleanup catalogue so retained MQTT
    # Discovery entries disappear after upgrading to per-volume entities.
    prefix = expanded.mqtt.discovery_prefix
    object_root = slugify(expanded.device_id)
    for metric, name, unit, icon in (
        ("disk_used", "Disk Used", "%", "mdi:harddisk"),
        ("disk_free", "Disk Free", "GiB", "mdi:harddisk-plus"),
    ):
        payload = _base_entity(expanded, f"{object_root}_{metric}")
        payload.update(
            {
                "name": name,
                "state_topic": system_metric_topic(expanded, metric),
                "unit_of_measurement": unit,
                "state_class": "measurement",
                "icon": icon,
                "entity_category": "diagnostic",
            }
        )
        messages.append(
            DiscoveryMessage(
                f"{prefix}/sensor/{object_root}/{metric}/config",
                payload,
            )
        )
    return messages


def all_possible_discovery_topics(config: AppConfig) -> set[str]:
    return {message.topic for message in all_possible_discovery_messages(config)}


def referenced_mqtt_topics(payload: dict) -> set[str]:
    """Extract state, command and availability topics from a Discovery payload."""
    return {
        value
        for key, value in payload.items()
        if key.endswith("_topic") and isinstance(value, str) and value.strip()
    }


def all_possible_mqtt_topics(config: AppConfig) -> set[str]:
    """Return retained integration and state topics owned by this v1 configuration."""
    messages = all_possible_discovery_messages(config)
    topics: set[str] = set()
    for message in messages:
        topics.update(referenced_mqtt_topics(message.payload))
    topics.add(status_topic(config))
    media_command, media_state = media_topics(config)
    topics.update(
        (
            media_announcement_topic(config),
            media_command,
            media_state,
            media_thumbnail_topic(config),
        )
    )
    return topics
