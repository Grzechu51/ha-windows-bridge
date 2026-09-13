"""Stable monitor topology and existing HA inventory projection coverage."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from ha_windows_bridge.application.telemetry import TelemetryService
from ha_windows_bridge.application.windows_commands import WindowsCommands
from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.core.commands import Command
from ha_windows_bridge.core.events import Event, EventBus
from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import DeliveryDisposition, LifecycleReason
from ha_windows_bridge.overlays.monitors import (
    monitor_label,
    resolve_screen,
    screen_id,
    selected_monitor_label,
)
from ha_windows_bridge.overlays.positioning import CardSize, PlacementEngine, Rect


class Screen:
    def __init__(self, name, manufacturer="", model="", serial=""):
        self._values = name, manufacturer, model, serial

    def name(self):
        return self._values[0]

    def manufacturer(self):
        return self._values[1]

    def model(self):
        return self._values[2]

    def serialNumber(self):
        return self._values[3]


def test_stable_monitor_identity_survives_reorder_and_has_os_name_fallback():
    left = Screen("DISPLAY1", "Dell", "U2720Q", "ABC")
    right = Screen("DISPLAY2", "LG", "27UP", "XYZ")
    assert screen_id(left) == "Dell:U2720Q:ABC"
    assert screen_id(Screen("DISPLAY3")) == "DISPLAY3"
    labels = [monitor_label(screen_id(item), index)
              for index, item in enumerate((right, left))]
    assert selected_monitor_label(labels, screen_id(left), 0) == labels[1]
    assert resolve_screen((right, left), screen_id(left), 0, right) is left


def test_monitor_disconnect_falls_back_to_primary_and_no_screen_is_safe():
    primary = Screen("PRIMARY")
    secondary = Screen("SECONDARY")
    assert resolve_screen((primary,), screen_id(secondary), 1, primary) is primary
    assert resolve_screen((), screen_id(secondary), 1, None) is None


def test_mixed_dpi_work_areas_are_positioned_in_each_screen_coordinates():
    engine = PlacementEngine()
    card = CardSize("card", 420, 120, "bottom_right", False, 20)
    assert engine.place(Rect(-2560, 0, 2560, 1440), [card])["card"].x == -440
    assert engine.place(Rect(0, 0, 1920, 1040), [card])["card"].x == 1480


def test_config_roundtrip_keeps_preferred_monitor_id():
    config = AppConfig(overlay_monitor=1, overlay_monitor_id="Dell:U2720Q:ABC")
    restored = AppConfig.from_dict(config.to_dict())
    assert (restored.overlay_monitor, restored.overlay_monitor_id) == (
        1, "Dell:U2720Q:ABC"
    )


def test_explicit_command_monitor_wins_over_configured_default():
    config = AppConfig(
        overlay_enabled=True, overlay_monitor=0,
        overlay_monitor_id="PRIMARY",
    )
    engine = NotificationEngine()
    commands = WindowsCommands(
        config, object(), SimpleNamespace(context_snapshot=lambda: SimpleNamespace(
            locked=False, fullscreen=False
        )), object(), object(), EventBus(),
        ["1: PRIMARY", "2: SECONDARY"], notifications=engine,
    )
    result = commands._notification(Command(
        "cmd", "overlay.show", "",
        {"message": "hello", "data": {"id": "card", "monitor_id": "SECONDARY"}},
        9999999999,
    ))
    assert result["delivery"] == "accepted"
    assert engine.visible["card"].options["monitor_id"] == "SECONDARY"


def test_removed_display_has_terminal_reason_and_hotplug_wakes_inventory_worker():
    engine = NotificationEngine()
    admitted = engine.submit({"data": {"id": "card", "monitor_id": "SECONDARY"}})
    engine.mark_displayed("card", admitted.token)
    engine.drain_lifecycle()
    assert engine.begin_retire("card", admitted.token, LifecycleReason.DISPLAY_REMOVED)
    terminal = engine.drain_lifecycle()
    assert [(item.disposition, item.reason) for item in terminal] == [
        (DeliveryDisposition.CLOSED, LifecycleReason.DISPLAY_REMOVED)
    ]

    telemetry = object.__new__(TelemetryService)
    telemetry._inventory_requested = threading.Event()
    telemetry._wake_event = threading.Event()
    telemetry._connection_changed(Event("overlay.monitors_changed", ("1: PRIMARY",)))
    assert telemetry._inventory_requested.is_set() and telemetry._wake_event.is_set()
