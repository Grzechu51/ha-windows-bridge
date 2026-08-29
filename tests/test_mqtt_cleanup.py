from __future__ import annotations

from ha_windows_bridge.config import AppConfig, MqttConfig
from ha_windows_bridge.discovery import all_possible_mqtt_topics
from ha_windows_bridge.mqtt_cleanup import cleanup_application_mqtt_data


class FakePublish:
    def wait_for_publish(self, _timeout=None):
        return None


class FakeCleanupClient:
    def __init__(self):
        self.on_connect = None
        self.on_connect_fail = None
        self.published = []
        self.subscriptions = []

    def username_pw_set(self, *_args):
        return None

    def tls_set(self):
        return None

    def connect_async(self, *_args):
        return 0

    def loop_start(self):
        self.on_connect(self, None, None, 0, None)

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        raise AssertionError("cleanup must never subscribe to broker-wide topics")

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakePublish()

    def disconnect(self):
        return None

    def loop_stop(self):
        return None


def test_cleanup_removes_only_exact_generated_and_remembered_topics(monkeypatch) -> None:
    config = AppConfig(mqtt=MqttConfig(host="broker"), apps=[])
    client = FakeCleanupClient()
    monkeypatch.setattr("ha_windows_bridge.mqtt_cleanup.mqtt.Client", lambda *_a, **_kw: client)

    result = cleanup_application_mqtt_data(
        config,
        remembered_topics={
            "old-name/audio/master/state",
            "homeassistant/number/old_pc/volume/config",
            "unsafe/#",
            "unsafe/+",
            "unsafe/\x00topic",
        },
        timeout=1.0,
    )

    removed = {
        topic
        for topic, payload, qos, retain in client.published
        if payload == "" and qos == 1 and retain
    }
    assert result.publish_success
    assert result.scan_complete
    assert result.matched_entities >= 1
    assert client.subscriptions == []
    assert "old-name/audio/master/state" in removed
    assert "homeassistant/number/old_pc/volume/config" in removed
    assert all_possible_mqtt_topics(config).issubset(removed)
    assert not any("#" in topic or "+" in topic or "\x00" in topic for topic in removed)
