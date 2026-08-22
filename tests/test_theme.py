from __future__ import annotations

from ha_windows_bridge.theme import normalize_theme, style_for_theme


def test_theme_name_is_normalized_safely() -> None:
    assert normalize_theme(" LIGHT ") == "light"
    assert normalize_theme("unknown") == "dark"


def test_style_adds_distinct_dark_and_light_palettes() -> None:
    base = "QWidget { font-size: 10pt; }"

    assert "#050607" in style_for_theme(base, "dark")
    assert "#f4f6f7" in style_for_theme(base, "light")
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
    assert "color: #17211d" in style
