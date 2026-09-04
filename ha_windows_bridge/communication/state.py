"""Connection transitions with generations: stale callbacks cannot reconnect a stopped service."""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from enum import StrEnum

from ..core.events import EventBus


class ConnectionState(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RETRY_WAIT = "retry_wait"
    SUSPENDED = "suspended"
    AUTH_ERROR = "auth_error"
    CONFIGURATION_ERROR = "configuration_error"


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    transport: str
    state: ConnectionState
    attempt: int = 0
    error: str = ""


class ConnectionMachine:
    def __init__(self, name: str, events: EventBus):
        self.name, self.events = name, events
        self._lock = threading.RLock()
        self._epoch = 0
        self._status = ConnectionStatus(name, ConnectionState.STOPPED)

    @property
    def status(self) -> ConnectionStatus:
        with self._lock:
            return self._status

    def begin(self) -> int:
        with self._lock:
            self._epoch += 1
            self._set(ConnectionState.CONNECTING)
            return self._epoch

    def connected(self, epoch: int) -> bool:
        with self._lock:
            if epoch != self._epoch or self._status.state != ConnectionState.CONNECTING:
                return False
            self._set(ConnectionState.CONNECTED)
            return True

    def failed(self, epoch: int, code: str, *, authentication: bool = False, configuration: bool = False) -> bool:
        with self._lock:
            if epoch != self._epoch or self._status.state not in {ConnectionState.CONNECTING, ConnectionState.CONNECTED}:
                return False
            state = ConnectionState.AUTH_ERROR if authentication else ConnectionState.CONFIGURATION_ERROR if configuration else ConnectionState.RETRY_WAIT
            self._set(state,
                      self._status.attempt + 1, code)
            return True

    def retry(self, epoch: int) -> bool:
        with self._lock:
            if epoch != self._epoch or self._status.state != ConnectionState.RETRY_WAIT:
                return False
            self._set(ConnectionState.CONNECTING, self._status.attempt)
            return True

    def stop(self, *, suspended: bool = False) -> None:
        with self._lock:
            self._epoch += 1
            self._set(ConnectionState.SUSPENDED if suspended else ConnectionState.STOPPED)

    def _set(self, state: ConnectionState, attempt: int = 0, error: str = "") -> None:
        self._status = ConnectionStatus(self.name, state, attempt, error)
        self.events.emit("connection.changed", self._status)


@dataclass(frozen=True, slots=True)
class Backoff:
    minimum: float = 1.0
    maximum: float = 30.0

    def delay(self, attempt: int, random_value: float | None = None) -> float:
        jitter = random.random() if random_value is None else max(0.0, min(1.0, random_value))
        base = min(self.maximum, self.minimum * 2 ** min(16, max(0, attempt - 1)))
        return base * (0.75 + 0.25 * jitter)
