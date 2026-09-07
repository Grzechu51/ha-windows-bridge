"""Entry-owned command acknowledgements and live Direct HA availability."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .protocol import (
    CapabilitiesMessage,
    CommandMessage,
    ProtocolError,
    ResultMessage,
    SnapshotMessage,
    legacy_arguments,
)


def command_arguments(parser: str, payload: str) -> dict:
    try:
        return legacy_arguments(parser, payload)
    except ProtocolError:
        raise HomeAssistantError("Invalid legacy command payload") from None


@dataclass
class BridgeRuntime:
    hass: Any
    device_id: str
    unique_ids: set[str]
    overlay_unique_id: str
    overlay_topic: str
    overlay_event_type: str
    protocol: dict = field(default_factory=dict)
    available: bool = False
    listeners: set = field(default_factory=set)
    pending: dict = field(default_factory=dict)
    _direct_pending: set = field(default_factory=set)
    _unsubscribe: list = field(default_factory=list)
    _deadline_cancel: Any = None
    _closed: bool = False
    owner: Any = None
    _direct_sender: Any = None
    _direct_session: str = ""
    capabilities: Any = None
    snapshot: Any = None
    _snapshot_revision: int = -1
    _capabilities_revision: int = -1
    command_attempt_timeout: float = 5.0

    async def start(self):
        if not self.overlay_event_type and self.protocol:
            self._unsubscribe.append(await mqtt.async_subscribe(self.hass, self.protocol["result_topic"], self._mqtt_result, qos=1))
            if self.protocol.get("version") == 3:
                self._unsubscribe.append(await mqtt.async_subscribe(
                    self.hass, self.protocol["capabilities_topic"], self._mqtt_capabilities, qos=1))
                self._unsubscribe.append(await mqtt.async_subscribe(
                    self.hass, self.protocol["snapshot_topic"], self._mqtt_snapshot, qos=1))

    @callback
    def attach(self, owner, sender, session=""):
        if self._closed or self.owner is not None:
            raise HomeAssistantError("Windows Bridge is already connected or unloading")
        self.owner, self._direct_sender = owner, sender
        self._direct_session = session or self.protocol.get("session", "") or uuid.uuid4().hex
        self.heartbeat()

    @callback
    def detach(self, owner):
        if self.owner is owner:
            self.owner, self._direct_sender = None, None
            self._direct_session = ""
            self._expired(None)

    @callback
    def heartbeat(self):
        if self._deadline_cancel:
            self._deadline_cancel()
        self.available = True
        self._deadline_cancel = async_call_later(self.hass, 90, self._expired)
        self._notify()

    @callback
    def _expired(self, _now):
        if self._deadline_cancel:
            self._deadline_cancel()
        self.available = False
        self.owner, self._direct_sender = None, None
        self._direct_session = ""
        self._deadline_cancel = None
        for identifier in tuple(self._direct_pending):
            future = self.pending.get(identifier)
            if future is not None and not future.done():
                future.set_exception(HomeAssistantError("Windows Bridge disconnected"))
        self._notify()

    @callback
    def _notify(self):
        for listener in tuple(self.listeners):
            listener()

    @callback
    def _mqtt_result(self, message):
        if message.retain or len(message.payload) > 8192:
            return
        self._result(message.payload)

    @callback
    def _mqtt_capabilities(self, message):
        try:
            value = CapabilitiesMessage.decode(message.payload)
        except ProtocolError:
            return
        if value.device_id != self.device_id:
            return
        previous_session = self.protocol.get("session")
        if value.session == previous_session and value.revision < self._capabilities_revision:
            return
        if value.session != previous_session:
            self._snapshot_revision = -1
            self.snapshot = None
            for identifier, future in tuple(self.pending.items()):
                if identifier not in self._direct_pending and not future.done():
                    future.set_exception(HomeAssistantError("Windows Bridge session changed"))
        # A retained capability manifest is the authoritative current MQTT session.
        self.protocol["session"] = value.session
        self._capabilities_revision = value.revision
        self.capabilities = value

    @callback
    def _mqtt_snapshot(self, message):
        try:
            value = SnapshotMessage.decode(message.payload)
        except ProtocolError:
            return
        if (value.device_id != self.device_id or value.session != self.protocol.get("session")
                or value.revision < self._snapshot_revision):
            return
        self._snapshot_revision = value.revision
        self.snapshot = value
        self._notify()

    @callback
    def _result(self, value):
        if self.protocol.get("version") == 2:
            try:
                value = json.loads(value) if isinstance(value, (str, bytes)) else value
            except (ValueError, UnicodeError):
                return
            if not isinstance(value, dict) or value.get("version") != 2 or not isinstance(value.get("id"), str):
                return
            identifier, status = value["id"], value.get("status")
        else:
            try:
                raw = json.dumps(value, allow_nan=False) if isinstance(value, dict) else value
                message = ResultMessage.decode(raw)
            except (ProtocolError, ValueError, TypeError, RecursionError):
                return
            expected_session = self._direct_session if message.id in self._direct_pending else self.protocol.get("session")
            if message.device_id != self.device_id or message.session != expected_session:
                return
            identifier, status, value = message.id, message.status, message.to_dict()
        future = self.pending.get(identifier)
        if future is not None and not future.done() and status in {"succeeded", "failed", "rejected", "cancelled"}:
            future.set_result(value)

    async def send(self, topic: str, payload: str, *, direct=False):
        if self._closed:
            raise HomeAssistantError("Bridge integration is unloading")
        # Only popup commands may use the live Direct session. Audio, sensors
        # and every other route remain MQTT, including after a Direct reconnect.
        if topic and topic == self.overlay_topic and self.owner is not None:
            direct = True
        if not self.protocol and not direct:
            await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=False)
            return
        if direct:
            kind, target, arguments = "overlay.show", "", command_arguments("json", payload)
            if not self.available:
                raise HomeAssistantError("Windows Bridge is offline")
        else:
            route = self.protocol.get("routes", {}).get(topic)
            if route is None:
                raise HomeAssistantError("Command not allowed by this Windows Bridge")
            kind, target = route["kind"], route.get("target", "")
            arguments = command_arguments(route["parser"], payload)
        identifier = uuid.uuid4().hex
        version = 3 if direct else self.protocol.get("version", 3)
        if version == 3:
            if self.capabilities is not None:
                transport_name = "direct" if direct else "mqtt"
                capability = next(
                    (item for item in self.capabilities.capabilities if item.name == kind),
                    None,
                )
                if capability is None or transport_name not in capability.transports:
                    raise HomeAssistantError("Capability is not available on this transport")
            session = self._direct_session if direct else self.protocol.get("session", "")
            try:
                message = CommandMessage(identifier, session, self.device_id, kind, target,
                                         arguments, time.time(), 12000)
                command = message.to_dict()
                serialized = message.encode()
            except ProtocolError:
                raise HomeAssistantError("Invalid protocol session") from None
        else:
            command = {"version": 2, "id": identifier, "kind": kind, "target": target,
                       "arguments": arguments, "issued_at": time.time(), "ttl_ms": 12000}
            try:
                serialized = json.dumps(command, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            except (ValueError, TypeError, RecursionError):
                raise HomeAssistantError("Invalid command content") from None
        if len(serialized.encode()) > 768 * 1024:
            raise HomeAssistantError("Command exceeds size limit")
        if len(self.pending) >= 64:
            raise HomeAssistantError("Too many pending Windows commands")
        future = self.hass.loop.create_future()
        self.pending[identifier] = future
        if direct:
            self._direct_pending.add(identifier)
        try:
            attempts = 1 if direct else 2
            result = None
            for attempt in range(attempts):
                if direct:
                    self._direct_sender(command)
                else:
                    await mqtt.async_publish(self.hass, self.protocol["command_topic"], serialized, qos=1, retain=False)
                try:
                    async with asyncio.timeout(self.command_attempt_timeout):
                        result = await asyncio.shield(future)
                    break
                except TimeoutError:
                    if attempt + 1 == attempts:
                        raise
            if result.get("status") != "succeeded":
                # Error codes only; never render arbitrary remote details.
                raise HomeAssistantError("Windows Bridge rejected or failed the command")
        except TimeoutError:
            raise HomeAssistantError("Windows Bridge did not acknowledge the command in time") from None
        finally:
            self.pending.pop(identifier, None)
            self._direct_pending.discard(identifier)

    @callback
    def close(self):
        self._closed = True
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._deadline_cancel:
            self._deadline_cancel()
            self._deadline_cancel = None
        for future in self.pending.values():
            if not future.done():
                future.set_exception(HomeAssistantError("Bridge integration unloaded"))
        self.pending.clear()
        self._direct_pending.clear()
        self.listeners.clear()
        self.available = False
        self.owner, self._direct_sender = None, None
        self._direct_session = ""
