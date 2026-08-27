from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import suppress

import paho.mqtt.client as mqtt

from .audio import AudioOutputDevice, AudioSessionSnapshot, WindowsAudioService
from .config import AppConfig, AudioAppConfig, AudioProfileConfig
from .discovery import (
    active_app_topic,
    active_volume_topics,
    active_window_topic,
    app_close_topic,
    app_mute_topics,
    app_running_topic,
    app_session_count_topic,
    app_start_topic,
    app_volume_topics,
    audio_output_topics,
    audio_profile_topics,
    fullscreen_topic,
    idle_topic,
    master_balance_topics,
    master_mute_topics,
    master_volume_topics,
    microphone_active_topic,
    microphone_mute_topics,
    microphone_volume_topics,
    overlay_notification_topic,
    pc_active_topic,
    power_action_topic,
    session_locked_topic,
    status_topic,
    system_metric_topic,
    tracked_device_topic,
    windows_notification_topic,
)
from .i18n import translate
from .integration_protocol import integration_announcement_payload
from .media import WindowsMediaService
from .media_protocol import (
    media_announcement_topic,
    media_artwork_payload,
    media_state_payload,
    media_thumbnail_topic,
    media_topics,
)
from .system_actions import WindowsPowerActions
from .system_monitor import PcContext, WindowsSystemMonitor

StatusCallback = Callable[[str, bool], None]
NotificationCallback = Callable[[str, str], None]
OverlayCallback = Callable[[str, str, dict], None]
MAX_COMMAND_PAYLOAD = 8 * 1024
MAX_OVERLAY_PAYLOAD = 768 * 1024


