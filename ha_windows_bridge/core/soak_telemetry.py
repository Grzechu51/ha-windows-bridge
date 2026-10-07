"""Opt-in, allowlisted process telemetry for an external release soak monitor."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


class SoakTelemetry:
    def __init__(self, application, path: Path):
        if not path.is_absolute():
            raise ValueError("--soak-telemetry requires an absolute path")
        self._application = application
        self._path = path
        self._pid = os.getpid()
        self._started = psutil.Process(self._pid).create_time()
        self._lock = threading.RLock()
        self._connections: dict[str, dict] = {}
        self._closed = False
        self._unsubscribe = application.events.subscribe("connection.changed", self._on_connection)

    def _on_connection(self, event) -> None:
        status = event.data
        if status.transport not in {"mqtt", "home_assistant"}:
            return
        now = time.time()
        state = str(status.state)
        with self._lock:
            if self._closed:
                return
            entry = self._connections.setdefault(status.transport, {
                "state": "unknown", "attempt": 0, "transitions": 0,
                "failures": 0, "reconnects": 0, "recoveries": 0,
                "last_failure_utc": None, "last_recovery_utc": None,
                "last_recovery_seconds": None, "max_recovery_seconds": None,
                "failure_since": None,
                "was_connected": False,
            })
            if state != entry["state"]:
                entry["transitions"] += 1
            if status.error:
                entry["failures"] += 1
                entry["last_failure_utc"] = _utc(now)
                if entry["failure_since"] is None:
                    entry["failure_since"] = now
            if state == "connected":
                if entry["state"] != "connected" and (entry["was_connected"] or entry["failure_since"]):
                    entry["reconnects"] += 1
                if entry["failure_since"] is not None:
                    entry["recoveries"] += 1
                    entry["last_recovery_utc"] = _utc(now)
                    entry["last_recovery_seconds"] = round(max(0.0, now - entry["failure_since"]), 3)
                    entry["max_recovery_seconds"] = max(
                        entry["max_recovery_seconds"] or 0, entry["last_recovery_seconds"]
                    )
                    entry["failure_since"] = None
                entry["was_connected"] = True
            entry["state"] = state
            entry["attempt"] = max(0, int(status.attempt))

    def snapshot(self) -> dict:
        with self._lock:
            connections = {
                transport: {
                    **{key: value for key, value in values.items()
                       if key not in {"failure_since", "was_connected"}},
                    "pending_failure": values["failure_since"] is not None,
                }
                for transport, values in self._connections.items()
            }
            closed = self._closed
        return {
            "schema": 1,
            "pid": self._pid,
            "process_start_utc": _utc(self._started),
            "sample_utc": _utc(time.time()),
            "closed": closed,
            "logs": self._application.diagnostics.counts(),
            "connections": connections,
        }

    def write(self) -> bool:
        """Atomic replace; an unavailable output path cannot crash the desktop."""
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(self.snapshot(), separators=(",", ":")), encoding="utf-8")
            os.replace(temporary, self._path)
            return True
        except OSError:
            return False

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._unsubscribe()
        self.write()
