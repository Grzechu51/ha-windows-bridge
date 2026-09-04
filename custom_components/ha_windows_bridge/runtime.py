"""Entry-owned command acknowledgements and live Direct HA availability."""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later


def command_arguments(parser: str, payload: str) -> dict:
    if parser == "json":
        try:
            value = json.loads(payload)
        except (ValueError, RecursionError):
            raise HomeAssistantError("Invalid command JSON") from None
        if not isinstance(value, dict):
            raise HomeAssistantError("Command must be an object")
        return value
    if parser in {"volume", "balance"}:
        try:
            value = float(payload)
        except (ValueError, OverflowError):
            raise HomeAssistantError("Invalid command number") from None
        if not math.isfinite(value):
            raise HomeAssistantError("Command number is not finite")
        if parser == "balance" or not (0 < value < 1 or (value == 1 and ("." in payload or "e" in payload.lower()))):
            value /= 100
        return {"value": value}
    if parser == "switch":
        if payload.lower() not in {"on", "off", "true", "false", "1", "0", "yes", "no"}:
            raise HomeAssistantError("Invalid switch command")
        return {"value": payload.lower() in {"on", "true", "1", "yes"}}
    if parser == "button":
        if payload != "PRESS":
            raise HomeAssistantError("Invalid button command")
        return {}
    return {"value": payload}


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
    _unsubscribe: list = field(default_factory=list)
    _deadline_cancel: Any = None
    _closed: bool = False
    owner: Any = None
    _direct_sender: Any = None

    async def start(self):
        if not self.overlay_event_type and self.protocol:
            self._unsubscribe.append(await mqtt.async_subscribe(self.hass, self.protocol["result_topic"], self._mqtt_result, qos=1))

    @callback
    def attach(self, owner, sender):
        if self._closed or self.owner is not None:
            raise HomeAssistantError("Windows Bridge is already connected or unloading")
        self.owner, self._direct_sender = owner, sender
        self.heartbeat()

    @callback
    def detach(self, owner):
        if self.owner is owner:
            self.owner, self._direct_sender = None, None
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
        self._deadline_cancel = None
        for future in self.pending.values():
            if not future.done():
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
        try:
            value = json.loads(message.payload)
        except (ValueError, UnicodeError):
            return
        self._result(value)

    @callback
    def _result(self, value):
        if not isinstance(value, dict) or value.get("version") != 2 or not isinstance(value.get("id"), str):
            return
        future = self.pending.get(value.get("id"))
        status = value.get("status")
        if future is not None and not future.done() and isinstance(status, str) and status in {"succeeded", "failed", "rejected", "cancelled"}:
            future.set_result(value)

    async def send(self, topic: str, payload: str, *, direct=False):
        if self._closed:
            raise HomeAssistantError("Bridge integration is unloading")
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
        command = {"version": 2, "id": identifier, "kind": kind, "target": target,
                   "arguments": arguments, "issued_at": time.time(), "ttl_ms": 10000}
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
        try:
            if direct:
                self._direct_sender(command)
            else:
                await mqtt.async_publish(self.hass, self.protocol["command_topic"], serialized, qos=1, retain=False)
            async with asyncio.timeout(10):
                result = await future
            if result.get("status") != "succeeded":
                # Error codes only; never render arbitrary remote details.
                raise HomeAssistantError("Windows Bridge rejected or failed the command")
        except TimeoutError:
            raise HomeAssistantError("Windows Bridge did not acknowledge the command in time") from None
        finally:
            self.pending.pop(identifier, None)

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
        self.listeners.clear()
        self.available = False
        self.owner, self._direct_sender = None, None
