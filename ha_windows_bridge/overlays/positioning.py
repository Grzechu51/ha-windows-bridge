"""Logical-pixel placement, shared by every card kind and independent of Qt."""
from __future__ import annotations

from dataclasses import dataclass


def position_at_edge(area, width, height, corner, margin=0):
    """Single-card geometry retained as a useful pure algorithm."""
    left, top, area_width, area_height = area
    margin_x = min(max(0, margin), max(0, (area_width - width) // 2))
    margin_y = min(max(0, margin), max(0, (area_height - height) // 2))
    x, y = left + margin_x, top + margin_y
    if corner in {"top_right", "bottom_right"}:
        x = left + area_width - width - margin_x
    elif corner == "top_center":
        x = left + (area_width - width) // 2
    if corner in {"bottom_left", "bottom_right"}:
        y = top + area_height - height - margin_y
    return max(left, x), max(top, y)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    def intersects(self, other, gap=0):
        return self.x < other.right + gap and self.right + gap > other.x and self.y < other.bottom + gap and self.bottom + gap > other.y


@dataclass(frozen=True)
class CardSize:
    id: str
    width: int
    height: int
    corner: str = "top_right"
    badge: bool = False
    edge: int = 16


class PlacementEngine:
    """Pack badge rows and card columns, never overlapping other anchor groups.

    Unplaced IDs are deliberately omitted: the host defers them instead of
    clipping or overlapping. Coordinates are logical pixels (Qt scales once).
    """

    def __init__(self, gap=10):
        self.gap = gap

    def place(self, area: Rect, cards: list[CardSize]) -> dict[str, Rect]:
        placed = {}
        for card in cards:
            edge = max(0, min(card.edge, (min(area.width, area.height) - 1) // 2))
            bounds = Rect(area.x + edge, area.y + edge, area.width - edge * 2, area.height - edge * 2)
            if card.width > bounds.width or card.height > bounds.height:
                continue
            right = card.corner.endswith("right")
            bottom = card.corner.startswith("bottom")
            start_x = bounds.right - card.width if right else bounds.x
            if card.corner.endswith("center"):
                start_x = bounds.x + (bounds.width - card.width) // 2
            start_y = bounds.bottom - card.height if bottom else bounds.y
            xs = {start_x}
            ys = {start_y}
            for occupied in placed.values():
                if card.badge:
                    xs.add(occupied.x - self.gap - card.width if right else occupied.right + self.gap)
                ys.add(occupied.y - self.gap - card.height if bottom else occupied.bottom + self.gap)
            for y in sorted(ys, reverse=bottom):
                found = False
                for x in sorted(xs, reverse=right):
                    candidate = Rect(x, y, card.width, card.height)
                    if candidate.x < bounds.x or candidate.y < bounds.y or candidate.right > bounds.right or candidate.bottom > bounds.bottom:
                        continue
                    if any(candidate.intersects(other, self.gap) for other in placed.values()):
                        continue
                    placed[card.id] = candidate
                    found = True
                    break
                if found:
                    break
        return placed
