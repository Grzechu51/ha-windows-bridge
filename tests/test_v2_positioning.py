import pytest

from ha_windows_bridge.overlays.positioning import CardSize, PlacementEngine, Rect


@pytest.mark.parametrize("corner", ["top_left", "top_right", "top_center", "bottom_left", "bottom_right"])
@pytest.mark.parametrize("area", [Rect(0, 0, 1920, 1040), Rect(-1280, -320, 1280, 720), Rect(0, 0, 640, 480)])
def test_mixed_cards_are_inside_work_area_without_overlap(corner, area):
    cards = [CardSize("battery", 90, 40, corner, True), CardSize("light", 42, 40, corner, True),
             CardSize("message", 380, 120, corner), CardSize("media", 380, 180, "top_center")]
    placed = PlacementEngine().place(area, cards)
    assert len(placed) == 4
    for item in placed.values():
        assert item.x >= area.x + 16 and item.y >= area.y + 16
        assert item.right <= area.right - 16 and item.bottom <= area.bottom - 16
    values = list(placed.values())
    assert not any(left.intersects(right, 10) for i, left in enumerate(values) for right in values[i + 1:])


def test_overflow_is_not_clipped_or_overlapped():
    placed = PlacementEngine().place(Rect(0, 0, 400, 240), [CardSize(str(i), 360, 120) for i in range(4)])
    assert len(placed) == 1


def test_badges_pack_horizontally_with_gap():
    placed = PlacementEngine().place(Rect(0, 0, 1000, 800), [CardSize(str(i), 80, 40, badge=True) for i in range(3)])
    assert {item.y for item in placed.values()} == {16}
    xs = sorted(item.x for item in placed.values())
    assert xs[1] - xs[0] == xs[2] - xs[1] == 90
