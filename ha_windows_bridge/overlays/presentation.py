"""One notification window: render state, emit intent, own visual resources only."""
from __future__ import annotations

import base64

import qtawesome as qta
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QToolButton,
    QWidget,
)

from ..ui.motion import MotionSystem
from ..windows_effects import NativeBackdrop
from .media_style import artwork_rect, media_palette, transition_bounds

ACCENTS = {"default": "#b5c6cd", "success": "#62d6a1", "warning": "#efc261", "error": "#fa8798"}
MEDIA_CARD_WIDTH = 520
MEDIA_CARD_HEIGHT = 214


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
        self._media_image = QPixmap()
        self._media_palette = media_palette(None)
        self._effect_key = None
        self._glass_image = QPixmap()
        self._intro_snapshot = QPixmap()
        self._intro_visible = []
        self._awaiting_glass = False
        self.capture_excluded = False
        self._width_limit = 1200
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(16, 14, 16, 12)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(6)
        self.icon = QLabel(self)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(self)
        self.title.setWordWrap(True)
        self.title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.artwork = QLabel(self)
        self.artwork.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source = QLabel(self)
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        self.media_time = QLabel(self)
        self.media_time.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.close_button = QToolButton(self)
        self.close_button.setText("×")
        self.close_button.setAccessibleName("Zamknij nakładkę")
        self.close_button.clicked.connect(lambda: self.dismissed.emit(self._options["id"]))
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.lifetime = QProgressBar(self)
        self.lifetime.setRange(0, 1000)
        self.lifetime.setValue(1000)
        self.lifetime.setTextVisible(False)
        self.lifetime.setFixedHeight(4)
        self._media_buttons = []
        self.media_controls = QWidget(self)
        controls_layout = QHBoxLayout(self.media_controls)
        controls_layout.setContentsMargins(0, 4, 0, 4)
        controls_layout.setSpacing(10)
        for label, action in (("skip-previous", "previous"), ("play-pause", "play"), ("skip-next", "next")):
            button = QToolButton()
            button.setIcon(qta.icon("mdi6." + label, color="#f4f4f4"))
            button.setIconSize(QSize(32, 32) if action == "play" else QSize(28, 28))
            button.setFixedSize(48, 48)
            button.setAccessibleName({"previous": "Poprzedni utwór", "play": "Odtwórz", "next": "Następny utwór"}[action])
            button.clicked.connect(lambda _checked=False, kind=action: self.action.emit("pause" if kind == "play" and self._options.get("media_playing") else kind))
            self._media_buttons.append(button)
            controls_layout.addWidget(button)
        controls_layout.addStretch()
        for widget in (self.icon, self.title, self.message, self.artwork, self.source, self.media_time,
                       self.close_button, self.progress, self.lifetime, self.media_controls):
            widget.hide()
        self.update_notification(options)

    def update_notification(self, options):
        transport = {"media_position", "media_duration", "media_playing", "progress"}
        expected_width = min(self._width_limit, options["width"] if options["size_mode"] == "manual" else MEDIA_CARD_WIDTH)
        if self._options and options["layout"] == "media" and self.width() == expected_width and {k: v for k, v in self._options.items() if k not in transport} == {k: v for k, v in options.items() if k not in transport}:
            self._options = options.copy()
            self.set_media_position(options["media_position"], options["media_duration"])
            self._update_media_buttons()
            return
        self._options = options.copy()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().hide()
        for column in range(5):
            self._grid.setColumnStretch(column, 0)
        for row in range(self._grid.rowCount()):
            self._grid.setRowMinimumHeight(row, 0)
            self._grid.setRowStretch(row, 0)
        accent = ACCENTS.get(options["preset"], ACCENTS["default"])
        badge = options["layout"] == "badge"
        media = options["layout"] == "media"
        self.title.setWordWrap(not media)
        self.message.setWordWrap(not media)
        self.setStyleSheet("NotificationWindow { background: transparent; border: none; }"
                           "QLabel { color: #f4f4f4; background: transparent; }"
                           f"QProgressBar {{ border: none; background: rgba(160,180,188,65); }} QProgressBar::chunk {{ background: {accent}; }}"
                           "QToolButton { color: white; background: transparent; border: none; padding: 5px; }")
        self.title.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.title.setMaximumWidth(16777215)
        self.message.setMaximumWidth(16777215)
        self.source.setMaximumWidth(16777215)
        self.media_time.setMaximumWidth(16777215)
        self.progress.setMaximumWidth(16777215)
        self.message.setStyleSheet("color: #c3cccf; font-size: 10pt;")
        self.source.setStyleSheet("font-size: 9pt; color: #d8e0e2;")
        self.media_time.setStyleSheet("font-size: 8pt; color: #c3cccf;")
        margin = 20 if media else 16
        self._grid.setContentsMargins(10 if badge else margin, 8 if badge else 16 if media else 14, 10 if badge else margin, 8 if badge else 16 if media else 12)
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
            if not media:
                self._grid.addWidget(self.icon, 0, 0, 2 if not badge else 1, 1, Qt.AlignmentFlag.AlignVCenter)
                self.icon.show()
        column = 1 if icon and not media else 0
        self._grid.setColumnStretch(column, 1)
        if badge:
            self.message.setText(options["message"] or options["title"])
            self.message.setWordWrap(False)
            self._grid.addWidget(self.message, 0, column, Qt.AlignmentFlag.AlignVCenter)
            self.message.show()
            self.setFixedWidth(max(52, min(200, self.message.fontMetrics().horizontalAdvance(self.message.text()) + (54 if icon else 24))))
        else:
            self.message.setWordWrap(not media)
            self.setFixedWidth(min(self._width_limit, options["width"] if options["size_mode"] == "manual" else MEDIA_CARD_WIDTH if media else 380))
            if media:
                self.source.setText(options.get("media_source") or "Media Player")
                self._grid.addWidget(self.source, 0, column, 1, 4 - column)
                self.source.show()
                self._grid.addWidget(self.title, 1, 0, 1, 4)
                self._grid.addWidget(self.message, 2, 0, 1, 4)
            else:
                self._grid.addWidget(self.title, 0, column, 1, 3)
                self._grid.addWidget(self.message, 1, column, 1, 3)
            self.title.setVisible(bool(options["title"]))
            self.message.setVisible(bool(options["message"]))
        row = 3 if media else 2
        self._media_image = QPixmap()
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
                    bounds = QSize(round((self.width() - 32) * self.devicePixelRatioF()), round((MEDIA_CARD_HEIGHT if media else 180) * self.devicePixelRatioF()))
                    reader.setScaledSize(size.scaled(bounds, Qt.AspectRatioMode.KeepAspectRatio))
                    pixmap = QPixmap.fromImage(reader.read())
                    pixmap.setDevicePixelRatio(self.devicePixelRatioF())
                    if media:
                        self._media_image = pixmap
                    else:
                        self.artwork.setPixmap(pixmap)
                        self._grid.addWidget(self.artwork, row, 0, 1, 4)
                        self.artwork.show()
                        row += 1
            except (ValueError, IndexError):
                pass
        if media:
            self._media_palette = media_palette(self._media_image)
            surface, primary, secondary = self._media_palette
            self.title.setStyleSheet(f"color: {primary.name()}; font-size: 18px; font-weight: 700;")
            self.source.setStyleSheet(f"color: {primary.name()}; font-size: 12px; font-weight: 600;")
            self.message.setStyleSheet(f"color: {secondary.name()}; font-size: 14px;")
            self.media_time.setStyleSheet(f"color: {secondary.name()}; font-size: 12px;")
            self.media_time.setAlignment(Qt.AlignmentFlag.AlignLeft)
            # Keep the transport timeline inside the text/control sector. A
            # full-width bar crosses the artwork and looks like a window edge.
            self.media_time.setMaximumWidth(280)
            self.progress.setMaximumWidth(280)
            track = "rgba(0,0,0,58)" if surface.lightness() >= 145 else "rgba(255,255,255,54)"
            for bar in (self.progress, self.lifetime):
                bar.setStyleSheet(f"QProgressBar {{ border: none; border-radius: 2px; background: {track}; }} QProgressBar::chunk {{ border-radius: 2px; background: {primary.name()}; }}")
            self.close_button.setStyleSheet(f"color: {primary.name()};")
            if icon:
                self.icon.setPixmap(qta.icon(icon_name, color=primary.name()).pixmap(24, 24))
            self._update_media_buttons()
            for button in self._media_buttons:
                button.setStyleSheet(f"QToolButton {{ background: transparent; border: none; border-radius: 24px; padding: 0; }} QToolButton:hover {{ background: rgba({primary.red()},{primary.green()},{primary.blue()},28); }} QToolButton:pressed {{ background: rgba({primary.red()},{primary.green()},{primary.blue()},48); }}")
            text_width = max(120, min(280, round(self.width() * .54)))
            for label, text in ((self.source, options.get("media_source") or "Media Player"),
                                (self.title, options["title"]), (self.message, options["message"])):
                label.setMaximumWidth(text_width)
                elided = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_width)
                label.setText(elided)
                label.setToolTip(text if elided != text else "")
            self.media_time.setMaximumWidth(text_width)
            self.progress.setMaximumWidth(text_width)
        else:
            tone = QColor(accent)
            self.progress.setStyleSheet(f"QProgressBar {{ border: none; border-radius: 2px; background: rgba(127,127,127,38); }} QProgressBar::chunk {{ border-radius: 2px; background: {tone.name()}; }}")
            self.lifetime.setStyleSheet(f"QProgressBar {{ border: none; border-radius: 2px; background: rgba(127,127,127,24); }} QProgressBar::chunk {{ border-radius: 2px; background: rgba({tone.red()},{tone.green()},{tone.blue()},185); }}")
            self.close_button.setStyleSheet("")
        if not badge and options["qr"]:
            import qrcode
            code = qrcode.make(options["qr"]).convert("RGBA")
            qr_image = QImage(code.tobytes(), code.width, code.height, QImage.Format.Format_RGBA8888).copy()
            self.artwork.setPixmap(QPixmap.fromImage(qr_image).scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio))
            self._grid.addWidget(self.artwork, row, 0, 1, 4)
            self.artwork.show()
            row += 1
        if not badge and options["layout"] == "media" and options.get("media_controls"):
            self._grid.addWidget(self.media_controls, row, 0, 1, 4, Qt.AlignmentFlag.AlignLeft)
            self.media_controls.show()
            row += 1
        if options["show_close_button"]:
            self._grid.addWidget(self.close_button, 0, 4)
            self.close_button.show()
        if media:
            self._grid.setRowMinimumHeight(row, 4)
            self._grid.setRowStretch(row, 1)
            row += 1
            self.set_media_position(options["media_position"], options["media_duration"])
            self._grid.addWidget(self.media_time, row, 0, 1, 5)
            self.media_time.setVisible(bool(options["media_duration"]))
            row += 1
        if (media or options["progress"] is not None) and not badge:
            self.progress.setValue(options["progress"] or 0)
            self._grid.addWidget(self.progress, row, 0, 1, 5)
            self.progress.setVisible(bool(options["media_duration"]) if media else True)
            row += 1
        if options["show_lifetime"] and not options["pinned"] and not badge:
            self._grid.addWidget(self.lifetime, row, 0, 1, 5)
            self.lifetime.show()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self._grid.activate()
        if media:
            height = options["height"] if options["size_mode"] == "manual" else MEDIA_CARD_HEIGHT
            self.setFixedHeight(max(180, min(720, height)))
        else:
            self.adjustSize()
            if options["size_mode"] == "manual" and not badge:
                self.setMinimumHeight(max(self.height(), options["height"]))
        effect_key = (options["background_effect"], options["opacity"], badge)
        if effect_key != self._effect_key:
            self._backdrop.disable()
            self._effect_key = effect_key
            self._glass_image = QPixmap()
            self._backdrop.prepare_window(int(self.winId()))
            capture_background = options["background_effect"] in {"blur", "liquid"} and not badge
            self.capture_excluded = NativeBackdrop.exclude_capture(int(self.winId()), capture_background)
        self.update()

    def _surface_region(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 14, 14)
        return QRegion(path.toFillPolygon().toPolygon())

    def _apply_surface_mask(self):
        if not self.rect().isEmpty():
            self.setMask(self._surface_region())
            NativeBackdrop.apply_rounded_region(int(self.winId()), 14)

    def _reinforce_surface_mask(self, region=None):
        """Re-apply the native window region after the HWND becomes visible."""
        if self.rect().isEmpty():
            return
        self.clearMask()
        self.setMask(region if region is not None else self._surface_region())
        if region is None:
            NativeBackdrop.apply_rounded_region(int(self.winId()), 14)

    def _visual_widgets(self):
        return (self.icon, self.title, self.message, self.artwork, self.source,
                self.media_time, self.close_button, self.progress, self.lifetime,
                self.media_controls)

    def _prepare_intro_frame(self):
        """Animate one complete frame; never expose parent before its children."""
        self.ensurePolished()
        self._grid.activate()
        self._intro_snapshot = self.grab()
        self._intro_visible = [widget for widget in self._visual_widgets() if not widget.isHidden()]
        for widget in self._intro_visible:
            widget.hide()
        self.update()

    def _finish_intro_frame(self):
        for widget in self._intro_visible:
            widget.show()
        self._intro_visible.clear()
        self._intro_snapshot = QPixmap()
        self.update()

    def stage(self, point, screen=None):
        """Position a hidden card so its captured background can be prepared."""
        self._target = point
        self._awaiting_glass = True
        self.move(point)
        handle = self.windowHandle()
        if screen is not None and handle is not None:
            handle.setScreen(screen)
        self._apply_surface_mask()

    def _update_media_buttons(self):
        playing = self._options["media_playing"]
        for button, name in zip(self._media_buttons, ("skip-previous", "pause" if playing else "play", "skip-next"), strict=True):
            button.setIcon(qta.icon("mdi6." + name, color=self._media_palette[1].name()))
        self._media_buttons[1].setAccessibleName("Wstrzymaj" if playing else "Odtwórz")

    def set_glass_image(self, image):
        self._glass_image = QPixmap.fromImage(image)
        self.update()

    def set_media_position(self, position, duration):
        self.media_time.setVisible(bool(duration))
        if self._options.get("layout") == "media":
            self.progress.setVisible(bool(duration))
        if duration:
            self.progress.setValue(round(position / duration * 100))
            def timestamp(value):
                seconds = max(0, round(value))
                return f"{seconds // 60}:{seconds % 60:02d}"
            self.media_time.setText(f"{timestamp(position)} / {timestamp(duration)}")
        else:
            self.media_time.clear()
            self.progress.setValue(0)

    def paintEvent(self, _event):
        # A translucent top-level window needs an explicit painted surface; a
        # stylesheet on a Python QFrame subclass is not a reliable backing layer.
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(bounds, 14, 14)
        painter.setClipPath(path)
        media = self._options.get("layout") == "media"
        color = QColor(self._media_palette[0]) if media else QColor(24, 28, 31)
        glass = self._options.get("background_effect") in {"blur", "liquid"}
        if not self._glass_image.isNull():
            liquid = self._options["background_effect"] == "liquid"
            target = bounds.adjusted(-16, -10, 16, 10) if liquid else bounds
            painter.drawPixmap(target, self._glass_image, QRectF(self._glass_image.rect()))
            if liquid:
                # Two displaced bands create a restrained refraction that is
                # clearly different from the flat, frosted blur preset.
                painter.save()
                painter.setOpacity(.28)
                painter.setClipRect(QRectF(0, self.height() * .18, self.width(), self.height() * .23), Qt.ClipOperation.IntersectClip)
                painter.drawPixmap(bounds.translated(8, 0), self._glass_image, QRectF(self._glass_image.rect()))
                painter.restore()
                painter.save()
                painter.setOpacity(.20)
                painter.setClipRect(QRectF(0, self.height() * .62, self.width(), self.height() * .20), Qt.ClipOperation.IntersectClip)
                painter.drawPixmap(bounds.translated(-6, 0), self._glass_image, QRectF(self._glass_image.rect()))
                painter.restore()
        visible_blur = not self._glass_image.isNull() or self._backdrop.backend != "none"
        tint = (.12 if self._options.get("background_effect") == "liquid" else .40) if glass and visible_blur else 1.0
        color.setAlphaF(max(0.0, min(1.0, self._options.get("opacity", 0.94) * tint)))
        painter.fillPath(path, color)
        if glass:
            sheen = QLinearGradient(0, 0, 0, self.height())
            liquid = self._options["background_effect"] == "liquid"
            sheen.setColorAt(0, QColor(255, 255, 255, 62 if liquid else 12))
            sheen.setColorAt(.36, QColor(210, 242, 255, 14 if liquid else 0))
            sheen.setColorAt(1, QColor(0, 0, 0, 32 if liquid else 20))
            painter.fillPath(path, sheen)
            if self._options.get("preset") != "default":
                tone = QColor(ACCENTS.get(self._options["preset"], ACCENTS["default"]))
                tone.setAlpha(32)
                painter.fillPath(path, tone)
        if not self._media_image.isNull():
            image = self._media_image
            cover = artwork_rect(self.size(), image.size())
            painter.setOpacity(self._options.get("opacity", .94))
            painter.drawPixmap(cover, image, QRectF(image.rect()))
            start, end = transition_bounds(self.width(), cover)
            shade = QLinearGradient(start, 0, end, 0)
            effect = self._options.get("background_effect")
            stops = ((0, 205), (.18, 195), (.45, 145), (.72, 68), (1, 0)) if effect == "liquid" else ((0, 232), (.18, 222), (.45, 178), (.72, 88), (1, 0)) if effect == "blur" else ((0, 255), (.18, 250), (.45, 205), (.72, 105), (1, 0))
            for stop, alpha in stops:
                tone = QColor(self._media_palette[0])
                tone.setAlpha(alpha)
                shade.setColorAt(stop, tone)
            painter.fillPath(path, shade)
            painter.setOpacity(1)
        if self._options.get("layout") != "badge":
            accent = QColor(self._media_palette[1]) if media else QColor(ACCENTS.get(self._options.get("preset"), ACCENTS["default"]))
            accent.setAlpha(88 if media else 75)
            painter.setPen(QPen(accent, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        if not self._intro_snapshot.isNull():
            painter.drawPixmap(0, 0, self._intro_snapshot)
        painter.end()

    def constrain_width(self, maximum):
        if self._width_limit != maximum:
            self._width_limit = maximum
            self.update_notification(self._options)

    def place(self, point, *, appearing=False):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
            self._animation = None
        app = QGuiApplication.instance()
        style = app.property("bridgePopupAnimation") or "slide"
        duration = app.property("bridgePopupAnimationDuration") or 220
        direction = -1 if "left" in self._options["corner"] else 1
        start = point + QPoint(direction * 24, 0) if appearing and style == "slide" else point if appearing else self.pos()
        self._target = point
        self._awaiting_glass = False
        self._apply_surface_mask()
        if not MotionSystem.enabled() or style == "none":
            self.move(point)
            self.setWindowOpacity(0)
            self.show()
            self._apply_surface_mask()
            def reveal_static():
                if self.isVisible():
                    self._reinforce_surface_mask()
                    self.setWindowOpacity(1)
            QTimer.singleShot(0, reveal_static)
            return
        if appearing:
            self._prepare_intro_frame()
        self.move(start)
        fade = appearing and style == "fade"
        self.setWindowOpacity(0)
        if appearing and style == "reveal":
            reveal = QRegion(QRect(self.width() - 1 if direction > 0 else 0, self.height() // 2, 1, 1))
            self.setMask(self._surface_region().intersected(reveal))
        self.show()
        if appearing and style == "reveal":
            self.setMask(self._surface_region().intersected(reveal))
        else:
            self._apply_surface_mask()
        def frame(value):
            self.move(start + (point - start) * value)
            if fade:
                self.setWindowOpacity(value)
            if appearing and style == "reveal":
                width, height = max(1, round(self.width() * value)), max(1, round(self.height() * (.4 + .6 * value)))
                reveal = QRegion(QRect(self.width() - width if direction > 0 else 0, (self.height() - height) // 2, width, height))
                self.setMask(self._surface_region().intersected(reveal))
        def complete():
            self._animation = None
            self.move(self._target)
            self.setWindowOpacity(1)
            self._apply_surface_mask()
            self._finish_intro_frame()
        self._animation = MotionSystem.animate(self, "popup_enter" if appearing else "reposition", frame, complete, duration=duration if appearing else None)
        animation = self._animation
        def start_animation():
            if self._animation is animation:
                if appearing and style == "reveal":
                    self._reinforce_surface_mask(self._surface_region().intersected(reveal))
                else:
                    self._reinforce_surface_mask()
                if not fade:
                    self.setWindowOpacity(1)
                animation.start()
        QTimer.singleShot(0, start_animation)

    def retire(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
        self._animation = None
        self._awaiting_glass = False
        app = QGuiApplication.instance()
        style = app.property("bridgePopupAnimation") or "slide"
        duration = app.property("bridgePopupAnimationDuration") or 220
        if not MotionSystem.enabled() or style == "none":
            self.dispose()
            return
        opacity = self.windowOpacity()
        start = self.pos()
        direction = -1 if "left" in self._options["corner"] else 1
        def frame(value):
            if style == "fade":
                self.setWindowOpacity(opacity * (1 - value))
            elif style == "slide":
                self.move(start + QPoint(round(direction * 24 * value), 0))
            elif style == "reveal":
                width, height = max(1, round(self.width() * (1 - value))), max(1, round(self.height() * (1 - value)))
                reveal = QRegion(QRect(self.width() - width if direction > 0 else 0, (self.height() - height) // 2, width, height))
                self.setMask(self._surface_region().intersected(reveal))
        self._animation = MotionSystem.animate(self, "popup_exit", frame, self.dispose, duration=duration)
        self._animation.start()

    def dispose(self):
        if self._animation:
            self._animation.stop()
            self._animation.deleteLater()
        self._animation = None
        self._intro_visible.clear()
        self._intro_snapshot = QPixmap()
        self._backdrop.disable()
        NativeBackdrop.exclude_capture(int(self.winId()), False)
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
