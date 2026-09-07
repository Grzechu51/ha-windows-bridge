"""Project ComputerState snapshots into the transport-neutral protocol v3 model."""
from __future__ import annotations

import logging
import threading


class ProtocolStateProjection:
    def __init__(self, state, publisher, events, protocol, generation: int):
        self.state, self.publisher, self.events = state, publisher, events
        self.protocol, self.generation = protocol, generation
        self.log = logging.getLogger("bridge.protocol_projection")
        self._lock = threading.Lock()
        self._unsubscribe = None
        self._stopped = True
        self._last_revision = -1

    def start(self):
        with self._lock:
            if not self._stopped:
                raise RuntimeError("Protocol state projection is already running")
            self._stopped = False
            self._last_revision = -1
        self._unsubscribe = self.events.subscribe(
            "computer_state.changed", lambda event: self._project(event.data)
        )
        self._project(self.state.snapshot())

    def stop(self):
        with self._lock:
            self._stopped = True
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        return True

    def _project(self, state):
        with self._lock:
            if (
                self._stopped
                or state.generation != self.generation
                or state.revision < self._last_revision
            ):
                return
        message = self.protocol.snapshot(state)
        try:
            accepted = self.publisher.publish_observation(
                self.protocol.snapshot_topic,
                message.encode(),
                qos=1,
                generation=self.generation,
                revision=state.revision,
            )
        except Exception:
            self.log.exception("Protocol snapshot projection failed")
            return
        if accepted:
            with self._lock:
                if not self._stopped and state.revision >= self._last_revision:
                    self._last_revision = state.revision
