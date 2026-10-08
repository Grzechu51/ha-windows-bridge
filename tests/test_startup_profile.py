from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge import desktop
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.core.configuration import ConfigurationStore
from ha_windows_bridge.core.secrets import SecretStore


def test_frozen_startup_loads_existing_profile_into_runtime_and_gui(tmp_path, monkeypatch):
    class Cipher:
        def encrypt(self, value):
            return value

        def decrypt(self, value):
            return value

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(desktop, "DpapiCipher", Cipher)
    config = AppConfig(
        mqtt=MqttConfig(host="saved-broker", username="saved-user", password="test-password"),
        home_assistant=HomeAssistantConfig(enabled=True, url="http://saved-ha", token="test-token"),
        auto_connect=True, overlay_enabled=True,
    )
    store = ConfigurationStore(SecretStore(Cipher()))
    store.save(config)
    before = store.config_path.read_bytes()
    qt_app()
    for name in ("enable_per_monitor_v2", "WindowsStartupManager", "WindowsAudioService",
                 "WindowsSystemMonitor", "WindowsMediaService", "WindowsPowerActions"):
        monkeypatch.setattr(desktop, name, lambda *args, **kwargs: None)

    seen = []

    def application(loaded, actual_store, *args, **kwargs):
        assert loaded == config
        assert actual_store.config_path == store.config_path
        app = runtime(loaded)
        monkeypatch.setattr(app, "start", lambda: seen.append("unexpected_start"))
        seen.append(app)
        return app

    monkeypatch.setattr(desktop, "Application", application)
    monkeypatch.setattr(desktop, "WindowsEventBridge", lambda *args: SimpleNamespace(close=lambda: None))
    report_path = tmp_path / "startup.json"
    assert desktop.main(["--startup-diagnostic", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["stage"] == "gui_created"
    assert report["frozen"] is True
    assert report["config_path"] == str(store.config_path)
    assert report["profile_exists"] is True
    for key in ("mqtt_host_present", "ha_url_present", "ha_enabled", "auto_connect",
                "runtime_matches_loaded", "gui_matches_runtime", "draft_matches_loaded",
                "fields_match_loaded"):
        assert report[key] is True, key
    assert report["services_started"] is False
    assert len(seen) == 1
    assert store.config_path.read_bytes() == before
    for secret_or_setting in ("saved-broker", "saved-user", "test-password", "saved-ha", "test-token"):
        assert secret_or_setting not in report_path.read_text()
