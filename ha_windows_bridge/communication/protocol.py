"""Protocol v3 routing plus the deliberately isolated legacy compatibility edge."""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass

from .. import discovery as topics
from ..config import AppConfig
from ..core.commands import Command, CommandError, CommandResult, reject_constant
from ..media_protocol import media_topics
from .schema import (
    CapabilitiesMessage,
    Capability,
    CommandMessage,
    ProtocolError,
    ResultMessage,
    SnapshotMessage,
    legacy_arguments,
)

LEGACY_PROTOCOL_VERSION = 2
LEGACY_COMMAND_BYTES = 768 * 1024


@dataclass(frozen=True)
class Route:
    kind: str
    target: str = ""
    parser: str = "value"


@dataclass(frozen=True, slots=True)
class ReplyContext:
    protocol_version: int
    session: str
    result_topic: str


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


class LegacyProtocolAdapter:
    """Translate v2/entity commands at the edge; never expose legacy internally."""

    def __init__(self, command_topic: str, routes: dict[str, Route], *, clock=time.time,
                 monotonic_clock=time.monotonic):
        self.command_topic, self.routes, self._clock = command_topic, routes, clock
        self._monotonic_clock = monotonic_clock

    def decode(self, topic: str, payload: bytes, retained: bool) -> Command:
        if retained:
            raise CommandError("retained_command")
        if topic == self.command_topic:
            return self._envelope(payload)
        route = self.routes.get(topic)
        if route is None:
            raise CommandError("not_allowed")
        limit = LEGACY_COMMAND_BYTES if route.kind == "overlay.show" else 8192
        if not payload or len(payload) > limit:
            raise CommandError("payload_size")
        arguments = self._arguments(route.parser, payload)
        if route.parser in {"button", "json"}:
            raise CommandError("legacy_command_id_required")
        now = self._clock()
        # Entity setters have no retry identity. Every frame is a new,
        # idempotent set operation; effectful commands require an envelope ID.
        identifier = "legacy-" + uuid.uuid4().hex
        return Command(identifier, route.kind, route.target, arguments, now + 10,
                       session="legacy-v2", monotonic_expires_at=self._monotonic_clock() + 10)

    def _envelope(self, payload: bytes) -> Command:
        if not payload or len(payload) > LEGACY_COMMAND_BYTES:
            raise CommandError("payload_size")
        try:
            value = json.loads(payload.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeError, ValueError, RecursionError):
            raise CommandError("invalid_json") from None
        allowed = {"version", "id", "kind", "target", "arguments", "issued_at", "ttl_ms"}
        if not isinstance(value, dict) or value.get("version") != LEGACY_PROTOCOL_VERSION:
            raise CommandError("protocol_version")
        if set(value) - allowed:
            raise CommandError("unknown_field")
        identifier, kind = value.get("id"), value.get("kind")
        target, arguments = value.get("target", ""), value.get("arguments", {})
        from ..core.commands import COMMAND_KIND, IDENTIFIER
        if not isinstance(identifier, str) or IDENTIFIER.fullmatch(identifier) is None:
            raise CommandError("command_id")
        if not isinstance(kind, str) or COMMAND_KIND.fullmatch(kind) is None:
            raise CommandError("command_kind")
        if not isinstance(target, str) or (target and IDENTIFIER.fullmatch(target) is None):
            raise CommandError("command_target")
        if not isinstance(arguments, dict):
            raise CommandError("command_arguments")
        issued, ttl = value.get("issued_at"), value.get("ttl_ms", 10_000)
        if type(issued) not in {int, float} or not math.isfinite(issued):
            raise CommandError("issued_at")
        if type(ttl) is not int or not 100 <= ttl <= 60_000:
            raise CommandError("ttl")
        now, deadline = self._clock(), issued + ttl / 1000
        if issued > now + 30:
            raise CommandError("clock_skew")
        if deadline <= now:
            raise CommandError("expired")
        return Command(identifier, kind, target, arguments, deadline, session="legacy-v2",
                       monotonic_expires_at=self._monotonic_clock() + deadline - now)

    @staticmethod
    def _arguments(parser: str, payload: bytes) -> dict:
        try:
            text = payload.decode("utf-8").strip()
            return legacy_arguments(parser, text)
        except (UnicodeError, ProtocolError) as exc:
            raise CommandError(exc.code if isinstance(exc, ProtocolError) else "invalid_payload") from None


