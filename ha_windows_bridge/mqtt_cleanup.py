from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass

import paho.mqtt.client as mqtt

from .config import AppConfig
from .discovery import all_possible_mqtt_topics

MAX_CLEANUP_TOPICS = 20_000


@dataclass(frozen=True, slots=True)
class MqttCleanupResult:
    publish_success: bool
    scan_complete: bool
    removed_topics: int
    matched_entities: int
    error: str = ""


def _safe_topic(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    topic = value.strip()
    if not topic or "+" in topic or "#" in topic or "\x00" in topic:
        return None
    if len(topic.encode("utf-8")) > 65_535:
        return None
    return topic


def cleanup_application_mqtt_data(
    config: AppConfig,
    remembered_topics: Iterable[str] = (),
    timeout: float = 6.0,
) -> MqttCleanupResult:
    """Clear retained MQTT topics generated or remembered by this installation.

    The cleanup intentionally never subscribes to the broker-wide ``#`` wildcard.
    This keeps the MQTT account least-privileged and prevents the application from
    receiving unrelated retained messages. Previous names and base topics are
    covered by the local topic history maintained by the application.
    """
    connected = threading.Event()
    errors: list[str] = []
    connection_ok = [False]

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"ha-windows-bridge-cleanup-{uuid.uuid4().hex[:12]}",
        protocol=mqtt.MQTTv311,
    )
    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    if config.mqtt.tls:
        client.tls_set()

    def on_connect(_client, _userdata, _flags, reason_code, _properties) -> None:
        if getattr(reason_code, "is_failure", False):
            errors.append(f"Broker odrzucił połączenie: {reason_code}")
        else:
            connection_ok[0] = True
        connected.set()

    def on_connect_fail(_client, _userdata) -> None:
        errors.append("Nie można połączyć z brokerem MQTT.")
        connected.set()

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail

    try:
        client.connect_async(config.mqtt.host, config.mqtt.port, config.mqtt.keepalive)
        client.loop_start()
        if not connected.wait(timeout=min(3.0, timeout)):
            return MqttCleanupResult(False, False, 0, 0, "Przekroczono czas połączenia z MQTT.")
        if not connection_ok[0]:
            return MqttCleanupResult(
                False,
                False,
                0,
                0,
                errors[0] if errors else "Nie można połączyć z brokerem MQTT.",
            )

        candidates = set(remembered_topics)
        candidates.update(all_possible_mqtt_topics(config))
        targets = sorted(
            topic for topic in (_safe_topic(candidate) for candidate in candidates) if topic
        )
        if len(targets) > MAX_CLEANUP_TOPICS:
            return MqttCleanupResult(
                False,
                False,
                0,
                0,
                "Lokalna historia MQTT zawiera zbyt wiele topiców do bezpiecznego usunięcia.",
            )

        pending = [client.publish(topic, "", qos=1, retain=True) for topic in targets]
        confirmed = True
        deadline = time.monotonic() + max(3.0, min(15.0, len(pending) / 20.0))
        for publication in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                confirmed = False
                break
            try:
                publication.wait_for_publish(remaining)
            except Exception:
                confirmed = False
                break

        error = "" if confirmed else "Nie udało się potwierdzić usunięcia wszystkich topiców MQTT."
        return MqttCleanupResult(
            confirmed,
            confirmed,
            len(targets) if confirmed else 0,
            sum(topic.endswith("/config") for topic in targets) if confirmed else 0,
            error,
        )
    except Exception as exc:
        return MqttCleanupResult(False, False, 0, 0, str(exc))
    finally:
        with suppress(Exception):
            client.disconnect()
        with suppress(Exception):
            client.loop_stop()
