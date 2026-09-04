"""Artwork composition and colour rules retained from the 0.9.0 player."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPixmap


def artwork_rect(card: QSize, artwork: QSize) -> QRectF:
    width, height = max(1, card.width()), max(1, card.height())
    scale = min(round(width * .68) / max(1, artwork.width()), height / max(1, artwork.height()))
    image_width, image_height = max(1, round(artwork.width() * scale)), max(1, round(artwork.height() * scale))
    return QRectF(width - image_width, (height - image_height) // 2, image_width, image_height)


def transition_bounds(width, rect):
    blend = max(72, min(round(width * .29), round(rect.width() * .72)))
    return max(0, rect.left() - round(blend * .22)), min(width, rect.left() + blend)


def edge_colour(pixmap: QPixmap | None) -> QColor:
    if pixmap is None or pixmap.isNull():
        return QColor(47, 61, 67)
    sample = pixmap.toImage().scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    red = green = blue = total = 0.0
    for x in range(max(1, round(sample.width() * .35))):
        for y in range(sample.height()):
            color = sample.pixelColor(x, y)
            if color.alpha() < 32:
                continue
            weight = 1 + color.hsvSaturationF() * 1.6
            if color.lightness() >= 242:
                weight *= .35
            red += color.red() * weight
            green += color.green() * weight
            blue += color.blue() * weight
            total += weight
    return QColor(round(red / total), round(green / total), round(blue / total)) if total else QColor(28, 34, 38)


def contrast_ratio(first: QColor, second: QColor) -> float:
    def luminance(color):
        channels = [channel / 255 for channel in (color.red(), color.green(), color.blue())]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear, strict=True))
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def ensure_contrast(foreground, background, minimum):
    if contrast_ratio(foreground, background) >= minimum:
        return foreground
    hsl = foreground.toHsl()
    hue = hsl.hslHue() if hsl.hslHue() >= 0 else 190
    target = 18 if background.lightness() >= 145 else 238
    for step in range(1, 21):
        adjusted = QColor.fromHsl(hue, max(0, hsl.hslSaturation()), round(hsl.lightness() + (target - hsl.lightness()) * step / 20))
        if contrast_ratio(adjusted, background) >= minimum:
            return adjusted
    return QColor("#111617" if background.lightness() >= 145 else "#f3f7f5")


def media_palette(pixmap: QPixmap | None):
    artwork = edge_colour(pixmap)
    hsl = artwork.toHsl()
    hue = hsl.hslHue() if hsl.hslHue() >= 0 else 190
    saturation = max(28, min(150, hsl.hslSaturation()))
    light = artwork.lightness() >= 145
    surface = QColor.fromHsl(hue, max(24, round(saturation * .72)), 205 if light else max(38, min(92, round(artwork.lightness() * .78))))
    if light:
        primary = QColor.fromHsl(hue, max(32, min(115, saturation)), 42)
        secondary = QColor.fromHsl(hue, max(20, min(80, round(saturation * .65))), 72)
    else:
        primary = QColor.fromHsl(hue, max(32, min(135, saturation)), 220)
        secondary = QColor.fromHsl(hue, max(18, min(90, round(saturation * .58))), 178)
    return surface, ensure_contrast(primary, surface, 4.8), ensure_contrast(secondary, surface, 3.6)
