from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class PollScheduler:
    """Single-owner polling with per-source failure isolation and cached values."""

    def __init__(self, logger: logging.Logger, clock: Callable[[], float] = time.monotonic):
        self._log = logger
        self._clock = clock
        self._next: dict[str, float] = {}
        self._last_error: dict[str, float] = {}
        self._values: dict[str, Any] = {}

    def run(self, key: str, interval: float, callback: Callable[[], T], default: T | None = None) -> T | None:
        now = self._clock()
        if now < self._next.get(key, 0):
            return self._values.get(key, default)
        self._next[key] = now + interval
        try:
            value = callback()
        except Exception:
            if now - self._last_error.get(key, float("-inf")) >= 60:
                self._log.exception("Windows source failed: %s", key)
                self._last_error[key] = now
            return self._values.get(key, default)
        self._values[key] = value
        self._last_error.pop(key, None)
        return value
