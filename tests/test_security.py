from __future__ import annotations

import json
import logging
import sys

import pytest

from ha_windows_bridge.config import AppConfig, HomeAssistantConfig, MqttConfig
from ha_windows_bridge.data_exchange import MAX_DIAGNOSTIC_LOG_BYTES, build_diagnostic_report
from ha_windows_bridge.i18n import LocalizedFormatter
from ha_windows_bridge.security import redact_data, redact_text


@pytest.mark.parametrize("text", [
    "Authorization: Bearer abc.def.ghi",
    '{"access_token": "abc.def.ghi"}',
    "password='a spaced secret'",
    "wss://user:password@ha.local/api/websocket",
    "Bearer standalone-token",
])
def test_unknown_secrets_are_redacted(text):
    cleaned = redact_text(text)
    for value in ("abc.def.ghi", "a spaced secret", "user:password", "standalone-token"):
        assert value not in cleaned


def test_known_secrets_nested_encoded_and_tracebacks():
    source = {"message": "failed my credential!", "inner": [{"TOKEN": "hidden"}]}
    cleaned = redact_data(source, ("my credential!",))
    assert cleaned["inner"][0]["TOKEN"] == "<redacted>"
    assert source["inner"][0]["TOKEN"] == "hidden"
    assert "my%20credential%21" not in redact_text("my%20credential%21", ("my credential!",))
    formatter = LocalizedFormatter("%(message)s")
    formatter.add_secrets("my credential!")
    try:
        raise ValueError("failed my credential!")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "error %s", ("my credential!",), sys.exc_info())
    assert "my credential!" not in formatter.format(record)
    assert record.args == ("my credential!",)


def test_diagnostics_redacts_nested_checks_and_large_log_tail(tmp_path):
    config = AppConfig(mqtt=MqttConfig(host="broker.local", password="mqtt-credential"),
                       home_assistant=HomeAssistantConfig(url="https://ha.private", token="ha-credential"))
    log = tmp_path / "bridge.log"
    log.write_text("x\n" * MAX_DIAGNOSTIC_LOG_BYTES + "failure ha-credential mqtt-credential\n", encoding="utf-8")
    report = build_diagnostic_report(config, connected=False, messages_processed=0, log_path=log,
                                     extra={"nested": [{"detail": "https://ha.private ha-credential"}]})
    encoded = json.dumps(report)
    assert report["log_tail"]
    assert "ha-credential" not in encoded
    assert "mqtt-credential" not in encoded
    assert "https://ha.private" not in encoded
    assert len(report["log_tail"]) <= 100
