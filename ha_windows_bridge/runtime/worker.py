from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable


class SerialWorker:
    """Bounded FIFO worker. Stop discards waiting jobs, never kills an active call."""

    def __init__(self, name: str, logger: logging.Logger, capacity: int = 64):
        self._name = name
        self._log = logger
        self._capacity = capacity
        self._condition = threading.Condition()
        self._pending: deque[Callable[[], object]] = deque()
        self._closed = False
        self._thread: threading.Thread | None = None

    def submit(self, callback: Callable[[], object]) -> bool:
        with self._condition:
            if self._closed or len(self._pending) >= self._capacity:
                return False
            self._pending.append(callback)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
                self._thread.start()
            self._condition.notify()
            return True

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                job = self._pending.popleft()
            try:
                job()
            except Exception:
                self._log.exception("Background task failed: %s", self._name)

    def close(self, timeout: float = 1) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
