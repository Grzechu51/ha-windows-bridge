from __future__ import annotations

from PySide6.QtCore import QRect

from ha_windows_bridge.overlay import OverlayManager


def test_overlay_request_is_bounded_and_uses_safe_defaults() -> None:
    manager = OverlayManager(duration_seconds=8)
    request = manager._validated_request(  # noqa: SLF001
        "  ",
        "message" * 500,
        {
            "id": "invalid id with spaces",
            "corner": "somewhere",
            "size": "huge",
            "layout": "unknown",
            "preset": "unknown",
            "progress": 250,
            "duration": 999,
            "opacity": 0.01,
            "monitor": 99,
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
    assert request["icon"] == "1234567890"

    default_request = manager._validated_request("Title", "Message", {})  # noqa: SLF001
    assert default_request["opacity"] == 0.94
    assert default_request["icon"] == ""
    assert default_request["show_close_button"] is False
    assert default_request["close_on_click"] is False


def test_overlay_uses_action_defaults_and_configured_monitor() -> None:
    manager = OverlayManager(default_monitor=2)

    request = manager._validated_request("Title", "Message", {})  # noqa: SLF001

    assert request["monitor"] == 2
    assert request["corner"] == "top_right"
    assert request["size_mode"] == "auto"
    assert request["opacity"] == 0.94
    assert request["show_close_button"] is False
    assert request["close_on_click"] is False


def test_overlay_manual_size_and_legacy_size_are_supported() -> None:
    manager = OverlayManager()

    manual = manager._validated_request(  # noqa: SLF001
        "Title", "Message", {"size_mode": "manual", "width": 730, "height": 410}
    )
    legacy = manager._validated_request("Title", "Message", {"size": "large"})  # noqa: SLF001

    assert (manual["size_mode"], manual["width"], manual["height"]) == (
        "manual",
        730,
        410,
    )
    assert legacy["size_mode"] == "manual"
    assert legacy["width"] == 520


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
