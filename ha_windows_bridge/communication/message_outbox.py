"""Bounded protocol-frame outbox with explicit acceptance and delivery states."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import StrEnum


class DeliveryState(StrEnum):
    ACCEPTED = "accepted"
    INFLIGHT = "inflight"
    DELIVERED = "delivered"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class MessageItem:
    key: str
    topic: str
    payload: str | bytes
    retain: bool
    qos: int
    token: int
    state: DeliveryState = DeliveryState.ACCEPTED
    connection_generation: int = 0
    attempts: int = 0


class MessageOutbox:
    """Store bounded frames; replacing a state key always keeps only the latest."""

    def __init__(self, capacity: int = 256):
        if capacity <= 0:
            raise ValueError("MessageOutbox capacity must be positive")
        self.capacity = capacity
        self._lock = threading.Lock()
        self._items: OrderedDict[str, MessageItem] = OrderedDict()
        self._token = 0
        self._closed = False

    def accept(self, key: str, topic: str, payload: str | bytes, *, retain: bool,
               qos: int = 1, replace_latest: bool = False) -> MessageItem | None:
        if not key or not topic:
            raise ValueError("MessageOutbox key and topic are required")
        with self._lock:
            if self._closed:
                return None
            if key in self._items and not replace_latest:
                current = self._items[key]
                if current.payload == payload and current.topic == topic:
                    return current
                return None
            if key not in self._items and len(self._items) >= self.capacity:
                evicted = next(
                    (
                        candidate
                        for candidate, item in self._items.items()
                        if not item.retain
                        and item.state
                        in {DeliveryState.EXHAUSTED, DeliveryState.DELIVERED}
                    ),
                    None,
                )
                if evicted is None:
                    return None
                self._items.pop(evicted)
            self._token += 1
            item = MessageItem(key, topic, payload, bool(retain), int(qos), self._token)
            self._items[key] = item
            self._items.move_to_end(key)
            return item

    def mark_delivered(
        self, key: str, token: int, connection_generation: int | None = None
    ) -> bool:
        return self._mark(
            key, token, DeliveryState.DELIVERED, connection_generation
        )

    def mark_failed(
        self, key: str, token: int, connection_generation: int | None = None
    ) -> bool:
        return self._mark(key, token, DeliveryState.FAILED, connection_generation)

    def _mark(
        self,
        key: str,
        token: int,
        state: DeliveryState,
        connection_generation: int | None,
    ) -> bool:
        with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current.token != token
                or current.state != DeliveryState.INFLIGHT
                or (
                    connection_generation is not None
                    and current.connection_generation != connection_generation
                )
            ):
                return False
            self._items[key] = replace(current, state=state)
            return True

    def mark_exhausted(
        self, key: str, token: int, connection_generation: int | None = None
    ) -> bool:
        with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current.token != token
                or current.state != DeliveryState.FAILED
                or (
                    connection_generation is not None
                    and current.connection_generation != connection_generation
                )
            ):
                return False
            self._items[key] = replace(current, state=DeliveryState.EXHAUSTED)
            return True

    def begin_attempt(
        self, key: str, token: int, connection_generation: int
    ) -> MessageItem | None:
        """Give one wire attempt a unique identity tied to its connection."""

        with self._lock:
            current = self._items.get(key)
            if (
                current is None
                or current.token != token
                or current.state not in {DeliveryState.ACCEPTED, DeliveryState.FAILED}
                or self._closed
            ):
                return None
            self._token += 1
            attempted = replace(
                current,
                token=self._token,
                state=DeliveryState.INFLIGHT,
                connection_generation=int(connection_generation),
                attempts=current.attempts + 1,
            )
            self._items[key] = attempted
            return attempted

    def replay(
        self, connection_generation: int = 0, *, retained_only: bool = False
    ) -> None:
        """Invalidate every old attempt before making messages replayable."""

        with self._lock:
            for key, item in tuple(self._items.items()):
                if retained_only and not item.retain:
                    continue
                self._token += 1
                self._items[key] = replace(
                    item,
                    token=self._token,
                    state=DeliveryState.ACCEPTED,
                    connection_generation=int(connection_generation),
                    attempts=0,
                )

    def pending(self) -> tuple[MessageItem, ...]:
        with self._lock:
            return tuple(
                item
                for item in self._items.values()
                if item.state in {DeliveryState.ACCEPTED, DeliveryState.FAILED}
            )

    def snapshot(self) -> tuple[MessageItem, ...]:
        with self._lock:
            return tuple(self._items.values())

    def discard_delivered(self, *, keep_retained: bool = True) -> None:
        with self._lock:
            for key, item in tuple(self._items.items()):
                if item.state == DeliveryState.DELIVERED and not (keep_retained and item.retain):
                    self._items.pop(key)

    def discard(self, key: str, token: int) -> bool:
        with self._lock:
            current = self._items.get(key)
            if current is None or current.token != token:
                return False
            self._items.pop(key)
            return True

    def close(self) -> None:
        with self._lock:
            self._closed = True

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed
