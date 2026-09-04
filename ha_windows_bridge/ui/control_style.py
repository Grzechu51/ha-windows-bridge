from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle

from .theme import PALETTES, normalize_theme


class BridgeProxyStyle(QProxyStyle):
    """Draw checks with the shared theme; QSS must not cover the checkmark."""

    def drawPrimitive(self, element, option, painter: QPainter, widget=None) -> None:
        if element != QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            super().drawPrimitive(element, option, painter, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect.adjusted(1, 1, -1, -1))
        checked = bool(option.state & QStyle.StateFlag.State_On)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)

        palette = PALETTES[normalize_theme(QApplication.instance().property("bridgeTheme"))]
        border = QColor(palette.accent if hovered or checked else palette.muted)
        fill = QColor(palette.accent if checked else palette.field)
        if not enabled:
            border.setAlpha(105)
            fill.setAlpha(105)
        painter.setPen(QPen(border, 1.8))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 4.5, 4.5)

        if checked:
            check = QPainterPath()
            check.moveTo(rect.left() + 4.2, rect.center().y())
            check.lineTo(rect.left() + 7.7, rect.bottom() - 4.4)
            check.lineTo(rect.right() - 3.7, rect.top() + 4.1)
            ink = QColor(palette.accent_text)
            if not enabled:
                ink.setAlpha(150)
            pen = QPen(ink, 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(check)
        painter.restore()
