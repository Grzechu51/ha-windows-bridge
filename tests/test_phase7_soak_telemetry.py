from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from ha_windows_bridge.communication.state import ConnectionState, ConnectionStatus
from ha_windows_bridge.core import soak_telemetry
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.observability import DiagnosticBuffer
from ha_windows_bridge.core.soak_telemetry import SoakTelemetry


def test_soak_telemetry_counts_short_failure_and_writes_only_allowlisted_data(tmp_path) -> None:
    events = EventBus()
    diagnostics = DiagnosticBuffer(events)
    diagnostics.protect("private-token")
    app = SimpleNamespace(events=events, diagnostics=diagnostics)
    output = tmp_path / "telemetry.json"
    soak = SoakTelemetry(app, output)

    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.CONNECTED))
    events.emit("connection.changed", ConnectionStatus(
        "mqtt", ConnectionState.RETRY_WAIT, attempt=1, error="private-token"
    ))
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.CONNECTED))
    diagnostics.emit(logging.LogRecord("bridge", logging.ERROR, __file__, 1,
                                       "private-token in app error", (), None))

    assert soak.write()
    raw = output.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "private-token" not in raw
    assert "app error" not in raw
    assert data["logs"] == {"warnings": 0, "errors": 1}
    assert data["connections"]["mqtt"]["failures"] == 1
    assert data["connections"]["mqtt"]["reconnects"] == 1
    assert data["connections"]["mqtt"]["recoveries"] == 1
    assert not data["connections"]["mqtt"]["pending_failure"]
    assert data["pid"] > 0

    soak.close()
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.RETRY_WAIT,
                                                       error="after_close"))
    assert json.loads(output.read_text(encoding="utf-8"))["closed"] is True
    assert soak.snapshot()["connections"]["mqtt"]["failures"] == 1


def test_soak_telemetry_write_failure_does_not_interrupt_application(tmp_path) -> None:
    events = EventBus()
    app = SimpleNamespace(events=events, diagnostics=DiagnosticBuffer(events))
    soak = SoakTelemetry(app, tmp_path / "missing" / "telemetry.json")
    assert soak.write() is False
    soak.close()


def test_recovery_duration_starts_at_first_failure(tmp_path, monkeypatch) -> None:
    times = iter([1000.0, 1001.0, 1003.0, 1011.0])
    monkeypatch.setattr(soak_telemetry.time, "time", lambda: next(times, 1011.0))
    events = EventBus()
    app = SimpleNamespace(events=events, diagnostics=DiagnosticBuffer(events))
    soak = SoakTelemetry(app, tmp_path / "telemetry.json")
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.CONNECTED))
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.RETRY_WAIT,
                                                   error="network"))
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.RETRY_WAIT,
                                                   error="network"))
    events.emit("connection.changed", ConnectionStatus("mqtt", ConnectionState.CONNECTED))
    mqtt = soak.snapshot()["connections"]["mqtt"]
    assert mqtt["failures"] == 2
    assert mqtt["last_recovery_seconds"] == 10.0
    assert mqtt["max_recovery_seconds"] == 10.0
