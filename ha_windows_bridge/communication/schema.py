"""Protocol v3 domain messages shared semantically by Windows and Home Assistant."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

PROTOCOL_VERSION = 3
MAX_CONTROL_BYTES = 64 * 1024
MAX_NORMAL_COMMAND_BYTES = 32 * 1024
MAX_COMMAND_BYTES = 768 * 1024
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
COMMAND_KIND = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
RESULT_STATUSES = frozenset(
    {"accepted", "pending", "succeeded", "failed", "rejected", "cancelled"}
)


class ProtocolError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _load(payload: str | bytes, limit: int) -> dict[str, Any]:
    if not isinstance(payload, (str, bytes)):
        raise ProtocolError("invalid_payload")
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not raw or len(raw) > limit:
        raise ProtocolError("payload_size")
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ProtocolError("invalid_json") from None
    if not isinstance(value, dict):
        raise ProtocolError("message_object")
    return value


def _dump(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
    except (TypeError, ValueError, RecursionError):
        raise ProtocolError("invalid_content") from None


def _base(value: dict[str, Any], message_type: str) -> tuple[str, str, dict[str, Any]]:
    if type(value.get("version")) is not int or value["version"] != PROTOCOL_VERSION:
        raise ProtocolError("protocol_version")
    if value.get("type") != message_type:
        raise ProtocolError("message_type")
    identifier = value.get("id")
    session = value.get("session")
    if not isinstance(identifier, str) or IDENTIFIER.fullmatch(identifier) is None:
        raise ProtocolError("message_id")
    if not isinstance(session, str) or IDENTIFIER.fullmatch(session) is None:
        raise ProtocolError("session")
    return identifier, session, value


def _device(value: Any) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ProtocolError("device_id")
    return value


def _revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ProtocolError("revision")
    return value


def _timestamp(value: Any, code: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ProtocolError(code)
    return float(value)


def _object(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(code)
    return dict(value)


def _extras(value: dict[str, Any], known: set[str]) -> dict[str, Any]:
    # Protocol v3 is additive: unknown fields are retained for a forwarding hop.
    return {key: item for key, item in value.items() if key not in known}


def legacy_arguments(parser: str, payload: str) -> dict[str, Any]:
    """Temporary v2 route payload adapter, shared by both deployed runtimes."""
    try:
        if parser == "json":
            value = json.loads(payload, parse_constant=_reject_constant)
            if not isinstance(value, dict):
                raise ProtocolError("command_arguments")
            return value
        if parser in {"volume", "balance"}:
            value = float(payload)
            if not math.isfinite(value):
                raise ProtocolError("invalid_number")
            if parser == "balance":
                if not -100 <= value <= 100:
                    raise ProtocolError("number_out_of_range")
                return {"value": value / 100}
            if not 0 <= value <= 100:
                raise ProtocolError("number_out_of_range")
            fraction = 0 < value < 1 or (
                value == 1 and ("." in payload or "e" in payload.lower())
            )
            return {"value": value if fraction else value / 100}
        if parser == "switch":
            lowered = payload.lower()
            if lowered not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:
                raise ProtocolError("invalid_switch")
            return {"value": lowered in {"on", "true", "1", "yes"}}
        if parser == "button":
            if payload != "PRESS":
                raise ProtocolError("invalid_button")
            return {}
        return {"value": payload}
    except ProtocolError:
        raise
    except (ValueError, TypeError, RecursionError):
        raise ProtocolError("invalid_payload") from None


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    transports: tuple[str, ...]
    permission: str = "control"
    options: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> Capability:
        if not isinstance(value, dict):
            raise ProtocolError("capability")
        name = value.get("name")
        transports = value.get("transports")
        permission = value.get("permission", "control")
        if not isinstance(name, str) or COMMAND_KIND.fullmatch(name) is None:
            raise ProtocolError("capability_name")
        if (
            not isinstance(transports, list)
            or not transports
            or len(transports) > 2
            or any(item not in {"mqtt", "direct"} for item in transports)
            or len(set(transports)) != len(transports)
        ):
            raise ProtocolError("capability_transports")
        if permission not in {"control", "read"}:
            raise ProtocolError("capability_permission")
        options = _object(value.get("options", {}), "capability_options")
        return cls(
            name,
            tuple(transports),
            permission,
            options,
            _extras(value, {"name", "transports", "permission", "options"}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extensions,
            "name": self.name,
            "transports": list(self.transports),
            "permission": self.permission,
            "options": self.options,
        }


@dataclass(frozen=True, slots=True)
class CapabilitiesMessage:
    id: str
    session: str
    device_id: str
    revision: int
    capabilities: tuple[Capability, ...]
    extensions: dict[str, Any] = field(default_factory=dict)
    type: ClassVar[str] = "capabilities"

    @classmethod
    def decode(cls, payload: str | bytes) -> CapabilitiesMessage:
        value = _load(payload, MAX_CONTROL_BYTES)
        identifier, session, value = _base(value, cls.type)
        protocol = value.get("protocol")
        if not isinstance(protocol, dict) or protocol.get("min") != 3 or protocol.get("max") != 3:
            raise ProtocolError("protocol_range")
        raw = value.get("capabilities")
        if not isinstance(raw, list) or len(raw) > 512:
            raise ProtocolError("capabilities")
        capabilities = tuple(Capability.from_dict(item) for item in raw)
        names = [item.name for item in capabilities]
        if len(names) != len(set(names)):
            raise ProtocolError("duplicate_capability")
        known = {"version", "type", "id", "session", "device_id", "revision", "protocol", "capabilities"}
        return cls(identifier, session, _device(value.get("device_id")),
                   _revision(value.get("revision")), capabilities, _extras(value, known))

    def to_dict(self) -> dict[str, Any]:
        return {**self.extensions, "version": 3, "type": self.type, "id": self.id,
                "session": self.session, "device_id": self.device_id,
                "revision": self.revision, "protocol": {"min": 3, "max": 3},
                "capabilities": [item.to_dict() for item in self.capabilities]}

    def encode(self) -> str:
        payload = _dump(self.to_dict())
        type(self).decode(payload)
        return payload


@dataclass(frozen=True, slots=True)
class SnapshotMessage:
    id: str
    session: str
    device_id: str
    revision: int
    observed_at: float
    state: dict[str, Any]
    quality: dict[str, Any]
    extensions: dict[str, Any] = field(default_factory=dict)
    type: ClassVar[str] = "snapshot"

    @classmethod
    def decode(cls, payload: str | bytes) -> SnapshotMessage:
        value = _load(payload, MAX_CONTROL_BYTES)
        identifier, session, value = _base(value, cls.type)
        known = {"version", "type", "id", "session", "device_id", "revision", "observed_at", "state", "quality"}
        return cls(identifier, session, _device(value.get("device_id")),
                   _revision(value.get("revision")),
                   _timestamp(value.get("observed_at"), "observed_at"),
                   _object(value.get("state"), "state"),
                   _object(value.get("quality", {}), "quality"), _extras(value, known))

    def to_dict(self) -> dict[str, Any]:
        return {**self.extensions, "version": 3, "type": self.type, "id": self.id,
                "session": self.session, "device_id": self.device_id,
                "revision": self.revision, "observed_at": self.observed_at,
                "state": self.state, "quality": self.quality}

    def encode(self) -> str:
        payload = _dump(self.to_dict())
        type(self).decode(payload)
        return payload


@dataclass(frozen=True, slots=True)
class CommandMessage:
    id: str
    session: str
    device_id: str
    kind: str
    target: str
    arguments: dict[str, Any]
    issued_at: float
    ttl_ms: int
    extensions: dict[str, Any] = field(default_factory=dict)
    type: ClassVar[str] = "command"

    @classmethod
    def decode(cls, payload: str | bytes, *, retained: bool = False) -> CommandMessage:
        if retained:
            raise ProtocolError("retained_command")
        value = _load(payload, MAX_COMMAND_BYTES)
        identifier, session, value = _base(value, cls.type)
        kind, target = value.get("kind"), value.get("target", "")
        if not isinstance(kind, str) or COMMAND_KIND.fullmatch(kind) is None:
            raise ProtocolError("command_kind")
        raw_size = len(payload.encode("utf-8")) if isinstance(payload, str) else len(payload)
        if kind != "overlay.show" and raw_size > MAX_NORMAL_COMMAND_BYTES:
            raise ProtocolError("payload_size")
        if not isinstance(target, str) or (target and IDENTIFIER.fullmatch(target) is None):
            raise ProtocolError("command_target")
        ttl = value.get("ttl_ms")
        if type(ttl) is not int or not 100 <= ttl <= 60_000:
            raise ProtocolError("ttl")
        known = {"version", "type", "id", "session", "device_id", "kind", "target", "arguments", "issued_at", "ttl_ms"}
        return cls(identifier, session, _device(value.get("device_id")), kind, target,
                   _object(value.get("arguments", {}), "command_arguments"),
                   _timestamp(value.get("issued_at"), "issued_at"), ttl, _extras(value, known))

    def to_dict(self) -> dict[str, Any]:
        return {**self.extensions, "version": 3, "type": self.type, "id": self.id,
                "session": self.session, "device_id": self.device_id, "kind": self.kind,
                "target": self.target, "arguments": self.arguments,
                "issued_at": self.issued_at, "ttl_ms": self.ttl_ms}

    def encode(self) -> str:
        payload = _dump(self.to_dict())
        type(self).decode(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ResultMessage:
    id: str
    session: str
    device_id: str
    status: str
    code: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    type: ClassVar[str] = "result"

    @classmethod
    def decode(cls, payload: str | bytes) -> ResultMessage:
        value = _load(payload, MAX_CONTROL_BYTES)
        identifier, session, value = _base(value, cls.type)
        status, code = value.get("status"), value.get("code", "")
        if status not in RESULT_STATUSES:
            raise ProtocolError("result_status")
        if not isinstance(code, str) or len(code) > 64:
            raise ProtocolError("result_code")
        known = {"version", "type", "id", "session", "device_id", "status", "code", "data"}
        return cls(identifier, session, _device(value.get("device_id")), status, code,
                   _object(value.get("data", {}), "result_data"), _extras(value, known))

    def to_dict(self) -> dict[str, Any]:
        return {**self.extensions, "version": 3, "type": self.type, "id": self.id,
                "session": self.session, "device_id": self.device_id,
                "status": self.status, "code": self.code, "data": self.data}

    def encode(self) -> str:
        payload = _dump(self.to_dict())
        type(self).decode(payload)
        return payload


MESSAGE_TYPES = {
    CapabilitiesMessage.type: CapabilitiesMessage,
    SnapshotMessage.type: SnapshotMessage,
    CommandMessage.type: CommandMessage,
    ResultMessage.type: ResultMessage,
}


def decode_message(payload: str | bytes):
    value = _load(payload, MAX_COMMAND_BYTES)
    message_type = value.get("type")
    decoder = MESSAGE_TYPES.get(message_type)
    if decoder is None:
        raise ProtocolError("message_type")
    return decoder.decode(payload)
