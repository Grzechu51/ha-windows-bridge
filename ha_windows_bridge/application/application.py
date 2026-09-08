"""The product runtime owns configuration and services. A window is only a client."""
from __future__ import annotations

import copy
import json
import logging
import platform
import threading
import time
import uuid
from dataclasses import asdict
from importlib.metadata import version

from .. import __version__
from ..audio import AudioProviderSnapshot
from ..communication.status import CONNECTION_NAMES, connection_text
from ..config import AppConfig
from ..core.commands import Command, CommandResult
from ..core.events import EventBus
from ..core.observability import DiagnosticBuffer
from ..core.state import ComputerStateStore, StateStore
from ..runtime.worker import SerialWorker
from ..security import redact_data
from ..system_monitor import DiskMetrics
from ..windows.resources import ProcessResources
from .commands import CommandRouter
from .lifecycle import (
    LifecycleOutcome,
    LifecycleReport,
    LifecycleResult,
    ServiceSupervisor,
)
from .master_audio import MasterAudioProvider
from .protocol_projection import ProtocolStateProjection
from .providers import (
    AdaptiveProvider,
    DeviceSnapshot,
    MediaProvider,
    StorageSnapshot,
    SystemProviderView,
)
from .state_projection import MasterAudioProjection
from .windows_commands import WindowsCommands


class _StaleLifecycleOperation(RuntimeError):
    """A queued lifecycle action was fenced by final shutdown."""


