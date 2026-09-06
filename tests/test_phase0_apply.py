"""Audit P11: persistence/runtime/autostart agree after each apply failure."""
import copy

import pytest
from test_v2_application import runtime

from ha_windows_bridge.config import AppConfig, MqttConfig


@pytest.mark.parametrize("stage", ["save", "autostart", "build", "start"])
@pytest.mark.parametrize("running", [False, True])
def test_p11_apply_failure_restores_profile_runtime_and_desired_state(monkeypatch, stage, running):
    app = runtime()
    old = copy.deepcopy(app.config)
    candidate = AppConfig(mqtt=MqttConfig(host="new-broker"), control_master_volume=False, start_with_windows=True)
    disk = [copy.deepcopy(old)]
    startup = [False]
    changed = []
    failures = []
    injected = []
    def fail_once(name):
        if name == stage and not injected:
            injected.append(name)
            raise OSError(name)
    def save(config):
        fail_once("save")
        disk[0] = copy.deepcopy(config)
    def autostart(enabled):
        startup[0] = enabled  # Also exercise partial registry changes before failure.
        fail_once("autostart")
    app.store.save = save
    app.startup.is_enabled = lambda: startup[0]
    app.startup.set_enabled = autostart
    app.events.subscribe("configuration.changed", lambda event: changed.append(event.data))
    app.events.subscribe("application.error", lambda event: failures.append(event.data))
    monkeypatch.setattr(app, "_schedule", lambda action: app._run_operation(action) or True)
    try:
        if running:
            app.start()
        build, start = app._build_services, app._start
        def build_services():
            fail_once("build")
            build()
        def start_services():
            fail_once("start")
            start()
        monkeypatch.setattr(app, "_build_services", build_services)
        monkeypatch.setattr(app, "_start", start_services)
        assert app.apply_configuration(candidate)
        assert injected == [stage]
        assert failures and not changed
        assert disk[0] == app.config == old
        assert startup[0] is False
        assert bool(app.supervisor.active) is running
        assert app._desired_running is running
    finally:
        assert app.shutdown()


def test_failed_stop_does_not_write_configuration_or_autostart(monkeypatch):
    app = runtime()
    calls = []
    app.store.save = lambda config: calls.append("save")
    app.startup.set_enabled = lambda enabled: calls.append("startup")
    original = app._stop
    monkeypatch.setattr(app, "_schedule", lambda action: app._run_operation(action) or True)
    monkeypatch.setattr(app, "_stop", lambda: (_ for _ in ()).throw(RuntimeError("still stopping")))
    try:
        app.apply_configuration(copy.deepcopy(app.config))
        assert calls == []
    finally:
        monkeypatch.setattr(app, "_stop", original)
        assert app.shutdown()


def test_rollback_failure_reports_recovery_required_and_never_applied(monkeypatch):
    app = runtime()
    changed, errors = [], []
    app.events.subscribe("configuration.changed", lambda event: changed.append(event.data))
    app.events.subscribe("application.error", lambda event: errors.append(event.data))
    writes = []
    def save(config):
        writes.append(config)
        if len(writes) == 2:
            raise OSError("rollback disk failure")
    app.store.save = save
    app.startup.set_enabled = lambda _: (_ for _ in ()).throw(OSError("registry failure"))
    monkeypatch.setattr(app, "_schedule", lambda action: app._run_operation(action) or True)
    try:
        app.apply_configuration(copy.deepcopy(app.config))
        assert len(writes) == 2
        assert "configuration_rollback_failed" in errors
        assert not changed and not app.supervisor.active
    finally:
        assert app.shutdown()


def test_rollback_reports_service_start_failure_caught_by_supervisor(monkeypatch):
    app = runtime()
    errors, changed = [], []
    app.events.subscribe("application.error", lambda event: errors.append(event.data))
    app.events.subscribe("configuration.changed", lambda event: changed.append(event.data))
    monkeypatch.setattr(app, "_schedule", lambda action: app._run_operation(action) or True)
    attempts = []
    def autostart(enabled):
        attempts.append(enabled)
        if len(attempts) == 1:
            raise OSError("registry failure")
    app.startup.set_enabled = autostart
    try:
        app.start()
        gateway_type = type(app.supervisor._services["mqtt"].service)
        def failed_start(self):
            raise OSError("previous gateway cannot restart")
        monkeypatch.setattr(gateway_type, "start", failed_start)
        app.apply_configuration(copy.deepcopy(app.config))
        assert "configuration_rollback_failed" in errors
        assert not changed and not app.supervisor.active
        assert any(status.state.value == "error" for status in app.states.snapshot())
    finally:
        assert app.shutdown()
