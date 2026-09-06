"""Single-thread owner for the master Windows audio endpoint."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.state import ComputerStateStore, StateQuality


@dataclass(slots=True)
class _Request:
    callback: Callable[[], Any]
    completed: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None
    cancelled: bool = False


class MasterAudioProvider:
    """Own polling and commands for master audio on exactly one thread."""

    def __init__(
        self,
        adapter,
        state: ComputerStateStore,
        generation: int,
        *,
        poll_interval: float,
        command_timeout: float = 3.0,
        capacity: int = 32,
        logger: logging.Logger | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.state = state
        self.generation = generation
        self.poll_interval = poll_interval
        self.command_timeout = command_timeout
        self.capacity = capacity
        self.log = logger or logging.getLogger("bridge.master_audio")
        self._clock = monotonic_clock
        self._condition = threading.Condition()
        self._pending: deque[_Request] = deque()
        self._thread: threading.Thread | None = None
        self._stopping = True
        self._paused = False
        self._sample_requested = False

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Master audio provider is already running")
            self._stopping = False
            self._paused = False
            self._sample_requested = True
            self._thread = threading.Thread(
                target=self._run,
                name=f"master-audio-{self.generation}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> bool:
        with self._condition:
            self._stopping = True
            while self._pending:
                request = self._pending.popleft()
                request.cancelled = True
                request.completed.set()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        stopped = thread is None or not thread.is_alive()
        if stopped:
            self.state.fail_master_audio(
                StateQuality.STOPPED,
                "provider_stopped",
                generation=self.generation,
            )
        return stopped

    def pause(self, enabled: bool) -> None:
        with self._condition:
            self._paused = enabled
            if not enabled:
                self._sample_requested = True
            self._condition.notify_all()
        if enabled:
            self.state.fail_master_audio(
                StateQuality.PAUSED,
                "sampling_paused",
                generation=self.generation,
            )

    def set_master_volume(self, volume: float) -> bool:
        def command() -> bool:
            changed = bool(self.adapter.set_master_volume(volume))
            if changed:
                self._sample()
            return changed

        return bool(self._call(command))

    def set_master_mute(self, muted: bool) -> bool:
        def command() -> bool:
            changed = bool(self.adapter.set_master_mute(muted))
            if changed:
                self._sample()
            return changed

        return bool(self._call(command))

    def get_master_balance(self) -> float | None:
        result = self._call(self.adapter.get_master_balance)
        return float(result) if result is not None and result is not False else None

    def set_master_balance(self, balance: float) -> bool:
        return bool(self._call(lambda: self.adapter.set_master_balance(balance)))

    def sample_now(self) -> bool:
        return bool(self._call(self._sample))

    @property
    def is_alive(self) -> bool:
        with self._condition:
            return self._thread is not None and self._thread.is_alive()

    @property
    def thread_ident(self) -> int | None:
        with self._condition:
            return self._thread.ident if self._thread is not None else None

    def _call(self, callback: Callable[[], Any]) -> Any:
        if self._thread is threading.current_thread():
            return callback()
        request = _Request(callback)
        with self._condition:
            if self._stopping or self._thread is None or not self._thread.is_alive():
                return False
            if len(self._pending) >= self.capacity:
                return False
            self._pending.append(request)
            self._condition.notify()
        if not request.completed.wait(self.command_timeout):
            with self._condition:
                request.cancelled = True
            return False
        if request.error is not None:
            self.log.warning("Master audio command failed", exc_info=request.error)
            return False
        return request.result

    def _run(self) -> None:
        next_sample = self._clock()
        while True:
            request = None
            should_sample = False
            with self._condition:
                while not self._stopping and not self._pending:
                    now = self._clock()
                    should_sample = self._sample_requested or (
                        not self._paused and now >= next_sample
                    )
                    if should_sample:
                        break
                    timeout = None if self._paused else max(0.0, next_sample - now)
                    self._condition.wait(timeout)
                if self._stopping:
                    return
                if self._pending:
                    request = self._pending.popleft()
                else:
                    self._sample_requested = False
                    should_sample = not self._paused
            if request is not None:
                if request.cancelled:
                    request.completed.set()
                    continue
                try:
                    request.result = request.callback()
                except Exception as exc:
                    request.error = exc
                finally:
                    request.completed.set()
                next_sample = self._clock() + self.poll_interval
            elif should_sample:
                self._sample()
                next_sample = self._clock() + self.poll_interval

    def _sample(self) -> bool:
        try:
            snapshot = self.adapter.get_master_snapshot()
        except Exception:
            self.log.exception("Master audio sample failed")
            self.state.fail_master_audio(
                StateQuality.ERROR,
                "provider_error",
                generation=self.generation,
            )
            return False
        if snapshot is None:
            self.state.fail_master_audio(
                StateQuality.UNAVAILABLE,
                "endpoint_unavailable",
                generation=self.generation,
            )
            return False
        return self.state.observe_master_audio(
            snapshot.volume,
            snapshot.muted,
            generation=self.generation,
        )
