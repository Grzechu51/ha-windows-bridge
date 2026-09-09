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
class ProviderSample:
    """Latest observation produced by one owned Windows provider.

    Value is a provider-domain immutable snapshot. A successful empty
    collection is represented by an empty value with GOOD quality; a failed
    read retains the previous value with degraded quality. This keeps a
    transient WMI/COM failure distinct from device or session removal.
    """

    source: str
    value: object
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
    providers: tuple[ProviderSample, ...] = ()
    health: tuple[ProviderHealth, ...] = ()

    def health_for(self, source: str) -> ProviderHealth | None:
        return next((item for item in self.health if item.source == source), None)

    def provider(self, source: str) -> ProviderSample | None:
        return next((item for item in self.providers if item.source == source), None)


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
            sources = {"master_audio"}
            sources.update(item.source for item in self._state.health)
            sources.update(item.source for item in self._state.providers)
            health = tuple(
                ProviderHealth(
                    source,
                    StateQuality.STOPPED,
                    now,
                    self._last_success_locked(source),
                    detail,
                )
                for source in sorted(sources)
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
        accept_if: Callable[[], bool] | None = None,
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
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
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

    def observe_provider(
        self,
        source: str,
        value: object,
        *,
        generation: int,
        quality: StateQuality = StateQuality.GOOD,
        detail: str = "",
        observed_at: float | None = None,
        observed_monotonic: float | None = None,
        accept_if: Callable[[], bool] | None = None,
    ) -> bool:
        """Accept one provider snapshot if it belongs to the active generation."""

        if not source:
            raise ValueError("Provider source is required")
        wall_now = self._wall_clock() if observed_at is None else float(observed_at)
        monotonic_now = (
            self._monotonic_clock()
            if observed_monotonic is None
            else float(observed_monotonic)
        )
        with self._lock:
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
                return False
            sample = ProviderSample(
                source,
                value,
                wall_now,
                monotonic_now,
                quality,
                detail,
            )
            providers = tuple(
                item for item in self._state.providers if item.source != source
            ) + (sample,)
            last_success = (
                wall_now
                if quality == StateQuality.GOOD
                else self._last_success_locked(source)
            )
            health = self._replace_health_locked(
                ProviderHealth(source, quality, wall_now, last_success, detail)
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=wall_now,
                providers=providers,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return True

    def observe_audio_provider(
        self,
        value: object,
        master: tuple[float, bool] | None,
        *,
        generation: int,
        provider_quality: StateQuality = StateQuality.GOOD,
        provider_detail: str = "",
        master_quality: StateQuality = StateQuality.GOOD,
        master_detail: str = "",
        accept_if: Callable[[], bool] | None = None,
        observed_at: float | None = None,
        observed_monotonic: float | None = None,
    ) -> bool:
        """Atomically commit the complete Core Audio observation.

        The provider snapshot and the master-audio projection share one
        revision. The lifecycle predicate is evaluated while the state lock is
        held, so a provider transition cannot be followed by a stale GOOD
        commit from an older sampling epoch.
        """

        wall_now = self._wall_clock() if observed_at is None else float(observed_at)
        monotonic_now = (
            self._monotonic_clock()
            if observed_monotonic is None
            else float(observed_monotonic)
        )
        if master is not None:
            volume, muted = float(master[0]), master[1]
            if not 0.0 <= volume <= 1.0 or not isinstance(muted, bool):
                raise ValueError("Invalid master audio observation")
        with self._lock:
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
                return False
            provider_sample = ProviderSample(
                "audio",
                value,
                wall_now,
                monotonic_now,
                provider_quality,
                provider_detail,
            )
            providers = tuple(
                item for item in self._state.providers if item.source != "audio"
            ) + (provider_sample,)
            provider_last_success = (
                wall_now
                if provider_quality == StateQuality.GOOD
                else self._last_success_locked("audio")
            )
            health = self._replace_health_locked(
                ProviderHealth(
                    "audio",
                    provider_quality,
                    wall_now,
                    provider_last_success,
                    provider_detail,
                )
            )
            current_master = self._state.master_audio
            if master is not None:
                current_master = MasterAudioState(
                    volume,
                    muted,
                    wall_now,
                    monotonic_now,
                    master_quality,
                    master_detail,
                )
            elif current_master is not None:
                current_master = replace(
                    current_master,
                    quality=master_quality,
                    detail=master_detail,
                )
            master_last_success = (
                wall_now
                if master is not None and master_quality == StateQuality.GOOD
                else self._last_success_locked("master_audio")
            )
            remaining_health = tuple(
                item for item in health if item.source != "master_audio"
            )
            health = (
                *remaining_health,
                ProviderHealth(
                    "master_audio",
                    master_quality,
                    wall_now,
                    master_last_success,
                    master_detail,
                ),
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=wall_now,
                master_audio=current_master,
                providers=providers,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return True

    def fail_provider(
        self,
        source: str,
        quality: StateQuality,
        detail: str,
        *,
        generation: int,
        accept_if: Callable[[], bool] | None = None,
    ) -> bool:
        """Degrade a provider without turning its last value into an empty result."""

        if quality not in {
            StateQuality.ERROR,
            StateQuality.UNAVAILABLE,
            StateQuality.PAUSED,
            StateQuality.STOPPED,
        }:
            raise ValueError("Failure quality must describe a degraded source")
        with self._lock:
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
                return False
            now = self._wall_clock()
            providers = tuple(
                replace(item, quality=quality, detail=detail)
                if item.source == source
                else item
                for item in self._state.providers
            )
            health = self._replace_health_locked(
                ProviderHealth(
                    source,
                    quality,
                    now,
                    self._last_success_locked(source),
                    detail,
                )
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=now,
                providers=providers,
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
        accept_if: Callable[[], bool] | None = None,
    ) -> bool:
        if quality not in {
            StateQuality.ERROR,
            StateQuality.UNAVAILABLE,
            StateQuality.PAUSED,
            StateQuality.STOPPED,
        }:
            raise ValueError("Failure quality must describe a degraded source")
        with self._lock:
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
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

    def fail_audio_provider(
        self,
        quality: StateQuality,
        detail: str,
        *,
        generation: int,
        accept_if: Callable[[], bool] | None = None,
    ) -> bool:
        """Atomically degrade both views owned by the Core Audio provider."""

        if quality not in {
            StateQuality.ERROR,
            StateQuality.UNAVAILABLE,
            StateQuality.PAUSED,
            StateQuality.STOPPED,
        }:
            raise ValueError("Failure quality must describe a degraded source")
        with self._lock:
            if generation != self._state.generation or (
                accept_if is not None and not accept_if()
            ):
                return False
            now = self._wall_clock()
            providers = tuple(
                replace(item, quality=quality, detail=detail)
                if item.source == "audio"
                else item
                for item in self._state.providers
            )
            master = self._state.master_audio
            if master is not None:
                master = replace(master, quality=quality, detail=detail)
            health = tuple(
                item
                for item in self._state.health
                if item.source not in {"audio", "master_audio"}
            )
            health = (
                *health,
                ProviderHealth(
                    "audio",
                    quality,
                    now,
                    self._last_success_locked("audio"),
                    detail,
                ),
                ProviderHealth(
                    "master_audio",
                    quality,
                    now,
                    self._last_success_locked("master_audio"),
                    detail,
                ),
            )
            current = replace(
                self._state,
                revision=self._state.revision + 1,
                updated_at=now,
                master_audio=master,
                providers=providers,
                health=health,
            )
            self._state = current
        self.events.emit("computer_state.changed", current)
        return True

    def snapshot(self, *, stale_after: float | None = None) -> ComputerState:
        with self._lock:
            current = self._state
        if stale_after is None:
            return current
        now = self._monotonic_clock()
        master = current.master_audio
        if (
            master is not None
            and master.quality == StateQuality.GOOD
            and now - master.observed_monotonic > stale_after
        ):
            master = replace(
                master,
                quality=StateQuality.STALE,
                detail="freshness_deadline_exceeded",
            )
        stale_sources = {
            item.source
            for item in current.providers
            if item.quality == StateQuality.GOOD
            and now - item.observed_monotonic > stale_after
        }
        providers = tuple(
            replace(
                item,
                quality=StateQuality.STALE,
                detail="freshness_deadline_exceeded",
            )
            if item.source in stale_sources
            else item
            for item in current.providers
        )
        health = tuple(
            replace(item, quality=StateQuality.STALE, detail="freshness_deadline_exceeded")
            if (
                item.quality == StateQuality.GOOD
                and (
                    (
                        item.source == "master_audio"
                        and master is not None
                        and master.quality == StateQuality.STALE
                    )
                    or item.source in stale_sources
                )
            )
            else item
            for item in current.health
        )
        return replace(
            current,
            master_audio=master,
            providers=providers,
            health=health,
        )

    def _replace_health_locked(self, replacement: ProviderHealth) -> tuple[ProviderHealth, ...]:
        remaining = tuple(item for item in self._state.health if item.source != replacement.source)
        return (*remaining, replacement)

    def _last_success_locked(self, source: str) -> float | None:
        previous = next((item for item in self._state.health if item.source == source), None)
        return previous.last_success_at if previous else None
