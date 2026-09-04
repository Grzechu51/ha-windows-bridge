from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import MAX_CONFIG_BYTES, AppConfig
from .security import redact_data, redact_text

EXPORT_FORMAT = "ha-windows-bridge-config"
MAX_DIAGNOSTIC_LOG_BYTES = 512 * 1024


def export_configuration(path: Path, config: AppConfig) -> None:
    payload = {
        "format": EXPORT_FORMAT,
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "config": config.to_dict(),
        "notice": "MQTT password and Home Assistant token are intentionally not included.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_configuration(path: Path, current_password: str | None = None) -> AppConfig:
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("Plik konfiguracji jest zbyt duży")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Nie można odczytać pliku konfiguracji") from exc
    if not isinstance(payload, dict):
        raise ValueError("Plik konfiguracji jest nieprawidłowy")
    if payload.get("format") == EXPORT_FORMAT:
        payload = payload.get("config")
    if not isinstance(payload, dict):
        raise ValueError("Plik konfiguracji jest nieprawidłowy")
    config = AppConfig.from_dict(payload)
    config.mqtt.password = current_password or ""
    errors = config.validation_errors()
    if errors:
        raise ValueError("\n".join(errors))
    return config


def _redact(text: str, config: AppConfig) -> str:
    replacements = {
        str(Path.home()): "%USERPROFILE%",
        config.mqtt.host: "<mqtt-host>",
        config.mqtt.username: "<mqtt-user>",
        config.mqtt.base_topic: "<base-topic>",
        config.home_assistant.url: "<ha-url>",
    }
    for value, replacement in replacements.items():
        if value:
            text = text.replace(value, replacement)
    return redact_text(text, (config.mqtt.password, config.home_assistant.token))


def build_diagnostic_report(
    config: AppConfig,
    *,
    connected: bool,
    messages_processed: int,
    log_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    log_tail: list[str] = []
    if log_path:
        try:
            with log_path.open("rb") as stream:
                size = stream.seek(0, 2)
                start = max(0, size - MAX_DIAGNOSTIC_LOG_BYTES)
                stream.seek(start)
                lines = stream.read(MAX_DIAGNOSTIC_LOG_BYTES).decode("utf-8", errors="replace").splitlines()
                if start:
                    lines = lines[1:]
            log_tail = [_redact(line, config) for line in lines[-100:]]
        except OSError:
            pass
    safe_config = config.to_dict()
    safe_mqtt = safe_config.get("mqtt", {})
    if isinstance(safe_mqtt, dict):
        safe_mqtt["host"] = "<configured>" if config.mqtt.host else ""
        safe_mqtt["username"] = "<configured>" if config.mqtt.username else ""
        safe_mqtt["base_topic"] = "<configured>" if config.mqtt.base_topic else ""
    safe_config["home_assistant"]["url"] = "<configured>" if config.home_assistant.url else ""

    report: dict[str, Any] = {
        "format": "ha-windows-bridge-diagnostics",
        "generated_at": datetime.now(UTC).isoformat(),
        "application": {
            "version": __version__,
            "frozen": bool(getattr(sys, "frozen", False)),
            "python": platform.python_version(),
            "windows": platform.platform(),
        },
        "runtime": {
            "mqtt_connected": connected,
            "messages_processed": max(0, int(messages_processed)),
        },
        "configuration": safe_config,
        "configuration_errors": config.validation_errors(),
        "log_tail": log_tail,
    }
    if extra:
        report["checks"] = extra
    report = redact_data(report, (config.mqtt.password, config.home_assistant.token))
    return _redact_report(report, config)


def _redact_report(value: Any, config: AppConfig) -> Any:
    if isinstance(value, dict):
        return {_redact(str(key), config): _redact_report(item, config) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_report(item, config) for item in value]
    return _redact(value, config) if isinstance(value, str) else value


def save_diagnostic_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
