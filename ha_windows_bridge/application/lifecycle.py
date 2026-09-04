"""Dependency-ordered startup and reverse shutdown, independent of GUI."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

from ..core.state import ServiceState, StateStore


class Service(Protocol):
    def start(self) -> None: ...
    def stop(self) -> bool | None: ...


@dataclass(frozen=True)
class Registration:
    service: Service
    dependencies: tuple[str, ...] = ()


class ServiceSupervisor:
    def __init__(self, states: StateStore, logger: logging.Logger | None = None):
        self.states = states
        self.log = logger or logging.getLogger("bridge.app")
        self._services: dict[str, Registration] = {}
        self._active: list[str] = []
        self._ready: set[str] = set()
        self._lock = threading.RLock()

    def register(self, name: str, service: Service, *dependencies: str) -> None:
        with self._lock:
            if self._active:
                raise RuntimeError("Cannot alter services while running")
            if name in self._services:
                raise ValueError(f"Duplicate service: {name}")
            self._services[name] = Registration(service, dependencies)
            self.states.set(name, ServiceState.STOPPED)

    def _order(self) -> list[str]:
        ordered: list[str] = []
        visiting: set[str] = set()
        def visit(name: str) -> None:
            if name in ordered:
                return
            if name in visiting:
                raise ValueError(f"Cyclic service dependency: {name}")
            if name not in self._services:
                raise ValueError(f"Unknown service dependency: {name}")
            visiting.add(name)
            for dependency in self._services[name].dependencies:
                visit(dependency)
            visiting.remove(name)
            ordered.append(name)
        for name in self._services:
            visit(name)
        return ordered

    def start(self) -> None:
        with self._lock:
            for name in self._order():
                if name in self._active:
                    continue
                registration = self._services[name]
                if any(dependency not in self._ready for dependency in registration.dependencies):
                    self.states.set(name, ServiceState.ERROR, "dependency_unavailable")
                    continue
                self.states.set(name, ServiceState.STARTING)
                try:
                    registration.service.start()
                except Exception:
                    self.log.exception("Service startup failed: %s", name)
                    self.states.set(name, ServiceState.ERROR, "startup_failed")
                    # Partially started services also own resources.
                    try:
                        if registration.service.stop() is False:
                            self._active.append(name)
                    except Exception:
                        self._active.append(name)
                        self.log.exception("Partial startup cleanup failed: %s", name)
                else:
                    self._active.append(name)
                    self._ready.add(name)
                    self.states.set(name, ServiceState.RUNNING)

    def stop(self) -> bool:
        with self._lock:
            for name in tuple(reversed(self._active)):
                # A failed dependent must stop before its dependencies are torn down.
                if any(name in self._services[active].dependencies for active in self._active):
                    continue
                self.states.set(name, ServiceState.STOPPING)
                try:
                    stopped = self._services[name].service.stop()
                    if stopped is False:
                        raise RuntimeError("service still stopping")
                except Exception:
                    self.log.exception("Service shutdown incomplete: %s", name)
                    self.states.set(name, ServiceState.ERROR, "shutdown_incomplete")
                    continue
                self._active.remove(name)
                self._ready.discard(name)
                self.states.set(name, ServiceState.STOPPED)
            return not self._active

    @property
    def active(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._active)
