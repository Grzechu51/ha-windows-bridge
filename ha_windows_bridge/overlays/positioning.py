"""Geometry in logical pixels; independent of Qt, physical DPI and capture APIs."""


def position_at_edge(
    area: tuple[int, int, int, int], width: int, height: int, corner: str, margin: int = 0
) -> tuple[int, int]:
    left, top, area_width, area_height = area
    # A large margin on a small/removed monitor must not push content off-screen.
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
