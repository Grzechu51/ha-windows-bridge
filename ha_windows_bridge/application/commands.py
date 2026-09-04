"""Bounded command execution, explicit allowlist and idempotent retry results."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core.commands import Command, CommandError, CommandResult
from ..runtime.worker import SerialWorker

Handler = Callable[[Command], dict[str, Any] | None]
Reply = Callable[[CommandResult], None]


@dataclass
class Execution:
    fingerprint: str
    created: float
    result: CommandResult | None = None
    reply: Reply | None = None
    started: bool = False


class CommandRouter:
    def __init__(self, *, logger: logging.Logger | None = None, capacity: int = 1024,
                 clock: Callable[[], float] = time.time):
        self.log = logger or logging.getLogger("bridge.commands")
        self._clock, self._capacity = clock, capacity
        self._handlers: dict[str, Handler] = {}
        self._executions: OrderedDict[str, Execution] = OrderedDict()
        self._worker = SerialWorker("bridge-commands", self.log, capacity=64)
        self._lock = threading.RLock()
        self._closed = False

    def register(self, kind: str, handler: Handler) -> None:
        with self._lock:
            if kind in self._handlers:
                raise ValueError(f"Duplicate command handler: {kind}")
            self._handlers[kind] = handler

    def submit(self, command: Command, reply: Reply) -> CommandResult:
        with self._lock:
            if self._closed:
                return CommandResult(command.id, "rejected", "stopping")
            if command.kind not in self._handlers:
                return CommandResult(command.id, "rejected", "not_allowed")
            try:
                fingerprint = command.fingerprint()
            except (ValueError, TypeError, RecursionError):
                return CommandResult(command.id, "rejected", "invalid_arguments")
            previous = self._executions.get(command.id)
            if previous:
                if previous.fingerprint != fingerprint:
                    return CommandResult(command.id, "rejected", "id_conflict")
                return previous.result or CommandResult(command.id, "pending")
            now = self._clock()
            if command.expires_at <= now:
                return CommandResult(command.id, "rejected", "expired")
            # Do not evict in-flight or recent results: saturated dedup cache rejects new work.
            for identifier, execution in tuple(self._executions.items()):
                if execution.result is not None and now - execution.created >= 300:
                    self._executions.pop(identifier)
            if len(self._executions) >= self._capacity:
                return CommandResult(command.id, "rejected", "dedup_capacity")
            self._executions[command.id] = Execution(fingerprint, now, reply=reply)
            if not self._worker.submit(lambda: self._execute(command, reply)):
                self._executions.pop(command.id)
                return CommandResult(command.id, "rejected", "queue_full")
            return CommandResult(command.id, "accepted")

    def _execute(self, command: Command, reply: Reply) -> None:
        with self._lock:
            execution = self._executions[command.id]
            if execution.result is not None:
                return
            execution.started = True
        try:
            if command.expires_at <= self._clock():
                raise CommandError("expired")
            data = self._handlers[command.kind](command) or {}
            # Windows operations cannot safely be killed halfway through an OS API.
            if command.expires_at <= self._clock():
                result = CommandResult(command.id, "failed", "deadline_exceeded", {"may_have_completed": True})
            else:
                result = CommandResult(command.id, "succeeded", data=data)
        except CommandError as exc:
            result = CommandResult(command.id, "failed", exc.code)
        except Exception:
            self.log.exception("Application command failed: %s", command.kind)
            result = CommandResult(command.id, "failed", "execution_failed")
        with self._lock:
            self._executions[command.id].result = result
            self._executions[command.id].reply = None
        self._reply(reply, result)

    def _reply(self, callback: Reply, result: CommandResult) -> None:
        try:
            callback(result)
        except Exception:
            self.log.exception("Command result delivery failed")

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def stop(self) -> bool:
        with self._lock:
            self._closed = True
        self._worker.close()
        cancelled = []
        with self._lock:
            for identifier, execution in self._executions.items():
                if execution.result is None and not execution.started:
                    execution.result = CommandResult(identifier, "cancelled", "stopping")
                    if execution.reply:
                        cancelled.append((execution.reply, execution.result))
                        execution.reply = None
        for callback, result in cancelled:
            self._reply(callback, result)
        return not self._worker.is_alive
