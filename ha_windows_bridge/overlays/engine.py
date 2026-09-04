"""Notification lifecycle, independent of Qt and monitor hardware."""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass

from .models import validated_request


@dataclass
class Notification:
    options: dict
    deadline: float | None = None
    remaining: float | None = None
    presented_at: float = 0.0

    @property
    def id(self):
        return self.options["id"]


class NotificationEngine:
    def __init__(self, *, limit=4, queue_limit=32, clock=time.monotonic):
        self.limit, self.queue_limit, self.clock = limit, queue_limit, clock
        self.visible: dict[str, Notification] = {}
        self.pending: list[Notification] = []
        self._deferred: set[str] = set()

    def submit(self, payload: dict) -> str:
        options = payload.get("data", {})
        if not isinstance(options, dict):
            raise ValueError("Notification options must be an object")
        action = options.get("action", "show")
        identifier = options.get("id")
        if not isinstance(action, str) or action not in {"show", "update", "remove", "clear"}:
            raise ValueError("Invalid notification action")
        if identifier is not None and not isinstance(identifier, str):
            raise ValueError("Invalid notification ID")
        previous = self.visible.get(identifier)
        if previous is None:
            previous = next((item for item in self.pending if item.id == identifier), None)
        if action == "clear":
            self.visible.clear()
            self.pending.clear()
            self._deferred.clear()
            return "cleared"
        if action == "remove":
            self.remove(identifier)
            return "removed"
        if action == "update" and previous is None:
            return "not_found"
        if previous:
            merged = {**previous.options, **copy.deepcopy(options)}
            title = payload.get("title", previous.options["title"])
            message = payload.get("message", previous.options["message"])
        else:
            merged = copy.deepcopy(options)
            title, message = payload.get("title", ""), payload.get("message", "")
        request = validated_request(title, message, merged)
        notification = Notification(request)
        if previous and previous.id in self.visible:
            self.visible[previous.id] = notification
            self._activate(notification)
            return "updated"
        self.pending = [item for item in self.pending if item.id != notification.id]
        if len(self.visible) < self.limit and (request["display_mode"] == "parallel" or not self.visible):
            self._activate(notification)
            self.visible[notification.id] = notification
            return "shown"
        self.pending.append(notification)
        self.pending.sort(key=lambda item: -item.options["priority"])
        dropped = self.pending[self.queue_limit:]
        del self.pending[self.queue_limit:]
        self._deferred.intersection_update(item.id for item in self.pending)
        return "queue_full" if notification in dropped else "queued"

    def _activate(self, notification):
        notification.presented_at = self.clock()
        notification.remaining = None
        notification.deadline = None if notification.options["pinned"] else self.clock() + notification.options["duration"]

    def remove(self, identifier):
        self.visible.pop(identifier, None)
        self.pending = [item for item in self.pending if item.id != identifier]
        self._deferred.clear()
        self._promote()

    def defer(self, identifier):
        notification = self.visible.pop(identifier)
        notification.deadline = None
        self._deferred.add(identifier)
        self.pending.append(notification)
        self.pending.sort(key=lambda item: -item.options["priority"])
        del self.pending[self.queue_limit:]
        self._deferred.intersection_update(item.id for item in self.pending)

    def release_deferred(self):
        self._deferred.clear()
        self._promote()

    def _promote(self):
        while self.pending and len(self.visible) < self.limit:
            notification = next((item for item in self.pending if item.id not in self._deferred), None)
            if notification is None:
                break
            if self.visible and notification.options["display_mode"] != "parallel":
                break
            self.pending.remove(notification)
            self._activate(notification)
            self.visible[notification.id] = notification

    def pause(self, identifier, paused):
        notification = self.visible.get(identifier)
        if notification is None or not notification.options["pause_on_hover"] or notification.options["pinned"]:
            return
        if paused and notification.deadline is not None:
            notification.remaining = max(0.0, notification.deadline - self.clock())
            notification.deadline = None
        elif not paused and notification.remaining is not None:
            notification.deadline = self.clock() + notification.remaining
            notification.remaining = None

    def tick(self):
        now = self.clock()
        expired = [item.id for item in self.visible.values() if item.deadline is not None and item.deadline <= now]
        for identifier in expired:
            self.visible.pop(identifier)
        if expired:
            self._deferred.clear()
        self._promote()

    def lifetime(self, identifier):
        notification = self.visible[identifier]
        remaining = notification.remaining
        if remaining is None:
            remaining = max(0.0, notification.deadline - self.clock()) if notification.deadline is not None else notification.options["duration"]
        return min(1.0, remaining / notification.options["duration"])

    @property
    def needs_clock(self):
        return any(item.deadline is not None or self.media_advancing(item.id) for item in self.visible.values())

    def media_position(self, identifier):
        item = self.visible[identifier]
        position = item.options["media_position"]
        if item.options["media_playing"]:
            position += max(0, self.clock() - item.presented_at)
        return min(item.options["media_duration"], position)

    def media_advancing(self, identifier):
        item = self.visible[identifier]
        return item.options["media_playing"] and self.media_position(identifier) < item.options["media_duration"]
