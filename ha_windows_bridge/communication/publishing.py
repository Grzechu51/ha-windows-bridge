"""Project the latest state outbox onto the existing MQTT wire contract."""
from __future__ import annotations

import logging

from ..core.events import EventBus
from .state_outbox import OutboxItem, StateOutbox


class StatePublisher:
    def __init__(
        self,
        transport,
        events: EventBus,
        *,
        outbox: StateOutbox | None = None,
        generation: int = 0,
    ):
        self.transport, self.events = transport, events
        self.outbox = outbox or StateOutbox(generation=generation)
        self.log = logging.getLogger("bridge.publishing")

    @property
    def connected(self):
        return self.transport.connected

    def begin_generation(self, generation: int) -> None:
        if generation != self.outbox.generation:
            self.outbox.begin_generation(generation)

    def publish(
        self,
        topic,
        payload,
        *,
        qos=1,
        retain=True,
        generation: int | None = None,
        revision: int | None = None,
    ):
        if not retain:
            return self.transport.publish(topic, payload, qos=qos, retain=False)
        observed = self._observe_retained(
            topic,
            payload,
            qos=qos,
            generation=generation,
            revision=revision,
        )
        if not observed:
            return False
        if not self.outbox.is_dirty(topic):
            return True
        self.flush()
        return not self.outbox.is_dirty(topic)

    def publish_observation(
        self,
        topic,
        payload,
        *,
        qos=1,
        generation: int | None = None,
        revision: int | None = None,
    ) -> bool:
        """Accept a retained observation independently of transport delivery."""

        observed = self._observe_retained(
            topic,
            payload,
            qos=qos,
            generation=generation,
            revision=revision,
        )
        if observed and self.outbox.is_dirty(topic):
            self.flush()
        return observed

    def _observe_retained(
        self,
        topic,
        payload,
        *,
        qos: int,
        generation: int | None,
        revision: int | None,
    ) -> bool:
        try:
            return self.outbox.observe(
                topic,
                payload,
                qos=qos,
                retain=True,
                generation=generation,
                revision=revision,
            )
        except OverflowError:
            self.log.error("State outbox is full; rejected new key: %s", topic)
            return False

    def request_replay(self):
        """Network callbacks only schedule work; the publishing owner drains it."""
        self.outbox.request_replay()

    def replay(self):
        self.request_replay()
        return self.flush()

    def flush(self):
        def send(item: OutboxItem) -> bool:
            try:
                return self.transport.publish(
                    item.key,
                    item.payload,
                    qos=item.qos,
                    retain=item.retain,
                )
            except Exception:
                self.log.exception("State send failed; observation remains pending")
                return False

        return self.outbox.flush(
            send,
            lambda item: self.events.emit("telemetry.published", item.key),
        )
