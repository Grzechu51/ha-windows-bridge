"""Connect MQTT wire messages to the application router without executing OS code."""
from __future__ import annotations

import logging
import threading

from ..core.commands import CommandError
from .message_outbox import MessageItem, MessageOutbox
from .mqtt import MqttTransport
from .protocol import ReplyContext, TopicProtocol
from .publishing import StatePublisher
from .state import Backoff

_RESULT_PRECEDENCE = {
    "accepted": 0,
    "pending": 1,
    "succeeded": 2,
    "failed": 2,
    "rejected": 2,
    "cancelled": 2,
}
_TERMINAL_RESULTS = frozenset({"succeeded", "failed", "rejected", "cancelled"})


class MqttGateway:
    def __init__(self, config, router, events, *, protocol_retry_delay=None):
        self.protocol = TopicProtocol(config)
        self.router, self.events = router, events
        self.log = logging.getLogger("bridge.mqtt")
        self.transport = MqttTransport(config.mqtt, config.device_id, events, self.receive,
                                       self.protocol.subscriptions)
        self.publisher = StatePublisher(self.transport, events)
        self.outbox = MessageOutbox(capacity=256)
        self._unsubscribe = None
        self._lock = threading.Lock()
        self._connection_generation = 0
        self._result_status = {}
        self._stop = threading.Event()
        self._retry = threading.Event()
        self._retry_thread = None
        self._retry_round = 0
        self._retry_delay = protocol_retry_delay or (
            lambda attempt: Backoff(0.25, 5.0).delay(attempt)
        )
        self._max_active_attempts = 5
        capabilities = self.protocol.capabilities()
        self.outbox.accept("capabilities", self.protocol.capabilities_topic,
                           capabilities.encode(), retain=True, replace_latest=True)

    def start(self):
        self._stop.clear()
        self._unsubscribe = self.events.subscribe("connection.changed", self._connection_changed)
        self._retry_thread = threading.Thread(
            target=self._retry_loop, name="mqtt-protocol-outbox", daemon=True
        )
        self._retry_thread.start()
        self.transport.start()

    def stop(self):
        self._stop.set()
        self._retry.set()
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        result = self.transport.stop()
        if self._retry_thread and self._retry_thread is not threading.current_thread():
            self._retry_thread.join(timeout=2)
            result = result and not self._retry_thread.is_alive()
        self.outbox.close()
        return result

    def _connection_changed(self, event):
        if event.data.transport == "mqtt" and event.data.state == "connected":
            with self._lock:
                self._connection_generation += 1
                generation = self._connection_generation
            self.publisher.request_replay()
            self.outbox.replay(generation)
            self._flush_protocol()

    def receive(self, topic, payload, retained=False):
        if topic == self.protocol.birth_topic:
            if payload == b"online":
                with self._lock:
                    generation = self._connection_generation
                self.events.emit("inventory.requested", {"force": True})
                self.publisher.request_replay()
                self.publisher.flush()
                self.outbox.replay(generation, retained_only=True)
                self._flush_protocol()
            return
        try:
            command, context = self.protocol.decode_inbound(topic, payload, retained)
        except CommandError as exc:
            self.log.warning("MQTT command rejected: %s", exc.code)
            return

        def reply(result):
            self._reply(result, context)

        result = self.router.submit(command, reply)
        reply(result)

    def _reply(self, result, context: ReplyContext | None = None):
        context = context or ReplyContext(3, self.protocol.session, self.protocol.result_topic)
        identity = (context.protocol_version, context.session, result.id)
        with self._lock:
            previous = self._result_status.get(identity)
            if (previous in _TERMINAL_RESULTS and previous != result.status) or (
                previous is not None
                and _RESULT_PRECEDENCE[result.status] < _RESULT_PRECEDENCE[previous]
            ):
                return
            if identity not in self._result_status and len(self._result_status) >= 1024:
                self._result_status.pop(next(iter(self._result_status)))
            self._result_status[identity] = result.status
        topic, payload = self.protocol.encode_result(result, context)
        key = f"result:{context.protocol_version}:{context.session}:{result.id}"
        item = self.outbox.accept(key, topic, payload, retain=False, replace_latest=True)
        if item is None:
            self.log.error("Protocol result outbox is full")
            return
        self._send_protocol(item)

    def _flush_protocol(self):
        for item in self.outbox.pending():
            self._send_protocol(item)
        self.outbox.discard_delivered()

    def _send_protocol(self, item: MessageItem):
        with self._lock:
            generation = self._connection_generation
        attempt = self.outbox.begin_attempt(item.key, item.token, generation)
        if attempt is None:
            return

        def delivered(success: bool):
            if success:
                self.outbox.mark_delivered(
                    attempt.key, attempt.token, attempt.connection_generation
                )
                self.outbox.discard_delivered()
            else:
                if not self.outbox.mark_failed(
                    attempt.key, attempt.token, attempt.connection_generation
                ):
                    return
                if attempt.attempts >= self._max_active_attempts:
                    if not attempt.retain:
                        self.log.error(
                            "Dropping protocol result after bounded retries: %s",
                            attempt.key,
                        )
                        self.outbox.discard(attempt.key, attempt.token)
                    # Retained contract state stays failed for the next reconnect
                    # or HA birth, but does not retry forever on this connection.
                elif not self._stop.is_set() and self.transport.connected:
                    self._retry.set()

        try:
            accepted = self.transport.publish(attempt.topic, attempt.payload, qos=attempt.qos,
                                              retain=attempt.retain, on_delivery=delivered)
        except TypeError:
            # Test/compatibility transports pre-dating delivery callbacks.
            accepted = self.transport.publish(attempt.topic, attempt.payload, qos=attempt.qos,
                                              retain=attempt.retain)
            if accepted:
                delivered(True)
        except Exception:
            accepted = False
        if not accepted:
            delivered(False)

    def _retry_loop(self):
        while not self._stop.is_set():
            if not self._retry.wait(1):
                continue
            self._retry.clear()
            self._retry_round += 1
            if self._stop.wait(max(0.0, float(self._retry_delay(self._retry_round)))):
                break
            if self.transport.connected:
                self._flush_protocol()
