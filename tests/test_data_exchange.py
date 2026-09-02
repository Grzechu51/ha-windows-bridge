from __future__ import annotations

import json

from ha_windows_bridge.config import AppConfig, MqttConfig, OverlayTemplateConfig
from ha_windows_bridge.data_exchange import (
    build_diagnostic_report,
    export_configuration,
    export_overlay_templates,
    import_configuration,
    import_overlay_templates,
)


def test_export_excludes_password_and_import_preserves_current_secret(tmp_path) -> None:
    config = AppConfig(
        device_name="Gaming PC",
        mqtt=MqttConfig(
            host="broker.local",
            username="bridge-user",
            password="export-secret",
        ),
    )
    path = tmp_path / "bridge-config.json"

    export_configuration(path, config)
    exported = path.read_text(encoding="utf-8")
    imported = import_configuration(path, current_password="existing-secret")

    assert "export-secret" not in exported
    assert json.loads(exported)["format"] == "ha-windows-bridge-config"
    assert imported.device_name == "Gaming PC"
    assert imported.mqtt.host == "broker.local"
    assert imported.mqtt.password == "existing-secret"


def test_diagnostic_report_redacts_connection_details_and_log_secrets(tmp_path) -> None:
    config = AppConfig(
        mqtt=MqttConfig(
            host="broker.local",
            username="bridge-user",
            password="private",
            base_topic="ha-windows-bridge/gaming",
        )
    )
    log_path = tmp_path / "bridge.log"
    log_path.write_text(
        "broker.local bridge-user ha-windows-bridge/gaming password=private",
        encoding="utf-8",
    )

    report = build_diagnostic_report(
        config,
        connected=True,
        messages_processed=7,
        log_path=log_path,
    )
    serialized = json.dumps(report)

    assert "private" not in serialized
    assert "broker.local" not in serialized
    assert "bridge-user" not in serialized
    assert "ha-windows-bridge/gaming" not in serialized
    assert report["runtime"] == {"mqtt_connected": True, "messages_processed": 7}
    assert report["configuration"]["mqtt"]["host"] == "<configured>"


def test_selected_overlay_templates_round_trip_without_the_rest_of_config(tmp_path) -> None:
    templates = [
        OverlayTemplateConfig(template_id="door", name="Drzwi", preset="warning"),
        OverlayTemplateConfig(template_id="battery", name="Bateria", layout="badge"),
    ]
    path = tmp_path / "popups.json"

    export_overlay_templates(path, [templates[1]], selected_id="battery")
    imported, selected = import_overlay_templates(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "ha-windows-bridge-overlay-templates"
    assert [item.template_id for item in imported] == ["battery"]
    assert imported[0].layout == "badge"
    assert selected == "battery"


def test_overlay_import_accepts_complete_configuration_export(tmp_path) -> None:
    config = AppConfig(
        overlay_templates=[
            OverlayTemplateConfig(template_id="security", name="Alarm", preset="error")
        ],
        selected_overlay_template_id="security",
    )
    path = tmp_path / "complete.json"
    export_configuration(path, config)

    imported, selected = import_overlay_templates(path)

    assert len(imported) == 1
    assert imported[0].preset == "error"
    assert selected == "security"
