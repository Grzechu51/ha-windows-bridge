from __future__ import annotations

import json
import platform
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import MAX_CONFIG_BYTES, AppConfig, OverlayTemplateConfig

EXPORT_FORMAT = "ha-windows-bridge-config"
OVERLAY_EXPORT_FORMAT = "ha-windows-bridge-overlay-templates"
MAX_DIAGNOSTIC_LOG_BYTES = 512 * 1024


def export_configuration(path: Path, config: AppConfig) -> None:
    payload = {
        "format": EXPORT_FORMAT,
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "config": config.to_dict(),
        "notice": "MQTT password is intentionally not included.",
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


def export_overlay_templates(
    path: Path,
    templates: list[OverlayTemplateConfig],
    selected_id: str = "",
) -> None:
    """Export only explicitly selected overlay designs."""
    if not templates:
        raise ValueError("Wybierz co najmniej jeden popup do eksportu")
    selected = selected_id if any(item.template_id == selected_id for item in templates) else ""
    payload = {
        "format": OVERLAY_EXPORT_FORMAT,
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "selected_overlay_template_id": selected,
        "overlay_templates": [asdict(template) for template in templates[:64]],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_overlay_templates(
    path: Path,
) -> tuple[list[OverlayTemplateConfig], str]:
    """Read overlay designs from a focused export or a complete app export."""
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
    raw_templates = payload.get("overlay_templates")
    if not isinstance(raw_templates, list):
        raise ValueError("Plik nie zawiera zapisanych popupów")
    templates: list[OverlayTemplateConfig] = []
    seen: set[str] = set()
    for raw in raw_templates[:64]:
        if not isinstance(raw, dict):
            continue
        template = OverlayTemplateConfig.from_dict(raw)
        if template.template_id in seen:
            continue
        seen.add(template.template_id)
        templates.append(template)
    if not templates:
        raise ValueError("Plik nie zawiera prawidłowych popupów")
    selected = str(payload.get("selected_overlay_template_id", ""))
    if selected not in seen:
        selected = templates[0].template_id
    return templates, selected


def _redact(text: str, config: AppConfig) -> str:
    replacements = {
        str(Path.home()): "%USERPROFILE%",
        config.mqtt.host: "<mqtt-host>",
        config.mqtt.username: "<mqtt-user>",
        config.mqtt.base_topic: "<base-topic>",
    }
    for value, replacement in replacements.items():
        if value:
            text = text.replace(value, replacement)
    return re.sub(
        r"(?i)(password|token|authorization|secret)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )


def build_diagnostic_report(
    config: AppConfig,
    *,
    connected: bool,
    messages_processed: int,
    log_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    log_tail: list[str] = []
    if log_path and log_path.is_file() and log_path.stat().st_size <= MAX_DIAGNOSTIC_LOG_BYTES:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            log_tail = [_redact(line, config) for line in lines[-100:]]
        except OSError:
            pass
    safe_config = config.to_dict()
    safe_mqtt = safe_config.get("mqtt", {})
    if isinstance(safe_mqtt, dict):
        safe_mqtt["host"] = "<configured>" if config.mqtt.host else ""
        safe_mqtt["username"] = "<configured>" if config.mqtt.username else ""
        safe_mqtt["base_topic"] = "<configured>" if config.mqtt.base_topic else ""

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
    return report


def save_diagnostic_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
