"""Remote security boundary: only configured capabilities and application identities."""
from __future__ import annotations

import base64
from dataclasses import replace

from ..communication.protocol import number
from ..core.commands import Command, CommandError
from ..overlays.monitors import monitor_id_from_label, selected_monitor_label


class WindowsCommands:
    def __init__(
        self,
        config,
        audio,
        system,
        media,
        power,
        events,
        monitors,
        *,
        master_audio=None,
        notifications=None,
    ):
        self.config, self.audio, self.system = config, audio, system
        self.master_audio = master_audio
        self.media, self.power, self.events = media, power, events
        self.monitors = monitors
        self.notifications = notifications

    def install(self, router):
        c = self.config
        enabled = {
            "audio.master.volume": c.control_master_volume,
            "audio.master.mute": c.control_master_volume,
            "audio.master.balance": c.control_master_volume and c.audio_enhancements_enabled and c.control_channel_balance,
            "audio.microphone.volume": c.control_microphone,
            "audio.microphone.mute": c.control_microphone,
            "audio.output": c.control_audio_output,
            "audio.active.volume": c.control_active_app,
            "media.control": c.media_player_enabled,
            "overlay.show": c.overlay_enabled,
            "overlay.monitor": c.overlay_enabled,
            "notification.show": c.enable_windows_notifications,
        }
        for kind, allowed in enabled.items():
            if allowed:
                router.register(
                    kind,
                    self.execute,
                    prepare=(
                        self._bind_media_target
                        if kind == "media.control"
                        else None
                    ),
                )
        if any(app.enabled for app in c.apps):
            for kind in ("application.volume", "application.mute", "application.start", "application.close"):
                router.register(kind, self.execute)
        if c.allow_power_actions:
            for action in ("lock", "sleep", "restart", "shutdown", "cancel"):
                router.register("power." + action, self.execute)

    @staticmethod
    def _bool(value):
        if not isinstance(value, bool):
            raise CommandError("invalid_boolean")
        return value

    @staticmethod
    def _success(value):
        if not value:
            raise CommandError("device_rejected")

    def execute(self, command: Command):
        kind, value = command.kind, command.arguments.get("value")
        if kind.startswith("application."):
            app = next((app for app in self.config.apps if app.enabled and app.slug == command.target), None)
            if app is None:
                raise CommandError("unknown_application")
            if kind == "application.volume":
                self._success(self.audio.set_volume(app.process_name, number(value)))
            elif kind == "application.mute":
                self._success(self.audio.set_mute(app.process_name, self._bool(value)))
            elif kind == "application.start":
                if not app.allow_remote_start or not app.executable_path:
                    raise CommandError("not_allowed")
                self._success(self.system.start_application(app.executable_path, app.process_name, app.display_name))
            elif kind == "application.close":
                if not app.allow_remote_close:
                    raise CommandError("not_allowed")
                if self.system.close_application(app.process_name) < 0:
                    raise CommandError("protected_process")
        elif kind == "audio.master.volume":
            self._success(self._master_audio().set_master_volume(number(value)))
        elif kind == "audio.master.mute":
            self._success(self._master_audio().set_master_mute(self._bool(value)))
        elif kind == "audio.master.balance":
            self._success(self._master_audio().set_master_balance(number(value, -1, 1)))
        elif kind == "audio.microphone.volume":
            self._success(self.audio.set_microphone_volume(number(value)))
        elif kind == "audio.microphone.mute":
            self._success(self.audio.set_microphone_mute(self._bool(value)))
        elif kind == "audio.active.volume":
            process = self.audio.get_active_process_name()
            if not process:
                raise CommandError("no_active_application")
            self._success(self.audio.set_volume(process, number(value)))
        elif kind == "audio.output":
            if not isinstance(value, str) or value not in {device.name for device in self.audio.list_output_devices()}:
                raise CommandError("unknown_audio_output")
            self._success(self.audio.set_output_device(value))
        elif kind.startswith("power."):
            ok, _detail = self.power.execute(kind.removeprefix("power."))
            self._success(ok)
        elif kind == "media.control":
            action = command.arguments.get("action")
            if action == "set_volume":
                self._success(self._master_audio().set_master_volume(number(value)))
            elif action == "mute":
                self._success(self._master_audio().set_master_mute(self._bool(value)))
            elif action in {"play", "pause", "stop", "next", "previous", "seek"}:
                self._success(
                    self.media.execute(
                        action,
                        number(value, 0, 86400) if action == "seek" else None,
                        session_id=command.target,
                    )
                )
            else:
                raise CommandError("not_allowed")
        elif kind == "overlay.monitor":
            if value not in self.monitors:
                raise CommandError("unknown_monitor")
            self.config.overlay_monitor = self.monitors.index(value)
            self.config.overlay_monitor_id = monitor_id_from_label(value)
            self.events.emit("overlay.monitor_changed", self.config.overlay_monitor)
        elif kind in {"overlay.show", "notification.show"}:
            return self._notification(command)
        else:
            raise CommandError("not_allowed")
        return {"applied": True}

    def _bind_media_target(self, command: Command) -> Command:
        if command.arguments.get("action") not in {
            "play",
            "pause",
            "stop",
            "next",
            "previous",
            "seek",
        }:
            return command
        if command.target:
            return command
        snapshot = self.media.snapshot()
        if not snapshot.supported or not snapshot.session_id:
            raise CommandError("media_session_unavailable")
        return replace(command, target=snapshot.session_id)

    def _master_audio(self):
        if self.master_audio is None:
            raise CommandError("unavailable")
        return self.master_audio

    def _notification(self, command):
        value = command.arguments
        data = value.get("data", {})
        if not isinstance(data, dict):
            raise CommandError("notification_arguments")
        data = dict(data)
        action = data.get("action", "show")
        if action not in {"show", "update", "remove", "clear"}:
            raise CommandError("notification_action")
        for field, limit in (("title", 128), ("message", 2048)):
            if field in value and (
                not isinstance(value[field], str) or len(value[field]) > limit
            ):
                raise CommandError("notification_arguments")
        title = value.get("title", "Home Assistant" if action == "show" else None)
        message = value.get("message", "" if action == "show" else None)
        if action == "show":
            data["media_controls"] = False
            data["media_live"] = False
        if command.kind == "overlay.show" and action in {"show", "update"}:
            context = self.system.context_snapshot()
            if context.locked or (context.fullscreen and not self.config.overlay_allow_fullscreen):
                raise CommandError("presentation_suppressed")
        if data.get("media") and command.kind == "overlay.show":
            snapshot = self.media.snapshot()
            if snapshot.supported:
                title = snapshot.title or title
                message = " · ".join(part for part in (snapshot.artist, snapshot.album_title) if part) or message
                data.update(layout="media", media_source=self.config.device_name, media_position=snapshot.position,
                            media_duration=snapshot.duration, media_playing=snapshot.state == "playing",
                            media_controls=self.config.media_player_enabled, media_live=True)
                if snapshot.artwork.data and len(snapshot.artwork.data) <= 512 * 1024:
                    data["image"] = f"data:{snapshot.artwork.content_type};base64," + base64.b64encode(snapshot.artwork.data).decode()
        if action == "show":
            data.setdefault("monitor", self.config.overlay_monitor)
        if action == "show" and self.monitors:
            selected = selected_monitor_label(
                self.monitors, self.config.overlay_monitor_id,
                self.config.overlay_monitor,
            )
            data.setdefault("monitor_id", monitor_id_from_label(selected))
        payload = {"data": data}
        if title is not None:
            payload["title"] = title
        if message is not None:
            payload["message"] = message
        if command.kind == "overlay.show" and self.notifications is not None:
            from ..overlays.models import NotificationCommand

            request = NotificationCommand.parse(
                payload,
                source=command.transport or "local",
                command_id=command.id,
                session=command.session,
                device_id=command.device_id,
                default_monitor=self.config.overlay_monitor,
            )
            result = self.notifications.submit(request)
            if not result.accepted:
                self.events.emit("overlay.wakeup", {
                    "notification_id": result.notification_id,
                })
                raise CommandError(result.reason.value)
            self.events.emit("overlay.wakeup", {
                "notification_id": result.notification_id,
            })
            return {
                "delivery": result.disposition.value,
                "notification_id": result.notification_id,
                "reason": result.reason.value,
            }
        self.events.emit(command.kind, payload)
        return {"delivery": "queued_for_presentation"}
