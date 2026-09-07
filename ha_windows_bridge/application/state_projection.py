"""HA state projections fed exclusively by ComputerState."""
from __future__ import annotations

import threading

from ..core.state import ComputerState, ComputerStateStore, StateQuality
from ..discovery import master_mute_topics, master_volume_topics


class MasterAudioProjection:
    """Project master audio to the existing HA MQTT topics via StateOutbox."""

    def __init__(
        self,
        config,
        state: ComputerStateStore,
        publisher,
        events,
        generation: int,
    ) -> None:
        self.config = config
        self.state = state
        self.publisher = publisher
        self.events = events
        self.generation = generation
        self._unsubscribe = None
        self._lock = threading.RLock()
        self._last_revision = -1
        self._first_sample_seen = False
        self._last_volume: float | None = None
        self._last_mute: bool | None = None

    def start(self) -> None:
        if self._unsubscribe is not None:
            raise RuntimeError("Master audio projection is already running")
        self._unsubscribe = self.events.subscribe(
            "computer_state.changed",
            lambda event: self._project(event.data),
        )
        self._project(self.state.snapshot())

    def stop(self) -> bool:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        return True

    def _project(self, state: ComputerState) -> None:
        with self._lock:
            if (
                state.generation != self.generation
                or state.revision <= self._last_revision
            ):
                return
            master = state.master_audio
            if master is None or master.quality != StateQuality.GOOD:
                # Degraded/newer state still fences delayed good callbacks.
                self._last_revision = state.revision
                return
            if not self._first_sample_seen:
                self._first_sample_seen = True
                if not self.config.publish_initial_state:
                    self._last_volume = master.volume
                    self._last_mute = master.muted
                    self._last_revision = state.revision
                    return

            volume_changed = (
                self._last_volume is None
                or abs(self._last_volume - master.volume) >= 0.005
            )
            mute_changed = self._last_mute is None or self._last_mute != master.muted
            accepted = True
            if volume_changed:
                _, topic = master_volume_topics(self.config)
                accepted = self.publisher.publish_observation(
                    topic,
                    str(round(master.volume * 100)),
                    qos=1,
                    generation=state.generation,
                    revision=state.revision,
                ) and accepted
            if mute_changed:
                _, topic = master_mute_topics(self.config)
                accepted = self.publisher.publish_observation(
                    topic,
                    "ON" if master.muted else "OFF",
                    qos=1,
                    generation=state.generation,
                    revision=state.revision,
                ) and accepted
            if not accepted:
                return
            self._last_volume = master.volume
            self._last_mute = master.muted
            self._last_revision = state.revision
