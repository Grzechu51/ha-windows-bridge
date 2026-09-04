"""MQTT transport only: connection, bounded frames and byte delivery."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import suppress

import paho.mqtt.client as mqtt

from ..config import MqttConfig
from ..core.events import EventBus
from .state import Backoff, ConnectionMachine, ConnectionState


class MqttTransport:
    def __init__(self, config: MqttConfig, device_id: str, events: EventBus,
                 on_message: Callable[[str, bytes, bool], None], topics: set[str],
                 *, client_factory=None):
        self.config, self.events = config, events
        self.machine = ConnectionMachine("mqtt", events)
        self.log = logging.getLogger("bridge.mqtt")
        self._receive, self._topics = on_message, frozenset(topics)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = (client_factory or mqtt.Client)(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"ha-windows-bridge-{device_id}"[:64],
            protocol=mqtt.MQTTv311, reconnect_on_failure=False)
        self._client.connect_timeout = 3
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        if config.tls:
            self._client.tls_set()
        self._status_topic = f"{config.base_topic}/status"
        self._client.will_set(self._status_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._epoch = 0

    @property
    def connected(self) -> bool:
        return self.machine.status.state == ConnectionState.CONNECTED

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("MQTT transport already running or stopping")
        self._stop.clear()
        self._epoch = self.machine.begin()
        self._thread = threading.Thread(target=self._run, name="mqtt-transport", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        self._stop.set()
        if self.connected:
            with suppress(Exception):
                self._client.publish(self._status_topic, "offline", qos=1, retain=True)
        self.machine.stop()
        with suppress(Exception):
            self._client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=4)
        return self._thread is None or not self._thread.is_alive()

    def publish(self, topic: str, payload: str | bytes, *, retain: bool = True, qos: int = 1) -> bool:
        if not self.connected:
            return False
        return self._client.publish(topic, payload, qos=qos, retain=retain).rc == mqtt.MQTT_ERR_SUCCESS

    def _run(self) -> None:
        backoff = Backoff()
        while not self._stop.is_set():
            try:
                self._client.connect(self.config.host, self.config.port, self.config.keepalive)
                while not self._stop.is_set():
                    rc = self._client.loop(timeout=1.0)
                    if rc != mqtt.MQTT_ERR_SUCCESS:
                        raise ConnectionError("network")
                    if self.machine.status.state in {ConnectionState.RETRY_WAIT, ConnectionState.AUTH_ERROR}:
                        break
            except Exception:
                if not self._stop.is_set():
                    self.machine.failed(self._epoch, "network")
                    self.log.warning("MQTT connection unavailable")
            finally:
                with suppress(Exception):
                    self._client.disconnect()
            if self.machine.status.state == ConnectionState.AUTH_ERROR:
                break  # Configuration must change; do not retry bad credentials forever.
            if self._stop.wait(backoff.delay(self.machine.status.attempt)):
                break
            if not self.machine.retry(self._epoch):
                break

    def _on_connect(self, client, _userdata, _flags, reason, _properties):
        if getattr(reason, "is_failure", False):
            authentication = getattr(reason, "value", None) in {4, 5, 134, 135}
            self.machine.failed(self._epoch, "authentication" if authentication else "broker_rejected",
                                authentication=authentication)
            return
        if self._stop.is_set():
            client.disconnect()
            return
        for topic in self._topics:
            client.subscribe(topic, qos=1)
        if self.machine.connected(self._epoch):
            client.publish(self._status_topic, "online", qos=1, retain=True)

    def _on_disconnect(self, _client, _userdata, _flags, _reason, _properties):
        if not self._stop.is_set():
            self.machine.failed(self._epoch, "disconnected")

    def _on_message(self, _client, _userdata, message):
        if self._stop.is_set() or message.topic not in self._topics:
            return
        if len(message.payload) > 768 * 1024:
            self.log.warning("MQTT frame exceeded limit")
            return
        try:
            self._receive(str(message.topic), bytes(message.payload), bool(message.retain))
        except Exception:
            self.log.exception("MQTT frame consumer failed")
