"""State publication cache. Network code never enumerates Windows devices."""
from __future__ import annotations

import threading

from ..core.events import EventBus


class StatePublisher:
    def __init__(self, transport, events: EventBus):
        self.transport, self.events = transport, events
        self._lock = threading.RLock()
        self._cache: dict[str, str | bytes] = {}

    @property
    def connected(self):
        return self.transport.connected

    def publish(self, topic, payload, *, qos=1, retain=True):
        with self._lock:
            if retain and self._cache.get(topic) == payload:
                return True
            if not self.transport.publish(topic, payload, qos=qos, retain=retain):
                return False
            if retain:
                self._cache[topic] = payload
        self.events.emit("telemetry.published", topic)
        return True

    def replay(self):
        with self._lock:
            for topic, payload in self._cache.items():
                self.transport.publish(topic, payload, retain=True)
