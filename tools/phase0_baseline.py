"""Read-only Phase 0 process baseline with an isolated reference configuration.

Run from the repository: python tools/phase0_baseline.py --seconds 1800.
No user profile, broker, autostart registration or Windows controls are changed.
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import socket
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.audio import WindowsAudioService
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.media import WindowsMediaService
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.runtime.polling import PollScheduler
from ha_windows_bridge.system_monitor import WindowsSystemMonitor
from ha_windows_bridge.ui.shell import DesktopWindow
from ha_windows_bridge.ui.theme import style_for_theme


def summarize(values):
    values = sorted(values)
    if not values:
        return None
    return {"min": values[0], "median": statistics.median(values),
            "p95": values[min(len(values) - 1, int(len(values) * .95))], "max": values[-1],
            "samples": len(values)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("build/phase0-baseline.json"))
    args = parser.parse_args()
    qt = QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    qt.setStyleSheet(style_for_theme("", "dark"))
    # A bound, non-listening socket guarantees a local offline broker endpoint.
    reserved = socket.socket()
    reserved.bind(("127.0.0.1", 0))
    config = AppConfig(device_name="Phase 0 reference", device_id="phase0_reference", apps=[],
                       mqtt=MqttConfig(host="127.0.0.1", port=reserved.getsockname()[1], base_topic="phase0_reference"),
                       auto_check_updates=False, start_with_windows=False,
                       publish_cpu_stats=True, publish_ram_stats=True, publish_gpu_stats=False,
                       control_master_volume=True, media_player_enabled=True)
    process = psutil.Process()
    samples = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_output = args.output.with_suffix(".jsonl").open("w", encoding="utf-8", buffering=1)
    provider_ms = defaultdict(list)
    health = Counter()
    published = Counter()
    original_run = PollScheduler.run
    def measured_run(scheduler, key, interval, callback, default=None):
        def measured():
            started = time.perf_counter()
            try:
                return callback()
            finally:
                provider_ms[key].append((time.perf_counter() - started) * 1000)
        return original_run(scheduler, key, interval, measured, default)
    PollScheduler.run = measured_run
    def forbidden(*args):
        raise RuntimeError("Baseline must not persist configuration or modify autostart")
    runtime = Application(config, SimpleNamespace(save=forbidden),
                          SimpleNamespace(is_enabled=lambda: False, set_enabled=forbidden),
                          WindowsAudioService(), WindowsSystemMonitor(),
                          WindowsMediaService(logging.getLogger("bridge.media")), object())
    runtime.events.subscribe("provider.health", lambda e: health.update(e.data["errors"]))
    runtime.events.subscribe("telemetry.published", lambda e: published.update(["accepted"]))
    overlays = OverlayService(runtime)
    window = DesktopWindow(runtime)
    runtime.start()
    begin = time.monotonic()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    previous = [begin, process.cpu_times()]
    def sample():
        now = time.monotonic()
        elapsed = now - begin
        cpu = process.cpu_times()
        percent = 100 * ((cpu.user + cpu.system) - (previous[1].user + previous[1].system)) / (now - previous[0]) / (psutil.cpu_count() or 1)
        previous[:] = now, cpu
        if elapsed < args.warmup:
            return
        phase = "hidden" if elapsed - args.warmup < args.seconds / 2 else "visible_offscreen"
        if phase == "visible_offscreen" and not window.isVisible():
            window.show()
        memory = process.memory_info()
        samples.append({"elapsed_s": elapsed, "phase": phase, "cpu_percent_total": percent,
                        "working_set_mib": memory.rss / 1024**2,
                        "private_mib": memory.private / 1024**2,
                        "handles": process.num_handles(), "threads": process.num_threads()})
        raw_output.write(json.dumps(samples[-1]) + "\n")
        if elapsed >= args.warmup + args.seconds:
            qt.quit()
    timer = QTimer()
    timer.timeout.connect(sample)
    timer.start(1000)
    qt.exec()
    timer.stop()
    raw_output.close()
    window.dispose()
    overlays.close()
    stop_started = time.perf_counter()
    stopped = runtime.shutdown()
    stop_seconds = time.perf_counter() - stop_started
    reserved.close()
    phases = {}
    for phase in ("hidden", "visible_offscreen"):
        rows = [row for row in samples if row["phase"] == phase]
        phases[phase] = {key: summarize([row[key] for row in rows]) for key in
                         ("cpu_percent_total", "working_set_mib", "private_mib", "handles", "threads")}
        phases[phase]["first"] = rows[0] if rows else None
        phases[phase]["last"] = rows[-1] if rows else None
    report = {"started_utc": started_at, "duration_s": time.monotonic() - begin,
              "requested_measurement_s": args.seconds, "warmup_s": args.warmup,
              "os": platform.platform(), "python": platform.python_version(),
              "cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
              "physical_cpus": psutil.cpu_count(logical=False),
              "ram_gib": psutil.virtual_memory().total / 1024**3,
              "battery": str(psutil.sensors_battery()),
              "configuration": config.to_dict(), "phases": phases,
              "provider_duration_ms": {key: summarize(value) for key, value in provider_ms.items()},
              "provider_errors": dict(health), "publications": dict(published),
              "shutdown_completed": stopped, "shutdown_s": stop_seconds,
              "limits": ["Broker offline on loopback; no real broker delivery measured",
                         "Qt offscreen; native GUI latency/physical displays not measured",
                         "No capture, notifications, WUA or GPU polling in reference profile",
                         "Wakeups and queue depths not instrumented; not a soak test"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "samples": len(samples), "stopped": stopped}))
    return 0 if stopped else 1


if __name__ == "__main__":
    raise SystemExit(main())