class Application:
    def __init__(self, config, store, startup, audio, system, media, power, *, events=None,
                 mqtt_factory=None, direct_factory=None, monitors=None):
        self.events = events or EventBus()
        self.states = StateStore(self.events)
        self.computer_state = ComputerStateStore(self.events)
        self.log = logging.getLogger("bridge")
        self.log.setLevel(logging.INFO)
        self.diagnostics = DiagnosticBuffer(self.events)
        self.log.addHandler(self.diagnostics)
        self.config = copy.deepcopy(config)
        self.store, self.startup = store, startup
        self.audio, self.system, self.media, self.power = audio, system, media, power
        self.monitors = monitors or ["1: Monitor"]
        self._mqtt_factory, self._direct_factory = mqtt_factory, direct_factory
        self.supervisor = ServiceSupervisor(self.states, self.log)
        self.router = CommandRouter(logger=self.log)
        self._operations = SerialWorker("application-lifecycle", self.log)
        self._queries = SerialWorker("application-queries", self.log, capacity=8)
        self._guard = threading.RLock()
        self._teardown_guard = threading.Lock()
        self._operation_context = threading.local()
        self._lifecycle_epoch = 0
        self._closed = False
        self._desired_running = False
        self._suspended = False
        self._telemetry = None
        self._master_audio = None
        self._media_provider = None
        self._system_providers = []
        self._system_view = SystemProviderView(self.system, self.computer_state)
        self._state_projection = None
        self._protocol_projection = None
        self._generation = 0
        self._services_generation = None
        self._restart_blocked = False
        self._connections = {}
        self._pending_queries = set()
        self.last_start_report = LifecycleReport("start")
        self.last_stop_report = LifecycleReport("stop")
        self.last_shutdown_report = LifecycleReport("shutdown")
        self._shutdown_finalized = False
        self.resources = ProcessResources()
        self._connection_unsubscribe = self.events.subscribe("connection.changed", self._connection_changed)
        self._protect_secrets(config)
        self._build_services()
        self.log.info("HA Windows Bridge %s — aplikacja gotowa", __version__)

    def _protect_secrets(self, config):
        self.diagnostics.protect(config.mqtt.password, config.home_assistant.token)

    def _connection_changed(self, event):
        with self._guard:
            self._connections[event.data.transport] = asdict(event.data)
        level = logging.WARNING if event.data.error else logging.INFO
        self.log.log(level, "%s: %s", CONNECTION_NAMES.get(event.data.transport, event.data.transport), connection_text(event.data))

    def connection_snapshot(self):
        with self._guard:
            return copy.deepcopy(tuple(self._connections.values()))

    def check_updates(self):
        from ..updater import GitHubUpdateChecker
        if self._closed:
            return False
        return self._queries.submit(lambda: self.events.emit("updates.checked", GitHubUpdateChecker().check(__version__)))

    def _operation_is_current_locked(self) -> bool:
        operation_epoch = getattr(
            self._operation_context,
            "epoch",
            self._lifecycle_epoch,
        )
        return not self._closed and operation_epoch == self._lifecycle_epoch

    def _ensure_operation_current_locked(self) -> None:
        if not self._operation_is_current_locked():
            raise _StaleLifecycleOperation("Lifecycle operation was fenced by shutdown")

    def _ensure_operation_current(self) -> None:
        with self._guard:
            self._ensure_operation_current_locked()

    def _build_services(self):
        with self._guard:
            self._ensure_operation_current_locked()
            self._build_services_locked()

    def _build_services_locked(self):
        from ..communication.gateway import MqttGateway
        from .telemetry import TelemetryService
        if self.supervisor.active:
            raise RuntimeError("Cannot replace services with active owners")
        self._generation += 1
        self._services_generation = self._generation
        self.computer_state.begin_generation(self._generation)
        self.states.clear()
        with self._guard:
            self._connections.clear()
        self.supervisor = ServiceSupervisor(self.states, self.log)
        self.router = CommandRouter(logger=self.log)
        enabled_apps = tuple(app.process_name for app in self.config.apps if app.enabled)
        needs_audio = (
            self.config.control_master_volume
            or self.config.media_player_enabled
            or bool(enabled_apps)
            or self.config.control_active_app
            or self.config.control_microphone
            or self.config.control_audio_output
            or (
                self.config.audio_enhancements_enabled
                and (
                    self.config.control_channel_balance
                    or self.config.publish_audio_sessions
                )
            )
        )
        self._master_audio = (
            MasterAudioProvider(
                self.audio,
                self.computer_state,
                self._generation,
                poll_interval=self.config.poll_interval,
                process_names=enabled_apps,
                include_sessions=bool(enabled_apps)
                or self.config.control_active_app
                or self.config.publish_audio_sessions,
                include_microphone=self.config.control_microphone,
                include_outputs=self.config.control_audio_output,
                logger=self.log,
            )
            if needs_audio
            else None
        )
        self._media_provider = (
            MediaProvider(
                self.media,
                self.computer_state,
                self._generation,
                interval=max(0.25, self.config.poll_interval),
                logger=self.log,
            )
            if (
                (self.config.media_player_enabled or self.config.overlay_enabled)
                and callable(getattr(self.media, "snapshot", None))
            )
            else None
        )
        self._system_providers = self._create_system_providers(enabled_apps)
        self._system_view = SystemProviderView(self.system, self.computer_state)
        audio_view = self._master_audio or self.audio
        media_view = self._media_provider or self.media
        WindowsCommands(self.config, audio_view, self._system_view, media_view, self.power,
                        self.events, self.monitors,
                        master_audio=self._master_audio).install(self.router)
        self._telemetry = None
        self._state_projection = None
        self._protocol_projection = None
        if self._master_audio is not None:
            self.supervisor.register("audio", self._master_audio)
        if self._media_provider is not None:
            self.supervisor.register("media", self._media_provider)
        provider_names = []
        for provider in self._system_providers:
            name = f"provider_{provider.source}"
            provider_names.append(name)
            self.supervisor.register(name, provider)
        if self.config.mqtt.host:
            gateway = (self._mqtt_factory or MqttGateway)(self.config, self.router, self.events)
            if hasattr(gateway.publisher, "begin_generation"):
                gateway.publisher.begin_generation(self._generation)
            self.supervisor.register("mqtt", gateway)
            if hasattr(gateway, "protocol") and hasattr(gateway.protocol, "snapshot_topic"):
                self._protocol_projection = ProtocolStateProjection(
                    self.computer_state,
                    gateway.publisher,
                    self.events,
                    gateway.protocol,
                    self._generation,
                )
                self.supervisor.register("protocol_projection", self._protocol_projection, "mqtt")
            if self.config.control_master_volume and self._master_audio is not None:
                self._state_projection = MasterAudioProjection(
                    self.config,
                    self.computer_state,
                    gateway.publisher,
                    self.events,
                    self._generation,
                )
                self.supervisor.register(
                    "master_audio_projection",
                    self._state_projection,
                    "audio",
                    "mqtt",
                )
            self._telemetry = TelemetryService(self.config, audio_view, self._system_view, media_view,
                                              gateway.publisher, self.events, self.monitors,
                                              self.computer_state, self._master_audio,
                                              getattr(gateway, "protocol", None))
            telemetry_dependencies = ["mqtt", *provider_names]
            if self._master_audio is not None:
                telemetry_dependencies.append("audio")
            if self._media_provider is not None:
                telemetry_dependencies.append("media")
            self.supervisor.register(
                "sensors",
                self._telemetry,
                *telemetry_dependencies,
            )
        if self.config.home_assistant.enabled and self.config.overlay_enabled:
            if self._direct_factory is None:
                from ..communication.home_assistant import HomeAssistantGateway
                self._direct_factory = HomeAssistantGateway
            self.supervisor.register("home_assistant", self._direct_factory(self.config, self.router, self.events))

    def _event_subscription(self, *topics: str):
        def subscribe(changed):
            subscriptions = [
                self.events.subscribe(topic, lambda event, wake=changed: wake(event))
                for topic in topics
            ]

            def unsubscribe():
                for callback in subscriptions:
                    callback()

            return unsubscribe

        return subscribe

    def _create_system_providers(self, enabled_apps):
        providers = []
        interval = max(0.1, self.config.poll_interval)

        def add(
            source,
            enabled,
            read,
            *,
            minimum,
            maximum,
            events=(),
            owns_com=False,
            stop_timeout=3.0,
            read_timeout=None,
        ):
            if not enabled or not callable(read):
                return
            providers.append(
                AdaptiveProvider(
                    source,
                    read,
                    self.computer_state,
                    self._generation,
                    interval=minimum,
                    maximum_interval=maximum,
                    subscribe=self._event_subscription(*events) if events else None,
                    owns_com=owns_com,
                    stop_timeout=stop_timeout,
                    read_timeout=read_timeout,
                    logger=self.log,
                )
            )

        add(
            "desktop_context",
            (
                self.config.publish_activity
                or self.config.publish_idle
                or self.config.publish_session_lock
                or self.config.overlay_enabled
            ),
            getattr(self.system, "context_snapshot", None),
            minimum=interval,
            maximum=max(2.0, interval * 5),
            events=("windows.locked", "windows.display_changed"),
        )
        add(
            "processes",
            bool(enabled_apps),
            (
                lambda: frozenset(self.system.running_process_names(list(enabled_apps)))
                if hasattr(self.system, "running_process_names")
                else frozenset()
            ),
            minimum=max(0.5, interval),
            maximum=max(5.0, interval * 10),
        )
        add(
            "cpu_ram",
            self.config.publish_cpu_stats or self.config.publish_ram_stats,
            getattr(self.system, "cpu_ram_metrics", None),
            minimum=max(0.5, interval),
            maximum=max(5.0, interval * 10),
        )
        add(
            "gpu",
            self.config.publish_gpu_stats or self.config.publish_cpu_stats,
            (
                lambda: self.system.gpu_metrics_snapshot(
                    include_cpu_hardware=self.config.publish_cpu_stats
                )
                if hasattr(self.system, "gpu_metrics_snapshot")
                else self.system.system_metrics(
                    include_cpu=self.config.publish_cpu_stats,
                    include_gpu=self.config.publish_gpu_stats,
                    include_ram=False,
                )
            ),
            minimum=5.0,
            maximum=30.0,
            owns_com=True,
            stop_timeout=4.0,
        )
        add(
            "windows_health",
            self.config.publish_windows_health,
            (
                getattr(self.system, "windows_health_snapshot", None)
                or getattr(self.system, "windows_health", None)
            ),
            minimum=30.0,
            maximum=300.0,
            events=("windows.power_changed",),
        )
        add(
            "windows_update",
            self.config.publish_windows_health,
            getattr(self.system, "pending_windows_updates", None),
            minimum=30 * 60.0,
            maximum=30 * 60.0,
            stop_timeout=4.0,
            read_timeout=15.0,
        )

        def storage_snapshot():
            volumes = list(self.system.list_disk_volumes())
            try:
                metrics = self.system.disk_metrics(
                    self.config.disk_mounts,
                    volumes=volumes,
                )
            except TypeError:
                metrics = self.system.disk_metrics(self.config.disk_mounts)
            return StorageSnapshot(tuple(volumes), metrics)

        add(
            "storage",
            self.config.publish_disk_stats,
            storage_snapshot,
            minimum=5.0,
            maximum=60.0,
            events=("windows.device_changed",),
            owns_com=True,
            stop_timeout=4.0,
        )
        add(
            "pnp",
            self.config.publish_devices,
            (
                lambda: DeviceSnapshot(tuple(self.system.list_pnp_devices()))
                if hasattr(self.system, "list_pnp_devices")
                else DeviceSnapshot()
            ),
            minimum=10.0,
            maximum=120.0,
            events=("windows.device_changed",),
            owns_com=True,
            stop_timeout=4.0,
        )
        return providers

    def _schedule(self, action):
        with self._guard:
            if self._closed:
                return False
            operation_epoch = self._lifecycle_epoch
            return self._operations.submit(
                lambda: self._run_operation(action, operation_epoch)
            )

    def _run_operation(self, action, operation_epoch=None):
        if operation_epoch is None:
            with self._guard:
                operation_epoch = self._lifecycle_epoch
        had_previous = hasattr(self._operation_context, "epoch")
        previous = getattr(self._operation_context, "epoch", None)
        self._operation_context.epoch = operation_epoch
        try:
            action()
        except _StaleLifecycleOperation:
            self.log.info("Discarded stale lifecycle operation after shutdown")
        except Exception:
            self.log.exception("Application operation failed")
            self.events.emit("application.error", "operation_failed")
        finally:
            if had_previous:
                self._operation_context.epoch = previous
            else:
                del self._operation_context.epoch

    def start(self):
        with self._guard:
            if self._closed:
                return False
            self._desired_running = True
        return self._schedule(self._start)

    def _start(self):
        # Serialize the short startup transition with synchronous stop intent.
        # Service start methods only create their owned workers and return.
        with self._guard:
            self._ensure_operation_current_locked()
            if self._suspended or not self._desired_running:
                return
            if self._restart_blocked:
                raise RuntimeError("Restart refused until every previous owner stops")
            if self.router.closed:
                self._build_services()
            errors = self.config.validation_errors()
            if errors:
                self.log.warning("Nie uruchomiono usług: %s", "; ".join(errors))
                self.events.emit("application.error", "\n".join(errors))
                return
            self.last_start_report = self.supervisor.start()
            self.events.emit("application.start_report", self.last_start_report)
            self.events.emit("application.running", bool(self.supervisor.active))

    def stop(self):
        with self._guard:
            self._desired_running = False
        self._begin_stop("stopping")
        return self._schedule(self._stop)

    def _begin_stop(self, detail: str) -> None:
        self.router.reject_new_work()
        with self._guard:
            if self._services_generation is None:
                return
            self._services_generation = None
            self._generation += 1
            generation = self._generation
        self.computer_state.begin_generation(generation, detail=detail)

    @staticmethod
    def _stop_result(owner: str, stopped, detail: str) -> LifecycleResult:
        return LifecycleResult(
            owner,
            LifecycleOutcome.STOPPED if stopped is not False else LifecycleOutcome.TIMEOUT,
            "" if stopped is not False else detail,
        )

    def _stop(self):
        with self._teardown_guard:
            return self._stop_owned()

    def _stop_owned(self):
        self._begin_stop("stopping")
        results = []
        try:
            results.append(
                self._stop_result(
                    "commands",
                    self.router.stop(),
                    "command_worker_timeout",
                )
            )
        except Exception:
            self.log.exception("Command shutdown failed")
            results.append(
                LifecycleResult(
                    "commands",
                    LifecycleOutcome.FAILED,
                    "command_shutdown_failed",
                )
            )
        try:
            results.extend(self.supervisor.stop().results)
        except Exception:
            self.log.exception("Service supervisor shutdown failed")
            results.append(
                LifecycleResult(
                    "services",
                    LifecycleOutcome.FAILED,
                    "supervisor_shutdown_failed",
                )
            )
        self.events.emit("application.running", False)
        report = LifecycleReport("stop", tuple(results))
        self.last_stop_report = report
        self._restart_blocked = not report.ok
        self.events.emit("application.stop_report", report)
        if not report:
            raise RuntimeError(
                "Application shutdown incomplete: " + ", ".join(report.unfinished)
            )
        return report

    def reconnect(self):
        with self._guard:
            if self._closed:
                return False
            self._desired_running = True
        self._begin_stop("reconnecting")
        def reconnect():
            self._stop()
            self._build_services()
            self._start()
        return self._schedule(reconnect)

    def apply_configuration(self, config: AppConfig):
        candidate = copy.deepcopy(config)
        errors = candidate.validation_errors()
        if not candidate.mqtt.host and not candidate.home_assistant.enabled:
            errors = [error for error in errors if error != "Skonfiguruj MQTT lub bezpośrednie połączenie z Home Assistant."]
        if errors:
            self.log.warning("Nie zapisano ustawień: %s", "; ".join(errors))
            self.events.emit("application.error", "\n".join(errors))
            return False
        self._protect_secrets(candidate)
        def apply():
            previous = copy.deepcopy(self.config)
            # Read before stopping anything; a read failure leaves runtime intact.
            previous_startup = self.startup.is_enabled()
            saved = startup_attempted = False
            self._ensure_operation_current()
            self._stop()
            self._ensure_operation_current()
            try:
                self.store.save(candidate)
                saved = True
                self._ensure_operation_current()
                startup_attempted = True
                self.startup.set_enabled(candidate.start_with_windows)
                self._ensure_operation_current()
                with self._guard:
                    self._ensure_operation_current_locked()
                    self.config = candidate
                self._build_services()
                self._start()
                self._ensure_operation_current()
                if any(status.state.value == "error" for status in self.states.snapshot()):
                    raise RuntimeError("Configuration service startup failed")
            except Exception:
                # Cover every stage after stop, including registry, build and start.
                # A rollback failure is explicit and never reported as applied.
                with self._guard:
                    operation_current = self._operation_is_current_locked()
                try:
                    if operation_current:
                        self._stop()
                    if saved:
                        self.store.save(previous)
                    if startup_attempted:
                        self.startup.set_enabled(previous_startup)
                    with self._guard:
                        self.config = previous
                        operation_current = self._operation_is_current_locked()
                    if operation_current:
                        self._build_services()
                        self._start()
                        self._ensure_operation_current()
                        if any(status.state.value == "error" for status in self.states.snapshot()):
                            raise RuntimeError("Previous configuration service startup failed")
                except Exception:
                    self.log.exception("Configuration rollback failed; recovery required")
                    self.events.emit("application.error", "configuration_rollback_failed")
                    raise
                raise
            self.events.emit("configuration.changed", copy.deepcopy(candidate))
            self.log.info("Zapisano i zastosowano ustawienia")
        return self._schedule(apply)

    def pause_sensors(self, paused: bool):
        if self._telemetry:
            self._telemetry.pause(paused)
        if self._master_audio:
            self._master_audio.pause(paused)
        if self._media_provider:
            self._media_provider.pause(paused)
        for provider in self._system_providers:
            provider.pause(paused)

    def request_inventory(self, kind):
        if kind not in {"disks", "devices", "applications"} or self._closed:
            return False
        def query():
            try:
                if kind == "applications":
                    if self._master_audio is not None and self._master_audio.is_alive:
                        items = self._master_audio.list_audio_applications()
                    else:
                        items = self.audio.list_audio_applications(
                            include_processes=[
                                app.process_name for app in self.config.apps
                            ]
                        )
                        generation = self._services_generation
                        if generation is not None:
                            self.computer_state.observe_provider(
                                "audio",
                                AudioProviderSnapshot(applications=tuple(items)),
                                generation=generation,
                            )
                else:
                    source = "storage" if kind == "disks" else "pnp"
                    sample = self.computer_state.snapshot().provider(source)
                    if sample is None:
                        generation = self._services_generation
                        if kind == "disks":
                            items = self.system.list_disk_volumes()
                            snapshot = StorageSnapshot(
                                tuple(items),
                                DiskMetrics(0.0, 0.0, 0.0, 0.0),
                            )
                        else:
                            items = self.system.list_pnp_devices()
                            snapshot = DeviceSnapshot(tuple(items))
                        if generation is not None:
                            self.computer_state.observe_provider(
                                source,
                                snapshot,
                                generation=generation,
                            )
                    else:
                        items = (
                            list(sample.value.volumes)
                            if kind == "disks"
                            else list(sample.value.devices)
                        )
                self.events.emit("inventory." + kind, items)
            except Exception:
                self.log.exception("Device inventory unavailable")
                self.events.emit("application.error", "Nie można odczytać urządzeń. Spróbuj ponownie.")
        return self._query_once(kind, query)

    def _query_once(self, key, callback, *, worker=None):
        with self._guard:
            if self._closed or key in self._pending_queries:
                return False
            self._pending_queries.add(key)
        def run():
            try:
                callback()
            finally:
                with self._guard:
                    self._pending_queries.discard(key)
        accepted = (worker or self._queries).submit(run)
        if not accepted:
            with self._guard:
                self._pending_queries.discard(key)
        return accepted

    def request_resources(self):
        return self._query_once("resources", lambda: self.events.emit("resources.updated", self.resources.sample()))

    def request_media_example(self, request_id):
        def query():
            try:
                media = self._media_provider
                if media is None:
                    self.media.reopen()
                    try:
                        snapshot = self.media.snapshot()
                    finally:
                        self.media.close()
                else:
                    snapshot = media.snapshot()
                if not snapshot.supported:
                    raise RuntimeError("Windows Media unavailable")
                if not snapshot.source_app and not snapshot.title:
                    self.log.info("Podgląd odtwarzacza: brak aktywnej sesji Windows")
                    self.events.emit("application.error", "Uruchom odtwarzanie w Windows i ponów podgląd.")
                    return
                from ..overlays.windows_media import windows_media_payload
                payload = windows_media_payload(snapshot, device_name=self.config.device_name,
                                                controls=self.config.media_player_enabled and not self.router.closed)
                payload["data"].update(id="example-media", show_close_button=True, pause_on_hover=True,
                                       duration=12, edge_offset=16, monitor=self.config.overlay_monitor)
                self.events.emit("overlay.media_example", {"request_id": request_id, "payload": payload})
                self.log.info("Wyświetlono podgląd odtwarzacza Windows")
            except Exception:
                self.log.exception("Nie można odczytać odtwarzacza Windows")
                self.events.emit("application.error", "Nie można odczytać odtwarzacza Windows. Sprawdź diagnostykę.")
        # Serialize media open/read against configuration changes and shutdown.
        return self._query_once("media_example", query, worker=self._operations)

    def request_media_refresh(self):
        def query():
            if self._closed or self._suspended:
                return
            media = self._media_provider
            if media is None:
                return
            snapshot = media.snapshot()
            if snapshot.supported:
                from ..overlays.windows_media import windows_media_payload
                payload = windows_media_payload(snapshot, controls=self.config.media_player_enabled and not self.router.closed)
                if not snapshot.source_app and not snapshot.title:
                    payload["title"] = "Brak aktywnego odtwarzacza"
                self.events.emit("overlay.media_refresh", payload)
        return self._query_once("media_refresh", query, worker=self._operations)

    def suspend(self):
        with self._guard:
            self._suspended = True
        self._begin_stop("suspended")
        return self._schedule(self._stop)

    def resume(self):
        with self._guard:
            if self._closed or not self._suspended:
                return False
            self._suspended = False
        def resume():
            self._stop()
            self._build_services()
            self._start()
        return self._schedule(resume)

    def command(self, kind: str, arguments: dict, target=""):
        command = Command(uuid.uuid4().hex, kind, target, copy.deepcopy(arguments),
                          time.time() + 10, monotonic_expires_at=time.monotonic() + 10)
        with self._guard:
            if self._closed:
                result = CommandResult(command.id, "rejected", "stopping")
            else:
                result = self.router.submit(
                    command,
                    lambda reply: self.events.emit("command.result", reply),
                )
        if result.status != "accepted":
            self.events.emit("command.result", result)
        return result

    def computer_snapshot(self):
        return self.computer_state.snapshot(
            stale_after=max(2.0, self.config.poll_interval * 3)
        )

    def diagnostic_report(self):
        with self._guard:
            report = {
                "version": __version__, "platform": platform.platform(), "qt": version("PySide6"),
                "python": platform.python_version(), "services": [asdict(status) for status in self.states.snapshot()],
                "connections": list(self._connections.values()),
                "configuration": self.config.to_dict(), "recent_logs": self.diagnostics.snapshot(),
                "process_resources": self.resources.sample(),
                "computer_state": asdict(self.computer_snapshot()),
                "last_start": asdict(self.last_start_report),
                "last_stop": asdict(self.last_stop_report),
            }
        return redact_data(report, (self.config.mqtt.password, self.config.home_assistant.token))

    def export_diagnostics(self, path):
        report = self.diagnostic_report()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def _close_system_owner(self) -> LifecycleResult | None:
        closer = getattr(self.system, "close", None)
        if not callable(closer):
            return None
        try:
            return self._stop_result(
                "windows_update",
                closer(),
                "windows_update_worker_timeout",
            )
        except Exception:
            self.log.exception("Windows Update worker shutdown failed")
            return LifecycleResult(
                "windows_update",
                LifecycleOutcome.FAILED,
                "windows_update_worker_shutdown_failed",
            )

    def shutdown(self) -> bool:
        with self._guard:
            if self._shutdown_finalized:
                return bool(self.last_shutdown_report)
            self._closed = True
            self._desired_running = False
            self._lifecycle_epoch += 1
        self._begin_stop("shutdown")
        self._operations.close(timeout=4)
        self._queries.close(timeout=4)
        results = [
            self._stop_result(
                "application-lifecycle-worker",
                not self._operations.is_alive,
                "lifecycle_worker_timeout",
            ),
            self._stop_result(
                "application-query-worker",
                not self._queries.is_alive,
                "query_worker_timeout",
            ),
        ]
        if self._teardown_guard.acquire(blocking=False):
            try:
                try:
                    self._stop_owned()
                except Exception:
                    self.log.exception("Shutdown has unfinished resources")
                stop_report = self.last_stop_report
            finally:
                self._teardown_guard.release()
        else:
            stop_report = LifecycleReport(
                "stop",
                (
                    LifecycleResult(
                        "services",
                        LifecycleOutcome.BLOCKED,
                        "teardown_in_progress",
                    ),
                ),
            )
        results.extend(stop_report.results)
        system_result = self._close_system_owner()
        if system_result is not None:
            results.append(system_result)
        self.last_shutdown_report = LifecycleReport("shutdown", tuple(results))
        if not self.last_shutdown_report:
            self.log.error(
                "Shutdown incomplete; unfinished owners: %s",
                ", ".join(self.last_shutdown_report.unfinished),
            )
        self.events.emit("application.shutdown_report", self.last_shutdown_report)
        self._connection_unsubscribe()
        self.log.removeHandler(self.diagnostics)
        self.diagnostics.close()
        self.events.clear()
        self._shutdown_finalized = True
        return bool(self.last_shutdown_report)
