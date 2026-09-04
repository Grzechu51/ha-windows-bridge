"""Validated application commands; no MQTT, Qt or Windows imports."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 2
MAX_COMMAND_BYTES = 768 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
COMMAND_KIND = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")


def reject_constant(_value):
    raise ValueError("Non-finite JSON number")


class CommandError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Command:
    id: str
    kind: str
    target: str
    arguments: dict[str, Any] = field(repr=False)
    expires_at: float

    @classmethod
    def parse(cls, payload: bytes, *, retained: bool = False, now: float | None = None) -> Command:
        if retained:
            raise CommandError("retained_command")
        if not payload or len(payload) > MAX_COMMAND_BYTES:
            raise CommandError("payload_size")
        try:
            value = json.loads(payload.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeError, ValueError, RecursionError):
            raise CommandError("invalid_json") from None
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != PROTOCOL_VERSION:
            raise CommandError("protocol_version")
        if set(value) - {"version", "id", "kind", "target", "arguments", "issued_at", "ttl_ms"}:
            raise CommandError("unknown_field")
        identifier, kind = value.get("id"), value.get("kind")
        target, arguments = value.get("target", ""), value.get("arguments", {})
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise CommandError("command_id")
        if not isinstance(kind, str) or not COMMAND_KIND.fullmatch(kind):
            raise CommandError("command_kind")
        if not isinstance(target, str) or (target and not IDENTIFIER.fullmatch(target)):
            raise CommandError("command_target")
        if not isinstance(arguments, dict):
            raise CommandError("command_arguments")
        issued, ttl = value.get("issued_at"), value.get("ttl_ms", 10000)
        if type(issued) not in {int, float} or not math.isfinite(issued):
            raise CommandError("issued_at")
        if type(ttl) is not int or not 100 <= ttl <= 60000:
            raise CommandError("ttl")
        now = time.time() if now is None else now
        deadline = issued + ttl / 1000
        if issued > now + 30:
            raise CommandError("clock_skew")
        if deadline <= now:
            raise CommandError("expired")
        return cls(identifier, kind, target, arguments, deadline)

    def fingerprint(self) -> str:
        # Command identity includes intent, not retry timestamp/TTL.
        import hashlib
        intent = json.dumps([self.kind, self.target, self.arguments], sort_keys=True, allow_nan=False, separators=(",", ":"))
        return hashlib.sha256(intent.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CommandResult:
    id: str
    status: str
    code: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> str:
        return json.dumps({"version": PROTOCOL_VERSION, "id": self.id, "status": self.status,
                           "error": self.code or None, "data": self.data}, allow_nan=False)
