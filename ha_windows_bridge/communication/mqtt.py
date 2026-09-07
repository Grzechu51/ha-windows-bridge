"""MQTT transport only: connection, bounded frames and byte delivery."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

import paho.mqtt.client as mqtt

from ..config import MqttConfig
from ..core.events import EventBus
from .state import Backoff, ConnectionMachine, ConnectionState


@dataclass(frozen=True, slots=True)
class _PendingPublish:
    callback: Callable[[bool], None]
    deadline: float
    connection_generation: int


class MqttTransport:
    supports_delivery_ack = True

    def __init__(self, config: MqttConfig, device_id: str, events: EventBus,
                 on_message: Callable[[str, bytes, bool], None], topics: set[str],
                 *, client_factory=None, monotonic_clock=time.monotonic,
                 ack_timeout: float = 10.0, shutdown_timeout: float = 1.0):
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
        # Paho's default outgoing queue is unbounded. Keep memory and retry work finite.
        self._client.max_queued_messages_set(256)
        self._client.max_inflight_messages_set(20)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        if config.tls:
            self._client.tls_set()
        self._status_topic = f"{config.base_topic}/status"
        self._client.will_set(self._status_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe
        self._client.on_publish = self._on_publish
        self._epoch = 0
        self._monotonic_clock = monotonic_clock
        self._ack_timeout = max(0.001, float(ack_timeout))
        self._shutdown_timeout = max(0.0, float(shutdown_timeout))
        self._ack_lock = threading.Lock()
        self._pending_subacks: dict[int, float] = {}
        self._pending_pubacks: dict[int, _PendingPublish] = {}
        self._early_pubacks: set[int] = set()
        self._ignored_pubacks: set[int] = set()
        self._ack_capacity = 256
        self._reserved_pubacks = 0
        self._connection_generation = 0
        self._unclean_shutdown = False

    @property
    def connected(self) -> bool:
        return self.machine.status.state == ConnectionState.CONNECTED

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("MQTT transport already running or stopping")
        self._stop.clear()
        self._unclean_shutdown = False
        self._epoch = self.machine.begin()
        self._thread = threading.Thread(target=self._run, name="mqtt-transport", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        offline_delivered = True
        if self.connected:
            completed = threading.Event()
            outcome = []

            def offline_ack(success: bool) -> None:
                outcome.append(bool(success))
                completed.set()

            try:
                accepted = self.publish(
                    self._status_topic,
                    "offline",
                    qos=1,
                    retain=True,
                    on_delivery=offline_ack,
                )
            except Exception:
                accepted = False
            offline_delivered = bool(
                accepted
                and completed.wait(self._shutdown_timeout)
                and outcome
                and outcome[-1]
            )
        self._unclean_shutdown = not offline_delivered
        if not offline_delivered:
            self.log.warning(
                "MQTT offline publication was not confirmed; preserving LWT shutdown"
            )
        self._stop.set()
        self.machine.stop()
        if offline_delivered:
            with suppress(Exception):
                self._client.disconnect()
        else:
            self._abort_socket()
        self._fail_pubacks()
        if self._thread is not None:
            self._thread.join(timeout=4)
        stopped = self._thread is None or not self._thread.is_alive()
        return stopped and offline_delivered

    def publish(self, topic: str, payload: str | bytes, *, retain: bool = True, qos: int = 1,
                on_delivery: Callable[[bool], None] | None = None) -> bool:
        """Return local acceptance; optional callback reports PUBACK delivery."""
        if not self.connected:
            return False
        reserved = on_delivery is not None and qos > 0
        with self._ack_lock:
            if reserved:
                if len(self._pending_pubacks) + self._reserved_pubacks >= self._ack_capacity:
                    return False
                self._reserved_pubacks += 1
        try:
            info = self._client.publish(topic, payload, qos=qos, retain=retain)
        except Exception:
            with self._ack_lock:
                if reserved:
                    self._reserved_pubacks -= 1
            raise
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            with self._ack_lock:
                if reserved:
                    self._reserved_pubacks -= 1
            return False
        if on_delivery is None:
            if qos > 0:
                with self._ack_lock:
                    if info.mid in self._early_pubacks:
                        self._early_pubacks.discard(info.mid)
                    else:
                        self._ignored_pubacks.add(info.mid)
                        if len(self._ignored_pubacks) > self._ack_capacity:
                            self._ignored_pubacks.pop()
            return True
        if qos == 0:
            try:
                on_delivery(True)
            except Exception:
                self.log.exception("MQTT delivery callback failed")
            return True
        immediate = False
        disconnected = False
        with self._ack_lock:
            self._reserved_pubacks -= 1
            if info.mid in self._early_pubacks:
                self._early_pubacks.discard(info.mid)
                immediate = True
            elif self._stop.is_set() or not self.connected:
                disconnected = True
            else:
                self._pending_pubacks[info.mid] = _PendingPublish(
                    on_delivery,
                    self._monotonic_clock() + self._ack_timeout,
                    self._connection_generation,
                )
        try:
            if immediate:
                on_delivery(True)
            elif disconnected:
                on_delivery(False)
        except Exception:
            self.log.exception("MQTT delivery callback failed")
        return True

    def _run(self) -> None:
        backoff = Backoff()
        while not self._stop.is_set():
            try:
                self._client.connect(self.config.host, self.config.port, self.config.keepalive)
                while not self._stop.is_set():
                    rc = self._client.loop(timeout=1.0)
                    if rc != mqtt.MQTT_ERR_SUCCESS:
                        raise ConnectionError("network")
                    self._expire_ack_deadlines()
                    if self.machine.status.state in {ConnectionState.RETRY_WAIT, ConnectionState.AUTH_ERROR}:
                        break
            except Exception:
                if not self._stop.is_set():
                    self.machine.failed(self._epoch, "network")
                    self.log.warning("MQTT connection unavailable")
            finally:
                if self._unclean_shutdown:
                    self._abort_socket()
                else:
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
        now = self._monotonic_clock()
        pending = {}
        for topic in self._topics:
            try:
                result = client.subscribe(topic, qos=1)
            except Exception:
                self.machine.failed(self._epoch, "subscribe_failed")
                with suppress(Exception):
                    client.disconnect()
                return
            try:
                code, message_id = result
            except (TypeError, ValueError):
                self.machine.failed(self._epoch, "subscribe_failed")
                with suppress(Exception):
                    client.disconnect()
                return
            if code != mqtt.MQTT_ERR_SUCCESS:
                self.machine.failed(self._epoch, "subscribe_failed")
                with suppress(Exception):
                    client.disconnect()
                return
            pending[int(message_id)] = now + self._ack_timeout
        with self._ack_lock:
            self._connection_generation += 1
            self._pending_subacks = pending
            self._early_pubacks.clear()
            self._ignored_pubacks.clear()
        if not pending:
            self._subscriptions_ready(client)

    def _on_subscribe(self, client, _userdata, mid, reason_codes, _properties):
        failures = any(getattr(reason, "is_failure", False) for reason in (reason_codes or ()))
        ready = False
        with self._ack_lock:
            if int(mid) not in self._pending_subacks:
                return
            self._pending_subacks.pop(int(mid), None)
            ready = not self._pending_subacks
        if failures:
            self.machine.failed(self._epoch, "subscribe_rejected")
            with suppress(Exception):
                client.disconnect()
            return
        if ready:
            self._subscriptions_ready(client)

    def _subscriptions_ready(self, client) -> None:
        if self._stop.is_set():
            return
        if self.machine.connected(self._epoch):
            client.publish(self._status_topic, "online", qos=1, retain=True)

    def _on_publish(self, _client, _userdata, mid, _reason_codes, _properties):
        with self._ack_lock:
            if int(mid) in self._ignored_pubacks:
                self._ignored_pubacks.discard(int(mid))
                return
            pending = self._pending_pubacks.pop(int(mid), None)
            if pending is None:
                self._early_pubacks.add(int(mid))
                if len(self._early_pubacks) > self._ack_capacity:
                    self._early_pubacks.pop()
            elif pending.connection_generation != self._connection_generation:
                pending = None
        if pending is not None:
            try:
                pending.callback(True)
            except Exception:
                self.log.exception("MQTT delivery callback failed")

    def _fail_pubacks(self) -> None:
        with self._ack_lock:
            callbacks = tuple(item.callback for item in self._pending_pubacks.values())
            self._pending_pubacks.clear()
            self._pending_subacks.clear()
            self._early_pubacks.clear()
            self._ignored_pubacks.clear()
        for callback in callbacks:
            try:
                callback(False)
            except Exception:
                self.log.exception("MQTT delivery callback failed")

    def _expire_ack_deadlines(self) -> bool:
        """Expire ACK waits using monotonic time and force a controlled reconnect."""

        now = self._monotonic_clock()
        with self._ack_lock:
            suback_timeout = any(deadline <= now for deadline in self._pending_subacks.values())
            if suback_timeout:
                self._pending_subacks.clear()
            expired = [
                mid for mid, item in self._pending_pubacks.items()
                if item.deadline <= now
            ]
            callbacks = tuple(
                self._pending_pubacks.pop(mid).callback for mid in expired
            )
        for callback in callbacks:
            try:
                callback(False)
            except Exception:
                self.log.exception("MQTT delivery callback failed")
        if not suback_timeout and not callbacks:
            return False
        code = "suback_timeout" if suback_timeout else "puback_timeout"
        self.machine.failed(self._epoch, code)
        with suppress(Exception):
            self._client.disconnect()
        return True

    def _abort_socket(self) -> None:
        """Close TCP without MQTT DISCONNECT so the broker retains the LWT path."""

        close_socket = getattr(self._client, "_sock_close", None)
        if callable(close_socket):
            with suppress(Exception):
                close_socket()

    def _on_disconnect(self, _client, _userdata, _flags, _reason, _properties):
        self._fail_pubacks()
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
