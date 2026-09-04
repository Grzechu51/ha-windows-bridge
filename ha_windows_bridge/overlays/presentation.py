"""One notification window: render state, emit intent, own visual resources only."""
from __future__ import annotations

import base64

import qtawesome as qta
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QToolButton

from ..ui.motion import MotionSystem
from ..windows_effects import NativeBackdrop

ACCENTS = {"default": "#b5c6cd", "success": "#62d6a1", "warning": "#efc261", "error": "#fa8798"}


class NotificationWindow(QFrame):
    dismissed = Signal(str)
    hovered = Signal(str, bool)
    action = Signal(str)

    def __init__(self, options):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._backdrop = NativeBackdrop()
        self._animation = None
        self._target = QPoint()
        self._options = {}
        self._width_limit = 1200
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(16, 14, 16, 12)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(6)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.artwork = QLabel()
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setAccessibleName("Zamknij nakładkę")
        self.close_button.clicked.connect(lambda: self.dismissed.emit(self._options["id"]))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.lifetime = QProgressBar()
        self.lifetime.setRange(0, 1000)
        self.lifetime.setTextVisible(False)
        self._media_buttons = []
        for label, action in (("⏮", "previous"), ("⏯", "play"), ("⏭", "next")):
            button = QToolButton()
            button.setText(label)
            button.setAccessibleName(action)
            button.clicked.connect(lambda _checked=False, kind=action: self.action.emit("pause" if kind == "play" and self._options.get("media_playing") else kind))
            self._media_buttons.append(button)
        self.update_notification(options)

    def update_notification(self, options):
        self._options = options.copy()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().hide()
        for column in range(5):
            self._grid.setColumnStretch(column, 0)
        accent = ACCENTS.get(options["preset"], ACCENTS["default"])
        badge = options["layout"] == "badge"
        opacity = max(0.2, options["opacity"])
        self.setStyleSheet(f"NotificationWindow {{ background: rgba(24,28,31,{int(opacity * 255)}); border: none; border-radius: 14px; }}"
                           "QLabel { color: #f4f4f4; background: transparent; }"
                           f"QProgressBar {{ height: 3px; border: none; background: #455057; }} QProgressBar::chunk {{ background: {accent}; }}"
                           "QToolButton { color: white; background: transparent; border: none; padding: 5px; }")
        self._grid.setContentsMargins(10 if badge else 16, 8 if badge else 14, 10 if badge else 16, 8 if badge else 12)
        self.title.setText(options["title"])
        self.message.setText(options["message"])
        self.message.setFont(QFont("Segoe UI", 10))
        icon_name = options["icon"].replace("mdi:", "mdi6.")
        try:
            icon = qta.icon(icon_name, color=accent) if icon_name else None
        except Exception:
            icon = None
        if icon and not icon.isNull():
            self.icon.setPixmap(icon.pixmap(24, 24))
            self._grid.addWidget(self.icon, 0, 0, 2 if not badge else 1, 1, Qt.AlignmentFlag.AlignVCenter)
            self.icon.show()
        column = 1 if icon else 0
        self._grid.setColumnStretch(column, 1)
        if badge:
            self.message.setText(options["message"] or options["title"])
            self.message.setWordWrap(False)
            self._grid.addWidget(self.message, 0, column, Qt.AlignmentFlag.AlignVCenter)
            self.message.show()
            self.setFixedWidth(max(52, min(200, self.message.fontMetrics().horizontalAdvance(self.message.text()) + (54 if icon else 24))))
        else:
            self.message.setWordWrap(True)
            self.setFixedWidth(min(self._width_limit, options["width"] if options["size_mode"] == "manual" else 380))
            self._grid.addWidget(self.title, 0, column, 1, 3)
            self._grid.addWidget(self.message, 1, column, 1, 3)
            self.title.setVisible(bool(options["title"]))
            self.message.setVisible(bool(options["message"]))
        row = 2
        image = options.get("image", "")
        if not badge and image.startswith("data:image/") and len(image) <= 768 * 1024:
            try:
                data = QByteArray(base64.b64decode(image.split(",", 1)[1], validate=True))
                buffer = QBuffer(data)
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader = QImageReader(buffer)
                size = reader.size()
                supported = bytes(reader.format()).lower() in {b"png", b"jpeg", b"jpg", b"webp", b"gif"}
                if supported and size.isValid() and size.width() * size.height() <= 16_000_000:
                    bounds = QSize(round((self.width() - 32) * self.devicePixelRatioF()), round(180 * self.devicePixelRatioF()))
                    reader.setScaledSize(size.scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio))
                    pixmap = QPixmap.fromImage(reader.read())
                    pixmap.setDevicePixelRatio(self.devicePixelRatioF())
                    self.artwork.setPixmap(pixmap)
                    self._grid.addWidget(self.artwork, row, 0, 1, 4)
                    self.artwork.show()
                    row += 1
            except (ValueError, IndexError):
                pass
        if not badge and options["qr"]:
            import qrcode
            code = qrcode.make(options["qr"]).convert("RGBA")
            qr_image = QImage(code.tobytes(), code.width, code.height, QImage.Format.Format_RGBA8888).copy()
            self.artwork.setPixmap(QPixmap.fromImage(qr_image).scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio))
            self._grid.addWidget(self.artwork, row, 0, 1, 4)
            self.artwork.show()
            row += 1
        if not badge and options["layout"] == "media" and options.get("media_controls"):
            for column, button in enumerate(self._media_buttons):
                self._grid.addWidget(button, row, column)
                button.show()
            row += 1
        if options["show_close_button"]:
            self._grid.addWidget(self.close_button, 0, 4)
            self.close_button.show()
        if options["progress"] is not None and not badge:
            self.progress.setValue(options["progress"])
            self._grid.addWidget(self.progress, row, 0, 1, 5)
            self.progress.show()
            row += 1
        if options["show_lifetime"] and not options["pinned"] and not badge:
            self._grid.addWidget(self.lifetime, row, 0, 1, 5)
            self.lifetime.show()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._grid.activate()
        self.adjustSize()
        if options["size_mode"] == "manual" and not badge:
            self.setMinimumHeight(max(self.height(), options["height"]))
        self._backdrop.prepare_window(int(self.winId()))
        # Until capture is benchmarked, liquid requests use the inexpensive native fallback.
        if options["background_effect"] in {"blur", "liquid"} and not badge:
            self._backdrop.apply_acrylic(int(self.winId()), options["opacity"])
        else:
            self._backdrop.disable()

    def constrain_width(self, maximum):
        if self._width_limit != maximum:
            self._width_limit = maximum
            self.update_notification(self._options)

    def place(self, point, *, appearing=False):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
        start = point + QPoint(round(MotionSystem.TOKENS["popup_enter"].distance), 0) if appearing else self.pos()
        self._target = point
        if not MotionSystem.enabled():
            self.move(point)
            self.setWindowOpacity(1)
            self.show()
            return
        self.move(start)
        self.setWindowOpacity(0 if appearing else 1)
        self.show()
        def frame(value):
            self.move(start + (point - start) * value)
            if appearing:
                self.setWindowOpacity(value)
        def complete():
            self._animation = None
            self.move(self._target)
            self.setWindowOpacity(1)
        self._animation = MotionSystem.animate(self, "popup_enter" if appearing else "reposition", frame, complete)
        self._animation.start()

    def retire(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
        self._animation = None
        if not MotionSystem.enabled():
            self.dispose()
            return
        opacity = self.windowOpacity()
        self._animation = MotionSystem.animate(self, "popup_exit",
                                               lambda value: self.setWindowOpacity(opacity * (1 - value)), self.dispose)
        self._animation.start()

    def dispose(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
        self._backdrop.disable()
        self.close()
        self.deleteLater()

    def enterEvent(self, event):
        self.hovered.emit(self._options["id"], True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(self._options["id"], False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._options["close_on_click"]:
            self.dismissed.emit(self._options["id"])
        super().mouseReleaseEvent(event)
