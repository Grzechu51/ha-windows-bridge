from __future__ import annotations

import threading
from types import SimpleNamespace

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.core.events import EventBus


class FakeGateway:
    instances = []
    def __init__(self, config, router, events):
        self.router, self.events = router, events
        self.publisher = SimpleNamespace(connected=False)
        self.running = False
        self.instances.append(self)
    def start(self):
        self.running = True
    def stop(self):
        self.running = False
        return True


def runtime(config=None):
    return Application(config or AppConfig(mqtt=MqttConfig(host="broker"), control_master_volume=False),
                       SimpleNamespace(save=lambda config: None),
                       SimpleNamespace(set_enabled=lambda enabled: None),
                       SimpleNamespace(list_audio_applications=lambda **_: []), object(), SimpleNamespace(reopen=lambda: None, close=lambda: None), object(),
                       mqtt_factory=FakeGateway, events=EventBus())


def test_application_owns_start_stop_restart_and_configuration():
    app = runtime()
    running, stopped, configured = threading.Event(), threading.Event(), threading.Event()
    app.events.subscribe("application.running", lambda event: running.set() if event.data else stopped.set())
    app.events.subscribe("configuration.changed", lambda event: configured.set())
    try:
        assert app.start()
        assert running.wait(2)
        assert set(app.supervisor.active) == {"mqtt", "sensors"}
        first = app.router
        assert app.stop()
        assert stopped.wait(2)
        assert first.closed
        running.clear()
        assert app.start()
        assert running.wait(2)
        assert app.router is not first
        changed = AppConfig(mqtt=MqttConfig(host="new-broker"), control_master_volume=False)
        assert app.apply_configuration(changed)
        assert configured.wait(2)
    finally:
        assert app.shutdown()
    assert not app.start()


def test_diagnostics_never_include_secrets():
    app = runtime()
    try:
        app.config.mqtt.password = "never-export"
        app.diagnostics.protect("never-export")
        app.log.warning("password=never-export")
        assert "never-export" not in str(app.diagnostic_report())
    finally:
        assert app.shutdown()
