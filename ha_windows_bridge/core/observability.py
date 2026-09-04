"""Bounded diagnostic history shared by every presentation."""
from __future__ import annotations

import logging
import threading
from collections import deque

from ..security import redact_text
from .events import EventBus


class DiagnosticBuffer(logging.Handler):
    def __init__(self, events: EventBus, capacity: int = 500):
        super().__init__()
        self.events = events
        self._records: deque[str] = deque(maxlen=capacity)
        self._guard = threading.RLock()
        self._secrets: set[str] = set()
        self.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S"))

    def protect(self, *secrets: str) -> None:
        with self._guard:
            self._secrets.update(secret for secret in secrets if secret)

    def emit(self, record: logging.LogRecord) -> None:
        with self._guard:
            line = redact_text(self.format(record), self._secrets)
            self._records.append(line)
        # No recursion if a diagnostic listener itself fails.
        if not getattr(record, "diagnostic_event", False):
            self.events.emit("log.appended", line)

    def snapshot(self) -> tuple[str, ...]:
        with self._guard:
            return tuple(self._records)
