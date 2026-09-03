from pathlib import Path

from PIL import Image


def test_brand_icons_are_included_and_not_empty() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("icon.png", "dark_icon.png"):
        integration_icon = root / "custom_components" / "ha_windows_bridge" / "brand" / name
        repository_icon = root / "brand" / name
        assert integration_icon.read_bytes() == repository_icon.read_bytes()
        with Image.open(integration_icon) as source:
            assert source.format == "PNG"
            assert source.size == (256, 256)
            image = source.convert("RGBA")
            assert image.getbbox() is not None
            assert len(image.getcolors(image.width * image.height)) > 16
            assert image.getchannel("A").getextrema() == (0, 255)
