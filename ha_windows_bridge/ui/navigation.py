"""Page transition without relayout or nested opacity effects on live controls."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget

from .motion import MotionSystem


class PageStack(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._transition = None
        self._snapshot = None

    def _clear_transition(self) -> None:
        if self._transition is not None:
            self._transition.stop()
            self._transition.deleteLater()
            self._transition = None
        if self._snapshot is not None:
            self._snapshot.hide()
            self._snapshot.deleteLater()
            self._snapshot = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        old = self.currentWidget()
        if index == self.currentIndex() or not 0 <= index < self.count():
            return
        self._clear_transition()
        snapshot = old.grab() if old is not None and self.isVisible() and MotionSystem.enabled() else None
        super().setCurrentIndex(index)
        if snapshot is None:
            return
        self._snapshot = QLabel(self)
        self._snapshot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._snapshot.setGeometry(self.rect())
        self._snapshot.setPixmap(snapshot)
        effect = QGraphicsOpacityEffect(self._snapshot)
        self._snapshot.setGraphicsEffect(effect)
        self._snapshot.show()
        self._snapshot.raise_()
        self._transition = MotionSystem.animate(self, "page", lambda value: effect.setOpacity(1 - value), self._clear_transition)
        self._transition.start()
