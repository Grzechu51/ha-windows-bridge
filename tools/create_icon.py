from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "assets" / "icon.png"
    destination = root / "assets" / "icon.ico"
    integration_icon = root / "custom_components" / "ha_windows_bridge" / "brand" / "icon.png"
    original = QImage(str(source))
    if original.isNull():
        raise RuntimeError("Nie można odczytać assets/icon.png")
    image = original.scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if not image.save(str(destination), "ICO"):
        raise RuntimeError("Qt nie potrafi zapisać assets/icon.ico")
    integration_icon.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(integration_icon), "PNG"):
        raise RuntimeError("Qt nie potrafi zapisać ikony integracji Home Assistant")


if __name__ == "__main__":
    main()
