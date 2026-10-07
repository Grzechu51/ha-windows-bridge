import json

import pytest

from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.core.configuration import ConfigurationStore, parse_settings
from ha_windows_bridge.core.secrets import SecretStore


class TestCipher:
    __test__ = False
    def encrypt(self, value): return b"sealed:" + value[::-1]
    def decrypt(self, value):
        if not value.startswith(b"sealed:"):
            raise ValueError()
        return value[7:][::-1]


def test_v2_profile_is_isolated_atomic_and_exports_without_secrets(tmp_path):
    legacy = tmp_path / "config.json"
    legacy.write_text("unchanged", encoding="utf-8")
    store = ConfigurationStore(SecretStore(TestCipher()), tmp_path)
    assert store.load().theme == "system"
    config = AppConfig(mqtt=MqttConfig(host="broker", password="private"), theme="system")
    store.save(config)
    assert store.load().mqtt.password == "private"
    assert "private" not in store.config_path.read_text()
    assert legacy.read_text() == "unchanged"
    destination = tmp_path / "export.json"
    store.export(config, destination)
    assert "credentials" not in json.loads(destination.read_text())
    assert store.import_settings(destination).mqtt.password == ""
    assert not store.config_path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("value", [[], {"auto_connect": "false"}, {"mqtt": {"port": True}},
                                  {"mqtt": {"password": "plain"}}, {"other": 1}, {"disk_mounts": [None]}])
def test_strict_v2_configuration_rejects_ambiguous_or_secret_values(value):
    with pytest.raises(ValueError):
        parse_settings(value)


def test_bad_credentials_are_reported_instead_of_silently_cleared():
    with pytest.raises(ValueError, match="odszyfrować"):
        SecretStore(TestCipher()).unseal("YmFk")


def test_partial_profile_never_uses_or_overwrites_an_uncommitted_temp_file(tmp_path):
    store = ConfigurationStore(SecretStore(TestCipher()), tmp_path)
    store.save(AppConfig(theme="dark"))
    committed = store.config_path.read_bytes()
    temporary = store.config_path.with_suffix(".json.tmp")

    temporary.write_bytes(b'{"format": 2, "settings":')
    assert store.load().theme == "dark"
    assert store.config_path.read_bytes() == committed
    assert temporary.exists()

    store.config_path.write_bytes(b'{"format": 2, "settings":')
    damaged = store.config_path.read_bytes()
    temporary.write_bytes(committed)
    with pytest.raises(ValueError):
        store.load()
    assert store.config_path.read_bytes() == damaged
    assert temporary.read_bytes() == committed
