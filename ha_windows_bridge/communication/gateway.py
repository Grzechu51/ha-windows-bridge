"""Connect MQTT wire messages to the application router without executing OS code."""
from __future__ import annotations

import logging

from ..core.commands import CommandError
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
        self._unsubscribe = None

    def start(self):
        self._unsubscribe = self.events.subscribe("connection.changed", self._connection_changed)
        self.transport.start()

    def stop(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        return self.transport.stop()

    def _connection_changed(self, event):
        if event.data.transport == "mqtt" and event.data.state == "connected":
            self.publisher.replay()

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
        # accepted is an internal receipt; publish terminal/cached or rejected results only.
        if result.status != "accepted":
            self._reply(result)

    def _reply(self, result):
        self.transport.publish(self.protocol.result_topic, result.encode(), retain=False)
