"""Remaining deterministic audit probes P03/P05/P09/P10/P12."""
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from test_overlay_service import service_harness
from test_v2_desktop import qt_app

from ha_windows_bridge.communication.protocol import TopicProtocol
from ha_windows_bridge.config import AppConfig, AudioAppConfig, MqttConfig
from ha_windows_bridge.core.configuration import ConfigurationStore, parse_settings
from ha_windows_bridge.integration_protocol import (
    integration_announcement_payload,
    inventory_budget_errors,
)
from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.ui_components import AppCard
from ha_windows_bridge.updater import parse_release


def decoder():
    path = Path(__file__).parents[1] / "custom_components/ha_windows_bridge/announcement.py"
    spec = importlib.util.spec_from_file_location("phase0_announcement", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p03_progress_only_ha_update_keeps_engine_title_message_and_options():
    call, _, _, _ = service_harness()
    engine = NotificationEngine(clock=lambda: 100)
    engine.submit({"title": "Keep title", "message": "Keep message", "data": {"id": "one", "pinned": True}})
    payload = call({"notification_id": "one", "progress": 65}, "update_overlay")
    assert "title" not in payload and "message" not in payload
    assert engine.submit(payload) == "updated"
    options = engine.visible["one"].options
    assert options["title"] == "Keep title" and options["message"] == "Keep message"
    assert options["progress"] == 65 and options["pinned"]
    cleared = call({"notification_id": "one", "message": ""}, "update_overlay")
    engine.submit(cleared)
    assert engine.visible["one"].options["message"] == ""


@pytest.mark.parametrize("current,latest,available", [
    ("2.0.0-alpha.8", "v2.0.0", True), ("2.0.0rc1", "v2.0.0", True),
    ("2.0.0", "v2.0.0-alpha.8", False), ("2.0.0-alpha.8", "v2.0.0-alpha.9", True),
    ("2.0.0", "v2.0.0", False),
])
def test_p05_prerelease_order(current, latest, available):
    assert parse_release({"tag_name": latest, "html_url": "https://github.com/example/release"}, current).available is available


@pytest.mark.parametrize("count", [63, 64, 128])
def test_p09_inventory_limits_are_checked_before_save_and_agree_with_ha(count, tmp_path):
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[AudioAppConfig(f"app{i}.exe", f"App {i}", f"app{i}") for i in range(count)])
    payload = integration_announcement_payload(config)
    assert len(payload["entities"]) == 4 * count + 3
    parsed = decoder().parse_discovery_announcement(json.dumps(payload))
    errors = inventory_budget_errors(config)
    assert bool(errors) is (parsed is None)
    assert any("limit" in error for error in config.validation_errors()) is (count > 63)
    store = ConfigurationStore(Mock(), tmp_path)
    if count > 63:
        with pytest.raises(ValueError, match="limit"):
            store.save(config)
        assert not store.config_path.exists()
        store.secrets.seal.assert_not_called()


def test_p09_optional_features_reserve_their_full_entity_budget():
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[AudioAppConfig(f"app{i}.exe", f"App {i}", f"app{i}") for i in range(63)], publish_cpu_stats=True)
    assert inventory_budget_errors(config)


@pytest.mark.parametrize("platform", [[], {}, None, True, 123])
def test_p10_invalid_platform_type_is_rejected_without_exception(platform):
    payload = integration_announcement_payload(AppConfig())
    payload["entities"][0]["platform"] = platform
    assert decoder().parse_discovery_announcement(json.dumps(payload)) is None


def test_p12_real_qt_keyboard_wheel_drag_and_programmatic_refresh():
    qt = qt_app()
    card = AppCard(AudioAppConfig("app.exe", "App", "app"))
    emitted = []
    card.volume_requested.connect(lambda process, value: emitted.append(value))
    try:
        card.set_volume(.5)
        card.show()
        card.slider.setFocus()
        qt.processEvents()
        assert emitted == []
        QTest.keyClick(card.slider, Qt.Key.Key_Right)
        assert card.slider.value() == 51 and emitted == [51]
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        qt.sendEvent(card.slider, event)
        assert emitted[-1] == card.slider.value() and len(emitted) == 2
        card.slider.setSliderDown(True)
        card.slider.setValue(75)
        assert len(emitted) == 2
        card.slider.setSliderDown(False)
        assert emitted[-1] == 75 and len(emitted) == 3
        card.set_volume(.8)
        assert len(emitted) == 3
    finally:
        card.close()


def test_reference_profile_reproduces_linux_ha_announcement_fixture():
    root = Path(__file__).parents[1] / "tests_ha/fixtures"
    config = parse_settings(json.loads((root / "profile-settings-v2.json").read_text()))
    payload = integration_announcement_payload(config, ["Speakers"], overlay_monitors=["Monitor"])
    protocol = TopicProtocol(config)
    payload.update(schema=3, protocol={"version": 2, "command_topic": protocol.legacy_command_topic,
                                      "result_topic": f"{config.mqtt.base_topic}/v2/result",
                                      "routes": {topic: asdict(route) for topic, route in protocol.routes.items()}})
    assert payload == json.loads((root / "announcement-v2.json").read_text())
    assert decoder().parse_discovery_announcement(json.dumps(payload)) is not None
    assert not inventory_budget_errors(config)
