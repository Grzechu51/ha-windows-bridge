"""HA state projections fed exclusively by ComputerState."""
from __future__ import annotations

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
        self._last_volume: float | None = None
        self._last_mute: bool | None = None

    def start(self) -> None:
        if self._unsubscribe is not None:
            raise RuntimeError("Master audio projection is already running")
        self._unsubscribe = self.events.subscribe(
            "computer_state.changed",
            lambda event: self._project(event.data),
        )
        current = self.state.snapshot()
        if self.config.publish_initial_state:
            self._project(current)
        elif current.master_audio is not None:
            self._last_volume = current.master_audio.volume
            self._last_mute = current.master_audio.muted

    def stop(self) -> bool:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        return True

    def _project(self, state: ComputerState) -> None:
        master = state.master_audio
        if (
            state.generation != self.generation
            or master is None
            or master.quality != StateQuality.GOOD
        ):
            return
        if (
            self._last_volume is None
            or abs(self._last_volume - master.volume) >= 0.005
        ):
            self._last_volume = master.volume
            _, topic = master_volume_topics(self.config)
            self.publisher.publish(
                topic,
                str(round(master.volume * 100)),
                qos=1,
                retain=True,
                generation=state.generation,
                revision=state.revision,
            )
        if self._last_mute is None or self._last_mute != master.muted:
            self._last_mute = master.muted
            _, topic = master_mute_topics(self.config)
            self.publisher.publish(
                topic,
                "ON" if master.muted else "OFF",
                qos=1,
                retain=True,
                generation=state.generation,
                revision=state.revision,
            )
