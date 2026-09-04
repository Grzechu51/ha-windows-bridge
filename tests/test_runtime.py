from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from ha_windows_bridge.config import CONFIG_SCHEMA_VERSION, AppConfig
from ha_windows_bridge.media import _AsyncRunner
from ha_windows_bridge.runtime.polling import PollScheduler
from ha_windows_bridge.runtime.worker import SerialWorker


def test_sources_are_isolated_cached_and_errors_rate_limited(caplog):
    now = [100.0]
    scheduler = PollScheduler(logging.getLogger("poll-test"), lambda: now[0])
    calls = []
    def fail():
        raise OSError("sensor unavailable")
    for _ in range(3):
        assert scheduler.run("bad", 0, fail, "unknown") == "unknown"
        scheduler.run("good", 5, lambda: calls.append(1))
    assert len(caplog.records) == 1
    assert calls == [1]
    now[0] += 60
    scheduler.run("bad", 0, fail)
    assert len(caplog.records) == 2
    assert scheduler.run("cache", 5, lambda: 42) == 42
    assert scheduler.run("cache", 5, lambda: 99) == 42


def test_media_runner_close_is_idempotent_and_cancels_pending_tasks():
    runner = _AsyncRunner()
    started = threading.Event()
    cleaned = threading.Event()
    async def waiting():
        started.set()
        try:
            await asyncio.sleep(100)
        finally:
            cleaned.set()
    future = asyncio.run_coroutine_threadsafe(waiting(), runner._loop)
    assert started.wait(1)
    runner.close()
    runner.close()
    assert cleaned.wait(1)
    assert future.cancelled()
    assert not runner._thread.is_alive()
    assert runner._loop.is_closed()
    with pytest.raises(RuntimeError, match="closed"):
        runner.call(waiting())


@pytest.mark.parametrize("payload", [[], None, {"mqtt": []}, {"home_assistant": None},
    {"apps": "not-a-list"}, {"apps": [None]}, {"disk_mounts": None},
    {"tracked_devices": ["bad"]}, {"schema_version": CONFIG_SCHEMA_VERSION + 1}])
def test_invalid_configuration_containers_fail_cleanly(payload):
    with pytest.raises(ValueError):
        AppConfig.from_dict(payload)


def test_worker_preserves_order_bounds_pending_work_and_stops():
    worker = SerialWorker("test-worker", logging.getLogger(__name__), capacity=2)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def slow():
        started.set()
        release.wait(2)
        calls.append(0)
    try:
        assert worker.submit(slow)
        assert started.wait(1)
        assert worker.submit(lambda: calls.append(1))
        assert worker.submit(lambda: (calls.append(2), finished.set()))
        assert not worker.submit(lambda: calls.append(3))
        release.set()
        assert finished.wait(1)
        assert calls == [0, 1, 2]
    finally:
        release.set()
        worker.close()
    assert not worker.is_alive
    assert not worker.submit(lambda: None)


def test_worker_discards_waiting_jobs_on_close():
    worker = SerialWorker("test-stop", logging.getLogger(__name__))
    started, release = threading.Event(), threading.Event()
    calls = []
    worker.submit(lambda: (started.set(), release.wait(2)))
    assert started.wait(1)
    worker.submit(lambda: calls.append(1))
    worker.close(timeout=0)
    release.set()
    worker.close()
    assert not calls
