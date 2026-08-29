from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter


def _trim_transparent(image: QImage) -> QImage:
    if not image.hasAlphaChannel():
        return image
    left, top = image.width(), image.height()
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if QColor.fromRgba(image.pixel(x, y)).alpha() <= 8:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return image
    return image.copy(QRect(left, top, right - left + 1, bottom - top + 1))


def _square_icon(image: QImage, size: int = 256) -> QImage:
    trimmed = _trim_transparent(image)
    content = trimmed.scaled(
        size - 12,
        size - 12,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size - content.width()) // 2, (size - content.height()) // 2, content)
    painter.end()
    return canvas


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "assets" / "icon.png"
    destination = root / "assets" / "icon.ico"
    integration_brand = root / "custom_components" / "ha_windows_bridge" / "brand"
    hacs_brand = root / "brand"
    original = QImage(str(source))
    if original.isNull():
        raise RuntimeError("Nie można odczytać assets/icon.png")
    image = _square_icon(original)
    if not image.save(str(destination), "ICO"):
        raise RuntimeError("Qt nie potrafi zapisać assets/icon.ico")
    for directory in (integration_brand, hacs_brand):
        directory.mkdir(parents=True, exist_ok=True)
        for filename in ("icon.png", "dark_icon.png"):
            if not image.save(str(directory / filename), "PNG"):
                raise RuntimeError("Qt nie potrafi zapisać ikony integracji Home Assistant")
    for filename in ("logo.png", "dark_logo.png"):
        if not image.save(str(integration_brand / filename), "PNG"):
            raise RuntimeError("Qt nie potrafi zapisać logo integracji Home Assistant")


if __name__ == "__main__":
    main()
