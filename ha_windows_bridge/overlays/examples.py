"""Local examples with original, procedurally drawn artwork; no network access."""
from __future__ import annotations

import base64
from functools import lru_cache

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen


@lru_cache(maxsize=1)
def media_artwork():
    image = QImage(360, 240, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#1e243c"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 360, 240)
    gradient.setColorAt(0, QColor("#21213f"))
    gradient.setColorAt(0.6, QColor("#995165"))
    gradient.setColorAt(1, QColor("#eda069"))
    painter.fillRect(image.rect(), gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f5be86"))
    painter.drawEllipse(QRectF(232, 26, 82, 82))
    painter.setPen(QPen(QColor(32, 35, 60, 120), 2))
    for line in range(135, 240, 16):
        painter.drawLine(0, line, 360, line)
    for point in range(-120, 540, 45):
        painter.drawLine(180, 128, point, 240)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


def media_example():
    return {"title": "Midnight Drive", "message": "Neon Avenue · City Lights", "data": {
        "id": "example-media", "layout": "media", "media_source": "PC Media Player",
        "image": media_artwork(), "icon": "mdi:music-note", "media_duration": 222,
        "media_position": 65, "media_playing": True, "show_lifetime": False,
        "show_close_button": True, "pause_on_hover": True, "duration": 12, "edge_offset": 16}}
