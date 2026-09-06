"""Retain the latest observation independently of transport acceptance.

Phase 0 keeps the existing wire contract. A successful send means Paho accepted
it locally, not PUBACK. Every connection requests a complete retained replay.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ..core.events import EventBus


@dataclass(frozen=True)
class _Observation:
    payload: str | bytes
    qos: int


class StatePublisher:
    def __init__(self, transport, events: EventBus):
        self.transport, self.events = transport, events
        self._lock = threading.Lock()
        self._cache: dict[str, _Observation] = {}
        self._dirty: set[str] = set()
        self._session = 0
        self._sending = False
        self.log = logging.getLogger("bridge.publishing")

    @property
    def connected(self):
        return self.transport.connected

    def publish(self, topic, payload, *, qos=1, retain=True):
        if not retain:
            return self.transport.publish(topic, payload, qos=qos, retain=False)
        observation = _Observation(payload, qos)
        with self._lock:
            if self._cache.get(topic) != observation:
                self._cache[topic] = observation
                self._dirty.add(topic)
            if topic not in self._dirty:
                return True
        self.flush()
        with self._lock:
            return topic not in self._dirty

    def request_replay(self):
        """Network callbacks only schedule work; the publishing owner drains it."""
        with self._lock:
            self._session += 1
            self._dirty.update(self._cache)

    def replay(self):
        self.request_replay()
        return self.flush()

    def flush(self):
        """One bounded pass, serialized without holding a lock across any I/O.

        Concurrent/reentrant callers leave work dirty for the next scheduler
        pass. A late send result cannot acknowledge a newer observation/session.
        """
        with self._lock:
            if self._sending:
                return False
            self._sending = True
            topics = tuple(topic for topic in self._cache if topic in self._dirty)
        try:
            for topic in topics:
                with self._lock:
                    observation = self._cache[topic]
                    session = self._session
                try:
                    accepted = self.transport.publish(
                        topic, observation.payload, qos=observation.qos, retain=True)
                except Exception:
                    self.log.exception("State send failed; observation remains pending")
                    accepted = False
                if not accepted:
                    continue
                with self._lock:
                    if self._cache[topic] is observation and self._session == session:
                        self._dirty.discard(topic)
                self.events.emit("telemetry.published", topic)
        finally:
            with self._lock:
                self._sending = False
        with self._lock:
            return not self._dirty
