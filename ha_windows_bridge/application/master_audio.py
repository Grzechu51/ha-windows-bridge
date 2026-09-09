"""Single-thread owner for the master Windows audio endpoint."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from ..audio import (
    AudioApplication,
    AudioOutputDevice,
    AudioProviderSnapshot,
    AudioSessionSnapshot,
    MicrophoneSnapshot,
)
from ..core.state import ComputerStateStore, StateQuality
from ..windows.com import com_apartment


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
        process_names: tuple[str, ...] = (),
        include_sessions: bool = False,
        include_microphone: bool = False,
        include_outputs: bool = False,
        command_timeout: float = 3.0,
        capacity: int = 32,
        logger: logging.Logger | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.state = state
        self.generation = generation
        self.poll_interval = poll_interval
        self.maximum_poll_interval = max(5.0, poll_interval * 10)
        self.process_names = tuple(process_names)
        self.include_sessions = include_sessions
        self.include_microphone = include_microphone
        self.include_outputs = include_outputs
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
        self._sample_epoch = 0
        self._last_snapshot = AudioProviderSnapshot()
        self._subscription = None
        self._current_poll_interval = self.poll_interval
        self._cleanup_ok = True

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Master audio provider is already running")
            self._stopping = False
            self._paused = False
            self._sample_requested = True
            self._sample_epoch += 1
            self._current_poll_interval = self.poll_interval
            self._cleanup_ok = True
            self._thread = threading.Thread(
                target=self._run,
                name=f"master-audio-{self.generation}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> bool:
        with self._condition:
            self._stopping = True
            self._sample_epoch += 1
            while self._pending:
                request = self._pending.popleft()
                request.cancelled = True
                request.completed.set()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        stopped = (thread is None or not thread.is_alive()) and self._cleanup_ok
        quality = StateQuality.STOPPED if stopped else StateQuality.ERROR
        detail = "provider_stopped" if stopped else "shutdown_or_cleanup_failed"
        self.state.fail_audio_provider(
            quality,
            detail,
            generation=self.generation,
        )
        return stopped

    def pause(self, enabled: bool) -> None:
        with self._condition:
            self._paused = enabled
            self._sample_epoch += 1
            if not enabled:
                self._sample_requested = True
            self._condition.notify_all()
        if enabled:
            self.state.fail_audio_provider(
                StateQuality.PAUSED,
                "sampling_paused",
                generation=self.generation,
            )

    def request_refresh(self, *_args: object) -> bool:
        with self._condition:
            if self._stopping:
                return False
            self._sample_requested = True
            self._current_poll_interval = self.poll_interval
            self._condition.notify_all()
            return True

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
        return self._accepted_snapshot().balance

    def master_balance_snapshot(self) -> float | None:
        return self._accepted_snapshot().balance

    def set_master_balance(self, balance: float) -> bool:
        return bool(self._call(lambda: self.adapter.set_master_balance(balance), refresh=True))

    def session_snapshot(self, process_names: list[str]) -> dict[str, AudioSessionSnapshot]:
        requested = {name.casefold() for name in process_names}
        snapshot = self._accepted_snapshot()
        return {
            name: value
            for name, value in snapshot.sessions
            if name in requested
        }

    def volume_snapshot(self, process_names: list[str]) -> dict[str, float]:
        return {
            name: value.volume
            for name, value in self.session_snapshot(process_names).items()
        }

    def get_volume(self, process_name: str) -> float | None:
        item = self.session_snapshot([process_name]).get(process_name.casefold())
        return item.volume if item is not None else None

    def get_mute(self, process_name: str) -> bool | None:
        item = self.session_snapshot([process_name]).get(process_name.casefold())
        return item.muted if item is not None else None

    def set_volume(self, process_name: str, volume: float) -> bool:
        return bool(
            self._call(
                lambda: self.adapter.set_volume(process_name, volume),
                refresh=True,
            )
        )

    def set_mute(self, process_name: str, muted: bool) -> bool:
        return bool(
            self._call(
                lambda: self.adapter.set_mute(process_name, muted),
                refresh=True,
            )
        )

    def get_microphone_snapshot(self) -> MicrophoneSnapshot | None:
        return self._accepted_snapshot().microphone

    def set_microphone_volume(self, volume: float) -> bool:
        return bool(
            self._call(lambda: self.adapter.set_microphone_volume(volume), refresh=True)
        )

    def set_microphone_mute(self, muted: bool) -> bool:
        return bool(
            self._call(lambda: self.adapter.set_microphone_mute(muted), refresh=True)
        )

    def list_output_devices(self) -> list[AudioOutputDevice]:
        return list(self._accepted_snapshot().outputs)

    def set_output_device(self, device_name_or_id: str) -> bool:
        return bool(
            self._call(
                lambda: self.adapter.set_output_device(device_name_or_id),
                refresh=True,
            )
        )

    def list_audio_applications(self, **_kwargs) -> list[AudioApplication]:
        return list(self._accepted_snapshot().applications)

    def count_audio_sessions(self) -> int:
        return sum(
            item.session_count
            for _name, item in self._accepted_snapshot().sessions
        )

    def get_active_process_name(self) -> str | None:
        return self._accepted_snapshot().active_process or None

    def _accepted_snapshot(self) -> AudioProviderSnapshot:
        sample = self.state.snapshot().provider("audio")
        if sample is not None and isinstance(sample.value, AudioProviderSnapshot):
            return sample.value
        return AudioProviderSnapshot()

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

    def _call(self, callback: Callable[[], Any], *, refresh: bool = False) -> Any:
        if self._thread is threading.current_thread():
            result = callback()
            if refresh and result is not False:
                self.request_refresh()
            return result
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
        if refresh and request.result is not False:
            self.request_refresh()
        return request.result

    def _run(self) -> None:
        subscription = None
        try:
            with com_apartment():
                try:
                    subscribe = getattr(self.adapter, "subscribe", None)
                    if callable(subscribe):
                        try:
                            subscription = subscribe(self.request_refresh)
                            with self._condition:
                                self._subscription = subscription
                        except Exception:
                            # Core Audio callbacks are an optimization. Controlled
                            # polling remains the fallback on unsupported drivers.
                            self.log.warning(
                                "Core Audio callbacks unavailable; using polling fallback",
                                exc_info=True,
                            )
                    self._run_owned()
                finally:
                    if subscription is not None:
                        try:
                            if subscription() is False:
                                self._cleanup_ok = False
                        except Exception:
                            self._cleanup_ok = False
                            self.log.exception("Core Audio callback cleanup failed")
                    with self._condition:
                        self._subscription = None
        except Exception:
            self.log.exception("Audio provider owner failed")
            self.state.fail_audio_provider(
                StateQuality.ERROR,
                "owner_failed",
                generation=self.generation,
            )

    def _run_owned(self) -> None:
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
                next_sample = self._clock() + self._current_poll_interval
            elif should_sample:
                self._sample()
                next_sample = self._clock() + self._current_poll_interval

    def _sample(self) -> bool:
        with self._condition:
            sample_epoch = self._sample_epoch
            if self._stopping or self._paused:
                return False
        try:
            reader = getattr(self.adapter, "provider_snapshot", None)
            if callable(reader):
                audio_snapshot = reader(
                    include_processes=self.process_names,
                    include_sessions=self.include_sessions,
                    include_microphone=self.include_microphone,
                    include_outputs=self.include_outputs,
                )
            else:
                master = self.adapter.get_master_snapshot()
                balance_reader = getattr(self.adapter, "get_master_balance", None)
                balance = balance_reader() if callable(balance_reader) else None
                audio_snapshot = AudioProviderSnapshot(master=master, balance=balance)
        except Exception:
            self.log.exception("Audio provider sample failed")
            quality = StateQuality.ERROR
            detail = "provider_error"
            audio_snapshot = None
        else:
            quality = StateQuality.UNAVAILABLE
            detail = "endpoint_unavailable"
        with self._condition:
            previous = self._last_snapshot
            subscription = self._subscription
        if audio_snapshot is None:
            self.state.fail_audio_provider(
                quality,
                detail,
                generation=self.generation,
                accept_if=lambda: self._sample_is_current(sample_epoch),
            )
            return False
        audio_snapshot = self._preserve_partial_snapshot(
            audio_snapshot,
            previous,
        )
        detail = ",".join(audio_snapshot.errors)
        provider_quality = (
            StateQuality.UNAVAILABLE
            if audio_snapshot.errors
            else StateQuality.GOOD
        )
        master = audio_snapshot.master
        master_unavailable = master is None or "master" in audio_snapshot.errors
        accepted = self.state.observe_audio_provider(
            audio_snapshot,
            None if master is None else (master.volume, master.muted),
            generation=self.generation,
            provider_quality=provider_quality,
            provider_detail=detail,
            master_quality=(
                StateQuality.UNAVAILABLE
                if master_unavailable
                else StateQuality.GOOD
            ),
            master_detail=(
                "endpoint_unavailable"
                if master_unavailable
                else ""
            ),
            accept_if=lambda: self._sample_is_current(sample_epoch),
        )
        if not accepted:
            return False
        with self._condition:
            self._last_snapshot = audio_snapshot
            self._current_poll_interval = (
                self.poll_interval
                if audio_snapshot != previous
                else min(
                    self.maximum_poll_interval,
                    self._current_poll_interval * 1.5,
                )
            )
        refresh = getattr(subscription, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                self.log.exception("Audio callback rebind failed")
                self.state.fail_audio_provider(
                    StateQuality.ERROR,
                    "callback_rebind_failed",
                    generation=self.generation,
                    accept_if=lambda: self._sample_is_current(sample_epoch),
                )
                return False
        return accepted

    def _sample_is_current(self, sample_epoch: int) -> bool:
        return (
            not self._stopping
            and not self._paused
            and sample_epoch == self._sample_epoch
        )

    @staticmethod
    def _preserve_partial_snapshot(
        current: AudioProviderSnapshot,
        previous: AudioProviderSnapshot,
    ) -> AudioProviderSnapshot:
        replacements: dict[str, object] = {}
        errors = set(current.errors)
        if "master" in errors and current.master is None:
            replacements["master"] = previous.master
            replacements["balance"] = previous.balance
        if "microphone" in errors and current.microphone is None:
            replacements["microphone"] = previous.microphone
        if "outputs" in errors and not current.outputs:
            replacements["outputs"] = previous.outputs
        failed_processes = {
            process.casefold()
            for process, _session_id in current.session_failures
        }
        if failed_processes:
            current_sessions = dict(current.sessions)
            previous_sessions = dict(previous.sessions)
            for process in failed_processes:
                if process in previous_sessions:
                    current_sessions[process] = previous_sessions[process]
            current_apps = {
                item.process_name.casefold(): item
                for item in current.applications
            }
            previous_apps = {
                item.process_name.casefold(): item
                for item in previous.applications
            }
            for process in failed_processes:
                if process in previous_apps:
                    current_apps[process] = previous_apps[process]
            replacements["sessions"] = tuple(sorted(current_sessions.items()))
            replacements["applications"] = tuple(
                sorted(
                    current_apps.values(),
                    key=lambda item: item.display_name.casefold(),
                )
            )
        return replace(current, **replacements) if replacements else current
