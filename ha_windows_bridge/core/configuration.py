"""Versioned 2.0 profile: one atomic transaction for public settings and sealed credentials."""
from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import fields
from pathlib import Path
from typing import get_type_hints

from ..config import (
    AppConfig,
    AudioAppConfig,
    HomeAssistantConfig,
    MqttConfig,
    TrackedDeviceConfig,
    default_data_dir,
)
from .secrets import SecretStore

PROFILE_FORMAT = 2
MAX_PROFILE_BYTES = 1024 * 1024


def public_settings(config: AppConfig) -> dict:
    data = config.to_dict()
    data.pop("schema_version", None)
    return data


def parse_settings(value: dict) -> AppConfig:
    if not isinstance(value, dict):
        raise ValueError("Settings must be a JSON object")
    allowed = {field.name for field in fields(AppConfig)} - {"schema_version"}
    if set(value) - allowed:
        raise ValueError("Unknown configuration fields")
    defaults = AppConfig()
    data = {}
    nested = {"mqtt": MqttConfig, "home_assistant": HomeAssistantConfig}
    lists = {"apps": AudioAppConfig, "tracked_devices": TrackedDeviceConfig}
    for key, item in value.items():
        if key in nested:
            factory = nested[key]
            if not isinstance(item, dict) or set(item) - {field.name for field in fields(factory)}:
                raise ValueError(f"Invalid configuration section: {key}")
            if set(item) & {"password", "token"}:
                raise ValueError("Credentials must use SecretStore")
            base = factory()
            for name, subvalue in item.items():
                expected = getattr(base, name)
                if type(subvalue) is not type(expected):
                    raise ValueError(f"Invalid configuration value: {key}.{name}")
            data[key] = factory(**item)
        elif key in lists:
            if not isinstance(item, list) or len(item) > 256:
                raise ValueError(f"Invalid configuration list: {key}")
            factory = lists[key]
            converted = []
            for row in item:
                if not isinstance(row, dict) or set(row) - {field.name for field in fields(factory)}:
                    raise ValueError(f"Invalid configuration list item: {key}")
                types = get_type_hints(factory)
                if any(type(subvalue) is not types[name] for name, subvalue in row.items()):
                    raise ValueError(f"Invalid configuration list value: {key}")
                try:
                    converted.append(factory(**row))
                except (TypeError, AttributeError, ValueError) as exc:
                    raise ValueError(f"Invalid configuration list item: {key}") from exc
            data[key] = converted
        elif key == "disk_mounts":
            if not isinstance(item, list) or len(item) > 64 or any(not isinstance(mount, str) for mount in item):
                raise ValueError("Invalid disk list")
            data[key] = item
        else:
            expected = getattr(defaults, key)
            if isinstance(expected, float):
                if type(item) not in {float, int} or not math.isfinite(item):
                    raise ValueError(f"Invalid numeric setting: {key}")
            elif type(item) is not type(expected):
                raise ValueError(f"Invalid setting: {key}")
            data[key] = item
    try:
        config = AppConfig(**data)
    except (TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid configuration value") from exc
    return config


class ConfigurationStore:
    def __init__(self, secrets: SecretStore, directory: Path | None = None):
        self.secrets = secrets
        self.data_dir = directory or default_data_dir()
        self.config_path = self.data_dir / "profile-v2.json"
        self.load_diagnostic = None

    def load(self):
        diagnostic = {}

        def observe(**values):
            if self.load_diagnostic is not None:
                diagnostic.update(values)
                self.load_diagnostic(dict(diagnostic))

        exists = self.config_path.exists()
        observe(config_path=str(self.config_path), exists=exists)
        if not exists:
            observe(branch="missing_profile_fallback")
            return AppConfig(start_with_windows=False, auto_connect=False, theme="system")
        if self.config_path.stat().st_size > MAX_PROFILE_BYTES:
            observe(branch="parse_error")
            raise ValueError("Profile exceeds size limit")
        if self.load_diagnostic is not None:
            raw = self.config_path.read_bytes()
            observe(branch="profile_read", bytes_read=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            # Match read_text's UTF-8 decoding and universal newline handling;
            # fingerprint exactly the bytes supplied to this parser.
            with io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8") as stream:
                text = stream.read()
        else:
            text = self.config_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                settings = payload.get("settings")
                safe_settings = settings if isinstance(settings, dict) else {}
                mqtt = safe_settings.get("mqtt")
                ha = safe_settings.get("home_assistant")
                mqtt = mqtt if isinstance(mqtt, dict) else {}
                ha = ha if isinstance(ha, dict) else {}
                format_value = payload.get("format")
                observe(format=format_value if type(format_value) in (int, bool, type(None)) else "invalid_type",
                        settings_exists="settings" in payload,
                        settings_key_count=len(settings) if isinstance(settings, dict) else None,
                        mqtt_host_present=bool(mqtt.get("host")), ha_url_present=bool(ha.get("url")),
                        direct_enabled=ha.get("enabled") is True,
                        auto_connect=safe_settings.get("auto_connect") is True)
            if not isinstance(payload, dict) or payload.get("format") != PROFILE_FORMAT:
                raise ValueError("Unsupported profile format")
            config = parse_settings(payload.get("settings"))
        except Exception:
            observe(branch="parse_error")
            raise
        try:
            credentials = self.secrets.unseal(payload.get("credentials", ""))
        except Exception:
            observe(branch="secret_error")
            raise
        config.mqtt.password = credentials.get("mqtt_password", "")
        config.home_assistant.token = credentials.get("ha_token", "")
        return config

    def save(self, config):
        from ..integration_protocol import inventory_budget_errors
        errors = inventory_budget_errors(config) if config.mqtt.host else []
        if errors:
            raise ValueError("; ".join(errors))
        # Round-trip validation rejects ambiguous containers before any write.
        settings = public_settings(config)
        parse_settings(settings)
        credentials = self.secrets.seal({"mqtt_password": config.mqtt.password, "ha_token": config.home_assistant.token})
        document = json.dumps({"format": PROFILE_FORMAT, "settings": settings, "credentials": credentials},
                              ensure_ascii=False, indent=2)
        if len(document.encode()) > MAX_PROFILE_BYTES:
            raise ValueError("Profile exceeds size limit")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(document, encoding="utf-8")
            temporary.replace(self.config_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def export(config, path):
        path.write_text(json.dumps({"format": PROFILE_FORMAT, "settings": public_settings(config)}, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def import_settings(path):
        if path.stat().st_size > MAX_PROFILE_BYTES:
            raise ValueError("Profile exceeds size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("format") != PROFILE_FORMAT:
            raise ValueError("Unsupported profile format")
        return parse_settings(payload.get("settings"))
