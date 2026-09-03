from __future__ import annotations

from PySide6.QtCore import QPoint, QRect

from ha_windows_bridge.overlay import OverlayManager


def test_cpu_capture_bounds_respect_per_monitor_dpi() -> None:
    bounds = OverlayManager._physical_capture_bounds(  # noqa: SLF001
        QPoint(-2520, 20),
        200,
        100,
        QRect(-2560, 0, 1707, 960),
        1.5,
    )

    assert bounds == (-2500, 30, -2200, 180)


def test_overlay_request_is_bounded_and_uses_safe_defaults() -> None:
    manager = OverlayManager(duration_seconds=8)
    request = manager._validated_request(  # noqa: SLF001
        "  ",
        "message" * 500,
        {
            "id": "invalid id with spaces",
            "corner": "somewhere",
            "layout": "unknown",
            "preset": "unknown",
            "progress": 250,
            "duration": 999,
            "opacity": 0.01,
            "monitor": 99,
            "edge_offset": 999,
            "icon": "1234567890",
        },
    )

    assert request["title"] == "Home Assistant"
    assert len(request["message"]) == 2048
    assert request["id"].startswith("message-")
    assert request["corner"] == "top_right"
    assert request["size_mode"] == "auto"
    assert request["width"] == 400
    assert request["height"] == 160
    assert request["layout"] == "default"
    assert request["preset"] == "default"
    assert request["progress"] == 100
    assert request["duration"] == 60
    assert request["opacity"] == 0.01
    assert request["monitor"] == 15
    assert request["edge_offset"] == 240
    assert request["icon"] == "1234567890"

    default_request = manager._validated_request("Title", "Message", {})  # noqa: SLF001
    assert default_request["opacity"] == 0.94
    assert default_request["icon"] == ""
    assert default_request["show_close_button"] is False
    assert default_request["close_on_click"] is False
    assert default_request["background_effect"] == "none"
    assert default_request["glass"] is False
    assert default_request["edge_offset"] == 0
    assert default_request["display_mode"] == "queue"

    parallel_request = manager._validated_request(  # noqa: SLF001
        "Battery", "78%", {"layout": "status", "display_mode": "parallel"}
    )
    assert parallel_request["layout"] == "status"
    assert parallel_request["display_mode"] == "parallel"

    icon_badge = manager._validated_request(  # noqa: SLF001
        "", "", {"layout": "badge", "icon": "mdi:lightbulb-on"}
    )
    assert icon_badge["layout"] == "badge"
    assert icon_badge["title"] == ""

    blur_request = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"background_effect": "blur"}
    )
    liquid_request = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"background_effect": "liquid"}
    )
    invalid_effect = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"background_effect": "unknown"}
    )
    assert blur_request["background_effect"] == "blur"
    assert blur_request["glass"] is True
    assert liquid_request["background_effect"] == "liquid"
    assert liquid_request["glass"] is True
    assert invalid_effect["background_effect"] == "none"
    assert invalid_effect["glass"] is False


def test_overlay_uses_action_defaults_and_configured_monitor() -> None:
    manager = OverlayManager(default_monitor=2)

    request = manager._validated_request("Title", "Message", {})  # noqa: SLF001

    assert request["monitor"] == 2
    assert request["corner"] == "top_right"
    assert request["size_mode"] == "auto"
    assert request["opacity"] == 0.94
    assert request["show_close_button"] is False
    assert request["close_on_click"] is False


def test_overlay_manual_size_is_supported_and_removed_alias_is_ignored() -> None:
    manager = OverlayManager()

    manual = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"size_mode": "manual", "width": 730, "height": 410}
    )
    removed_alias = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"size": "large"}
    )

    assert (manual["size_mode"], manual["width"], manual["height"]) == (
        "manual",
        730,
        410,
    )
    assert removed_alias["size_mode"] == "auto"
    assert removed_alias["width"] == 400


def test_overlay_queue_can_update_remove_and_clear_messages() -> None:
    manager = OverlayManager()
    manager._display = lambda _request: True  # type: ignore[method-assign]  # noqa: SLF001

    assert manager.handle_message("One", "First", {"id": "one", "pinned": True})
    assert manager.handle_message("Two", "Second", {"id": "two"})
    assert manager.handle_message("Two updated", "Changed", {"action": "update", "id": "two"})
    assert len(manager._queue) == 1  # noqa: SLF001
    assert manager._queue[0]["title"] == "Two updated"  # noqa: SLF001

    assert manager.handle_message("", "", {"action": "remove", "id": "two"})
    assert not manager._queue  # noqa: SLF001
    assert manager.handle_message("", "", {"action": "clear"})
    assert manager._current is None  # noqa: SLF001


def test_overlay_priorities_and_automatic_layouts() -> None:
    manager = OverlayManager()
    manager._display = lambda _request: True  # type: ignore[method-assign]  # noqa: SLF001

    assert manager.handle_message(
        "Routine", "Queued", {"id": "routine", "priority": "low"}
    )
    assert manager.handle_message(
        "Security", "Motion", {"id": "camera", "priority": "critical"}
    )
    assert manager._current["id"] == "camera"  # noqa: SLF001
    assert manager._queue[0]["id"] == "routine"  # noqa: SLF001

    assert manager.handle_message("", "", {"action": "clear"})
    assert manager._current is None  # noqa: SLF001
    assert not manager._queue  # noqa: SLF001

    compact = manager._validated_request("Short", "Text", {})  # noqa: SLF001
    camera = manager._validated_request("Camera", "Motion", {"layout": "camera"})  # noqa: SLF001
    assert manager._resolve_layout(compact, False) == "compact"  # noqa: SLF001
    assert manager._resolve_layout(camera, True) == "camera"  # noqa: SLF001
    assert camera["camera"] is True


def test_overlay_lifetime_options_are_validated() -> None:
    manager = OverlayManager()
    request = manager._validated_request(  # noqa: SLF001
        "Timed",
        "Hover",
        {"show_lifetime": True, "pause_on_hover": True, "priority": "high"},
    )
    assert request["show_lifetime"] is True
    assert request["pause_on_hover"] is True
    assert request["priority"] == 2
    assert request["priority_name"] == "high"


def test_overlay_update_keeps_unspecified_options_and_requires_existing_id() -> None:
    manager = OverlayManager()
    manager._display = lambda _request: True  # type: ignore[method-assign]  # noqa: SLF001

    assert manager.handle_message(
        "Download", "Starting", {"id": "job", "pinned": True, "preset": "info"}
    )
    assert manager.handle_message("", "Halfway", {"action": "update", "id": "job", "progress": 50})
    assert manager._current is not None  # noqa: SLF001
    assert manager._current["title"] == "Download"  # noqa: SLF001
    assert manager._current["pinned"] is True  # noqa: SLF001
    assert manager._current["preset"] == "info"  # noqa: SLF001
    assert manager._current["progress"] == 50  # noqa: SLF001
    assert not manager.handle_message("Missing", "No item", {"action": "update", "id": "unknown"})


def test_overlay_is_placed_close_to_each_screen_corner() -> None:
    area = QRect(100, 50, 1000, 600)

    assert OverlayManager._position_for_geometry(area, 420, 120, "top_left") == (100, 50)
    assert OverlayManager._position_for_geometry(area, 420, 120, "top_right") == (680, 50)
    assert OverlayManager._position_for_geometry(area, 420, 120, "bottom_left") == (100, 530)
    assert OverlayManager._position_for_geometry(area, 420, 120, "bottom_right") == (
        680,
        530,
    )
    assert OverlayManager._position_for_geometry(area, 420, 120, "top_center") == (
        390,
        50,
    )
