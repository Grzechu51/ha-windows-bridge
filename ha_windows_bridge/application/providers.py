"""Owned Windows providers and read-only views over ComputerState.

Each provider owns exactly one worker. Slow WMI/WUA/GPU reads therefore cannot
stall audio, media, desktop context, or another provider. Provider callbacks
only request a coalesced refresh; all Windows I/O stays on the owning worker.
"""
from __future__ import annotations

import inspect
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from typing import Any

from ..core.state import ComputerStateStore, StateQuality
from ..media import MediaSnapshot
from ..system_monitor import (
    DiskMetrics,
    DiskVolume,
    PcContext,
    PnpDevice,
    SystemMetrics,
    WindowsHealth,
)
from ..windows.com import ProviderUnavailable, com_apartment


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    volumes: tuple[DiskVolume, ...] = ()
    metrics: DiskMetrics = DiskMetrics(0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    devices: tuple[PnpDevice, ...] = ()


@dataclass(slots=True)
class _Request:
    callback: Callable[[], Any]
    refresh: bool = True
    completed: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    cancelled: bool = False


class _ProviderReadTimeout(RuntimeError):
    pass


class AdaptiveProvider:
    """One lifecycle owner with event-first refresh and bounded polling fallback."""

    def __init__(
        self,
        source: str,
        read: Callable[[], object],
        state: ComputerStateStore,
        generation: int,
        *,
        interval: float,
        maximum_interval: float,
        subscribe: Callable[[Callable[..., None]], Callable[[], None] | None] | None = None,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], bool | None] | None = None,
        owns_com: bool = False,
        capacity: int = 32,
        command_timeout: float = 3.0,
        stop_timeout: float = 3.0,
        read_timeout: float | None = None,
        comparison_key: Callable[[object], object] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        if not source:
            raise ValueError("Provider source is required")
        self.source = source
        self.read = read
        self.state = state
        self.generation = generation
        self.interval = max(0.05, float(interval))
        self.maximum_interval = max(self.interval, float(maximum_interval))
        self.subscribe = subscribe
        self.on_start = on_start
        self.on_stop = on_stop
        self.owns_com = owns_com
        self.capacity = max(1, int(capacity))
        self.command_timeout = max(0.01, float(command_timeout))
        self.stop_timeout = max(0.01, float(stop_timeout))
        self.read_timeout = (
            None if read_timeout is None else max(0.01, float(read_timeout))
        )
        self.comparison_key = comparison_key or (lambda value: value)
        self._clock = monotonic_clock
        self.log = logger or logging.getLogger("bridge.providers")
        self._condition = threading.Condition()
        self._pending: deque[_Request] = deque()
        self._thread: threading.Thread | None = None
        self._stopping = True
        self._paused = False
        self._refresh_requested = False
        self._epoch = 0
        self._last_value: object = _MISSING
        self._last_comparison: object = _MISSING
        self._current_interval = self.interval
        self._cleanup_ok = True
        self._io_thread: threading.Thread | None = None
        self._io_done: threading.Event | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError(f"{self.source} provider is already running")
            self._stopping = False
            self._paused = False
            self._refresh_requested = True
            self._epoch += 1
            self._cleanup_ok = True
            self._current_interval = self.interval
            self._thread = threading.Thread(
                target=self._run,
                name=f"provider-{self.source}-{self.generation}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> bool:
        deadline = time.monotonic() + self.stop_timeout
        with self._condition:
            self._stopping = True
            self._epoch += 1
            while self._pending:
                request = self._pending.popleft()
                request.cancelled = True
                request.completed.set()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        io_thread = self._io_thread
        if io_thread is not None and io_thread is not threading.current_thread():
            io_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        stopped = (
            (thread is None or not thread.is_alive())
            and (io_thread is None or not io_thread.is_alive())
            and self._cleanup_ok
        )
        self.state.fail_provider(
            self.source,
            StateQuality.STOPPED if stopped else StateQuality.ERROR,
            "provider_stopped" if stopped else "shutdown_timeout",
            generation=self.generation,
        )
        return stopped

    def pause(self, enabled: bool) -> None:
        with self._condition:
            self._paused = bool(enabled)
            self._epoch += 1
            if not enabled:
                self._refresh_requested = True
            self._condition.notify_all()
        if enabled:
            self.state.fail_provider(
                self.source,
                StateQuality.PAUSED,
                "sampling_paused",
                generation=self.generation,
            )

    def request_refresh(self, *_args: object) -> bool:
        """Coalesce arbitrary Windows callback bursts into one owner-thread read."""

        with self._condition:
            if self._stopping:
                return False
            self._refresh_requested = True
            self._current_interval = self.interval
            self._condition.notify_all()
            return True

    def call(self, callback: Callable[[], Any], *, refresh: bool = True) -> Any:
        if self._thread is threading.current_thread():
            result = callback()
            if refresh:
                self.request_refresh()
            return result
        request = _Request(callback, refresh)
        with self._condition:
            if self._stopping or self._thread is None or not self._thread.is_alive():
                return False
            if len(self._pending) >= self.capacity:
                return False
            self._pending.append(request)
            self._condition.notify_all()
        if not request.completed.wait(self.command_timeout):
            with self._condition:
                request.cancelled = True
            return False
        if request.error is not None:
            self.log.warning("%s command failed: %s", self.source, request.error)
            return False
        return request.result

    def refresh_now(self) -> bool:
        """Queue a synchronous refresh on the provider owner."""

        with self._condition:
            sample_epoch = self._epoch
        return bool(
            self.call(
                lambda: self._sample(sample_epoch),
                refresh=False,
            )
        )

    @property
    def is_alive(self) -> bool:
        with self._condition:
            owner_alive = self._thread is not None and self._thread.is_alive()
            io_alive = self._io_thread is not None and self._io_thread.is_alive()
            return owner_alive or io_alive

    @property
    def thread_ident(self) -> int | None:
        with self._condition:
            return self._thread.ident if self._thread is not None else None

    def _run(self) -> None:
        unsubscribe: Callable[[], None] | None = None
        owner_scope = com_apartment() if self.owns_com else nullcontext()
        try:
            with owner_scope:
                try:
                    if self.on_start is not None:
                        self.on_start()
                    if self.subscribe is not None:
                        try:
                            unsubscribe = self.subscribe(self.request_refresh)
                        except Exception:
                            self.log.warning(
                                "%s callbacks unavailable; using polling fallback",
                                self.source,
                                exc_info=True,
                            )
                    self._loop()
                finally:
                    if unsubscribe is not None:
                        unsubscribe()
                    if self.on_stop is not None:
                        self._cleanup_ok = self.on_stop() is not False
        except Exception:
            self._cleanup_ok = False
            self.log.exception("%s provider owner failed", self.source)
            self.state.fail_provider(
                self.source,
                StateQuality.ERROR,
                "owner_failed",
                generation=self.generation,
            )

    def _loop(self) -> None:
        next_read = self._clock()
        while True:
            request = None
            should_read = False
            sample_epoch = 0
            with self._condition:
                while not self._stopping and not self._pending:
                    now = self._clock()
                    should_read = (
                        not self._paused
                        and (self._refresh_requested or now >= next_read)
                    )
                    if should_read:
                        sample_epoch = self._epoch
                        self._refresh_requested = False
                        break
                    timeout = None if self._paused else max(0.0, next_read - now)
                    self._condition.wait(timeout)
                if self._stopping:
                    return
                if self._pending:
                    request = self._pending.popleft()
            if request is not None:
                self._execute_request(request)
                next_read = min(next_read, self._clock())
                continue
            if should_read:
                self._sample(sample_epoch)
                next_read = self._clock() + self._current_interval

    def _execute_request(self, request: _Request) -> None:
        if request.cancelled:
            request.completed.set()
            return
        try:
            request.result = request.callback()
            if request.refresh and request.result is not False:
                self.request_refresh()
        except BaseException as exc:
            request.error = exc
        finally:
            request.completed.set()

    def _sample(self, sample_epoch: int) -> bool:
        try:
            value = self._read_with_deadline()
        except _ProviderReadTimeout:
            quality = StateQuality.ERROR
            detail = "read_timeout"
        except ProviderUnavailable as exc:
            quality = StateQuality.UNAVAILABLE
            detail = str(exc) or "provider_unavailable"
        except Exception as exc:
            self.log.exception("%s provider read failed", self.source)
            quality = StateQuality.ERROR
            detail = str(exc) or "provider_error"
        else:
            if getattr(value, "supported", True) is False:
                detail = str(getattr(value, "error", "") or "provider_unavailable")
                self._current_interval = min(
                    self.maximum_interval,
                    max(self.interval, self._current_interval * 1.5),
                )
                return self.state.fail_provider(
                    self.source,
                    StateQuality.UNAVAILABLE,
                    detail,
                    generation=self.generation,
                    accept_if=lambda: self._sample_is_current(sample_epoch),
                )
            comparison = self.comparison_key(value)
            changed = (
                self._last_comparison is _MISSING
                or comparison != self._last_comparison
            )
            provider_errors = tuple(getattr(value, "provider_errors", ()) or ())
            quality = (
                StateQuality.UNAVAILABLE
                if provider_errors
                else StateQuality.GOOD
            )
            detail = ",".join(str(item) for item in provider_errors)
            accepted = self.state.observe_provider(
                self.source,
                value,
                generation=self.generation,
                quality=quality,
                detail=detail,
                accept_if=lambda: self._sample_is_current(sample_epoch),
            )
            if accepted:
                self._last_value = value
                self._last_comparison = comparison
                self._current_interval = (
                    self.interval
                    if changed
                    else min(self.maximum_interval, self._current_interval * 1.5)
                )
            return accepted
        self._current_interval = min(
            self.maximum_interval,
            max(self.interval, self._current_interval * 1.5),
        )
        return self.state.fail_provider(
            self.source,
            quality,
            detail,
            generation=self.generation,
            accept_if=lambda: self._sample_is_current(sample_epoch),
        )

    def _sample_is_current(self, sample_epoch: int) -> bool:
        # Called by ComputerStateStore while its own lock is held. Do not take
        # the provider condition here: pause/stop advance the epoch before
        # committing their health transition, and the store serializes the
        # final predicate check with the state write.
        return (
            not self._stopping
            and not self._paused
            and sample_epoch == self._epoch
        )

    def _read_with_deadline(self) -> object:
        if self.read_timeout is None:
            return self.read()
        previous = self._io_thread
        if previous is not None and previous.is_alive():
            raise _ProviderReadTimeout
        self._io_thread = None
        self._io_done = None
        done = threading.Event()
        outcome: list[tuple[bool, object]] = []

        def run() -> None:
            try:
                outcome.append((True, self.read()))
            except BaseException as exc:
                outcome.append((False, exc))
            finally:
                done.set()

        thread = threading.Thread(
            target=run,
            name=f"provider-{self.source}-io-{self.generation}",
            daemon=True,
        )
        self._io_thread = thread
        self._io_done = done
        thread.start()
        if not done.wait(self.read_timeout):
            raise _ProviderReadTimeout
        thread.join(timeout=0)
        self._io_thread = None
        self._io_done = None
        ok, value = outcome[0]
        if not ok:
            raise value  # type: ignore[misc]
        return value


_MISSING = object()


def stable_system_sample_key(value: object) -> object:
    """Exclude clocks/counters that do not represent a semantic change."""

    if isinstance(value, (SystemMetrics, WindowsHealth)):
        return replace(value, uptime_seconds=0)
    return value


class MediaProvider(AdaptiveProvider):
    """State-backed façade for the single WinRT/GSMTC owner."""

    def __init__(
        self,
        adapter,
        state: ComputerStateStore,
        generation: int,
        *,
        interval: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self.adapter = adapter
        try:
            execute_parameters = inspect.signature(adapter.execute).parameters
        except (AttributeError, TypeError, ValueError):
            execute_parameters = {}
        self._execute_supports_session_id = "session_id" in execute_parameters
        subscribe = getattr(adapter, "subscribe", None)
        super().__init__(
            "media",
            adapter.snapshot,
            state,
            generation,
            interval=interval,
            maximum_interval=max(5.0, interval * 10),
            subscribe=subscribe if callable(subscribe) else None,
            on_start=getattr(adapter, "reopen", None),
            on_stop=getattr(adapter, "close", None),
            command_timeout=3.5,
            stop_timeout=4.0,
            logger=logger,
        )

    def snapshot(self) -> MediaSnapshot:
        current = self.state.snapshot()
        sample = current.provider("media")
        if sample is not None:
            if sample.quality == StateQuality.GOOD:
                return sample.value
            value = sample.value
            return replace(
                value,
                state="idle",
                supported=False,
                error=sample.detail or sample.quality.value,
            )
        health = current.health_for("media")
        if health is not None and health.quality in {
            StateQuality.ERROR,
            StateQuality.UNAVAILABLE,
        }:
            return MediaSnapshot(supported=False, error=health.detail)
        return MediaSnapshot()

    def execute(
        self,
        action: str,
        value: float | None = None,
        *,
        session_id: str = "",
    ) -> bool:
        expected = session_id or self.snapshot().session_id
        if not expected:
            return False

        def command() -> bool:
            if self._execute_supports_session_id:
                return bool(self.adapter.execute(action, value, session_id=expected))
            return bool(self.adapter.execute(action, value))

        return bool(self.call(command))

    def reopen(self) -> None:
        # Lifecycle is owned by start(); retained for the old application seam.
        return None

    def close(self) -> bool:
        return self.stop()


class SystemProviderView:
    """Read-only compatibility façade backed exclusively by ComputerState."""

    def __init__(self, raw, state: ComputerStateStore) -> None:
        self.raw = raw
        self.state = state

    def _sample(self, source: str):
        sample = self.state.snapshot().provider(source)
        if sample is None:
            raise ProviderUnavailable(f"{source} has no successful observation")
        return sample

    def _value(self, source: str, default: object) -> object:
        sample = self._sample(source)
        if sample.quality != StateQuality.GOOD:
            raise ProviderUnavailable(
                sample.detail or f"{source} is {sample.quality.value}"
            )
        return sample.value

    def _optional_value(
        self,
        source: str,
    ) -> tuple[object | None, tuple[str, ...]]:
        try:
            sample = self._sample(source)
        except ProviderUnavailable:
            return None, (f"{source}:unavailable",)
        if sample.quality != StateQuality.GOOD:
            return sample.value, (
                f"{source}:{sample.detail or sample.quality.value}",
            )
        return sample.value, ()

    def context_snapshot(self) -> PcContext:
        return self._value("desktop_context", PcContext())  # type: ignore[return-value]

    def running_process_names(self, names: list[str]) -> set[str]:
        running = self._value("processes", frozenset())
        requested = {name.casefold() for name in names}
        return set(running) & requested  # type: ignore[arg-type]

    def system_metrics(
        self,
        include_cpu: bool = True,
        include_gpu: bool = True,
        include_ram: bool = True,
    ) -> SystemMetrics:
        errors: list[str] = []
        fast = SystemMetrics(0.0, 0.0, 0)
        if include_cpu or include_ram:
            candidate, provider_errors = self._optional_value("cpu_ram")
            errors.extend(provider_errors)
            if isinstance(candidate, SystemMetrics):
                fast = candidate
        cpu_hardware = SystemMetrics(0.0, 0.0, 0)
        if include_cpu:
            candidate, provider_errors = self._optional_value("cpu_hardware")
            errors.extend(provider_errors)
            if isinstance(candidate, SystemMetrics):
                cpu_hardware = candidate
        gpu = SystemMetrics(0.0, 0.0, 0)
        if include_gpu:
            candidate, provider_errors = self._optional_value("gpu")
            errors.extend(provider_errors)
            if isinstance(candidate, SystemMetrics):
                gpu = candidate
        result = replace(
            fast,
            gpu_percent=gpu.gpu_percent if include_gpu else None,
            gpu_temperature=gpu.gpu_temperature if include_gpu else None,
            gpu_power_watts=gpu.gpu_power_watts if include_gpu else None,
            gpu_memory_used_mb=gpu.gpu_memory_used_mb if include_gpu else None,
            gpu_memory_total_mb=gpu.gpu_memory_total_mb if include_gpu else None,
            gpu_clock_mhz=gpu.gpu_clock_mhz if include_gpu else None,
            gpu_fan_percent=gpu.gpu_fan_percent if include_gpu else None,
            gpu_fan_rpm=gpu.gpu_fan_rpm if include_gpu else None,
            cpu_temperature=(
                cpu_hardware.cpu_temperature if include_cpu else None
            ),
            cpu_power_watts=(
                cpu_hardware.cpu_power_watts if include_cpu else None
            ),
            cpu_vendor=cpu_hardware.cpu_vendor if include_cpu else "",
            gpu_vendor=gpu.gpu_vendor if include_gpu else "",
            provider_errors=tuple(
                dict.fromkeys(
                    (
                        *errors,
                        *(
                            f"cpu_ram:{item}"
                            for item in fast.provider_errors
                        ),
                        *(
                            f"cpu_hardware:{item}"
                            for item in cpu_hardware.provider_errors
                        ),
                        *(f"gpu:{item}" for item in gpu.provider_errors),
                    )
                )
            ),
        )
        if include_cpu and include_ram:
            return result
        return replace(
            result,
            cpu_percent=result.cpu_percent if include_cpu else 0.0,
            cpu_frequency_mhz=result.cpu_frequency_mhz if include_cpu else None,
            ram_percent=result.ram_percent if include_ram else 0.0,
            ram_used_gb=result.ram_used_gb if include_ram else None,
            ram_available_gb=result.ram_available_gb if include_ram else None,
            ram_total_gb=result.ram_total_gb if include_ram else None,
        )

    def windows_health(self) -> WindowsHealth:
        health = self._value("windows_health", WindowsHealth())
        try:
            update_sample = self._sample("windows_update")
        except ProviderUnavailable:
            return replace(health, windows_update_status="Unavailable")
        if update_sample.quality != StateQuality.GOOD:
            return replace(health, windows_update_status="Unavailable")
        updates = update_sample.value
        if isinstance(updates, int):
            status = f"{updates} update(s) available" if updates else "Up to date"
            return replace(health, windows_update_status=status)
        return health

    def list_disk_volumes(self) -> list[DiskVolume]:
        storage = self._value("storage", StorageSnapshot())
        return list(storage.volumes)  # type: ignore[union-attr]

    def disk_metrics(self, _mounts: list[str] | None = None) -> DiskMetrics:
        storage = self._value("storage", StorageSnapshot())
        return storage.metrics  # type: ignore[union-attr,return-value]

    def list_pnp_devices(self, include_disconnected: bool = False) -> list[PnpDevice]:
        devices = self._value("pnp", DeviceSnapshot())
        visible = list(devices.devices)  # type: ignore[union-attr]
        return visible if include_disconnected else [item for item in visible if item.present]

    def present_device_ids(self) -> set[str]:
        return {
            item.instance_id.casefold()
            for item in self.list_pnp_devices()
            if item.present
        }

    def start_application(self, *args: object, **kwargs: object) -> bool:
        return bool(self.raw.start_application(*args, **kwargs))

    def close_application(self, process_name: str) -> int:
        return int(self.raw.close_application(process_name))
