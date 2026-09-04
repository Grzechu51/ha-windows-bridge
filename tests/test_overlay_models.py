from __future__ import annotations

import pytest

from ha_windows_bridge.overlays.engine import NotificationEngine
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.positioning import position_at_edge


def test_priority_queue_keeps_critical_card_on_overflow_and_stable_order():
    queue = NotificationEngine(limit=1, queue_limit=3)
    queue.submit({"data": {"id": "visible", "pinned": True}})
    for message_id, priority in [("critical", 3), ("normal-1", 1), ("normal-2", 1), ("low", 0)]:
        queue.submit({"data": {"id": message_id, "priority": priority}})
    assert [item.id for item in queue.pending] == ["critical", "normal-1", "normal-2"]
    queue.submit({"title": "updated", "data": {"id": "normal-1", "action": "update"}})
    assert len(queue.pending) == 3
    assert next(item for item in queue.pending if item.id == "normal-1").options["title"] == "updated"
    queue.remove("critical")
    assert len(queue.pending) == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "1e999"])
def test_model_rejects_non_finite_numbers(value):
    request = validated_request("test", "", {"opacity": value, "media_position": value, "media_duration": value, "progress": value})
    assert request["opacity"] == 0.94
    assert request["media_position"] == request["media_duration"] == 0
    assert request["progress"] is None


def test_ids_are_unique_even_when_input_object_is_reused():
    options = {}
    assert validated_request("", "", options)["id"] != validated_request("", "", options)["id"]


def test_positioning_handles_negative_origins_and_large_margin():
    assert position_at_edge((-1920, -1080, 1920, 1080), 400, 100, "bottom_right", 20) == (-420, -120)
    assert position_at_edge((0, 0, 300, 100), 250, 80, "top_right", 240) == (25, 10)
