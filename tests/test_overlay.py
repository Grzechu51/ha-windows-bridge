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
    assert request["size"] == "medium"
    assert request["layout"] == "default"
    assert request["preset"] == "default"
    assert request["progress"] == 100
    assert request["duration"] == 60
    assert request["opacity"] == 0.35
    assert request["monitor"] == 15
    assert request["icon"] == "12345678"

    default_request = manager._validated_request("Title", "Message", {})  # noqa: SLF001
    assert default_request["opacity"] == 0.92


def test_overlay_queue_can_update_remove_and_clear_messages() -> None:
    manager = OverlayManager()
    manager._display = lambda _request: True  # type: ignore[method-assign]  # noqa: SLF001

    assert manager.handle_message("One", "First", {"id": "one", "pinned": True})
    assert manager.handle_message("Two", "Second", {"id": "two"})
    assert manager.handle_message(
        "Two updated", "Changed", {"action": "update", "id": "two"}
    )
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
    assert manager.handle_message(
        "", "Halfway", {"action": "update", "id": "job", "progress": 50}
    )
    assert manager._current is not None  # noqa: SLF001
    assert manager._current["title"] == "Download"  # noqa: SLF001
    assert manager._current["pinned"] is True  # noqa: SLF001
    assert manager._current["preset"] == "info"  # noqa: SLF001
    assert manager._current["progress"] == 50  # noqa: SLF001
    assert not manager.handle_message(
        "Missing", "No item", {"action": "update", "id": "unknown"}
    )


def test_overlay_is_placed_close_to_each_screen_corner() -> None:
    area = QRect(100, 50, 1000, 600)

    assert OverlayManager._position_for_geometry(area, 420, 120, "top_left") == (104, 54)
    assert OverlayManager._position_for_geometry(area, 420, 120, "top_right") == (676, 54)
    assert OverlayManager._position_for_geometry(area, 420, 120, "bottom_left") == (104, 526)
    assert OverlayManager._position_for_geometry(area, 420, 120, "bottom_right") == (
        676,
        526,
    )
    assert OverlayManager._position_for_geometry(area, 420, 120, "top_center") == (
        390,
        54,
    )
