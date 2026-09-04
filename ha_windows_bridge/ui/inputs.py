from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QComboBox


class WheelSafeComboBox(QComboBox):
    """Let a surrounding settings page consume the mouse wheel."""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


class SettingsWheelGuard(QObject):
    """Prevent wheel changes in settings fields while preserving page scrolling."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel or not isinstance(
            watched, (QAbstractSpinBox, QComboBox)
        ):
            return False
        parent = watched.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QAbstractScrollArea):
            delta = event.angleDelta().y()
            bar = parent.verticalScrollBar()
            if delta:
                steps = max(1, abs(delta) // 120)
                direction = -1 if delta > 0 else 1
                bar.setValue(bar.value() + direction * steps * max(24, bar.singleStep()))
        event.accept()
        return True
