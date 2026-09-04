from __future__ import annotations

from PySide6.QtCore import (
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
)


class OverlayCard(QFrame):
    """Card surface that can paint glass or full-card media artwork."""

    def __init__(self) -> None:
        super().__init__()
        self._glass_background: QPixmap | None = None
        self._glass_opacity = 0.0
        self._glass_effect = "none"
        self._media_background: QPixmap | None = None
        self._media_surface = QColor(18, 22, 24)
        self._media_opacity = 1.0
        self._media_scaled: QPixmap | None = None
        self._media_scaled_key: tuple[int, int, int] | None = None
        self._text_scrim = QColor(0, 0, 0, 0)
        self._glass_accent = QColor("#91a1a8")

    def set_glass_background(
        self,
        pixmap: QPixmap | None,
        opacity: float = 0.0,
        effect: str = "none",
    ) -> None:
        self._glass_background = pixmap
        self._glass_opacity = max(0.0, min(1.0, float(opacity)))
        self._glass_effect = effect if effect in {"blur", "liquid"} else "none"
        self.update()

    def set_media_background(
        self,
        pixmap: QPixmap | None,
        surface: QColor | None = None,
        opacity: float = 1.0,
    ) -> None:
        self._media_background = pixmap
        self._media_scaled = None
        self._media_scaled_key = None
        if surface is not None:
            self._media_surface = QColor(surface)
        self._media_opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def set_glass_accent(self, color: QColor) -> None:
        self._glass_accent = QColor(color)
        self.update()

    def set_text_scrim(self, color: QColor | None = None) -> None:
        self._text_scrim = QColor(color) if color is not None else QColor(0, 0, 0, 0)
        self.update()

    @staticmethod
    def _right_artwork_rect(card_size: QSize, artwork_size: QSize) -> QRect:
        """Fit the complete artwork into the right side without cropping it."""
        card_width = max(1, card_size.width())
        card_height = max(1, card_size.height())
        artwork_width = max(1, artwork_size.width())
        artwork_height = max(1, artwork_size.height())
        maximum_width = max(1, round(card_width * 0.68))
        scale = min(maximum_width / artwork_width, card_height / artwork_height)
        width = max(1, round(artwork_width * scale))
        height = max(1, round(artwork_height * scale))
        return QRect(card_width - width, (card_height - height) // 2, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        background = self._media_background or self._glass_background
        if background is None or background.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card_rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(card_rect, 16, 16)
        painter.setClipPath(path)
        if self._media_background is not None:
            painter.setOpacity(self._media_opacity)
            painter.fillPath(path, self._media_surface)
            artwork_rect = self._right_artwork_rect(self.size(), background.size())
            cache_key = (
                int(background.cacheKey()),
                artwork_rect.width(),
                artwork_rect.height(),
            )
            if self._media_scaled is None or self._media_scaled_key != cache_key:
                self._media_scaled = background.scaled(
                    artwork_rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._media_scaled_key = cache_key
            scaled = self._media_scaled
            painter.drawPixmap(artwork_rect.topLeft(), scaled)
            transition_width = max(
                72,
                min(
                    round(self.width() * 0.29),
                    round(artwork_rect.width() * 0.72),
                ),
            )
            transition_start = max(
                0,
                artwork_rect.left() - round(transition_width * 0.22),
            )
            transition_end = min(
                self.width(),
                artwork_rect.left() + transition_width,
            )
            blend = QLinearGradient(
                transition_start,
                0,
                transition_end,
                0,
            )
            solid = QColor(self._media_surface)
            blend.setColorAt(0.0, solid)
            near_edge = QColor(solid)
            near_edge.setAlpha(250)
            blend.setColorAt(0.18, near_edge)
            middle = QColor(solid)
            middle.setAlpha(205)
            blend.setColorAt(0.45, middle)
            soft_edge = QColor(solid)
            soft_edge.setAlpha(105)
            blend.setColorAt(0.72, soft_edge)
            clear = QColor(solid)
            clear.setAlpha(0)
            blend.setColorAt(1.0, clear)
            painter.fillPath(path, QBrush(blend))
            painter.setOpacity(1.0)
        else:
            painter.setOpacity(self._glass_opacity)
            if self._glass_effect == "liquid":
                # A slight magnification of the blurred capture suggests the
                # lensing used by thicker glass without distorting the content.
                source_rect = QRectF(background.rect()).adjusted(4, 4, -4, -4)
                painter.drawPixmap(QRectF(self.rect()), background, source_rect)
            else:
                painter.drawPixmap(self.rect(), background)
            painter.setOpacity(1.0)
            if self._glass_effect == "liquid":
                shade = QLinearGradient(0, 0, 0, self.height())
                shade.setColorAt(0.0, QColor(255, 255, 255, 36))
                shade.setColorAt(0.42, QColor(255, 255, 255, 8))
                shade.setColorAt(1.0, QColor(5, 12, 18, 38))
                painter.fillPath(path, QBrush(shade))
                gloss = QRadialGradient(
                    self.width() * 0.18,
                    0,
                    max(self.width(), self.height()) * 0.78,
                )
                accent_gloss = QColor(self._glass_accent)
                accent_gloss.setAlpha(76)
                gloss.setColorAt(0.0, accent_gloss)
                accent_soft = QColor(self._glass_accent)
                accent_soft.setAlpha(28)
                gloss.setColorAt(0.34, accent_soft)
                gloss.setColorAt(0.72, QColor(188, 224, 238, 10))
                gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(path, QBrush(gloss))
                painter.setClipping(False)
                edge = QLinearGradient(0, 0, 0, self.height())
                edge_top = QColor(self._glass_accent)
                edge_top.setAlpha(168)
                edge_middle = QColor(self._glass_accent)
                edge_middle.setAlpha(58)
                edge_bottom = QColor(self._glass_accent)
                edge_bottom.setAlpha(104)
                edge.setColorAt(0.0, edge_top)
                edge.setColorAt(0.48, edge_middle)
                edge.setColorAt(1.0, edge_bottom)
                painter.setPen(QPen(QBrush(edge), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), 15, 15)
        if self._text_scrim.alpha() > 0 and self._media_background is None:
            painter.setClipPath(path)
            scrim = QLinearGradient(0, 0, max(1, self.width() * 0.82), 0)
            solid_scrim = QColor(self._text_scrim)
            scrim.setColorAt(0.0, solid_scrim)
            middle_scrim = QColor(solid_scrim)
            middle_scrim.setAlpha(round(solid_scrim.alpha() * 0.82))
            scrim.setColorAt(0.62, middle_scrim)
            clear_scrim = QColor(solid_scrim)
            clear_scrim.setAlpha(0)
            scrim.setColorAt(1.0, clear_scrim)
            painter.fillPath(path, QBrush(scrim))
        painter.end()
