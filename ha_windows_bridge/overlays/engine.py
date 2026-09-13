"""Notification lifecycle, independent of Qt and monitor hardware."""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass

from .models import (
    DeliveryDisposition,
    EngineResult,
    LifecycleReason,
    NotificationCommand,
    validated_request,
)


@dataclass
class Notification:
    options: dict
    token: int = 0
    queued_at: float = 0.0
    source: str = "remote"
    command_id: str = ""
    session: str = ""
    device_id: str = ""
    displayed: bool = False
    deadline: float | None = None
    remaining: float | None = None
    presented_at: float | None = None
    media_updated_at: float = 0.0

    @property
    def id(self):
        return self.options["id"]


class NotificationEngine:
    def __init__(self, *, limit=4, queue_limit=32, clock=time.monotonic,
                 queue_max_age=30.0, pinned_per_source=4, lifecycle_limit=256):
        self.limit, self.queue_limit, self.clock = limit, queue_limit, clock
        self.queue_max_age = queue_max_age
        self.pinned_per_source = pinned_per_source
        self.lifecycle_limit = max(3, lifecycle_limit)
        self.visible: dict[str, Notification] = {}
        self.pending: list[Notification] = []
        self.retiring: dict[str, Notification] = {}
        self._deferred: set[str] = set()
        self._token = 0
        self._closed = False
        self._lock = threading.RLock()
        self._lifecycle: list[EngineResult] = []
        self._lifecycle_reserved: dict[int, int] = {}

    def _result(self, item, disposition, reason):
        return EngineResult(
            disposition, item.id, reason, item.token, item.command_id,
            item.source, item.session, item.device_id,
        )

    def _command_result(self, command, disposition, reason, token=0):
        policy = command.policy
        return EngineResult(
            disposition, command.notification_id, reason, token, command.command_id,
            policy.source if policy else "", policy.session if policy else "",
            policy.device_id if policy else "",
        )

    def _lifecycle_load(self):
        return len(self._lifecycle) + sum(self._lifecycle_reserved.values())

    def _can_admit(self, previous=None):
        released = self._lifecycle_reserved.get(previous.token, 0) if previous else 0
        terminal = 1 if previous is not None else 0
        return self._lifecycle_load() - released + terminal + 3 <= self.lifecycle_limit

    def _reject(self, command, reason):
        result = self._command_result(command, DeliveryDisposition.REJECTED, reason)
        if self._lifecycle_load() < self.lifecycle_limit:
            self._lifecycle.append(result)
        return result

    def _accept(self, item, reason):
        result = self._result(item, DeliveryDisposition.ACCEPTED, reason)
        self._lifecycle.append(result)
        self._lifecycle_reserved[item.token] = 2
        return result

    def _terminal(self, item, reason):
        if item.token not in self._lifecycle_reserved:
            return False
        self._lifecycle_reserved.pop(item.token)
        disposition = (
            DeliveryDisposition.CLOSED if item.displayed
            else DeliveryDisposition.DROPPED
        )
        self._lifecycle.append(self._result(item, disposition, reason))
        return True

    def submit(self, payload: dict | NotificationCommand) -> EngineResult:
        command = payload if isinstance(payload, NotificationCommand) else NotificationCommand.parse(payload)
        action, identifier = command.action.value, command.notification_id
        with self._lock:
            return self._submit_locked(command, action, identifier)

    def _submit_locked(self, command, action, identifier):
        if self._closed:
            return self._reject(command, LifecycleReason.STOPPING)
        options = command.options()
        previous = self.visible.get(identifier)
        if previous is None:
            previous = next((item for item in self.pending if item.id == identifier), None)
        if action == "clear":
            for item in (*self.visible.values(), *self.pending):
                self._terminal(item, LifecycleReason.USER)
            self.retiring.update(self.visible)
            self.visible.clear()
            self.pending.clear()
            self._deferred.clear()
            return EngineResult(DeliveryDisposition.ACCEPTED, reason=LifecycleReason.REPLACED)
        if action == "remove":
            if previous is None or identifier in self.retiring:
                return self._reject(command, LifecycleReason.NOT_FOUND)
            self.remove(identifier, reason=LifecycleReason.USER)
            return EngineResult(DeliveryDisposition.ACCEPTED, identifier, LifecycleReason.USER)
        if action == "update" and (previous is None or identifier in self.retiring):
            return self._reject(command, LifecycleReason.NOT_FOUND)
        if previous:
            patch = (
                copy.deepcopy(dict(command.patch))
                if action == "update"
                else copy.deepcopy(options)
            )
            title = patch.pop("title", previous.options["title"])
            message = patch.pop("message", previous.options["message"])
            merged = {**previous.options, **patch}
        else:
            merged = copy.deepcopy(options)
            title, message = options.get("title", ""), options.get("message", "")
        request = validated_request(title, message, merged)
        source = command.policy.source if command.policy else "remote"
        if (previous is None and request["pinned"]
                and sum(item.options["pinned"] and item.source == source
                        for item in (*self.visible.values(), *self.pending))
                >= self.pinned_per_source):
            return self._reject(command, LifecycleReason.PINNED_LIMIT)
        if previous is not None and action == "update":
            if self._lifecycle_load() + 1 > self.lifecycle_limit:
                return self._reject(command, LifecycleReason.QUEUE_FULL)
            updated = Notification(
                request,
                token=previous.token,
                queued_at=previous.queued_at,
                source=previous.source,
                command_id=previous.command_id,
                session=previous.session,
                device_id=previous.device_id,
                displayed=previous.displayed,
                deadline=previous.deadline,
                remaining=previous.remaining,
                presented_at=previous.presented_at,
                media_updated_at=previous.media_updated_at,
            )
            if {"media_position", "media_playing"} & set(command.patch):
                updated.media_updated_at = self.clock()
            if request["pinned"]:
                updated.deadline = None
                updated.remaining = None
            elif previous.options["pinned"] and previous.displayed:
                updated.deadline = self.clock() + request["duration"]
            elif (previous.options["pause_on_hover"]
                  and not request["pause_on_hover"]
                  and updated.remaining is not None):
                updated.deadline = self.clock() + updated.remaining
                updated.remaining = None
            if "title" in command.patch and command.patch["title"] == "":
                updated.options["title"] = ""
            if previous.id in self.visible:
                self.visible[previous.id] = updated
            else:
                self.pending[self.pending.index(previous)] = updated
            result = self._command_result(
                command, DeliveryDisposition.ACCEPTED, LifecycleReason.UPDATED,
                previous.token,
            )
            self._lifecycle.append(result)
            return result
        if not self._can_admit(previous):
            return self._reject(command, LifecycleReason.QUEUE_FULL)
        self._token += 1
        notification = Notification(
            request,
            token=self._token,
            queued_at=self.clock(),
            source=source,
            command_id=command.command_id,
            session=command.policy.session if command.policy else "",
            device_id=command.policy.device_id if command.policy else "",
        )
        if previous is not None:
            self._terminal(previous, LifecycleReason.REPLACED)
        if previous and previous.id in self.visible:
            self.visible[previous.id] = notification
            self._activate(notification)
            return self._accept(notification, LifecycleReason.REPLACED)
        self.pending = [item for item in self.pending if item.id != notification.id]
        occupied = len(self.visible) + len(self.retiring)
        if (identifier not in self.retiring and occupied < self.limit
                and (request["display_mode"] == "parallel" or not self.visible)):
            self._activate(notification)
            self.visible[notification.id] = notification
            return self._accept(notification, LifecycleReason.QUEUED)
        self.pending.append(notification)
        self.pending.sort(key=lambda item: -item.options["priority"])
        dropped = self.pending[self.queue_limit:]
        del self.pending[self.queue_limit:]
        for item in dropped:
            if item is not notification:
                self._terminal(item, LifecycleReason.QUEUE_FULL)
        self._deferred.intersection_update(item.id for item in self.pending)
        if notification in dropped:
            return self._reject(command, LifecycleReason.QUEUE_FULL)
        return self._accept(notification, LifecycleReason.QUEUED)

    def _activate(self, notification):
        notification.presented_at = None
        notification.media_updated_at = self.clock()
        notification.remaining = None
        notification.deadline = None

    def remove(self, identifier, token=None, reason=LifecycleReason.USER):
        with self._lock:
            item = self.visible.get(identifier)
            pending = next((candidate for candidate in self.pending
                            if candidate.id == identifier), None)
            target = item or pending
            if target is None or token is not None and target.token != token:
                return False
            if item is not None:
                self.visible.pop(identifier)
                self.retiring[identifier] = item
            self._terminal(target, reason)
            self.pending = [item for item in self.pending if item.id != identifier]
            self._deferred.clear()
            return True

    def defer(self, identifier, token=None):
        with self._lock:
            notification = self.visible.get(identifier)
            if notification is None or token is not None and notification.token != token:
                return False
            self.visible.pop(identifier)
            notification.deadline = None
            self._deferred.add(identifier)
            self.pending.append(notification)
            self.pending.sort(key=lambda item: -item.options["priority"])
            dropped = self.pending[self.queue_limit:]
            del self.pending[self.queue_limit:]
            for item in dropped:
                self._terminal(item, LifecycleReason.NO_SPACE)
            self._deferred.intersection_update(item.id for item in self.pending)
            return True

    def release_deferred(self):
        with self._lock:
            self._deferred.clear()
            self._promote()

    def _promote(self):
        while self.pending and len(self.visible) + len(self.retiring) < self.limit:
            notification = next((
                item for item in self.pending
                if item.id not in self._deferred and item.id not in self.retiring
            ), None)
            if notification is None:
                break
            if self.visible and notification.options["display_mode"] != "parallel":
                break
            self.pending.remove(notification)
            self._activate(notification)
            self.visible[notification.id] = notification

    def pause(self, identifier, paused, token=None):
        with self._lock:
            notification = self.visible.get(identifier)
            if (notification is None or token is not None and notification.token != token
                    or not notification.options["pause_on_hover"] or notification.options["pinned"]):
                return False
            if paused and notification.deadline is not None:
                notification.remaining = max(0.0, notification.deadline - self.clock())
                notification.deadline = None
            elif not paused and notification.remaining is not None:
                notification.deadline = self.clock() + notification.remaining
                notification.remaining = None
            return True

    def tick(self):
        with self._lock:
            now = self.clock()
            stale = [item for item in self.pending
                     if item.queued_at + self.queue_max_age <= now]
            self.pending[:] = [item for item in self.pending if item not in stale]
            for item in stale:
                self._terminal(item, LifecycleReason.NO_SPACE)
            expired = [item.id for item in self.visible.values()
                       if item.deadline is not None and item.deadline <= now]
            for identifier in expired:
                item = self.visible.pop(identifier)
                self.retiring[identifier] = item
                self._terminal(item, LifecycleReason.EXPIRED)
            if expired:
                self._deferred.clear()
            self._promote()

    def lifetime(self, identifier):
        with self._lock:
            notification = self.visible[identifier]
            remaining = notification.remaining
            if remaining is None:
                remaining = max(0.0, notification.deadline - self.clock()) if notification.deadline is not None else notification.options["duration"]
            return min(1.0, remaining / notification.options["duration"])

    @property
    def needs_clock(self):
        with self._lock:
            return bool(self.pending) or any(
                item.deadline is not None or self.media_advancing(item.id)
                for item in self.visible.values()
            )

    def media_position(self, identifier):
        with self._lock:
            item = self.visible[identifier]
            position = item.options["media_position"]
            if item.options["media_playing"]:
                position += max(0, self.clock() - item.media_updated_at)
            return min(item.options["media_duration"], position)

    def media_advancing(self, identifier):
        with self._lock:
            item = self.visible[identifier]
            return item.options["media_playing"] and self.media_position(identifier) < item.options["media_duration"]

    def refresh_media(self, payload):
        """Refresh content in place: never extend lifetime or release hover pause."""
        with self._lock:
            changed = False
            keys = {"media_position", "media_duration", "media_playing", "media_source", "media_controls", "image"}
            for item in (*self.visible.values(), *self.pending):
                if not item.options.get("media_live"):
                    continue
                content = {key: payload["data"].get(key, "" if key in {"image", "media_source"} else False if key in {"media_controls", "media_playing"} else 0) for key in keys}
                content["progress"] = None
                item.options = validated_request(payload["title"], payload["message"], {**item.options, **content})
                item.media_updated_at = self.clock()
                changed = True
            return changed

    def bind_monitor(self, identifier, token, monitor_id):
        with self._lock:
            item = self.visible.get(identifier)
            if item is None or item.token != token or item.options.get("monitor_id"):
                return False
            item.options["monitor_id"] = monitor_id
            return True

    def presentation_state(self, identifier, token):
        """Return one coherent GUI frame for a notification generation."""
        with self._lock:
            item = self.visible.get(identifier)
            if item is None or item.token != token or self._closed:
                return None
            now = self.clock()
            remaining = item.remaining
            if remaining is None:
                remaining = (
                    max(0.0, item.deadline - now)
                    if item.deadline is not None else item.options["duration"]
                )
            lifetime = min(1.0, remaining / item.options["duration"])
            duration = item.options["media_duration"]
            position = item.options["media_position"]
            if item.options["media_playing"]:
                position += max(0, now - item.media_updated_at)
            return lifetime, duration, min(duration, position)

    def mark_displayed(self, identifier, token):
        with self._lock:
            item = self.visible.get(identifier)
            if item is None or item.token != token or self._closed:
                return EngineResult(DeliveryDisposition.REJECTED, identifier,
                                    LifecycleReason.NOT_FOUND, token)
            if not item.displayed:
                item.presented_at = self.clock()
                item.deadline = None if item.options["pinned"] else (
                    item.presented_at + item.options["duration"]
                )
                item.displayed = True
                if self._lifecycle_reserved.get(item.token) == 2:
                    self._lifecycle_reserved[item.token] = 1
                    self._lifecycle.append(self._result(
                        item, DeliveryDisposition.DISPLAYED,
                        LifecycleReason.DISPLAYED,
                    ))
            return self._result(item, DeliveryDisposition.DISPLAYED,
                                LifecycleReason.DISPLAYED)

    def begin_retire(self, identifier, token=None, reason=None):
        with self._lock:
            item = self.visible.get(identifier)
            if item is None or token is not None and item.token != token:
                return False
            self.visible.pop(identifier)
            self.retiring[identifier] = item
            if reason is not None:
                self._terminal(item, reason)
            return True

    def finish_retire(self, identifier, token):
        with self._lock:
            item = self.retiring.get(identifier)
            if item is None or item.token != token:
                return False
            self.retiring.pop(identifier)
            self._promote()
            return True

    def token_matches(self, identifier, token):
        with self._lock:
            item = self.visible.get(identifier)
            return item is not None and item.token == token and not self._closed

    def snapshot(self):
        with self._lock:
            return (
                copy.deepcopy(self.visible),
                copy.deepcopy(tuple(self.pending)),
                copy.deepcopy(self.retiring),
            )

    def drain_lifecycle(self):
        with self._lock:
            results, self._lifecycle = tuple(self._lifecycle), []
            return results

    def suppress(self, reason):
        with self._lock:
            for item in (*self.visible.values(), *self.pending):
                self._terminal(item, reason)
            self.retiring.update(self.visible)
            self.visible.clear()
            self.pending.clear()
            self._deferred.clear()

    def shutdown(self):
        with self._lock:
            for item in (*self.visible.values(), *self.pending):
                self._terminal(item, LifecycleReason.STOPPING)
            self._closed = True
            self._token += 1
            self.visible.clear()
            self.pending.clear()
            self.retiring.clear()
            self._deferred.clear()