class MqttBridge:
    def __init__(
        self,
        config: AppConfig,
        audio: WindowsAudioService | None = None,
        logger: logging.Logger | None = None,
        status_callback: StatusCallback | None = None,
        system_monitor: WindowsSystemMonitor | None = None,
        media_service: WindowsMediaService | None = None,
        power_actions: WindowsPowerActions | None = None,
        notification_callback: NotificationCallback | None = None,
        overlay_callback: OverlayCallback | None = None,
    ):
        self.config = config
        self.audio = audio or WindowsAudioService()
        self.system = system_monitor or WindowsSystemMonitor()
        self.media = media_service or WindowsMediaService(logger)
        self.log = logger or logging.getLogger(__name__)
        self.status_callback = status_callback
        self.power_actions = power_actions or WindowsPowerActions()
        self.notification_callback = notification_callback
        self.overlay_callback = overlay_callback
        self.client: mqtt.Client | None = None
        self._stop_event = threading.Event()
        self._connected = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._intentional_stop = False

        self._last_volumes: dict[str, float] = {}
        self._last_mutes: dict[str, bool] = {}
        self._last_running: dict[str, bool] = {}
        self._last_active: tuple[str, float] | None = None
        self._last_master_volume: float | None = None
        self._last_master_mute: bool | None = None
        self._last_master_balance: float | None = None
        self._last_session_counts: dict[str, int] = {}
        self._last_device_states: dict[str, bool] = {}
        self._ducked_volumes: dict[str, float] = {}
        self._last_microphone: tuple[float, bool, bool] | None = None
        self._microphone_active_until = 0.0
        self._last_context: PcContext | None = None
        self._last_audio_output = ""
        self._last_media_payload = ""
        self._last_media_artwork_hash: str | None = None
        self._audio_outputs: list[AudioOutputDevice] = []

        self._command_apps: dict[str, AudioAppConfig] = {}
        self._app_mute_commands: dict[str, AudioAppConfig] = {}
        self._app_action_commands: dict[str, tuple[str, AudioAppConfig]] = {}
        self._active_command = ""
        self._master_command = ""
        self._master_mute_command = ""
        self._microphone_volume_command = ""
        self._microphone_mute_command = ""
        self._audio_output_command = ""
        self._media_command = ""
        self._power_action_commands: dict[str, str] = {}
        self._notification_command = ""
        self._overlay_command = ""
        self._master_balance_command = ""
        self._audio_profile_command = ""
        self._active_audio_profile = ""
        self.started_at: float | None = None
        self.messages_processed = 0

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self.client is not None:
            return
        errors = self.config.validation_errors()
        if errors:
            raise ValueError("\n".join(errors))

        self._intentional_stop = False
        self._stop_event.clear()
        self.started_at = time.monotonic()
        self.messages_processed = 0
        self._build_command_map()
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-windows-bridge-{self.config.device_id}"[:64],
            protocol=mqtt.MQTTv311,
        )
        if self.config.mqtt.username:
            self.client.username_pw_set(self.config.mqtt.username, self.config.mqtt.password)
        if self.config.mqtt.tls:
            self.client.tls_set()
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.will_set(status_topic(self.config), "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._emit_status("Łączenie…", False)
        self.log.info("Łączenie z MQTT %s:%s", self.config.mqtt.host, self.config.mqtt.port)
        self.client.connect_async(
            self.config.mqtt.host,
            self.config.mqtt.port,
            self.config.mqtt.keepalive,
        )
        self.client.loop_start()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="bridge-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        if self._ducked_volumes:
            for process_name, volume in self._ducked_volumes.items():
                self.audio.set_volume(process_name, volume)
            self._ducked_volumes.clear()
        client = self.client
        if client is None:
            return
        self._intentional_stop = True
        self._stop_event.set()
        if self._connected.is_set():
            try:
                client.publish(
                    status_topic(self.config), "offline", qos=1, retain=True
                ).wait_for_publish(1)
            except Exception:
                self.log.debug("Nie udało się potwierdzić stanu offline MQTT", exc_info=True)
        try:
            client.disconnect()
            client.loop_stop()
        finally:
            self._connected.clear()
            self.client = None
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=2)
            self._monitor_thread = None
            close_media = getattr(self.media, "close", None)
            if callable(close_media):
                close_media()
            self._emit_status("Zatrzymano", False)
            self.log.info("Most MQTT zatrzymany")

    def remove_discovery(self, topics: Iterable[str]) -> bool:
        client = self.client
        if client is None or not self._connected.is_set():
            return False
        pending = [client.publish(topic, "", qos=1, retain=True) for topic in dict.fromkeys(topics)]
        confirmed = True
        deadline = time.monotonic() + 2.0
        for publication in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                confirmed = False
                break
            try:
                publication.wait_for_publish(remaining)
            except Exception:
                confirmed = False
                self.log.warning("Nie udało się potwierdzić usunięcia wpisu MQTT Discovery")
        return confirmed

    @staticmethod
    def parse_volume(payload: bytes | str) -> float:
        text = payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else payload
        normalized = text.strip().lower()
        value = float(normalized)
        if not math.isfinite(value):
            raise ValueError("Głośność musi być skończoną liczbą")
        value = max(value, 0)
        is_explicit_fraction = 0 < value < 1 or (
            value == 1 and ("." in normalized or "e" in normalized)
        )
        if not is_explicit_fraction:
            value /= 100.0
        return max(0.0, min(1.0, value))

    @staticmethod
    def parse_switch(payload: bytes | str) -> bool:
        text = payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else payload
        normalized = text.strip().lower()
        if normalized in {"on", "1", "true", "yes"}:
            return True
        if normalized in {"off", "0", "false", "no"}:
            return False
        raise ValueError(f"Nieprawidłowy stan przełącznika: {text}")

    @staticmethod
    def test_connection(config: AppConfig, timeout: float = 6.0) -> tuple[bool, str]:
        done = threading.Event()
        outcome = {"ok": False, "message": "Przekroczono czas oczekiwania."}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        if config.mqtt.username:
            client.username_pw_set(config.mqtt.username, config.mqtt.password)
        if config.mqtt.tls:
            client.tls_set()

        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            if getattr(reason_code, "is_failure", False):
                outcome["message"] = f"Broker odrzucił połączenie: {reason_code}"
            else:
                outcome["ok"] = True
                outcome["message"] = "Połączenie z brokerem działa."
            done.set()

        def on_connect_fail(_client, _userdata):
            outcome["message"] = "Nie można nawiązać połączenia z brokerem."
            done.set()

        client.on_connect = on_connect
        client.on_connect_fail = on_connect_fail
        try:
            client.connect_async(config.mqtt.host, config.mqtt.port, config.mqtt.keepalive)
            client.loop_start()
            done.wait(timeout)
        except Exception as exc:
            outcome["message"] = str(exc)
        finally:
            with suppress(Exception):
                client.disconnect()
                client.loop_stop()
        return bool(outcome["ok"]), str(outcome["message"])

    def _build_command_map(self) -> None:
        self._command_apps.clear()
        self._app_mute_commands.clear()
        self._app_action_commands.clear()
        self._master_command, _ = master_volume_topics(self.config)
        self._master_mute_command, _ = master_mute_topics(self.config)
        self._master_balance_command, _ = master_balance_topics(self.config)
        self._microphone_volume_command, _ = microphone_volume_topics(self.config)
        self._microphone_mute_command, _ = microphone_mute_topics(self.config)
        self._audio_output_command, _ = audio_output_topics(self.config)
        self._media_command, _ = media_topics(self.config)
        self._audio_profile_command, _ = audio_profile_topics(self.config)
        self._power_action_commands = (
            {
                power_action_topic(self.config, action): action
                for action in ("lock", "sleep", "restart", "shutdown", "cancel")
            }
            if self.config.allow_power_actions
            else {}
        )
        self._notification_command = (
            windows_notification_topic(self.config)
            if self.config.enable_windows_notifications
            else ""
        )
        self._overlay_command = (
            overlay_notification_topic(self.config) if self.config.overlay_enabled else ""
        )
        for app in self.config.apps:
            if not app.enabled:
                continue
            volume_command, _ = app_volume_topics(self.config, app)
            mute_command, _ = app_mute_topics(self.config, app)
            self._command_apps[volume_command] = app
            self._app_mute_commands[mute_command] = app
            if app.allow_remote_start and app.executable_path:
                self._app_action_commands[app_start_topic(self.config, app)] = ("start", app)
            if app.allow_remote_close:
                self._app_action_commands[app_close_topic(self.config, app)] = ("close", app)
        if self.config.control_active_app:
            self._active_command, _ = active_volume_topics(self.config)
        else:
            self._active_command = ""

    def _command_topics(self) -> set[str]:
        topics = {
            *self._command_apps,
            *self._app_mute_commands,
            *self._app_action_commands,
            *self._power_action_commands,
        }
        if self.config.control_master_volume:
            topics.update((self._master_command, self._master_mute_command))
            if self.config.audio_enhancements_enabled and self.config.control_channel_balance:
                topics.add(self._master_balance_command)
        if self._active_command:
            topics.add(self._active_command)
        if self.config.control_microphone:
            topics.update((self._microphone_volume_command, self._microphone_mute_command))
        if self.config.control_audio_output:
            topics.add(self._audio_output_command)
        if (
            self.config.audio_enhancements_enabled
            and self.config.audio_profiles_enabled
            and self.config.audio_profiles
        ):
            topics.add(self._audio_profile_command)
        if self.config.media_player_enabled:
            topics.add(self._media_command)
        if self._notification_command:
            topics.add(self._notification_command)
        if self._overlay_command:
            topics.add(self._overlay_command)
        return {topic for topic in topics if topic}

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if getattr(reason_code, "is_failure", False):
            message = f"Błąd MQTT: {reason_code}"
            self.log.error("Błąd MQTT: %s", reason_code)
            self._emit_status(message, False)
            return
        for topic in self._command_topics():
            client.subscribe(topic, qos=1)
        client.subscribe(f"{self.config.mqtt.discovery_prefix}/status", qos=0)
        if self.config.control_audio_output:
            self._audio_outputs = self.audio.list_output_devices()
        self._connected.set()
        self._last_media_payload = ""
        self._last_media_artwork_hash = None
        entity_count = self.publish_discovery()
        client.publish(status_topic(self.config), "online", qos=1, retain=True)
        self.log.info(
            "Połączono z MQTT; przekazano %s encji do integracji HA Windows Bridge",
            entity_count,
        )
        self._emit_status("MQTT połączone", True)

    def _on_connect_fail(self, _client, _userdata) -> None:
        self._connected.clear()
        self.log.warning("Nie można połączyć z MQTT; nastąpi ponowienie")
        self._emit_status("MQTT niedostępne — ponawianie", False)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        self._connected.clear()
        if not self._intentional_stop:
            self.log.warning("Rozłączono MQTT: %s", reason_code)
            self._emit_status("MQTT rozłączone — ponawianie", False)

    def _on_message(self, _client, _userdata, message) -> None:
        self.messages_processed += 1
        payload_limit = (
            MAX_OVERLAY_PAYLOAD if message.topic == self._overlay_command else MAX_COMMAND_PAYLOAD
        )
        if len(message.payload) > payload_limit:
            self.log.warning("Zignorowano zbyt dużą komendę MQTT na %s", message.topic)
            return
        birth_topic = f"{self.config.mqtt.discovery_prefix}/status"
        if message.topic == birth_topic:
            if message.payload.decode(errors="ignore").strip().lower() == "online":
                self.publish_discovery()
            return
        if message.retain:
            self.log.warning("Zignorowano retained command: %s", message.topic)
            return

        if message.topic == self._notification_command:
            self._handle_windows_notification(message.payload)
            return
        if message.topic == self._overlay_command:
            self._handle_overlay_notification(message.payload)
            return
        power_action = self._power_action_commands.get(message.topic)
        if power_action:
            self._handle_power_action(power_action, message.payload)
            return
        if message.topic == self._media_command:
            self._handle_media_command(message.payload)
            return

        action = self._app_action_commands.get(message.topic)
        if action:
            self._handle_app_action(*action, message.payload)
            return
        if message.topic == self._audio_output_command:
            self._handle_audio_output(message.payload)
            return
        if message.topic == self._audio_profile_command:
            self._handle_audio_profile(message.payload)
            return
        if message.topic == self._master_mute_command:
            self._handle_master_mute(message.payload)
            return
        if message.topic == self._microphone_mute_command:
            self._handle_microphone_mute(message.payload)
            return
        if message.topic == self._master_balance_command:
            self._handle_master_balance(message.payload)
            return
        app_for_mute = self._app_mute_commands.get(message.topic)
        if app_for_mute:
            self._handle_app_mute(app_for_mute, message.payload)
            return

        try:
            volume = self.parse_volume(message.payload)
        except (ValueError, UnicodeDecodeError):
            self.log.warning("Nieprawidłowa głośność MQTT na %s", message.topic)
            return
        if message.topic == self._master_command:
            self._handle_master_volume(volume)
            return
        if message.topic == self._microphone_volume_command:
            self._handle_microphone_volume(volume)
            return
        self._handle_application_volume(message.topic, volume)

    def _handle_windows_notification(self, payload: bytes) -> None:
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
            title = str(value.get("title", "Home Assistant")).strip()
            message = str(value.get("message", "")).strip()
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            self.log.warning("Nieprawidłowe powiadomienie Windows")
            return
        if not message or len(title) > 128 or len(message) > 2048:
            self.log.warning("Nieprawidłowe powiadomienie Windows")
            return
        if self.notification_callback:
            self.notification_callback(title or "Home Assistant", message)
        self.log.info("Wyświetlono powiadomienie Windows z Home Assistant")

    def _handle_overlay_notification(self, payload: bytes) -> None:
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
            title = str(value.get("title", "Home Assistant")).strip()
            message = str(value.get("message", "")).strip()
            data = value.get("data") or {}
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            self.log.warning("Nieprawidłowa wiadomość nakładki Windows")
            return
        action = str(data.get("action", "show")).strip().lower() if isinstance(data, dict) else ""
        if (
            action not in {"show", "update", "remove", "clear"}
            or (action in {"show", "update"} and not message)
            or len(title) > 128
            or len(message) > 2048
            or not isinstance(data, dict)
        ):
            self.log.warning("Nieprawidłowa wiadomość nakładki Windows")
            return
        if self.overlay_callback:
            self.overlay_callback(title or "Home Assistant", message, data)
        self.log.info("Przekazano wiadomość do nakładki Windows")

    @staticmethod
    def _is_button_press(payload: bytes) -> bool:
        try:
            return payload.decode("utf-8", errors="strict").strip().upper() == "PRESS"
        except UnicodeDecodeError:
            return False

    def _handle_power_action(self, action: str, payload: bytes) -> None:
        if not self._is_button_press(payload):
            self.log.warning("Zignorowano nieprawidłowe naciśnięcie przycisku MQTT")
            return
        ok, detail = self.power_actions.execute(action)
        detail = translate(detail, self.config.language)
        if ok:
            self.log.warning("Wykonano akcję systemową z Home Assistant: %s", action)
            if self.notification_callback:
                self.notification_callback("HA Windows Bridge", detail)
        else:
            self.log.error("Nie udało się wykonać akcji systemowej %s: %s", action, detail)

    def _handle_master_volume(self, volume: float) -> None:
        current = self.audio.get_master_volume()
        if current is None or abs(current - volume) >= 0.005:
            if not self.audio.set_master_volume(volume):
                self.log.warning("Nie można ustawić głównej głośności Windows")
                return
            time.sleep(0.03)
            current = self.audio.get_master_volume()
        actual = volume if current is None else current
        self._last_master_volume = actual
        self._publish_master_volume(actual)
        self.log.info("Ustawiono główną głośność na %s%%", round(actual * 100))

    def _handle_master_balance(self, payload: bytes) -> None:
        try:
            value = float(payload.decode("utf-8", errors="strict").strip())
        except (UnicodeDecodeError, ValueError):
            return
        if not math.isfinite(value) or not -100 <= value <= 100:
            return
        balance = value / 100.0
        if not self.audio.set_master_balance(balance):
            self.log.warning("Urządzenie audio nie obsługuje balansu kanałów")
            return
        self._last_master_balance = balance
        _, state = master_balance_topics(self.config)
        self._publish_text_state(state, round(balance * 100))

    def _handle_master_mute(self, payload: bytes) -> None:
        try:
            muted = self.parse_switch(payload)
        except (ValueError, UnicodeDecodeError):
            self.log.warning("Nieprawidłowa komenda master mute")
            return
        if not self.audio.set_master_mute(muted):
            self.log.warning("Nie można zmienić wyciszenia Windows")
            return
        self._last_master_mute = muted
        _, state = master_mute_topics(self.config)
        self._publish_switch_state(state, muted)

    def _handle_microphone_volume(self, volume: float) -> None:
        if not self.audio.set_microphone_volume(volume):
            self.log.warning("Nie można ustawić poziomu mikrofonu")
            return
        _, state = microphone_volume_topics(self.config)
        self._publish_number_state(state, volume)

    def _handle_microphone_mute(self, payload: bytes) -> None:
        try:
            muted = self.parse_switch(payload)
        except (ValueError, UnicodeDecodeError):
            self.log.warning("Nieprawidłowa komenda microphone mute")
            return
        if not self.audio.set_microphone_mute(muted):
            self.log.warning("Nie można zmienić wyciszenia mikrofonu")
            return
        _, state = microphone_mute_topics(self.config)
        self._publish_switch_state(state, muted)

    def _handle_app_mute(self, app: AudioAppConfig, payload: bytes) -> None:
        try:
            muted = self.parse_switch(payload)
        except (ValueError, UnicodeDecodeError):
            self.log.warning("Nieprawidłowa komenda mute dla %s", app.process_name)
            return
        if not self.audio.set_mute(app.process_name, muted):
            self.log.warning("Brak aktywnej sesji audio dla %s", app.process_name)
            return
        self._last_mutes[app.slug] = muted
        _, state = app_mute_topics(self.config, app)
        self._publish_switch_state(state, muted)

    def _handle_audio_output(self, payload: bytes) -> None:
        try:
            name = payload.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            return
        if not name or not self.audio.set_output_device(name):
            self.log.warning("Nie można przełączyć wyjścia audio na %s", name)
            return
        self._last_audio_output = name
        _, state = audio_output_topics(self.config)
        self._publish_text_state(state, name)
        self.log.info("Przełączono wyjście audio na %s", name)

    def _handle_audio_profile(self, payload: bytes) -> None:
        try:
            name = payload.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            return
        profile = next(
            (
                item
                for item in self.config.audio_profiles
                if item.enabled and item.name.casefold() == name.casefold()
            ),
            None,
        )
        if profile is None:
            self.log.warning("Nieznany profil audio: %s", name)
            return
        self._apply_audio_profile(profile)

    def _apply_audio_profile(self, profile: AudioProfileConfig) -> None:
        master = profile.master_volume / 100.0
        self.audio.set_master_volume(master)
        if profile.output_device:
            self.audio.set_output_device(profile.output_device)
        for process_name, volume in profile.app_volumes.items():
            self.audio.set_volume(process_name, volume / 100.0)
        self._active_audio_profile = profile.name
        _, state = audio_profile_topics(self.config)
        self._publish_text_state(state, profile.name)
        self.log.info("Zastosowano profil audio: %s", profile.name)

    def _apply_triggered_audio_profile(self, process_name: str) -> None:
        if not (
            self.config.audio_enhancements_enabled
            and self.config.audio_profiles_enabled
            and self.config.automatic_audio_profiles
        ):
            return
        profile = next(
            (
                item
                for item in self.config.audio_profiles
                if item.enabled
                and item.trigger_process
                and item.trigger_process.casefold() == process_name.casefold()
            ),
            None,
        )
        if profile is not None and profile.name != self._active_audio_profile:
            self._apply_audio_profile(profile)

    def _handle_app_action(self, action: str, app: AudioAppConfig, payload: bytes) -> None:
        if not self._is_button_press(payload):
            self.log.warning("Zignorowano nieprawidłowe naciśnięcie przycisku MQTT")
            return
        if action == "start":
            ok = self.system.start_application(
                app.executable_path,
                app.process_name,
                app.display_name,
            )
            self.log.info(
                "Uruchomiono %s z Home Assistant", app.display_name
            ) if ok else self.log.warning("Nie można uruchomić %s", app.display_name)
            return
        closed = self.system.close_application(app.process_name)
        if closed < 0:
            self.log.warning(
                "Zablokowano zdalne zamknięcie chronionego procesu %s", app.process_name
            )
        elif closed:
            self.log.info("Wysłano zamknięcie do %s procesów %s", closed, app.display_name)
        else:
            self.log.warning("Nie znaleziono uruchomionej aplikacji %s", app.display_name)

    def _handle_application_volume(self, topic: str, volume: float) -> None:
        app = self._command_apps.get(topic)
        process_name = app.process_name if app else None
        if topic == self._active_command:
            process_name = self.audio.get_active_process_name()
        if not process_name:
            return
        current = self.audio.get_volume(process_name)
        if current is None or abs(current - volume) >= 0.005:
            if not self.audio.set_volume(process_name, volume):
                self.log.warning("Brak aktywnej sesji audio dla %s", process_name)
                return
            time.sleep(0.03)
            current = self.audio.get_volume(process_name)
        actual = volume if current is None else current
        if app is None:
            self._last_active = (process_name.lower(), actual)
        else:
            self._last_volumes[app.slug] = actual
        self._publish_volume_state(app, actual)
        self.log.info("Ustawiono %s na %s%%", process_name, round(actual * 100))

    def _handle_media_command(self, payload: bytes) -> None:
        try:
            command = json.loads(payload.decode("utf-8", errors="strict"))
            action = str(command.get("action", "")).strip().lower()
            value = command.get("value")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            self.log.warning("Nieprawidłowa komenda Media Player")
            return

        if action == "set_volume":
            try:
                volume = float(value)
            except (TypeError, ValueError):
                return
            if not math.isfinite(volume):
                return
            volume = max(0.0, min(1.0, volume))
            if self.audio.set_master_volume(volume):
                self._last_media_payload = ""
            return
        if action == "mute":
            if isinstance(value, bool) and self.audio.set_master_mute(value):
                self._last_media_payload = ""
            return
        if action not in {"play", "pause", "stop", "next", "previous", "seek"}:
            self.log.warning("Nieobsługiwana komenda Media Player: %s", action)
            return
        try:
            numeric_value = float(value) if action == "seek" else None
        except (TypeError, ValueError):
            return
        if numeric_value is not None and (not math.isfinite(numeric_value) or numeric_value < 0):
            return
        if not self.media.execute(action, numeric_value):
            self.log.warning("Sesja multimedialna odrzuciła komendę %s", action)
        self._last_media_payload = ""

    def _publish_number_state(self, topic: str, value: float) -> None:
        if self.client and self._connected.is_set():
            self.client.publish(topic, str(round(value * 100)), qos=1, retain=True)

    def _publish_switch_state(self, topic: str, enabled: bool) -> None:
        if self.client and self._connected.is_set():
            self.client.publish(topic, "ON" if enabled else "OFF", qos=1, retain=True)

    def _publish_text_state(self, topic: str, value: str | float) -> None:
        if self.client and self._connected.is_set():
            self.client.publish(topic, str(value), qos=1, retain=True)

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
        client = self.client
        if client is None or not self._connected.is_set():
            return 0

        outputs = [device.name for device in self._audio_outputs]
        hardware_metrics: set[str] = set()
        if self.config.publish_cpu_stats or self.config.publish_gpu_stats:
            metrics = self.system.system_metrics(
                include_cpu=self.config.publish_cpu_stats,
                include_gpu=self.config.publish_gpu_stats,
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
            hardware_metrics.update(("pending_restart", "windows_update"))
            if health.battery_percent is not None:
                hardware_metrics.update(("battery", "ac_power"))
            if health.power_plan:
                hardware_metrics.add("power_plan")
        if self.config.publish_disk_stats:
            disks = self.system.disk_metrics()
            hardware_metrics.update(("disk_used", "disk_free", "disk_read", "disk_write"))
            if disks.health:
                hardware_metrics.add("disk_health")
            if disks.temperature is not None:
                hardware_metrics.add("disk_temperature")
        payload = integration_announcement_payload(self.config, outputs, hardware_metrics)
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
        return len(payload["entities"]) + int(self.config.media_player_enabled)

    def publish_media_announcement(self) -> None:
        """Backward-compatible alias used by older callers."""
        self.publish_discovery()

    def _publish_discovery(self) -> None:
        self.publish_discovery()

    def _monitor_loop(self) -> None:
        enabled = [app for app in self.config.apps if app.enabled]
        names = [app.process_name for app in enabled]
        next_context = 0.0
        next_system = 0.0
        next_output = 0.0
        next_process_scan = 0.0
        next_media = 0.0
        next_health = 0.0
        next_disk = 0.0
        next_devices = 0.0
        running_processes: set[str] = set()
        while not self._stop_event.wait(self.config.poll_interval):
            if not self._connected.is_set():
                continue
            try:
                if self.config.control_master_volume:
                    self._monitor_master()
                snapshot = self.audio.session_snapshot(names)
                now = time.monotonic()
                if now >= next_process_scan:
                    running_processes = self.system.running_process_names(names)
                    next_process_scan = now + 2.0
                self._monitor_apps(enabled, snapshot, running_processes)
                if self.config.control_active_app:
                    self._monitor_active(snapshot)
                if self.config.control_microphone or (
                    self.config.audio_enhancements_enabled and self.config.automatic_ducking
                ):
                    self._monitor_microphone()

                if now >= next_context and (
                    self.config.publish_activity
                    or self.config.publish_idle
                    or self.config.publish_session_lock
                ):
                    self._monitor_context()
                    next_context = now + 1.0
                if now >= next_system and (
                    self.config.publish_system_stats
                    or self.config.publish_cpu_stats
                    or self.config.publish_gpu_stats
                ):
                    self._monitor_system()
                    next_system = now + 5.0
                if now >= next_health and self.config.publish_windows_health:
                    self._monitor_windows_health()
                    next_health = now + 30.0
                if now >= next_disk and self.config.publish_disk_stats:
                    self._monitor_disks()
                    next_disk = now + 5.0
                if now >= next_devices and self.config.publish_devices:
                    self._monitor_devices()
                    next_devices = now + 10.0
                if now >= next_output and self.config.control_audio_output:
                    self._monitor_audio_output()
                    next_output = now + 3.0
                if now >= next_media and self.config.media_player_enabled:
                    self._monitor_media()
                    next_media = now + 1.0
            except Exception:
                self.log.exception("Błąd podczas odczytu stanu Windows")

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
        for app in enabled:
            state = snapshot.get(app.process_name.lower())
            running = state is not None or app.process_name.casefold() in running_processes
            if self._last_running.get(app.slug) is not running:
                self._publish_running(app, running)
                self._last_running[app.slug] = running
                if running:
                    self._apply_triggered_audio_profile(app.process_name)
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

    def _monitor_microphone(self) -> None:
        snapshot = self.audio.get_microphone_snapshot(self.config.ducking_sensitivity)
        if snapshot is None:
            return
        now = time.monotonic()
        if snapshot.active and not snapshot.muted:
            self._microphone_active_until = now + 1.25
        active = not snapshot.muted and now < self._microphone_active_until
        if self.config.audio_enhancements_enabled and self.config.automatic_ducking:
            self._apply_automatic_ducking(active)
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
        )
        values: dict[str, float | int | str | None] = {}
        if self.config.publish_system_stats or self.config.publish_cpu_stats:
            values["cpu"] = round(metrics.cpu_percent, 1)
        if self.config.publish_system_stats:
            values.update(
                {
                    "ram": round(metrics.ram_percent, 1),
                    "uptime": metrics.uptime_seconds,
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
            self._publish_text_state(system_metric_topic(self.config, "power_plan"), health.power_plan)
        self._publish_text_state(
            system_metric_topic(self.config, "windows_update"),
            health.windows_update_status,
        )

    def _monitor_disks(self) -> None:
        metrics = self.system.disk_metrics()
        values = {
            "disk_used": round(metrics.used_percent, 1),
            "disk_free": round(metrics.free_gb, 1),
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
                self._publish_switch_state(tracked_device_topic(self.config, device.slug), connected)

    def _apply_automatic_ducking(self, active: bool) -> None:
        apps = [app for app in self.config.apps if app.enabled]
        if active and not self._ducked_volumes:
            snapshot = self.audio.session_snapshot([app.process_name for app in apps])
            target = self.config.ducking_volume / 100.0
            for app in apps:
                state = snapshot.get(app.process_name.casefold())
                if state is None or state.volume <= target:
                    continue
                self._ducked_volumes[app.process_name] = state.volume
                self.audio.set_volume(app.process_name, target)
        elif not active and self._ducked_volumes:
            for process_name, volume in self._ducked_volumes.items():
                self.audio.set_volume(process_name, volume)
            self._ducked_volumes.clear()

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
            if self.client and self._connected.is_set():
                serialized_artwork = (
                    json.dumps(artwork_payload, separators=(",", ":"))
                    if artwork_payload is not None
                    else ""
                )
                self.client.publish(
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
        if self.client and self._connected.is_set():
            _, state_topic = media_topics(self.config)
            self.client.publish(state_topic, payload, qos=1, retain=True)

    def _publish_running(self, app: AudioAppConfig, running: bool) -> None:
        self._publish_switch_state(app_running_topic(self.config, app), running)

    def _publish_active_app(self, process_name: str) -> None:
        self._publish_text_state(active_app_topic(self.config), process_name)

    def _emit_status(self, text: str, connected: bool) -> None:
        if self.status_callback:
            self.status_callback(text, connected)
