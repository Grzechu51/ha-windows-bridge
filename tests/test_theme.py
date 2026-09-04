from __future__ import annotations

from ha_windows_bridge.theme import normalize_theme, style_for_theme
from ha_windows_bridge.ui.theme import PALETTES


def test_theme_name_is_normalized_safely() -> None:
    assert normalize_theme(" LIGHT ") == "light"
    assert normalize_theme("unknown") == "dark"


def test_style_adds_distinct_dark_and_light_palettes() -> None:
    base = "QWidget { font-size: 10pt; }"

    assert PALETTES["dark"].canvas in style_for_theme(base, "dark")
    assert PALETTES["light"].canvas in style_for_theme(base, "light")
    assert base in style_for_theme(base, "dark")
    assert style_for_theme(base, "dark") != style_for_theme(base, "light")


def test_light_palette_overrides_problematic_dark_components() -> None:
    style = style_for_theme("", "light")

    assert "QFrame#uninstallCard" in style
    assert "QPushButton#dangerButton" in style
    assert "QLabel#masterAvatar" in style
    assert "QLabel#microphoneAvatar" in style
    assert "QLabel#audioOutputAvatar" in style
    assert "QSlider::groove:horizontal:disabled" in style
    assert "QToolButton#helpButton" in style
    assert "background: #ffffff" in style
    assert "color: " + PALETTES["light"].text in style
