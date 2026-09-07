"""Connect MQTT wire messages to the application router without executing OS code."""
from __future__ import annotations

import logging

from ..core.commands import CommandError
from .message_outbox import MessageItem, MessageOutbox
from .mqtt import MqttTransport
from .protocol import TopicProtocol
from .publishing import StatePublisher


class MqttGateway:
    def __init__(self, config, router, events):
        self.protocol = TopicProtocol(config)
        self.router, self.events = router, events
        self.log = logging.getLogger("bridge.mqtt")
        self.transport = MqttTransport(config.mqtt, config.device_id, events, self.receive,
                                       self.protocol.subscriptions)
        self.publisher = StatePublisher(self.transport, events)
        self.outbox = MessageOutbox(capacity=256)
        self._unsubscribe = None
        capabilities = self.protocol.capabilities()
        self.outbox.accept("capabilities", self.protocol.capabilities_topic,
                           capabilities.encode(), retain=True, replace_latest=True)

    def start(self):
        self._unsubscribe = self.events.subscribe("connection.changed", self._connection_changed)
        self.transport.start()

    def stop(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        result = self.transport.stop()
        self.outbox.close()
        return result

    def _connection_changed(self, event):
        if event.data.transport == "mqtt" and event.data.state == "connected":
            self.publisher.request_replay()
            self.outbox.replay()
            self._flush_protocol()

    def receive(self, topic, payload, retained=False):
        if topic == self.protocol.birth_topic:
            if payload == b"online":
                self.events.emit("inventory.requested")
            return
        try:
            command = self.protocol.decode(topic, payload, retained)
        except CommandError as exc:
            self.log.warning("MQTT command rejected: %s", exc.code)
            return
        result = self.router.submit(command, self._reply)
        self._reply(result)

    def _reply(self, result):
        message = self.protocol.result(result)
        item = self.outbox.accept("result:" + result.id, self.protocol.result_topic,
                                  message.encode(), retain=False, replace_latest=True)
        if item is None:
            self.log.error("Protocol result outbox is full")
            return
        self._send_protocol(item)

    def _flush_protocol(self):
        for item in self.outbox.pending():
            self._send_protocol(item)
        self.outbox.discard_delivered()

    def _send_protocol(self, item: MessageItem):
        def delivered(success: bool):
            if success:
                self.outbox.mark_delivered(item.key, item.token)
                self.outbox.discard_delivered()
            else:
                self.outbox.mark_failed(item.key, item.token)

        try:
            accepted = self.transport.publish(item.topic, item.payload, qos=item.qos,
                                              retain=item.retain, on_delivery=delivered)
        except TypeError:
            # Test/compatibility transports pre-dating delivery callbacks.
            accepted = self.transport.publish(item.topic, item.payload, qos=item.qos,
                                              retain=item.retain)
            if accepted:
                delivered(True)
        except Exception:
            accepted = False
        if not accepted:
            delivered(False)
