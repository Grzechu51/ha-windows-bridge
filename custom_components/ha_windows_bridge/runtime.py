"""Entry-owned command acknowledgements and live Direct HA availability."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .errors import failed, invalid
from .protocol import (
    MAX_CONTROL_BYTES,
    CapabilitiesMessage,
    CommandMessage,
    ProtocolError,
    ResultMessage,
    SnapshotMessage,
    legacy_arguments,
)

_LIFECYCLE_DISPOSITIONS = frozenset({"accepted", "displayed", "rejected", "closed", "dropped"})
_LIFECYCLE_REASONS = frozenset({
    "queued", "displayed", "queue_full", "pinned_limit", "not_found",
    "replaced", "updated", "expired", "user", "locked", "suspended",
    "fullscreen", "display_removed", "no_space", "render_error", "stopping",
})


def command_arguments(parser: str, payload: str) -> dict:
    try:
        return legacy_arguments(parser, payload)
    except ProtocolError:
        raise invalid("invalid_legacy_payload", "Invalid legacy command payload") from None


@dataclass
class BridgeRuntime:
    hass: Any
    device_id: str
    overlay_unique_id: str
    overlay_topic: str
    overlay_event_type: str
    protocol: dict = field(default_factory=dict)
    available: bool = False
    listeners: set = field(default_factory=set)
    pending: dict = field(default_factory=dict)
    _direct_pending: set = field(default_factory=set)
    _send_tasks: set = field(default_factory=set)
    _subscription_cleanup: Any = None
    notification_lifecycle: deque = field(default_factory=lambda: deque(maxlen=256))
    _unsubscribe: list = field(default_factory=list)
    _deadline_cancel: Any = None
    _closed: bool = False
    setup_failed: bool = False
    owner: Any = None
    _direct_sender: Any = None
    _direct_session: str = ""
    _direct_capabilities: frozenset[str] = field(default_factory=frozenset)
    capabilities: Any = None
    snapshot: Any = None
    _snapshot_revision: int = -1
    _capabilities_revision: int = -1
    command_attempt_timeout: float = 5.0

    def __post_init__(self):
        # Capabilities update the active session; config-entry data is immutable state.
        self.protocol = dict(self.protocol)

    async def start(self):
        if self.protocol:
            self._unsubscribe.append(await mqtt.async_subscribe(self.hass, self.protocol["result_topic"], self._mqtt_result, qos=1))
            if self.protocol.get("version") == 3:
                self._unsubscribe.append(await mqtt.async_subscribe(
                    self.hass, self.protocol["capabilities_topic"], self._mqtt_capabilities, qos=1))
                self._unsubscribe.append(await mqtt.async_subscribe(
                    self.hass, self.protocol["snapshot_topic"], self._mqtt_snapshot, qos=1))

    @callback
    def attach(self, owner, sender, session="", capabilities=("overlay.show",)):
        if self._closed or self.owner is not None:
            raise failed("bridge_busy", "Windows Bridge is already connected or unloading")
        self.owner, self._direct_sender = owner, sender
        self._direct_session = session or self.protocol.get("session", "") or uuid.uuid4().hex
        self._direct_capabilities = frozenset(capabilities)
        self.heartbeat()

    @callback
    def detach(self, owner):
        if self.owner is owner:
            self._clear_subscription()
            self.owner, self._direct_sender = None, None
            self._direct_session = ""
            self._direct_capabilities = frozenset()
            self._expired(None)

    @callback
    def heartbeat(self):
        if self._closed or self.owner is None:
            return
        if self._deadline_cancel:
            self._deadline_cancel()
        self.available = True
        self._deadline_cancel = async_call_later(self.hass, 90, self._expired)
        self._notify()

    @callback
    def _expired(self, _now):
        self._clear_subscription()
        if self._deadline_cancel:
            self._deadline_cancel()
        self.available = False
        self.owner, self._direct_sender = None, None
        self._direct_session = ""
        self._direct_capabilities = frozenset()
        self._deadline_cancel = None
        for identifier in tuple(self._direct_pending):
            future = self.pending.get(identifier)
            if future is not None and not future.done():
                future.set_exception(failed("bridge_disconnected", "Windows Bridge disconnected"))
        self._notify()

    @callback
    def _notify(self):
        if self._closed:
            return
        for listener in tuple(self.listeners):
            listener()

    @callback
    def _mqtt_result(self, message):
        if self._closed:
            return
        payload = message.payload
        if isinstance(payload, str):
            size = len(payload.encode("utf-8"))
        elif isinstance(payload, bytes):
            size = len(payload)
        else:
            return
        if message.retain or size > MAX_CONTROL_BYTES:
            return
        self._result(payload)

    @callback
    def _mqtt_capabilities(self, message):
        if self._closed:
            return
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
                    future.set_exception(failed("session_changed", "Windows Bridge session changed"))
        # A retained capability manifest is the authoritative current MQTT session.
        self.protocol["session"] = value.session
        self._capabilities_revision = value.revision
        self.capabilities = value

    @callback
    def _mqtt_snapshot(self, message):
        if self._closed:
            return
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
    def _result(self, value, *, direct=False):
        if self._closed:
            return
        if self.protocol.get("version") == 2 and not direct:
            try:
                value = json.loads(value) if isinstance(value, (str, bytes)) else value
            except (ValueError, UnicodeError):
                return
            if not isinstance(value, dict) or value.get("version") != 2 or not isinstance(value.get("id"), str):
                return
            identifier, status = value["id"], value.get("status")
            if identifier in self._direct_pending:
                return
        else:
            try:
                raw = json.dumps(value, allow_nan=False) if isinstance(value, dict) else value
                message = ResultMessage.decode(raw)
            except (ProtocolError, ValueError, TypeError, RecursionError):
                return
            expected_session = (
                self._direct_session
                if direct or message.id in self._direct_pending
                else self.protocol.get("session")
            )
            if message.device_id != self.device_id or message.session != expected_session:
                return
            identifier, status, value = message.id, message.status, message.to_dict()
            if message.code == "notification_lifecycle":
                self._notification_lifecycle(message)
                return
        future = self.pending.get(identifier)
        if future is not None and not future.done() and status in {"succeeded", "failed", "rejected", "cancelled"}:
            future.set_result(value)

    def _notification_lifecycle(self, message):
        data = message.data
        if (set(data) != {"notification_id", "disposition", "reason", "command_id"}
                or data.get("command_id") != message.id
                or not all(isinstance(data.get(key), str) for key in data)
                or not 1 <= len(data["notification_id"]) <= 128
                or not 1 <= len(data["command_id"]) <= 128
                or data["disposition"] not in _LIFECYCLE_DISPOSITIONS
                or data["reason"] not in _LIFECYCLE_REASONS):
            return
        public = dict(data)
        self.notification_lifecycle.append(public)
        bus = getattr(self.hass, "bus", None)
        if bus is not None:
            bus.async_fire("ha_windows_bridge_notification_lifecycle", public)

    async def send(self, topic: str, payload: str, *, direct=False):
        if self._closed:
            raise failed("bridge_unloading", "Bridge integration is unloading")
        task = asyncio.create_task(self._send(topic, payload, direct=direct))
        self._send_tasks.add(task)
        try:
            await task
        except asyncio.CancelledError:
            if self._closed:
                raise failed("bridge_unloaded", "Bridge integration unloaded") from None
            raise
        finally:
            self._send_tasks.discard(task)

    async def _send(self, topic: str, payload: str, *, direct=False):
        if self._closed:
            raise failed("bridge_unloading", "Bridge integration is unloading")
        # Only popup commands may use the live Direct session. Audio, sensors
        # and every other route remain MQTT, including after a Direct reconnect.
        if topic and topic == self.overlay_topic and self.owner is not None:
            direct = True
        if not self.protocol and not direct:
            try:
                await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=False)
            except asyncio.CancelledError:
                if self._closed:
                    raise failed("bridge_unloaded", "Bridge integration unloaded") from None
                raise
            return
        if direct:
            kind, target, arguments = "overlay.show", "", command_arguments("json", payload)
            if not self.available:
                raise failed("bridge_offline", "Windows Bridge is offline")
            if kind not in self._direct_capabilities:
                raise failed("capability_unavailable", "Capability is not available on this transport")
        else:
            route = self.protocol.get("routes", {}).get(topic)
            if route is None:
                raise failed("command_not_allowed", "Command not allowed by this Windows Bridge")
            kind, target = route["kind"], route.get("target", "")
            arguments = command_arguments(route["parser"], payload)
        identifier = uuid.uuid4().hex
        version = 3 if direct else self.protocol.get("version", 3)
        if version == 3:
            if not direct and self.capabilities is not None:
                capability = next(
                    (item for item in self.capabilities.capabilities if item.name == kind),
                    None,
                )
                if capability is None or "mqtt" not in capability.transports:
                    raise failed("capability_unavailable", "Capability is not available on this transport")
            session = self._direct_session if direct else self.protocol.get("session", "")
            try:
                message = CommandMessage(identifier, session, self.device_id, kind, target,
                                         arguments, time.time(), 12000)
                command = message.to_dict()
                serialized = message.encode()
            except ProtocolError:
                raise failed("invalid_protocol_session", "Invalid protocol session") from None
        else:
            command = {"version": 2, "id": identifier, "kind": kind, "target": target,
                       "arguments": arguments, "issued_at": time.time(), "ttl_ms": 12000}
            try:
                serialized = json.dumps(command, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            except (ValueError, TypeError, RecursionError):
                raise invalid("invalid_command_content", "Invalid command content") from None
        if len(serialized.encode()) > 768 * 1024:
            raise invalid("command_too_large", "Command exceeds size limit")
        if len(self.pending) >= 64:
            raise failed("too_many_pending", "Too many pending Windows commands")
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
                raise failed("command_rejected", "Windows Bridge rejected or failed the command")
        except TimeoutError:
            raise failed("command_timeout", "Windows Bridge did not acknowledge the command in time") from None
        except asyncio.CancelledError:
            if self._closed:
                raise failed("bridge_unloaded", "Bridge integration unloaded") from None
            raise
        finally:
            self.pending.pop(identifier, None)
            self._direct_pending.discard(identifier)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    @callback
    def set_subscription_cleanup(self, cleanup):
        self._subscription_cleanup = cleanup

    @callback
    def _clear_subscription(self):
        cleanup, self._subscription_cleanup = self._subscription_cleanup, None
        if cleanup is not None:
            cleanup()

    @callback
    def close(self):
        if self._closed:
            return
        self._closed = True
        self._clear_subscription()
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._deadline_cancel:
            self._deadline_cancel()
            self._deadline_cancel = None
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        for task in tuple(self._send_tasks):
            task.cancel()
        self.pending.clear()
        self._direct_pending.clear()
        self.notification_lifecycle.clear()
        self.capabilities = None
        self.snapshot = None
        self.listeners.clear()
        self.available = False
        self.owner, self._direct_sender = None, None
        self._direct_session = ""
        self._direct_capabilities = frozenset()

    async def async_close(self):
        """Close and wait for every entry-owned command coroutine to finish."""
        tasks = tuple(task for task in self._send_tasks if task is not asyncio.current_task())
        self.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self._send_tasks.difference_update(tasks)
