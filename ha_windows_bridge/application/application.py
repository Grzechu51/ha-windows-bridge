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
from ..communication.status import CONNECTION_NAMES, connection_text
from ..config import AppConfig
from ..core.commands import Command
from ..core.events import EventBus
from ..core.observability import DiagnosticBuffer
from ..core.state import StateStore
from ..runtime.worker import SerialWorker
from ..security import redact_data
from ..windows.resources import ProcessResources
from .commands import CommandRouter
from .lifecycle import ServiceSupervisor
from .windows_commands import WindowsCommands


class Application:
    def __init__(self, config, store, startup, audio, system, media, power, *, events=None,
                 mqtt_factory=None, direct_factory=None, monitors=None):
        self.events = events or EventBus()
        self.states = StateStore(self.events)
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
        self._closed = False
        self._desired_running = False
        self._suspended = False
        self._telemetry = None
        self._generation = 0
        self._connections = {}
        self._pending_queries = set()
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

    def _build_services(self):
        from ..communication.gateway import MqttGateway
        from .telemetry import TelemetryService
        self._generation += 1
        self.states.clear()
        with self._guard:
            self._connections.clear()
        self.supervisor = ServiceSupervisor(self.states, self.log)
        self.router = CommandRouter(logger=self.log)
        WindowsCommands(self.config, self.audio, self.system, self.media, self.power,
                        self.events, self.monitors).install(self.router)
        self._telemetry = None
        if self.config.mqtt.host:
            gateway = (self._mqtt_factory or MqttGateway)(self.config, self.router, self.events)
            self.supervisor.register("mqtt", gateway)
            self._telemetry = TelemetryService(self.config, self.audio, self.system, self.media,
                                              gateway.publisher, self.events, self.monitors)
            self.supervisor.register("sensors", self._telemetry, "mqtt")
        if self.config.home_assistant.enabled and self.config.overlay_enabled:
            if self._direct_factory is None:
                from ..communication.home_assistant import HomeAssistantGateway
                self._direct_factory = HomeAssistantGateway
            self.supervisor.register("home_assistant", self._direct_factory(self.config, self.router, self.events))

    def _schedule(self, action):
        with self._guard:
            if self._closed:
                return False
            return self._operations.submit(lambda: self._run_operation(action))

    def _run_operation(self, action):
        try:
            action()
        except Exception:
            self.log.exception("Application operation failed")
            self.events.emit("application.error", "operation_failed")

    def start(self):
        self._desired_running = True
        return self._schedule(self._start)

    def _start(self):
        if self._suspended or not self._desired_running:
            return
        if self.router.closed:
            self._build_services()
        errors = self.config.validation_errors()
        if errors:
            self.log.warning("Nie uruchomiono usług: %s", "; ".join(errors))
            self.events.emit("application.error", "\n".join(errors))
            return
        self.media.reopen()
        self.supervisor.start()
        self.events.emit("application.running", bool(self.supervisor.active))

    def stop(self):
        self._desired_running = False
        return self._schedule(self._stop)

    def _stop(self):
        if not self.supervisor.stop():
            raise RuntimeError("Service shutdown is incomplete; restart refused")
        if not self.router.stop():
            raise RuntimeError("Command execution is still stopping")
        self.media.close()
        self.events.emit("application.running", False)

    def reconnect(self):
        self._desired_running = True
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
            self._stop()
            # Saving occurs only after old services have relinquished their resources.
            try:
                self.store.save(candidate)
            except Exception:
                # A failed write must not leave a running installation stopped.
                self._start()
                raise
            self.startup.set_enabled(candidate.start_with_windows)
            self.config = candidate
            self._build_services()
            self.events.emit("configuration.changed", copy.deepcopy(candidate))
            self.log.info("Zapisano i zastosowano ustawienia")
            # auto_connect controls application startup, not the current run state.
            self._start()
        return self._schedule(apply)

    def pause_sensors(self, paused: bool):
        if self._telemetry:
            self._telemetry.pause(paused)

    def request_inventory(self, kind):
        if kind not in {"disks", "devices", "applications"} or self._closed:
            return False
        def query():
            try:
                if kind == "applications":
                    items = self.audio.list_audio_applications(include_processes=[app.process_name for app in self.config.apps])
                else:
                    items = self.system.list_disk_volumes() if kind == "disks" else self.system.list_pnp_devices()
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
                self.media.reopen()
                snapshot = self.media.snapshot()
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

    def suspend(self):
        self._suspended = True
        return self._schedule(self._stop)

    def resume(self):
        with self._guard:
            if not self._suspended:
                return False
            self._suspended = False
        def resume():
            self._stop()
            self._build_services()
            self._start()
        return self._schedule(resume)

    def command(self, kind: str, arguments: dict, target=""):
        command = Command(uuid.uuid4().hex, kind, target, copy.deepcopy(arguments), time.time() + 10)
        result = self.router.submit(command, lambda result: self.events.emit("command.result", result))
        if result.status != "accepted":
            self.events.emit("command.result", result)
        return result

    def diagnostic_report(self):
        with self._guard:
            report = {
                "version": __version__, "platform": platform.platform(), "qt": version("PySide6"),
                "python": platform.python_version(), "services": [asdict(status) for status in self.states.snapshot()],
                "connections": list(self._connections.values()),
                "configuration": self.config.to_dict(), "recent_logs": self.diagnostics.snapshot(),
                "process_resources": self.resources.sample(),
            }
        return redact_data(report, (self.config.mqtt.password, self.config.home_assistant.token))

    def export_diagnostics(self, path):
        report = self.diagnostic_report()
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def shutdown(self) -> bool:
        with self._guard:
            self._closed = True
            self._desired_running = False
        self._operations.close(timeout=4)
        self._queries.close(timeout=4)
        if self._operations.is_alive or self._queries.is_alive:
            return False
        try:
            self._stop()
        except Exception:
            self.log.exception("Shutdown has unfinished resources")
            return False
        self.log.removeHandler(self.diagnostics)
        self.diagnostics.close()
        self.events.clear()
        return True
