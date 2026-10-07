from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from csv import DictReader
from datetime import UTC, datetime
from pathlib import Path

import psutil
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell process observer")


@pytest.mark.parametrize("mode", [
    "valid", "bad_identity", "missing_counts", "stale", "stale_large_interval",
    "secret_counter", "partial_connection", "secret_connection_field", "missing_process",
])
def test_short_soak_never_passes_and_checks_observer_coverage(tmp_path, mode) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    process = psutil.Process(os.getpid())
    started = process.create_time() - (60 if mode == "bad_identity" else 0)
    telemetry = {
        "schema": 1,
        "pid": os.getpid(),
        "process_start_utc": datetime.fromtimestamp(started, UTC).isoformat(),
        "sample_utc": datetime.fromtimestamp(
            datetime.now(UTC).timestamp() - (60 if mode.startswith("stale") else 0), UTC
        ).isoformat(),
        "closed": False,
        "logs": {"warnings": 0, "errors": 0},
        "connections": {},
    }
    if mode == "missing_counts":
        del telemetry["logs"]
    elif mode == "secret_counter":
        telemetry["logs"]["errors"] = "SECRET_ERROR_TEXT"
    elif mode == "partial_connection":
        telemetry["connections"]["mqtt"] = {"state": "connected"}
    elif mode == "secret_connection_field":
        telemetry["connections"]["mqtt"] = {
            "state": "connected", "attempt": 0, "transitions": 1, "failures": 0,
            "reconnects": 0, "recoveries": 0, "last_failure_utc": None,
            "last_recovery_utc": None, "last_recovery_seconds": None,
            "max_recovery_seconds": None, "pending_failure": False,
            "error_message": "SECRET_ERROR_TEXT",
        }
    elif mode == "missing_process":
        telemetry["pid"] = 2147483647
    source = tmp_path / "telemetry.json"
    source.write_text(json.dumps(telemetry), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "tools" / "soak_monitor.ps1"
    subprocess.run(
        [shell, "-NoProfile", "-File", str(script), "-TelemetryPath", str(source),
         "-OutputDirectory", str(tmp_path / "results"), "-ProcessName", process.name()[:-4],
         "-DurationHours", "0.0003", "-IntervalSeconds",
         "3600" if mode == "stale_large_interval" else "1"],
        check=True, capture_output=True, text=True, timeout=30,
    )

    result = json.loads((tmp_path / "results" / "summary.json").read_text(encoding="utf-8-sig"))
    exported = (tmp_path / "results" / "samples.csv").read_text(encoding="utf-8-sig")
    assert "SECRET_ERROR_TEXT" not in exported
    assert "SECRET_ERROR_TEXT" not in json.dumps(result)
    assert result["verdict"] == "INCOMPLETE_OR_FAIL"
    assert "less_than_24h" in result["reasons"]
    if mode != "valid":
        assert result["invalid_samples"] > 0
        assert "invalid_or_missing_samples" in result["reasons"]
    else:
        assert result["invalid_samples"] == 0
        assert result["first_sample"]["working_set_mb"] > 0


def _run_powershell_harness(tmp_path: Path, commands: str) -> dict:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    script = Path(__file__).resolve().parents[1] / "tools" / "soak_monitor.ps1"
    source = str(script).replace("'", "''")
    harness = tmp_path / "harness.ps1"
    harness.write_text(f". '{source}' -ImportOnly\n{commands}\n", encoding="utf-8")
    result = subprocess.run(
        [shell, "-NoProfile", "-File", str(harness)],
        check=True, capture_output=True, text=True, timeout=20,
    )
    return json.loads(result.stdout)


def test_finalizer_rejects_early_stop_zero_samples_missing_samples_and_interruption(tmp_path) -> None:
    results = _run_powershell_harness(tmp_path, """
$s = [DateTimeOffset]::Parse('2026-09-01T00:00:00Z')
$duration = [TimeSpan]::FromHours(24)
$row = [pscustomobject]@{ timestamp_utc = $s.ToString('o'); status = 'ok'; app_errors = 0; mqtt_pending_failure = $false; direct_pending_failure = $false }
$hourly = @(0..24 | ForEach-Object { [pscustomobject]@{ timestamp_utc = $s.AddHours($_).ToString('o'); status = 'ok'; app_errors = 0; mqtt_pending_failure = $false; direct_pending_failure = $false } })
$missing = @($hourly | Where-Object { $_.timestamp_utc -ne $s.AddHours(12).ToString('o') })
$out = [ordered]@{}
$out.early = Get-SoakAssessment -Rows @($row) -Started $s -Ended $s.AddHours(23.5) -Duration $duration -IntervalSeconds 3600 -Completed $true -BadSamples 0 -GapCount 0
$out.empty = Get-SoakAssessment -Rows @() -Started $s -Ended $s.AddHours(24) -Duration $duration -IntervalSeconds 3600 -Completed $true -BadSamples 0 -GapCount 0
$out.missing = Get-SoakAssessment -Rows $missing -Started $s -Ended $s.AddHours(24) -Duration $duration -IntervalSeconds 3600 -Completed $true -BadSamples 0 -GapCount 0
$out.interrupted = Get-SoakAssessment -Rows $hourly -Started $s -Ended $s.AddHours(24) -Duration $duration -IntervalSeconds 3600 -Completed $false -BadSamples 0 -GapCount 0
$out.complete = Get-SoakAssessment -Rows $hourly -Started $s -Ended $s.AddHours(24) -Duration $duration -IntervalSeconds 3600 -Completed $true -BadSamples 0 -GapCount 0
$out | ConvertTo-Json -Depth 5 -Compress
""")
    assert results["early"]["verdict"] == "INCOMPLETE_OR_FAIL"
    assert "less_than_24h" in results["early"]["reasons"]
    assert results["empty"]["verdict"] == "INCOMPLETE_OR_FAIL"
    assert "insufficient_samples" in results["empty"]["reasons"]
    assert "sampling_gap" in results["missing"]["reasons"]
    assert "observer_not_completed" in results["interrupted"]["reasons"]
    assert results["complete"]["verdict"] == "PENDING_REVIEW"


def test_process_property_read_failure_is_captured(tmp_path) -> None:
    result = _run_powershell_harness(tmp_path, """
function Get-Process {
    param($Id, $ErrorAction)
    $fake = [pscustomobject]@{}
    $fake | Add-Member -MemberType ScriptProperty -Name StartTime -Value { throw 'process exited during sample' }
    return $fake
}
$sample = Get-SoakProcessSample -TargetPid 123 -ExpectedStart ([DateTimeOffset]::UtcNow) -ProcessName 'fake' -ExpectedExePath '' -Now ([DateTimeOffset]::UtcNow)
$sample | ConvertTo-Json -Compress
""")
    assert result["status"] == "process_unavailable"


def test_process_exit_after_cached_metrics_is_captured(tmp_path) -> None:
    result = _run_powershell_harness(tmp_path, """
$started = [DateTimeOffset]::UtcNow
function Get-Process {
    param($Id, $ErrorAction)
    return [pscustomobject]@{
        StartTime = $started.UtcDateTime
        ProcessName = 'fake'
        Id = 123
        WorkingSet64 = 1024
        PrivateMemorySize64 = 2048
        HandleCount = 4
        Threads = @(1)
        TotalProcessorTime = [TimeSpan]::FromSeconds(1)
        HasExited = $true
    }
}
$sample = Get-SoakProcessSample -TargetPid 123 -ExpectedStart $started -ProcessName 'fake' -ExpectedExePath '' -Now ([DateTimeOffset]::UtcNow)
$sample | ConvertTo-Json -Compress
""")
    assert result["status"] == "process_missing"


@pytest.mark.parametrize("change", ["pid", "reuse", "restart", "exit"])
def test_live_soak_detects_restart_or_process_loss(tmp_path, change) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    monitor = None
    replacement = None
    try:
        process = psutil.Process(child.pid)
        telemetry = {
            "schema": 1, "pid": child.pid,
            "process_start_utc": datetime.fromtimestamp(process.create_time(), UTC).isoformat(),
            "sample_utc": datetime.now(UTC).isoformat(), "closed": False,
            "logs": {"warnings": 0, "errors": 0}, "connections": {},
        }
        source = tmp_path / "telemetry.json"
        source.write_text(json.dumps(telemetry), encoding="utf-8")
        output = tmp_path / "results"
        script = Path(__file__).resolve().parents[1] / "tools" / "soak_monitor.ps1"
        monitor = subprocess.Popen(
            [shell, "-NoProfile", "-File", str(script), "-TelemetryPath", str(source),
             "-OutputDirectory", str(output), "-ProcessName", process.name()[:-4],
             "-DurationHours", "0.001", "-IntervalSeconds", "1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        csv_path = output / "samples.csv"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if csv_path.exists() and len(csv_path.read_text(encoding="utf-8-sig").splitlines()) >= 2:
                break
            time.sleep(0.05)
        else:
            pytest.fail("monitor did not record the first sample")

        if change == "pid":
            telemetry["pid"] = 2147483647
            telemetry["sample_utc"] = datetime.now(UTC).isoformat()
            source.write_text(json.dumps(telemetry), encoding="utf-8")
        elif change == "reuse":
            telemetry["process_start_utc"] = datetime.fromtimestamp(
                process.create_time() + 60, UTC
            ).isoformat()
            telemetry["sample_utc"] = datetime.now(UTC).isoformat()
            source.write_text(json.dumps(telemetry), encoding="utf-8")
        elif change == "restart":
            child.terminate()
            child.wait(timeout=5)
            replacement = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
            successor = psutil.Process(replacement.pid)
            telemetry["pid"] = replacement.pid
            telemetry["process_start_utc"] = datetime.fromtimestamp(
                successor.create_time(), UTC
            ).isoformat()
            telemetry["sample_utc"] = datetime.now(UTC).isoformat()
            source.write_text(json.dumps(telemetry), encoding="utf-8")
        else:
            child.terminate()
            child.wait(timeout=5)
        monitor.communicate(timeout=15)
        assert monitor.returncode == 0
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            statuses = [row["status"] for row in DictReader(handle)]
        assert "ok" in statuses
        assert ("process_missing" if change == "exit" else "process_restarted") in statuses
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8-sig"))
        assert summary["verdict"] == "INCOMPLETE_OR_FAIL"
        assert summary["invalid_samples"] > 0
    finally:
        if monitor and monitor.poll() is None:
            monitor.kill()
            monitor.wait(timeout=5)
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        if replacement and replacement.poll() is None:
            replacement.terminate()
            replacement.wait(timeout=5)
