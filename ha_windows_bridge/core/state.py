"""Immutable runtime snapshots shared by UI, projections and diagnostics."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from .events import EventBus


class ServiceState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class StateQuality(StrEnum):
    """Quality of an observation, independent of feature availability."""

    GOOD = "good"
    STALE = "stale"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    PAUSED = "paused"
    STOPPED = "stopped"


# SampleQuality is the term used by providers; keep both names explicit at
# the domain boundary so callers do not need a second enum.
SampleQuality = StateQuality


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    source: str
    quality: StateQuality
    checked_at: float
    last_success_at: float | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MasterAudioState:
    volume: float
    muted: bool
    observed_at: float
    observed_monotonic: float
    quality: StateQuality = StateQuality.GOOD
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ComputerState:
    """One immutable view of the currently observed Windows state."""

    generation: int = 0
    revision: int = 0
    updated_at: float = 0.0
    master_audio: MasterAudioState | None = None
    health: tuple[ProviderHealth, ...] = ()

    def health_for(self, source: str) -> ProviderHealth | None:
        return next((item for item in self.health if item.source == source), None)


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


class ComputerStateStore:
    """Thread-safe owner of the latest ComputerState snapshot.

    Providers may only update the generation they were created for. Events are
    emitted after releasing the data lock, so UI and transport callbacks cannot
    participate in a lock cycle with Windows I/O.
    """

    def __init__(
        self,
        events: EventBus,
        *,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.events = events
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._lock = threading.RLock()
        self._state = ComputerState(updated_at=wall_clock())

    def begin_generation(self, generation: int, *, detail: str = "starting") -> ComputerState:
        """Invalidate old callbacks and start an empty runtime generation."""

        with self._lock:
            if generation <= self._state.generation:
                raise ValueError("ComputerState generation must increase")
            now = self._wall_clock()
            health = (
                ProviderHealth(
                    "master_audio",
                    StateQuality.STOPPED,
                    now,
                    self._last_success_locked("master_audio"),
                    detail,
                ),
            )
            current = ComputerState(
                generation=generation,
                revision=self._state.revision + 1,
                updated_at=now,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return current

    def observe_master_audio(
        self,
        volume: float,
        muted: bool,
        *,
        generation: int,
        observed_at: float | None = None,
        observed_monotonic: float | None = None,
    ) -> bool:
        volume = float(volume)
        if not 0.0 <= volume <= 1.0 or not isinstance(muted, bool):
            raise ValueError("Invalid master audio observation")
        wall_now = self._wall_clock() if observed_at is None else float(observed_at)
        monotonic_now = (
            self._monotonic_clock()
            if observed_monotonic is None
            else float(observed_monotonic)
        )
        with self._lock:
            if generation != self._state.generation:
                return False
            master = MasterAudioState(volume, muted, wall_now, monotonic_now)
            health = self._replace_health_locked(
                ProviderHealth(
                    "master_audio",
                    StateQuality.GOOD,
                    wall_now,
                    wall_now,
                )
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=wall_now,
                master_audio=master,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return True

    def fail_master_audio(
        self,
        quality: StateQuality,
        detail: str,
        *,
        generation: int,
    ) -> bool:
        if quality not in {
            StateQuality.ERROR,
            StateQuality.UNAVAILABLE,
            StateQuality.PAUSED,
            StateQuality.STOPPED,
        }:
            raise ValueError("Failure quality must describe a degraded source")
        with self._lock:
            if generation != self._state.generation:
                return False
            now = self._wall_clock()
            master = self._state.master_audio
            if master is not None:
                master = replace(master, quality=quality, detail=detail)
            health = self._replace_health_locked(
                ProviderHealth(
                    "master_audio",
                    quality,
                    now,
                    self._last_success_locked("master_audio"),
                    detail,
                )
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=now,
                master_audio=master,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return True

    def snapshot(self, *, stale_after: float | None = None) -> ComputerState:
        with self._lock:
            current = self._state
        if (
            stale_after is None
            or current.master_audio is None
            or current.master_audio.quality != StateQuality.GOOD
            or self._monotonic_clock() - current.master_audio.observed_monotonic <= stale_after
        ):
            return current
        master = replace(
            current.master_audio,
            quality=StateQuality.STALE,
            detail="freshness_deadline_exceeded",
        )
        health = tuple(
            replace(item, quality=StateQuality.STALE, detail="freshness_deadline_exceeded")
            if item.source == "master_audio"
            else item
            for item in current.health
        )
        return replace(current, master_audio=master, health=health)

    def _replace_health_locked(self, replacement: ProviderHealth) -> tuple[ProviderHealth, ...]:
        remaining = tuple(item for item in self._state.health if item.source != replacement.source)
        return (*remaining, replacement)

    def _last_success_locked(self, source: str) -> float | None:
        previous = next((item for item in self._state.health if item.source == source), None)
        return previous.last_success_at if previous else None