class TopicProtocol:
    """Device/session-scoped v3 contract with explicit transport capabilities."""

    def __init__(self, config: AppConfig, *, session: str | None = None, clock=time.time,
                 monotonic_clock=time.monotonic):
        prefix = config.mqtt.base_topic
        self.device_id = config.device_id
        self.session = session or uuid.uuid4().hex
        self.command_topic = f"{prefix}/v3/command"
        self.result_topic = f"{prefix}/v3/result"
        self.capabilities_topic = f"{prefix}/v3/capabilities"
        self.snapshot_topic = f"{prefix}/v3/snapshot"
        self.legacy_command_topic = f"{prefix}/v2/command"
        self.legacy_result_topic = f"{prefix}/v2/result"
        self.birth_topic = f"{config.mqtt.discovery_prefix}/status"
        self._clock = clock
        self._monotonic_clock = monotonic_clock
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
        self.legacy = LegacyProtocolAdapter(
            self.legacy_command_topic,
            self.routes,
            clock=clock,
            monotonic_clock=monotonic_clock,
        )

    @property
    def subscriptions(self) -> set[str]:
        return {*self.routes, self.command_topic, self.legacy_command_topic, self.birth_topic}

    def decode(self, topic: str, payload: bytes, retained: bool = False) -> Command:
        if topic != self.command_topic:
            return self.legacy.decode(topic, payload, retained)
        try:
            message = CommandMessage.decode(payload, retained=retained)
        except ProtocolError as exc:
            raise CommandError(exc.code) from None
        if message.device_id != self.device_id:
            raise CommandError("wrong_device")
        if message.session != self.session:
            raise CommandError("stale_session")
        now = self._clock()
        deadline = message.issued_at + message.ttl_ms / 1000
        if message.issued_at > now + 30:
            raise CommandError("clock_skew")
        if deadline <= now:
            raise CommandError("expired")
        return Command(message.id, message.kind, message.target, message.arguments,
                       deadline, session=message.session, device_id=message.device_id,
                       monotonic_expires_at=self._monotonic_clock() + deadline - now)

    def decode_inbound(
        self, topic: str, payload: bytes, retained: bool = False
    ) -> tuple[Command, ReplyContext]:
        command = self.decode(topic, payload, retained)
        if topic == self.command_topic:
            context = ReplyContext(3, command.session, self.result_topic)
        else:
            context = ReplyContext(2, command.session or "legacy-v2", self.legacy_result_topic)
        return command, context

    def encode_result(
        self, result: CommandResult, context: ReplyContext
    ) -> tuple[str, str]:
        if context.protocol_version == LEGACY_PROTOCOL_VERSION:
            payload = json.dumps(
                {
                    "version": LEGACY_PROTOCOL_VERSION,
                    "id": result.id,
                    "status": result.status,
                    "code": result.code,
                    "data": result.data,
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            return context.result_topic, payload
        return context.result_topic, self.result(result).encode()

    def capabilities(self) -> CapabilitiesMessage:
        grouped: dict[str, dict] = {}
        for route in self.routes.values():
            item = grouped.setdefault(route.kind, {"targets": set(), "parsers": set()})
            if route.target:
                item["targets"].add(route.target)
            item["parsers"].add(route.parser)
        capabilities = []
        for kind, options in sorted(grouped.items()):
            transports = ("mqtt", "direct") if kind == "overlay.show" else ("mqtt",)
            capabilities.append(Capability(kind, transports, options={
                "targets": sorted(options["targets"]), "parsers": sorted(options["parsers"])
            }))
        return CapabilitiesMessage("capabilities-" + self.session, self.session,
                                   self.device_id, 1, tuple(capabilities))

    def snapshot(self, state) -> SnapshotMessage:
        master = state.master_audio
        values = {}
        if master is not None:
            values["master_audio"] = {
                "volume": master.volume, "muted": master.muted,
                "observed_at": master.observed_at,
            }
        quality = {
            item.source: {"quality": item.quality.value, "checked_at": item.checked_at,
                          "last_success_at": item.last_success_at, "detail": item.detail}
            for item in state.health
        }
        return SnapshotMessage("snapshot-" + str(state.revision), self.session,
                               self.device_id, state.revision, state.updated_at,
                               values, quality)

    def result(self, result: CommandResult) -> ResultMessage:
        return ResultMessage(result.id, self.session, self.device_id,
                             result.status, result.code, result.data)
