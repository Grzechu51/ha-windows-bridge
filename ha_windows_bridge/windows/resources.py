"""Cheap, non-blocking measurements of this process, not the whole computer."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True)
class ResourceUsage:
    cpu_percent: float | None
    memory_mib: float
    threads: int


class ProcessResources:
    def __init__(self, process=None, clock=time.monotonic, cpu_count=None):
        self._process = process or psutil.Process()
        self._clock = clock
        self._cpus = max(1, cpu_count or psutil.cpu_count() or 1)
        self._previous = None
        self._cached = None
        self._lock = threading.Lock()

    def sample(self):
        with self._lock:
            now = self._clock()
            if self._previous and now - self._previous[0] < 1:
                return self._cached
            try:
                with self._process.oneshot():
                    times = self._process.cpu_times()
                    cpu_time = times.user + times.system
                    memory = self._process.memory_info().rss / 1024**2
                    threads = self._process.num_threads()
                percent = None
                if self._previous:
                    elapsed = now - self._previous[0]
                    percent = min(100.0, max(0.0, (cpu_time - self._previous[1]) / elapsed / self._cpus * 100))
                self._previous = now, cpu_time
                self._cached = asdict(ResourceUsage(round(percent, 1) if percent is not None else None, round(memory, 1), threads))
            except (psutil.Error, OSError):
                self._cached = None
            return self._cached
