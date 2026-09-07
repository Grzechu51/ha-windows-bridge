"""Bounded projected-state outbox with separate observation and delivery state."""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutboxItem:
    key: str
    payload: str | bytes
    qos: int
    retain: bool
    generation: int
    revision: int


@dataclass(frozen=True, slots=True)
class DeliveredState:
    """State acknowledged as delivered by the current transport session."""

    key: str
    generation: int
    revision: int
    session: int


class StateOutbox:
    """Keep the newest projected state regardless of transport failures.

    The outbox never becomes a second source of Windows truth: values arrive
    with a ComputerState revision. A new value replaces an older value for the
    same key, while delivery is acknowledged only if generation, session and
    revision still match after I/O completes.
    """

    def __init__(self, *, capacity: int = 2048, generation: int = 0) -> None:
        if capacity <= 0:
            raise ValueError("StateOutbox capacity must be positive")
        self.capacity = capacity
        self._lock = threading.Lock()
        self._observed: OrderedDict[str, OutboxItem] = OrderedDict()
        self._delivered: dict[str, DeliveredState] = {}
        self._dirty: set[str] = set()
        self._inflight: dict[str, tuple[int, int, int]] = {}
        self._generation = generation
        self._session = 0
        self._next_revision = 0
        self._sending = False

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin_generation(self, generation: int) -> None:
        with self._lock:
            if generation <= self._generation:
                raise ValueError("StateOutbox generation must increase")
            self._generation = generation
            self._session += 1
            self._observed.clear()
            self._delivered.clear()
            self._dirty.clear()
            self._inflight.clear()

    def observe(
        self,
        key: str,
        payload: str | bytes,
        *,
        qos: int = 1,
        retain: bool = True,
        generation: int | None = None,
        revision: int | None = None,
    ) -> bool:
        if not key:
            raise ValueError("StateOutbox key must not be empty")
        with self._lock:
            selected_generation = self._generation if generation is None else generation
            if selected_generation != self._generation:
                return False
            if key not in self._observed and len(self._observed) >= self.capacity:
                raise OverflowError("StateOutbox capacity exceeded")
            if revision is None:
                self._next_revision += 1
                selected_revision = self._next_revision
            else:
                selected_revision = int(revision)
                self._next_revision = max(self._next_revision, selected_revision)
            previous = self._observed.get(key)
            if previous is not None and selected_revision < previous.revision:
                return False
            if (
                previous is not None
                and selected_revision == previous.revision
                and (
                    previous.payload != payload
                    or previous.qos != int(qos)
                    or previous.retain != bool(retain)
                )
            ):
                return False
            item = OutboxItem(
                key,
                payload,
                int(qos),
                bool(retain),
                selected_generation,
                selected_revision,
            )
            if previous == item:
                return True
            if (
                previous is not None
                and previous.payload == item.payload
                and previous.qos == item.qos
                and previous.retain == item.retain
                and key not in self._dirty
            ):
                self._observed[key] = item
                delivered = self._delivered.get(key)
                if delivered is not None:
                    self._delivered[key] = DeliveredState(
                        key,
                        item.generation,
                        item.revision,
                        delivered.session,
                    )
                return True
            self._observed[key] = item
            self._observed.move_to_end(key)
            self._dirty.add(key)
            self._inflight.pop(key, None)
            return True

    def request_replay(self) -> None:
        with self._lock:
            self._session += 1
            self._dirty.update(self._observed)
            self._inflight.clear()

    def flush(
        self,
        send: Callable[[OutboxItem], bool],
        delivered: Callable[[OutboxItem], None] | None = None,
    ) -> bool:
        """Attempt one bounded pass without holding the data lock during I/O."""

        with self._lock:
            if self._sending:
                return False
            self._sending = True
            generation = self._generation
            session = self._session
            items = tuple(
                item for key, item in self._observed.items() if key in self._dirty
            )
        try:
            for item in items:
                try:
                    accepted = bool(send(item))
                except Exception:
                    accepted = False
                if not accepted:
                    continue
                acknowledged = False
                with self._lock:
                    if (
                        self._generation == generation
                        and self._session == session
                        and self._observed.get(item.key) == item
                    ):
                        self._dirty.discard(item.key)
                        self._delivered[item.key] = DeliveredState(
                            item.key,
                            item.generation,
                            item.revision,
                            session,
                        )
                        acknowledged = True
                if acknowledged and delivered is not None:
                    delivered(item)
        finally:
            with self._lock:
                self._sending = False
        with self._lock:
            return not self._dirty

    def flush_confirmed(
        self,
        send: Callable[[OutboxItem, Callable[[bool], None]], bool],
        delivered: Callable[[OutboxItem], None] | None = None,
    ) -> bool:
        """Dispatch one pass and clear items only from matching PUBACK callbacks."""

        with self._lock:
            if self._sending:
                return False
            self._sending = True
            generation = self._generation
            session = self._session
            items = tuple(
                item for key, item in self._observed.items()
                if key in self._dirty and key not in self._inflight
            )
        try:
            for item in items:
                attempt = (generation, session, item.revision)
                with self._lock:
                    if (
                        self._generation != generation
                        or self._session != session
                        or self._observed.get(item.key) != item
                    ):
                        continue
                    self._inflight[item.key] = attempt

                def acknowledge(success: bool, selected=item, selected_attempt=attempt) -> None:
                    emitted = False
                    with self._lock:
                        if self._inflight.get(selected.key) != selected_attempt:
                            return
                        self._inflight.pop(selected.key, None)
                        if (
                            success
                            and
                            self._generation == generation
                            and self._session == session
                            and self._observed.get(selected.key) == selected
                        ):
                            self._dirty.discard(selected.key)
                            self._delivered[selected.key] = DeliveredState(
                                selected.key,
                                selected.generation,
                                selected.revision,
                                session,
                            )
                            emitted = True
                    if emitted and delivered is not None:
                        delivered(selected)

                try:
                    accepted = bool(send(item, acknowledge))
                except Exception:
                    accepted = False
                if not accepted:
                    acknowledge(False)
        finally:
            with self._lock:
                self._sending = False
        with self._lock:
            return not self._dirty

    def is_dirty(self, key: str) -> bool:
        with self._lock:
            return key in self._dirty

    def observed(self) -> tuple[OutboxItem, ...]:
        with self._lock:
            return tuple(self._observed.values())

    def delivered(self) -> tuple[DeliveredState, ...]:
        with self._lock:
            return tuple(self._delivered.values())

    def pending(self) -> tuple[OutboxItem, ...]:
        with self._lock:
            return tuple(
                item for key, item in self._observed.items() if key in self._dirty
            )
