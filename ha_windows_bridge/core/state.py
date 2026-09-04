"""Immutable runtime snapshots shared by UI, tray and diagnostics."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from enum import StrEnum

from .events import EventBus


class ServiceState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    name: str
    state: ServiceState = ServiceState.STOPPED
    detail: str = ""
    updated_at: float = 0.0


class StateStore:
    def __init__(self, events: EventBus):
        self.events = events
        self._lock = threading.RLock()
        self._services: dict[str, ServiceStatus] = {}

    def set(self, name: str, state: ServiceState, detail: str = "") -> None:
        with self._lock:
            previous = self._services.get(name, ServiceStatus(name))
            current = replace(previous, state=state, detail=detail, updated_at=time.time())
            self._services[name] = current
        self.events.emit("services.changed", current)

    def snapshot(self) -> tuple[ServiceStatus, ...]:
        with self._lock:
            return tuple(self._services.values())

    def clear(self) -> None:
        with self._lock:
            self._services.clear()
