import re

_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CORNERS = {"top_left", "top_right", "bottom_left", "bottom_right", "top_center"}
_PRIORITIES = {"low": 0, "normal": 1, "high": 2, "critical": 3}
_MAX_PARALLEL_CARDS = 4
_PARALLEL_GAP = 10
_WINDOW_EXTRA_WIDTH = 0
_WINDOW_EXTRA_HEIGHT = 0
_PRESET_COLORS = {
    "default": "#91a1a8",
    "success": "#43ce89",
    "warning": "#f2b84b",
    "error": "#e4656a",
    "info": "#5aa9e6",
}
