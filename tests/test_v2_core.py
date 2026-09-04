from __future__ import annotations

import json
import threading

import pytest

from ha_windows_bridge.application.commands import CommandRouter
from ha_windows_bridge.application.lifecycle import ServiceSupervisor
from ha_windows_bridge.communication.state import Backoff, ConnectionMachine, ConnectionState
from ha_windows_bridge.core.commands import Command, CommandError
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import ServiceState, StateStore


def payload(**updates):
    return json.dumps({"version": 2, "id": "test-1", "kind": "audio.volume", "issued_at": 100, **updates}).encode()


def test_commands_validate_replay_and_unknown_fields():
    command = Command.parse(payload(), now=101)
    assert command.expires_at == 110
    for value in (payload(version=1), payload(id="../bad"), payload(ttl_ms=True),
                  payload(issued_at=150), payload(arguments=[]), payload(shell="bad")):
        with pytest.raises(CommandError):
            Command.parse(value, now=101)
    with pytest.raises(CommandError, match="retained"):
        Command.parse(payload(), retained=True, now=101)
    with pytest.raises(CommandError, match="expired"):
        Command.parse(payload(), now=120)


def test_connection_ignores_callbacks_after_stop_or_replaced_attempt():
    bus = EventBus()
    machine = ConnectionMachine("mqtt", bus)
    epoch = machine.begin()
    assert machine.failed(epoch, "network")
    assert machine.retry(epoch)
    assert machine.connected(epoch)
    machine.stop()
    assert not machine.connected(epoch)
    assert not machine.failed(epoch, "network")
    assert machine.status.state == ConnectionState.STOPPED
    new_epoch = machine.begin()
    assert machine.failed(new_epoch, "auth", authentication=True)
    assert not machine.retry(new_epoch)
    assert machine.status.state == ConnectionState.AUTH_ERROR
    assert 22.5 <= Backoff().delay(100) <= 30


def test_bus_unsubscribes_and_isolates_bad_subscriber():
    bus, seen = EventBus(), []
    bus.subscribe("status", lambda event: 1 / 0)
    unsubscribe = bus.subscribe("status", lambda event: seen.append(event.data))
    bus.emit("status", 1)
    unsubscribe()
    unsubscribe()
    bus.emit("status", 2)
    assert seen == [1]


def test_supervisor_orders_shutdown_and_isolates_start_failure():
    bus = EventBus()
    states = StateStore(bus)
    supervisor = ServiceSupervisor(states)
    calls = []
    class Service:
        def __init__(self, name):
            self.name = name
        def start(self):
            calls.append("start-" + self.name)
            if self.name == "bad":
                raise OSError("start")
        def stop(self):
            calls.append("stop-" + self.name)
    supervisor.register("dependent", Service("dependent"), "base")
    supervisor.register("base", Service("base"))
    supervisor.register("bad", Service("bad"))
    supervisor.register("unrelated", Service("unrelated"))
    supervisor.start()
    assert supervisor.active == ("base", "dependent", "unrelated")
    assert {item.name: item.state for item in states.snapshot()}["bad"] == ServiceState.ERROR
    assert supervisor.stop()
    assert calls[-3:] == ["stop-unrelated", "stop-dependent", "stop-base"]


def test_supervisor_retains_unfinished_owner_and_its_dependencies():
    supervisor = ServiceSupervisor(StateStore(EventBus()))
    class Service:
        def start(self): pass
        def stop(self): return True
    class Slow(Service):
        def stop(self): return False
    supervisor.register("base", Service())
    supervisor.register("slow", Slow(), "base")
    supervisor.start()
    assert not supervisor.stop()
    assert supervisor.active == ("base", "slow")


def test_router_deduplicates_pending_completed_and_conflicting_commands():
    router = CommandRouter(clock=lambda: 101)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def execute(command):
        calls.append(command.id)
        started.set()
        release.wait(2)
        return {"applied": True}
    router.register("audio.volume", execute)
    command = Command.parse(payload(), now=101)
    try:
        assert router.submit(command, lambda result: finished.set()).status == "accepted"
        assert started.wait(1)
        assert router.submit(command, lambda result: None).status == "pending"
        conflict = Command.parse(payload(arguments={"value": 90}), now=101)
        assert router.submit(conflict, lambda result: None).code == "id_conflict"
        release.set()
        assert finished.wait(1)
        assert router.submit(command, lambda result: None).status == "succeeded"
        assert calls == ["test-1"]
        assert router.submit(Command.parse(payload(kind="shell.run"), now=101), lambda result: None).code == "not_allowed"
    finally:
        release.set()
        assert router.stop()
    assert router.submit(command, lambda result: None).code == "stopping"
