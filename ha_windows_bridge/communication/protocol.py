"""Decode wire messages into application commands; all route permissions are explicit."""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass

from .. import discovery as topics
from ..config import AppConfig
from ..core.commands import MAX_COMMAND_BYTES, Command, CommandError, reject_constant
from ..media_protocol import media_topics


@dataclass(frozen=True)
class Route:
    kind: str
    target: str = ""
    parser: str = "value"


def number(value, minimum=0.0, maximum=1.0):
    if isinstance(value, bool):
        raise CommandError("invalid_number")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise CommandError("invalid_number") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise CommandError("number_out_of_range")
    return result


def legacy_volume(text: str) -> float:
    value = number(text, 0, 100)
    fraction = 0 < value < 1 or (value == 1 and ("." in text or "e" in text.lower()))
    return value if fraction else value / 100


class TopicProtocol:
    def __init__(self, config: AppConfig):
        self.command_topic = f"{config.mqtt.base_topic}/v2/command"
        self.result_topic = f"{config.mqtt.base_topic}/v2/result"
        self.birth_topic = f"{config.mqtt.discovery_prefix}/status"
        self.routes: dict[str, Route] = {}
        def add(topic_pair, kind, parser="value", target=""):
            topic = topic_pair[0] if isinstance(topic_pair, tuple) else topic_pair
            self.routes[topic] = Route(kind, target, parser)
        if config.control_master_volume:
            add(topics.master_volume_topics(config), "audio.master.volume", "volume")
            add(topics.master_mute_topics(config), "audio.master.mute", "switch")
            if config.audio_enhancements_enabled and config.control_channel_balance:
                add(topics.master_balance_topics(config), "audio.master.balance", "balance")
        if config.control_microphone:
            add(topics.microphone_volume_topics(config), "audio.microphone.volume", "volume")
            add(topics.microphone_mute_topics(config), "audio.microphone.mute", "switch")
        if config.control_audio_output:
            add(topics.audio_output_topics(config), "audio.output")
        if config.control_active_app:
            add(topics.active_volume_topics(config), "audio.active.volume", "volume")
        for app in config.apps:
            if not app.enabled:
                continue
            add(topics.app_volume_topics(config, app), "application.volume", "volume", app.slug)
            add(topics.app_mute_topics(config, app), "application.mute", "switch", app.slug)
            if app.allow_remote_start and app.executable_path:
                add(topics.app_start_topic(config, app), "application.start", "button", app.slug)
            if app.allow_remote_close:
                add(topics.app_close_topic(config, app), "application.close", "button", app.slug)
        if config.allow_power_actions:
            for action in ("lock", "sleep", "restart", "shutdown", "cancel"):
                add(topics.power_action_topic(config, action), "power." + action, "button")
        if config.media_player_enabled:
            add(media_topics(config), "media.control", "json")
        if config.overlay_enabled:
            add(topics.overlay_notification_topic(config), "overlay.show", "json")
            add(topics.overlay_monitor_topics(config), "overlay.monitor")
        if config.enable_windows_notifications:
            add(topics.windows_notification_topic(config), "notification.show", "json")

    @property
    def subscriptions(self) -> set[str]:
        return {*self.routes, self.command_topic, self.birth_topic}

    def decode(self, topic: str, payload: bytes, retained: bool = False) -> Command:
        if topic == self.command_topic:
            return Command.parse(payload, retained=retained)
        if retained:
            raise CommandError("retained_command")
        route = self.routes.get(topic)
        if route is None:
            raise CommandError("not_allowed")
        limit = MAX_COMMAND_BYTES if route.kind == "overlay.show" else 8192
        if len(payload) > limit:
            raise CommandError("payload_size")
        try:
            text = payload.decode("utf-8").strip()
            if route.parser == "json":
                arguments = json.loads(text, parse_constant=reject_constant)
                if not isinstance(arguments, dict):
                    raise CommandError("command_arguments")
            elif route.parser == "volume":
                arguments = {"value": legacy_volume(text)}
            elif route.parser == "balance":
                arguments = {"value": number(text, -100, 100) / 100}
            elif route.parser == "switch":
                if text.lower() not in {"on", "off", "1", "0", "true", "false", "yes", "no"}:
                    raise CommandError("invalid_switch")
                arguments = {"value": text.lower() in {"on", "1", "true", "yes"}}
            elif route.parser == "button":
                if text != "PRESS":
                    raise CommandError("invalid_button")
                arguments = {}
            else:
                arguments = {"value": text}
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise CommandError(exc.code if isinstance(exc, CommandError) else "invalid_payload") from None
        return Command(uuid.uuid4().hex, route.kind, route.target, arguments, time.time() + 10)
