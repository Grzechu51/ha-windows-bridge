"""Small thread-safe event stream with explicit subscription ownership."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Event:
    topic: str
    data: Any = None


class EventBus:
    def __init__(self, logger: logging.Logger | None = None):
        self._log = logger or logging.getLogger("bridge.app")
        self._lock = threading.RLock()
        self._next_id = 0
        self._listeners: dict[int, tuple[str, Callable[[Event], None]]] = {}

    def subscribe(self, topic: str, callback: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._next_id += 1
            token = self._next_id
            self._listeners[token] = topic, callback

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.pop(token, None)
        return unsubscribe

    def emit(self, topic: str, data: Any = None) -> None:
        with self._lock:
            listeners = tuple(self._listeners.values())
        event = Event(topic, data)
        for selected, callback in listeners:
            if selected not in {topic, "*"}:
                continue
            try:
                callback(event)
            except Exception:
                self._log.exception("Event subscriber failed: %s", topic, extra={"diagnostic_event": True})

    def clear(self) -> None:
        with self._lock:
            self._listeners.clear()
