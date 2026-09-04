from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict
from functools import partial

from ..audio import AudioOutputDevice, AudioSessionSnapshot
from ..communication.protocol import TopicProtocol
from ..config import AudioAppConfig
from ..discovery import (
    active_app_topic,
    active_volume_topics,
    active_window_topic,
    app_mute_topics,
    app_running_topic,
    app_session_count_topic,
    app_volume_topics,
    audio_output_topics,
    disk_volume_metric,
    fullscreen_topic,
    idle_topic,
    master_balance_topics,
    master_mute_topics,
    master_volume_topics,
    microphone_active_topic,
    microphone_mute_topics,
    microphone_volume_topics,
    overlay_monitor_topics,
    pc_active_topic,
    session_locked_topic,
    system_metric_topic,
    total_audio_session_count_topic,
    tracked_device_topic,
)
from ..integration_protocol import integration_announcement_payload
from ..media_protocol import (
    media_announcement_topic,
    media_artwork_payload,
    media_state_payload,
    media_thumbnail_topic,
    media_topics,
)
from ..runtime.polling import PollScheduler
from ..system_monitor import PcContext


class TelemetryService:
    """Owns sensor scheduling and protocol publication, never network lifecycle."""

    def __init__(self, config, audio, system, media, publisher, events, monitors):
        self.config, self.audio, self.system, self.media = config, audio, system, media
        self.publisher, self.events = publisher, events
        self.log = logging.getLogger("bridge.sensors")
        self.overlay_monitors = monitors or ["1: Monitor"]
        _, self._overlay_monitor_state = overlay_monitor_topics(config)
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._thread = None
        self._inventory_requested = threading.Event()
        self._inventory_requested.set()
        self._unsubscribe = None
        self._last_volumes: dict[str, float] = {}
        self._last_mutes: dict[str, bool] = {}
        self._last_running: dict[str, bool] = {}
        self._last_active: tuple[str, float] | None = None
        self._last_master_volume: float | None = None
        self._last_master_mute: bool | None = None
        self._last_master_balance: float | None = None
        self._last_session_counts: dict[str, int] = {}
        self._last_total_session_count: int | None = None
        self._last_device_states: dict[str, bool] = {}
        self._last_microphone: tuple[float, bool, bool] | None = None
        self._microphone_active_until = 0.0
        self._last_context: PcContext | None = None
        self._last_audio_output = ""
        self._last_media_payload = ""
        self._last_media_artwork_hash: str | None = None
        self._audio_outputs: list[AudioOutputDevice] = []


    def start(self):
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Sensors are still running")
        self._stop_event.clear()
        self._unsubscribe = self.events.subscribe("*", self._connection_changed)
        self._thread = threading.Thread(target=self._monitor_loop, name="sensor-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._thread:
            self._thread.join(timeout=3)
        return self._thread is None or not self._thread.is_alive()

    def pause(self, enabled):
        self._paused.set() if enabled else self._paused.clear()
        self.events.emit("sensors.paused", enabled)

    def _connection_changed(self, event):
        if event.topic == "inventory.requested" or (
            event.topic == "connection.changed" and event.data.transport == "mqtt" and event.data.state == "connected"
        ):
            self._inventory_requested.set()

    def _publish_number_state(self, topic: str, value: float) -> None:
        if self.publisher.connected:
            self.publisher.publish(topic, str(round(value * 100)), qos=1, retain=True)

    def _publish_switch_state(self, topic: str, enabled: bool) -> None:
        if self.publisher.connected:
            self.publisher.publish(topic, "ON" if enabled else "OFF", qos=1, retain=True)

    def _publish_text_state(self, topic: str, value: str | float) -> None:
        if self.publisher.connected:
            self.publisher.publish(topic, str(value), qos=1, retain=True)

    def _publish_volume_state(self, app: AudioAppConfig | None, volume: float) -> None:
        if app is None:
            _, state = active_volume_topics(self.config)
        else:
            _, state = app_volume_topics(self.config, app)
        self._publish_number_state(state, volume)

    def _publish_master_volume(self, volume: float) -> None:
        _, state = master_volume_topics(self.config)
        self._publish_number_state(state, volume)

    def publish_discovery(self) -> int:
        """Publish one retained inventory owned by the HA Windows Bridge integration."""
        client = self.publisher
        if not client.connected:
            return 0

        outputs = [device.name for device in self._audio_outputs]
        hardware_metrics: set[str] = set()
        if self.config.publish_cpu_stats or self.config.publish_gpu_stats:
            metrics = self.system.system_metrics(
                include_cpu=self.config.publish_cpu_stats,
                include_gpu=self.config.publish_gpu_stats,
                include_ram=False,
            )
            candidates: dict[str, float | str | None] = {}
            if self.config.publish_cpu_stats:
                candidates.update(
                    {
                        "cpu_frequency": metrics.cpu_frequency_mhz,
                        "cpu_temperature": metrics.cpu_temperature,
                        "cpu_power": metrics.cpu_power_watts,
                        "cpu_vendor": metrics.cpu_vendor,
                    }
                )
            if self.config.publish_gpu_stats:
                candidates.update(
                    {
                        "gpu_usage": metrics.gpu_percent,
                        "gpu_temperature": metrics.gpu_temperature,
                        "gpu_power": metrics.gpu_power_watts,
                        "gpu_memory": metrics.gpu_memory_used_mb,
                        "gpu_clock": metrics.gpu_clock_mhz,
                        "gpu_fan": metrics.gpu_fan_rpm,
                        "gpu_vendor": metrics.gpu_vendor,
                    }
                )
            hardware_metrics.update(
                name for name, value in candidates.items() if value not in (None, "")
            )
        if self.config.publish_windows_health:
            health = self.system.windows_health()
            hardware_metrics.update(("pending_restart", "windows_update", "uptime"))
            if health.battery_percent is not None:
                hardware_metrics.update(("battery", "ac_power"))
            if health.power_plan:
                hardware_metrics.add("power_plan")
        if self.config.publish_disk_stats:
            volumes = self.system.list_disk_volumes()
            selected = {
                os.path.normcase(os.path.normpath(mount)) for mount in self.config.disk_mounts
            }
            for volume in volumes:
                if os.path.normcase(os.path.normpath(volume.mountpoint)) not in selected:
                    continue
                hardware_metrics.update(
                    (
                        disk_volume_metric(volume.mountpoint, "used"),
                        disk_volume_metric(volume.mountpoint, "free"),
                    )
                )
            disks = self.system.disk_metrics(self.config.disk_mounts)
            hardware_metrics.update(("disk_read", "disk_write"))
            if disks.health:
                hardware_metrics.add("disk_health")
            if disks.temperature is not None:
                hardware_metrics.add("disk_temperature")
        payload = integration_announcement_payload(
            self.config,
            outputs,
            hardware_metrics,
            self.overlay_monitors,
        )
        protocol = TopicProtocol(self.config)
        payload["schema"] = 3
        payload["protocol"] = {
            "version": 2, "command_topic": protocol.command_topic, "result_topic": protocol.result_topic,
            "routes": {topic: asdict(route) for topic, route in protocol.routes.items()},
        }
        client.publish(
            media_announcement_topic(self.config),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            qos=1,
            retain=True,
        )
        if not self.config.media_player_enabled:
            _, state_topic = media_topics(self.config)
            client.publish(state_topic, "", qos=1, retain=True)
            client.publish(media_thumbnail_topic(self.config), "", qos=1, retain=True)
        if self.config.overlay_enabled and self._overlay_monitor_state:
            selected = self.overlay_monitors[
                max(0, min(len(self.overlay_monitors) - 1, self.config.overlay_monitor))
            ]
            self._publish_text_state(self._overlay_monitor_state, selected)
        count = len(payload["entities"]) + int(self.config.media_player_enabled)
        self.events.emit("inventory.published", {"entities": count, "sensors": sum(item.get("platform") in {"sensor", "binary_sensor"} for item in payload["entities"])})
        return count

    def _monitor_loop(self) -> None:
        enabled = [app for app in self.config.apps if app.enabled]
        names = [app.process_name for app in enabled]
        scheduler = PollScheduler(self.log)
        while not self._stop_event.wait(self.config.poll_interval):
            if not self.publisher.connected or self._paused.is_set():
                continue
            if self._inventory_requested.is_set() and scheduler.run("inventory", 5, self.publish_discovery, 0):
                self._inventory_requested.clear()
            if self.config.control_master_volume:
                scheduler.run("master_audio", 0, self._monitor_master)
            if names or self.config.control_active_app:
                snapshot = scheduler.run("audio_sessions", 0, lambda: self.audio.session_snapshot(names), {})
                running = scheduler.run("processes", 2, lambda: self.system.running_process_names(names), set())
                scheduler.run("applications", 0, partial(self._monitor_apps, enabled, snapshot, running))
                if self.config.control_active_app:
                    scheduler.run("active_application", 0, partial(self._monitor_active, snapshot))
            if self.config.control_microphone:
                scheduler.run("microphone", 0, self._monitor_microphone)
            if self.config.audio_enhancements_enabled and self.config.publish_audio_sessions:
                scheduler.run("session_count", 2, self._monitor_total_audio_sessions)
            if self.config.publish_activity or self.config.publish_idle or self.config.publish_session_lock:
                scheduler.run("desktop_context", 1, self._monitor_context)
            if self.config.publish_ram_stats or self.config.publish_cpu_stats or self.config.publish_gpu_stats:
                scheduler.run("system_metrics", 5, self._monitor_system)
            if self.config.publish_windows_health:
                scheduler.run("windows_health", 30, self._monitor_windows_health)
            if self.config.publish_disk_stats:
                scheduler.run("disks", 5, self._monitor_disks)
            if self.config.publish_devices:
                scheduler.run("devices", 10, self._monitor_devices)
            if self.config.control_audio_output:
                scheduler.run("audio_output", 3, self._monitor_audio_output)
            if self.config.media_player_enabled:
                scheduler.run("media", 1, self._monitor_media)

    def _monitor_master(self) -> None:
        snapshot = self.audio.get_master_snapshot()
        if snapshot is None:
            return
        if self._last_master_volume is None:
            self._last_master_volume = snapshot.volume
            if self.config.publish_initial_state:
                self._publish_master_volume(snapshot.volume)
        elif abs(self._last_master_volume - snapshot.volume) >= 0.005:
            self._last_master_volume = snapshot.volume
            self._publish_master_volume(snapshot.volume)
        if self._last_master_mute is None:
            self._last_master_mute = snapshot.muted
            if self.config.publish_initial_state:
                _, state = master_mute_topics(self.config)
                self._publish_switch_state(state, snapshot.muted)
        elif self._last_master_mute != snapshot.muted:
            self._last_master_mute = snapshot.muted
            _, state = master_mute_topics(self.config)
            self._publish_switch_state(state, snapshot.muted)
        if self.config.audio_enhancements_enabled and self.config.control_channel_balance:
            balance = self.audio.get_master_balance()
            if balance is not None and (
                self._last_master_balance is None
                or abs(self._last_master_balance - balance) >= 0.01
            ):
                self._last_master_balance = balance
                _, state = master_balance_topics(self.config)
                self._publish_text_state(state, round(balance * 100))

    def _monitor_apps(
        self,
        enabled: list[AudioAppConfig],
        snapshot: dict[str, AudioSessionSnapshot],
        running_processes: set[str] | None = None,
    ) -> None:
        running_processes = running_processes or set()
        self.events.emit("audio.snapshot", snapshot)
        for app in enabled:
            state = snapshot.get(app.process_name.lower())
            running = state is not None or app.process_name.casefold() in running_processes
            if self._last_running.get(app.slug) is not running:
                self._publish_running(app, running)
                self._last_running[app.slug] = running
            if state is None:
                if (
                    self.config.audio_enhancements_enabled
                    and self.config.publish_audio_sessions
                    and self._last_session_counts.get(app.slug) != 0
                ):
                    self._publish_text_state(app_session_count_topic(self.config, app), 0)
                    self._last_session_counts[app.slug] = 0
                continue
            if (
                self.config.audio_enhancements_enabled
                and self.config.publish_audio_sessions
                and self._last_session_counts.get(app.slug) != state.session_count
            ):
                self._publish_text_state(
                    app_session_count_topic(self.config, app), state.session_count
                )
                self._last_session_counts[app.slug] = state.session_count
            if app.slug not in self._last_volumes:
                self._last_volumes[app.slug] = state.volume
                if self.config.publish_initial_state:
                    self._publish_volume_state(app, state.volume)
            elif abs(self._last_volumes[app.slug] - state.volume) >= 0.005:
                self._last_volumes[app.slug] = state.volume
                self._publish_volume_state(app, state.volume)
            if app.slug not in self._last_mutes:
                self._last_mutes[app.slug] = state.muted
                if self.config.publish_initial_state:
                    _, mute_state = app_mute_topics(self.config, app)
                    self._publish_switch_state(mute_state, state.muted)
            elif self._last_mutes[app.slug] != state.muted:
                self._last_mutes[app.slug] = state.muted
                _, mute_state = app_mute_topics(self.config, app)
                self._publish_switch_state(mute_state, state.muted)

    def _monitor_active(self, snapshot: dict[str, AudioSessionSnapshot]) -> None:
        process_name = self.audio.get_active_process_name()
        if not process_name:
            return
        session = snapshot.get(process_name.lower())
        volume = session.volume if session else self.audio.get_volume(process_name)
        if volume is None:
            return
        current = (process_name.lower(), volume)
        if self._last_active is None:
            self._last_active = current
            if not self.config.publish_activity:
                self._publish_active_app(process_name)
            if self.config.publish_initial_state:
                self._publish_volume_state(None, volume)
            return
        previous_process, previous_volume = self._last_active
        if previous_process != current[0] and not self.config.publish_activity:
            self._publish_active_app(process_name)
        if previous_process != current[0] or abs(previous_volume - volume) >= 0.005:
            self._last_active = current
            self._publish_volume_state(None, volume)

    def _monitor_total_audio_sessions(self) -> None:
        counter = getattr(self.audio, "count_audio_sessions", None)
        if not callable(counter):
            return
        count = counter()
        if count == self._last_total_session_count:
            return
        self._last_total_session_count = count
        self._publish_text_state(total_audio_session_count_topic(self.config), count)

    def _monitor_microphone(self) -> None:
        snapshot = self.audio.get_microphone_snapshot()
        if snapshot is None:
            return
        now = time.monotonic()
        if snapshot.active and not snapshot.muted:
            self._microphone_active_until = now + 1.25
        active = not snapshot.muted and now < self._microphone_active_until
        current = (snapshot.volume, snapshot.muted, active)
        if self._last_microphone is None:
            self._last_microphone = current
            if self.config.publish_initial_state:
                _, volume_state = microphone_volume_topics(self.config)
                _, mute_state = microphone_mute_topics(self.config)
                self._publish_number_state(volume_state, snapshot.volume)
                self._publish_switch_state(mute_state, snapshot.muted)
            self._publish_switch_state(microphone_active_topic(self.config), active)
            return
        previous_volume, previous_mute, previous_active = self._last_microphone
        if abs(previous_volume - snapshot.volume) >= 0.005:
            _, state = microphone_volume_topics(self.config)
            self._publish_number_state(state, snapshot.volume)
        if previous_mute != snapshot.muted:
            _, state = microphone_mute_topics(self.config)
            self._publish_switch_state(state, snapshot.muted)
        if previous_active != active:
            self._publish_switch_state(microphone_active_topic(self.config), active)
        self._last_microphone = current

    def _monitor_context(self) -> None:
        context = self.system.context_snapshot()
        previous = self._last_context
        if self.config.publish_activity and (
            previous is None or previous.process_name != context.process_name
        ):
            self._publish_text_state(active_app_topic(self.config), context.process_name or "Brak")
        if self.config.publish_activity and (
            previous is None or previous.window_title != context.window_title
        ):
            self._publish_text_state(
                active_window_topic(self.config), context.window_title or "Brak"
            )
        if self.config.publish_activity and (
            previous is None or previous.fullscreen != context.fullscreen
        ):
            self._publish_switch_state(fullscreen_topic(self.config), context.fullscreen)
        if self.config.publish_idle and (
            previous is None or previous.idle_seconds != context.idle_seconds
        ):
            self._publish_text_state(idle_topic(self.config), context.idle_seconds)
            was_active = previous is not None and previous.idle_seconds < self.config.idle_threshold
            is_active = context.idle_seconds < self.config.idle_threshold
            if previous is None or was_active != is_active:
                self._publish_switch_state(pc_active_topic(self.config), is_active)
        if self.config.publish_session_lock and (
            previous is None or previous.locked != context.locked
        ):
            self._publish_switch_state(session_locked_topic(self.config), context.locked)
        self._last_context = context

    def _monitor_system(self) -> None:
        metrics = self.system.system_metrics(
            include_cpu=self.config.publish_cpu_stats,
            include_gpu=self.config.publish_gpu_stats,
            include_ram=self.config.publish_ram_stats,
        )
        values: dict[str, float | int | str | None] = {}
        if self.config.publish_cpu_stats:
            values["cpu"] = round(metrics.cpu_percent, 1)
        if self.config.publish_ram_stats:
            values.update(
                {
                    "ram": round(metrics.ram_percent, 1),
                    "ram_used": (
                        round(metrics.ram_used_gb, 2)
                        if metrics.ram_used_gb is not None
                        else None
                    ),
                    "ram_available": (
                        round(metrics.ram_available_gb, 2)
                        if metrics.ram_available_gb is not None
                        else None
                    ),
                    "ram_total": (
                        round(metrics.ram_total_gb, 2)
                        if metrics.ram_total_gb is not None
                        else None
                    ),
                }
            )
        if self.config.publish_gpu_stats:
            values.update(
                {
                    "gpu_usage": metrics.gpu_percent,
                    "gpu_temperature": metrics.gpu_temperature,
                    "gpu_power": metrics.gpu_power_watts,
                    "gpu_memory": metrics.gpu_memory_used_mb,
                    "gpu_clock": metrics.gpu_clock_mhz,
                    "gpu_fan": metrics.gpu_fan_rpm,
                    "gpu_vendor": metrics.gpu_vendor,
                }
            )
        if self.config.publish_cpu_stats:
            values.update(
                {
                    "cpu_frequency": metrics.cpu_frequency_mhz,
                    "cpu_temperature": metrics.cpu_temperature,
                    "cpu_power": metrics.cpu_power_watts,
                    "cpu_vendor": metrics.cpu_vendor,
                }
            )
        for metric, value in values.items():
            if value not in (None, ""):
                self._publish_text_state(system_metric_topic(self.config, metric), value)

    def _monitor_windows_health(self) -> None:
        health = self.system.windows_health()
        self._publish_text_state(
            system_metric_topic(self.config, "uptime"), health.uptime_seconds
        )
        if health.battery_percent is not None:
            self._publish_text_state(
                system_metric_topic(self.config, "battery"), round(health.battery_percent, 1)
            )
        if health.on_ac_power is not None:
            self._publish_switch_state(
                system_metric_topic(self.config, "ac_power"), health.on_ac_power
            )
        self._publish_switch_state(
            system_metric_topic(self.config, "pending_restart"), health.pending_restart
        )
        if health.power_plan:
            self._publish_text_state(
                system_metric_topic(self.config, "power_plan"), health.power_plan
            )
        self._publish_text_state(
            system_metric_topic(self.config, "windows_update"),
            health.windows_update_status,
        )

    def _monitor_disks(self) -> None:
        volumes = self.system.list_disk_volumes()
        selected = {os.path.normcase(os.path.normpath(mount)) for mount in self.config.disk_mounts}
        for volume in volumes:
            if os.path.normcase(os.path.normpath(volume.mountpoint)) not in selected:
                continue
            self._publish_text_state(
                system_metric_topic(self.config, disk_volume_metric(volume.mountpoint, "used")),
                round(volume.used_percent, 1),
            )
            self._publish_text_state(
                system_metric_topic(self.config, disk_volume_metric(volume.mountpoint, "free")),
                round(volume.free_gb, 1),
            )
        metrics = self.system.disk_metrics(self.config.disk_mounts)
        values = {
            "disk_read": round(metrics.read_mb_s, 2),
            "disk_write": round(metrics.write_mb_s, 2),
            "disk_health": metrics.health,
            "disk_temperature": metrics.temperature,
        }
        for metric, value in values.items():
            if value not in (None, ""):
                self._publish_text_state(system_metric_topic(self.config, metric), value)

    def _monitor_devices(self) -> None:
        present = self.system.present_device_ids()
        for device in self.config.tracked_devices:
            if not device.enabled:
                continue
            connected = device.instance_id.casefold() in present
            if self._last_device_states.get(device.slug) != connected:
                self._last_device_states[device.slug] = connected
                self._publish_switch_state(
                    tracked_device_topic(self.config, device.slug), connected
                )

    def _monitor_audio_output(self) -> None:
        outputs = self.audio.list_output_devices()
        old_names = [device.name for device in self._audio_outputs]
        new_names = [device.name for device in outputs]
        self._audio_outputs = outputs
        if old_names != new_names:
            self._publish_discovery()
        current = next((device.name for device in outputs if device.is_default), "")
        if current and current != self._last_audio_output:
            self._last_audio_output = current
            _, state = audio_output_topics(self.config)
            self._publish_text_state(state, current)

    def _monitor_media(self) -> None:
        snapshot = self.media.snapshot()
        artwork_payload = media_artwork_payload(snapshot)
        artwork_hash = snapshot.artwork.digest or ""
        if artwork_hash != self._last_media_artwork_hash:
            self._last_media_artwork_hash = artwork_hash
            if self.publisher.connected:
                serialized_artwork = (
                    json.dumps(artwork_payload, separators=(",", ":"))
                    if artwork_payload is not None
                    else ""
                )
                self.publisher.publish(
                    media_thumbnail_topic(self.config),
                    serialized_artwork,
                    qos=1,
                    retain=True,
                )
        payload = json.dumps(
            media_state_payload(snapshot, self.audio.get_master_snapshot()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if payload == self._last_media_payload:
            return
        self._last_media_payload = payload
        if self.publisher.connected:
            _, state_topic = media_topics(self.config)
            self.publisher.publish(state_topic, payload, qos=1, retain=True)

    def _publish_running(self, app: AudioAppConfig, running: bool) -> None:
        self._publish_switch_state(app_running_topic(self.config, app), running)

    def _publish_active_app(self, process_name: str) -> None:
        self._publish_text_state(active_app_topic(self.config), process_name)
