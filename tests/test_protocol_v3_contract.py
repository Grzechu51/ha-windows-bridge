from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ha_windows_bridge.communication import schema as windows_schema

ROOT = Path(__file__).parents[1]


def _ha_schema():
    path = ROOT / "custom_components/ha_windows_bridge/protocol.py"
    spec = importlib.util.spec_from_file_location("ha_windows_bridge_protocol_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture():
    return json.loads((ROOT / "tests/fixtures/protocol_v3.json").read_text(encoding="utf-8"))


def test_deployed_ha_decoder_is_exact_protocol_source_mirror():
    canonical = (ROOT / "ha_windows_bridge/communication/schema.py").read_text(encoding="utf-8")
    deployed = (ROOT / "custom_components/ha_windows_bridge/protocol.py").read_text(encoding="utf-8")
    assert deployed == canonical


def test_windows_encoder_and_ha_decoder_share_all_contract_fixtures():
    ha = _ha_schema()
    for value in _fixture()["messages"]:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
        windows = windows_schema.decode_message(encoded)
        decoded = ha.decode_message(windows.encode())
        assert decoded.to_dict() == windows.to_dict() == value


def test_both_decoders_are_total_for_malformed_contract_fixtures():
    ha = _ha_schema()
    for raw in _fixture()["malformed"]:
        with pytest.raises(windows_schema.ProtocolError):
            windows_schema.decode_message(raw)
        with pytest.raises(ha.ProtocolError):
            ha.decode_message(raw)


def test_retained_command_is_rejected_by_both_sides():
    ha = _ha_schema()
    command = _fixture()["messages"][2]
    raw = json.dumps(command)
    with pytest.raises(windows_schema.ProtocolError, match="retained_command"):
        windows_schema.CommandMessage.decode(raw, retained=True)
    with pytest.raises(ha.ProtocolError, match="retained_command"):
        ha.CommandMessage.decode(raw, retained=True)


def test_legacy_payload_adapter_uses_the_same_shared_fixtures():
    ha = _ha_schema()
    for case in _fixture()["legacy_commands"]:
        assert windows_schema.legacy_arguments(case["parser"], case["payload"]) == case["arguments"]
        assert ha.legacy_arguments(case["parser"], case["payload"]) == case["arguments"]


def test_large_payload_budget_is_reserved_for_overlay_only():
    arguments = {"blob": "x" * (33 * 1024)}
    normal = windows_schema.CommandMessage(
        "large-normal", "session-a", "desktop", "audio.master.volume", "",
        arguments, 1.0, 10_000,
    )
    with pytest.raises(windows_schema.ProtocolError, match="payload_size"):
        normal.encode()
    overlay = windows_schema.CommandMessage(
        "large-overlay", "session-a", "desktop", "overlay.show", "",
        arguments, 1.0, 10_000,
    )
    assert windows_schema.CommandMessage.decode(overlay.encode()).kind == "overlay.show"
