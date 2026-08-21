from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QFileInfo,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    qAlpha,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .config import AudioAppConfig, slugify
from .i18n import translate


class HelpButton(QToolButton):
    """Small help button that shows its explanation on hover and click."""

    def __init__(self, explanation: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("helpButton")
        self.setText("?")
        self.setToolTip(explanation)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(28, 28)
        self.clicked.connect(self.show_help)

    def show_help(self) -> None:
        QToolTip.showText(
            self.mapToGlobal(QPoint(self.width() + 6, self.height() // 2)),
            self.toolTip(),
            self,
        )

    def enterEvent(self, event) -> None:
        self.show_help()
        super().enterEvent(event)


class ToggleSwitch(QAbstractButton):
    """Compact animated switch used by the new interface."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 25)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"knobPosition", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(46, 25)

    def get_knob_position(self) -> float:
        return self._position

    def set_knob_position(self, position: float) -> None:
        self._position = max(0.0, min(1.0, float(position)))
        self.update()

    knobPosition = Property(float, get_knob_position, set_knob_position)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 2, -1, -2)
        if not self.isEnabled():
            track_color = QColor("#20282c")
            knob_color = QColor("#59656a")
        elif self.isChecked():
            track_color = QColor("#287d57")
            knob_color = QColor("#eefaf4")
        else:
            track_color = QColor("#253238")
            knob_color = QColor("#9aa7ac")
        painter.setPen(QPen(QColor("#4b5c62"), 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        diameter = track.height() - 4
        start_x = track.left() + 2
        end_x = track.right() - diameter - 1
        x = start_x + (end_x - start_x) * self._position
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawEllipse(int(x), int(track.top() + 2), int(diameter), int(diameter))
        painter.end()


class TitleBar(QFrame):
    menu_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(0)

        self.menu_button = QToolButton()
        self.menu_button.setObjectName("hamburgerButton")
        self.menu_button.setText("☰")
        self.menu_button.setFixedSize(48, 48)
        self.menu_button.clicked.connect(self.menu_clicked)
        layout.addWidget(self.menu_button)

        divider = QFrame()
        divider.setObjectName("titleDivider")
        divider.setFixedSize(1, 34)
        layout.addSpacing(7)
        layout.addWidget(divider)
        layout.addSpacing(16)

        title_block = QWidget()
        title_block.setFixedHeight(39)
        title_layout = QVBoxLayout(title_block)
        title_layout.setSpacing(0)
        title_layout.setContentsMargins(0, 1, 0, 1)
        self.title = QLabel("HA Windows Bridge")
        self.title.setObjectName("windowTitle")
        self.subtitle = QLabel("Integracja Windows z Home Assistant przez MQTT")
        self.subtitle.setObjectName("windowSubtitle")
        subtitle_font = self.subtitle.font()
        subtitle_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.35)
        self.subtitle.setFont(subtitle_font)
        for label in (self.title, self.subtitle):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title_layout.addWidget(self.title)
        title_layout.addWidget(self.subtitle)
        layout.addWidget(title_block, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("topStatusDot")
        self.status_label = QLabel("Zatrzymano")
        self.status_label.setObjectName("topStatusLabel")
        layout.addWidget(self.status_dot)
        layout.addSpacing(7)
        layout.addWidget(self.status_label)
        layout.addSpacing(18)

        self.minimize_button = self._window_button("—", "Minimalizuj")
        self.maximize_button = self._window_button("□", "Maksymalizuj")
        self.close_button = self._window_button("×", "Zamknij", close=True)
        self.minimize_button.clicked.connect(lambda: self.window().showMinimized())
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(lambda: self.window().close())
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    @staticmethod
    def _window_button(text: str, tooltip: str, close: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("closeButton" if close else "windowButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFixedSize(40, 40)
        return button

    def toggle_maximize(self) -> None:
        window = self.window()
        if window.isMaximized():
            window.showNormal()
            self.maximize_button.setText("□")
        else:
            window.showMaximized()
            self.maximize_button.setText("❐")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class NavButton(QPushButton):
    def __init__(self, icon: str, text: str, parent: QWidget | None = None):
        super().__init__(f"{icon}    {text}", parent)
        self.nav_icon = icon
        self.nav_label = text
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(54)

    def set_language(self, language: str) -> None:
        self.nav_label = translate(self.nav_label, language)
        self.setText(f"{self.nav_icon}    {self.nav_label}")


class AppCard(QFrame):
    remove_requested = Signal(object)
    volume_requested = Signal(str, int)
    mute_requested = Signal(str, bool)

    _COLORS = ("#4285f4", "#5865f2", "#2ebd67", "#ef4b3f", "#8b5cf6", "#e59a3a")

    def __init__(self, config: AudioAppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("appCard")
        self.setMinimumHeight(88)
        self.config = config
        self._user_adjusting = False
        self._volume_available = False
        self._mute_available = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(13)

        self.avatar = QLabel(self._initials(config.display_name))
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(52, 52)
        self.avatar.setObjectName("appAvatar")
        self.avatar_effect = QGraphicsOpacityEffect(self.avatar)
        self.avatar.setGraphicsEffect(self.avatar_effect)
        color = self._COLORS[sum(config.slug.encode("utf-8")) % len(self._COLORS)]
        self._avatar_color = color
        self._show_initials()
        layout.addWidget(self.avatar)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.name_label = QLabel(config.display_name)
        self.name_label.setObjectName("appName")
        self.process_label = QLabel(config.process_name)
        self.process_label.setObjectName("appProcess")
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.process_label)
        layout.addLayout(text_layout, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(165)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.valueChanged.connect(self._slider_value_changed)
        layout.addWidget(self.slider)

        self.percent_label = QLabel("—")
        self.percent_label.setObjectName("volumePercent")
        self.percent_label.setFixedWidth(43)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.percent_label)

        self.mute_button = QToolButton()
        self.mute_button.setObjectName("muteButton")
        self.mute_button.setText("🔊")
        self.mute_button.setToolTip("Wycisz aplikację")
        self.mute_button.setCheckable(True)
        self.mute_button.setEnabled(False)
        self.mute_button.setFixedSize(36, 36)
        self.mute_button.toggled.connect(self._mute_toggled)
        layout.addWidget(self.mute_button)

        self.enabled_switch = ToggleSwitch()
        self.enabled_switch.setChecked(config.enabled)
        self.enabled_switch.setToolTip("Włącz encje Home Assistant dla tej aplikacji")
        self.enabled_switch.toggled.connect(self._apply_enabled_state)
        layout.addWidget(self.enabled_switch)

        self.more_button = QToolButton()
        self.more_button.setObjectName("moreButton")
        self.more_button.setText("⋮")
        self.more_button.setFixedSize(30, 36)
        self.more_button.setToolTip("Więcej opcji")
        self.options_menu = QMenu(self)
        self.options_menu.addAction("Zmień nazwę i topic", self.edit)
        self.options_menu.addSeparator()
        self.remote_start_action = self.options_menu.addAction("Uruchamianie z Home Assistant")
        self.remote_start_action.setCheckable(True)
        self.remote_start_action.setChecked(config.allow_remote_start)
        self.remote_start_action.setToolTip(
            "Jeśli ścieżka programu nie jest znana, aplikacja poprosi o wskazanie pliku EXE."
        )
        self.remote_start_action.toggled.connect(self._remote_start_toggled)
        self.remote_close_action = self.options_menu.addAction("Zamykanie z Home Assistant")
        self.remote_close_action.setCheckable(True)
        self.remote_close_action.setChecked(config.allow_remote_close)
        self.remote_close_action.toggled.connect(
            lambda checked: setattr(self.config, "allow_remote_close", checked)
        )
        self.options_menu.addSeparator()
        self.options_menu.addAction("Usuń", lambda: self.remove_requested.emit(self))
        self.more_button.clicked.connect(self._show_options_menu)
        layout.addWidget(self.more_button)
        self.set_executable_icon(config.executable_path)
        self._apply_enabled_state(config.enabled)

    @staticmethod
    def _initials(name: str) -> str:
        parts = [part for part in name.split() if part]
        if not parts:
            return "?"
        return "".join(part[0] for part in parts[:2]).upper()

    def _show_initials(self) -> None:
        self.avatar.setPixmap(QPixmap())
        self.avatar.setText(self._initials(self.config.display_name))
        self.avatar.setStyleSheet(
            f"background: {self._avatar_color}; color: white; "
            "border-radius: 26px; font-weight: 700; font-size: 11pt;"
        )

    def _show_options_menu(self) -> None:
        position = self.more_button.mapToGlobal(self.more_button.rect().bottomRight())
        position.setX(position.x() - self.options_menu.sizeHint().width())
        self.options_menu.exec(position)

    def set_executable_icon(self, executable_path: str) -> None:
        self.config.executable_path = executable_path.strip()
        file_info = QFileInfo(self.config.executable_path)
        if self.config.executable_path and file_info.exists():
            pixmap = QFileIconProvider().icon(file_info).pixmap(256, 256)
            if pixmap.isNull():
                pixmap = self._extract_windows_icon(self.config.executable_path)
            if not pixmap.isNull():
                pixmap = self._trim_transparent(pixmap)
                pixmap = pixmap.scaled(
                    46,
                    46,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.avatar.setText("")
                self.avatar.setPixmap(pixmap)
                self.avatar.setStyleSheet("background: transparent; border: none;")
                return
        self._show_initials()

    def _remote_start_toggled(self, checked: bool) -> None:
        if checked and not QFileInfo(self.config.executable_path).exists():
            file_name, _ = QFileDialog.getOpenFileName(
                self,
                "Wskaż plik EXE aplikacji",
                "",
                "Programy Windows (*.exe)",
            )
            if not file_name:
                self.remote_start_action.blockSignals(True)
                self.remote_start_action.setChecked(False)
                self.remote_start_action.blockSignals(False)
                self.config.allow_remote_start = False
                return
            self.set_executable_icon(file_name)
        self.config.allow_remote_start = checked

    @staticmethod
    def _extract_windows_icon(executable_path: str) -> QPixmap:
        try:
            import win32gui

            large_icons, small_icons = win32gui.ExtractIconEx(executable_path, 0)
            handles = large_icons or small_icons
            if not handles:
                return QPixmap()
            image = QImage.fromHICON(handles[0])
            for handle in (*large_icons, *small_icons):
                win32gui.DestroyIcon(handle)
            return QPixmap.fromImage(image)
        except Exception:
            return QPixmap()

    @staticmethod
    def _trim_transparent(pixmap: QPixmap) -> QPixmap:
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        left, top = image.width(), image.height()
        right = bottom = -1
        for y in range(image.height()):
            for x in range(image.width()):
                if qAlpha(image.pixel(x, y)) <= 8:
                    continue
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
        if right < left or bottom < top:
            return pixmap
        padding = max(1, round(max(right - left, bottom - top) * 0.04))
        crop = QRect(
            max(0, left - padding),
            max(0, top - padding),
            min(image.width() - left + padding, right - left + 1 + padding * 2),
            min(image.height() - top + padding, bottom - top + 1 + padding * 2),
        )
        return QPixmap.fromImage(image.copy(crop))

    def edit(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Nazwa aplikacji",
            "Przyjazna nazwa:",
            text=self.config.display_name,
        )
        if not accepted or not name.strip():
            return
        topic_id, accepted = QInputDialog.getText(
            self,
            "Identyfikator topicu",
            "Identyfikator MQTT:",
            text=self.config.slug,
        )
        if not accepted:
            return
        self.config.display_name = name.strip()
        self.config.slug = slugify(topic_id or name)
        self.name_label.setText(self.config.display_name)
        self.set_executable_icon(self.config.executable_path)

    def to_config(self) -> AudioAppConfig:
        return AudioAppConfig(
            process_name=self.config.process_name,
            display_name=self.config.display_name,
            slug=self.config.slug,
            enabled=self.enabled_switch.isChecked(),
            executable_path=self.config.executable_path,
            allow_remote_start=self.remote_start_action.isChecked(),
            allow_remote_close=self.remote_close_action.isChecked(),
        )

    def set_volume(self, volume: float | None) -> None:
        self._volume_available = volume is not None
        if volume is None:
            if not self._user_adjusting:
                self.percent_label.setText("—")
            self._apply_enabled_state(self.enabled_switch.isChecked())
            return
        value = max(0, min(100, round(volume * 100)))
        if not self._user_adjusting:
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
            self.percent_label.setText(f"{value}%")
        self._apply_enabled_state(self.enabled_switch.isChecked())

    def _slider_pressed(self) -> None:
        self._user_adjusting = True

    def _slider_released(self) -> None:
        self._user_adjusting = False
        self.volume_requested.emit(self.config.process_name, self.slider.value())

    def _slider_value_changed(self, value: int) -> None:
        self.percent_label.setText(f"{value}%")

    def set_muted(self, muted: bool | None) -> None:
        self._mute_available = muted is not None
        if muted is None:
            self._apply_enabled_state(self.enabled_switch.isChecked())
            return
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.setText("🔇" if muted else "🔊")
        self.mute_button.setToolTip("Włącz dźwięk aplikacji" if muted else "Wycisz aplikację")
        self.mute_button.blockSignals(False)
        self._apply_enabled_state(self.enabled_switch.isChecked())

    def _apply_enabled_state(self, enabled: bool) -> None:
        self.setProperty("featureEnabled", enabled)
        self.avatar_effect.setOpacity(1.0 if enabled else 0.28)
        for widget in (self.avatar, self.name_label, self.process_label, self.percent_label):
            widget.setEnabled(enabled)
        self.slider.setEnabled(enabled and self._volume_available)
        self.mute_button.setEnabled(enabled and self._mute_available)
        self.style().unpolish(self)
        self.style().polish(self)

    def _mute_toggled(self, muted: bool) -> None:
        self.mute_button.setText("🔇" if muted else "🔊")
        self.mute_requested.emit(self.config.process_name, muted)


class MasterVolumeCard(QFrame):
    volume_requested = Signal(int)
    mute_requested = Signal(bool)
    feature_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("masterVolumeCard")
        self.setMinimumHeight(82)
        self._user_adjusting = False
        self._feature_enabled = True
        self._volume_available = False
        self._mute_available = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(13)

        self.avatar = QLabel("🔊")
        self.avatar.setObjectName("masterAvatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(40, 40)
        self.avatar_effect = QGraphicsOpacityEffect(self.avatar)
        self.avatar.setGraphicsEffect(self.avatar_effect)
        layout.addWidget(self.avatar)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel("Master volume")
        name.setObjectName("appName")
        process = QLabel("Domyślne urządzenie wyjściowe Windows")
        process.setObjectName("appProcess")
        text.addWidget(name)
        text.addWidget(process)
        layout.addLayout(text, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(190)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.valueChanged.connect(self._slider_value_changed)
        layout.addWidget(self.slider)

        self.percent_label = QLabel("—")
        self.percent_label.setObjectName("volumePercent")
        self.percent_label.setFixedWidth(43)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.percent_label)

        self.mute_button = QToolButton()
        self.mute_button.setObjectName("muteButton")
        self.mute_button.setText("🔊")
        self.mute_button.setToolTip("Wycisz dźwięk Windows")
        self.mute_button.setCheckable(True)
        self.mute_button.setFixedSize(36, 36)
        self.mute_button.toggled.connect(self._mute_toggled)
        layout.addWidget(self.mute_button)

        self.enabled_switch = ToggleSwitch()
        self.enabled_switch.setToolTip("Włącz encje głośności systemu w Home Assistant")
        self.enabled_switch.setChecked(True)
        self.enabled_switch.toggled.connect(self.set_feature_enabled)
        self.enabled_switch.toggled.connect(self.feature_toggled)
        layout.addWidget(self.enabled_switch)

    def set_volume(self, volume: float | None) -> None:
        self._volume_available = volume is not None
        if volume is None:
            if not self._user_adjusting:
                self.percent_label.setText("—")
            self._apply_feature_state()
            return
        value = max(0, min(100, round(volume * 100)))
        if not self._user_adjusting:
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
            self.percent_label.setText(f"{value}%")
        self._apply_feature_state()

    def _slider_pressed(self) -> None:
        self._user_adjusting = True

    def _slider_released(self) -> None:
        self._user_adjusting = False
        self.volume_requested.emit(self.slider.value())

    def _slider_value_changed(self, value: int) -> None:
        self.percent_label.setText(f"{value}%")

    def set_muted(self, muted: bool | None) -> None:
        self._mute_available = muted is not None
        if muted is None:
            self._apply_feature_state()
            return
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.setText("🔇" if muted else "🔊")
        self.mute_button.blockSignals(False)
        self._apply_feature_state()

    def _mute_toggled(self, muted: bool) -> None:
        self.mute_button.setText("🔇" if muted else "🔊")
        self.mute_requested.emit(muted)

    def set_feature_enabled(self, enabled: bool) -> None:
        self._feature_enabled = enabled
        if self.enabled_switch.isChecked() != enabled:
            self.enabled_switch.setChecked(enabled)
        self._apply_feature_state()

    def _apply_feature_state(self) -> None:
        self.setProperty("featureEnabled", self._feature_enabled)
        self.avatar_effect.setOpacity(1.0 if self._feature_enabled else 0.28)
        self.slider.setEnabled(self._feature_enabled and self._volume_available)
        self.mute_button.setEnabled(self._feature_enabled and self._mute_available)
        for widget in self.findChildren(QLabel):
            widget.setEnabled(self._feature_enabled)
        self.style().unpolish(self)
        self.style().polish(self)


class MicrophoneCard(QFrame):
    volume_requested = Signal(int)
    mute_requested = Signal(bool)
    feature_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("microphoneCard")
        self.setMinimumHeight(82)
        self._user_adjusting = False
        self._feature_enabled = False
        self._available = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(13)
        self.avatar = QLabel("🎙")
        self.avatar.setObjectName("microphoneAvatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(40, 40)
        self.avatar_effect = QGraphicsOpacityEffect(self.avatar)
        self.avatar.setGraphicsEffect(self.avatar_effect)
        layout.addWidget(self.avatar)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel("Mikrofon")
        name.setObjectName("appName")
        self.activity = QLabel("Brak sygnału")
        self.activity.setObjectName("microphoneActivity")
        text.addWidget(name)
        text.addWidget(self.activity)
        layout.addLayout(text, 1)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(190)
        self.slider.setEnabled(False)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_adjusting", True))
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.valueChanged.connect(lambda value: self.percent_label.setText(f"{value}%"))
        layout.addWidget(self.slider)

        self.percent_label = QLabel("—")
        self.percent_label.setObjectName("volumePercent")
        self.percent_label.setFixedWidth(43)
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.percent_label)

        self.mute_button = QToolButton()
        self.mute_button.setObjectName("muteButton")
        self.mute_button.setText("🎙")
        self.mute_button.setCheckable(True)
        self.mute_button.setEnabled(False)
        self.mute_button.setFixedSize(36, 36)
        self.mute_button.toggled.connect(self._mute_toggled)
        layout.addWidget(self.mute_button)

        self.enabled_switch = ToggleSwitch()
        self.enabled_switch.setToolTip("Włącz encje mikrofonu w Home Assistant")
        self.enabled_switch.toggled.connect(self.set_feature_enabled)
        self.enabled_switch.toggled.connect(self.feature_toggled)
        layout.addWidget(self.enabled_switch)
        self._apply_feature_state()

    def set_state(self, volume: float | None, muted: bool | None, active: bool | None) -> None:
        available = volume is not None and muted is not None
        self._available = available
        if not available:
            self.percent_label.setText("—")
            self.activity.setText("Mikrofon niedostępny")
            self.activity.setProperty("active", False)
            self._apply_feature_state()
            return
        value = max(0, min(100, round(volume * 100)))
        if not self._user_adjusting:
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
            self.percent_label.setText(f"{value}%")
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(bool(muted))
        self.mute_button.setText("🚫" if muted else "🎙")
        self.mute_button.blockSignals(False)
        self.activity.setText("Aktywny" if active and not muted else "Brak sygnału")
        self.activity.setProperty("active", bool(active and not muted))
        self.activity.style().unpolish(self.activity)
        self.activity.style().polish(self.activity)
        self._apply_feature_state()

    def _slider_released(self) -> None:
        self._user_adjusting = False
        self.volume_requested.emit(self.slider.value())

    def _mute_toggled(self, muted: bool) -> None:
        self.mute_button.setText("🚫" if muted else "🎙")
        self.mute_requested.emit(muted)

    def set_feature_enabled(self, enabled: bool) -> None:
        self._feature_enabled = enabled
        if self.enabled_switch.isChecked() != enabled:
            self.enabled_switch.setChecked(enabled)
        self._apply_feature_state()

    def _apply_feature_state(self) -> None:
        self.setProperty("featureEnabled", self._feature_enabled)
        self.avatar_effect.setOpacity(1.0 if self._feature_enabled else 0.28)
        self.slider.setEnabled(self._feature_enabled and self._available)
        self.mute_button.setEnabled(self._feature_enabled and self._available)
        for widget in self.findChildren(QLabel):
            widget.setEnabled(self._feature_enabled)
        self.style().unpolish(self)
        self.style().polish(self)


class AudioOutputCard(QFrame):
    output_requested = Signal(str)
    refresh_requested = Signal()
    feature_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("audioOutputCard")
        self.setMinimumHeight(82)
        self._updating = False
        self._feature_enabled = False
        self._available = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(13)

        self.avatar = QLabel("🔈")
        self.avatar.setObjectName("audioOutputAvatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(40, 40)
        self.avatar_effect = QGraphicsOpacityEffect(self.avatar)
        self.avatar.setGraphicsEffect(self.avatar_effect)
        layout.addWidget(self.avatar)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel("Wyjście audio")
        name.setObjectName("appName")
        hint = QLabel("Domyślne urządzenie odtwarzania Windows")
        hint.setObjectName("appProcess")
        text.addWidget(name)
        text.addWidget(hint)
        layout.addLayout(text, 1)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(250)
        self.combo.setEnabled(False)
        self.combo.currentTextChanged.connect(self._selection_changed)
        layout.addWidget(self.combo)
        self.refresh_button = QToolButton()
        self.refresh_button.setObjectName("muteButton")
        self.refresh_button.setText("↻")
        self.refresh_button.setToolTip("Odśwież urządzenia audio")
        self.refresh_button.setFixedSize(36, 36)
        self.refresh_button.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_button)

        self.enabled_switch = ToggleSwitch()
        self.enabled_switch.setToolTip("Włącz wybór wyjścia audio w Home Assistant")
        self.enabled_switch.toggled.connect(self.set_feature_enabled)
        self.enabled_switch.toggled.connect(self.feature_toggled)
        layout.addWidget(self.enabled_switch)
        self._apply_feature_state()

    def set_devices(self, names: list[str], current: str) -> None:
        self._updating = True
        self.combo.clear()
        self.combo.addItems(names)
        if current in names:
            self.combo.setCurrentText(current)
        self._available = bool(names)
        self._updating = False
        self._apply_feature_state()

    def _selection_changed(self, name: str) -> None:
        if not self._updating and name:
            self.output_requested.emit(name)

    def set_feature_enabled(self, enabled: bool) -> None:
        self._feature_enabled = enabled
        if self.enabled_switch.isChecked() != enabled:
            self.enabled_switch.setChecked(enabled)
        self._apply_feature_state()

    def _apply_feature_state(self) -> None:
        self.setProperty("featureEnabled", self._feature_enabled)
        self.avatar_effect.setOpacity(1.0 if self._feature_enabled else 0.28)
        self.combo.setEnabled(self._feature_enabled and self._available)
        self.refresh_button.setEnabled(self._feature_enabled)
        for widget in self.findChildren(QLabel):
            widget.setEnabled(self._feature_enabled)
        self.style().unpolish(self)
        self.style().polish(self)


class SettingRow(QFrame):
    def __init__(self, title: str, description: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("settingTitle")
        self.description_label = QLabel(description)
        self.description_label.setObjectName("settingDescription")
        self.description_label.setWordWrap(True)
        text.addWidget(self.title_label)
        text.addWidget(self.description_label)
        layout.addLayout(text, 1)
        self.switch = ToggleSwitch()
        self.switch.toggled.connect(self._apply_enabled_style)
        layout.addWidget(self.switch)
        self._apply_enabled_style(False)

    def _apply_enabled_style(self, enabled: bool) -> None:
        self.setProperty("featureEnabled", enabled)
        self.title_label.setEnabled(enabled)
        self.description_label.setEnabled(enabled)
        self.style().unpolish(self)
        self.style().polish(self)


class WifiStatusBadge(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(62, 62)
        self._connected = False

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor("#43ce89" if self._connected else "#68757a")
        painter.setPen(QPen(accent, 1.2))
        painter.setBrush(QColor("#0d1214"))
        painter.drawEllipse(QRectF(1.5, 1.5, 59, 59))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(accent, 2.35)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        outer = QPainterPath()
        outer.moveTo(15, 27)
        outer.cubicTo(23, 18, 39, 18, 47, 27)
        painter.drawPath(outer)

        middle = QPainterPath()
        middle.moveTo(21, 33)
        middle.cubicTo(27, 27, 35, 27, 41, 33)
        painter.drawPath(middle)

        inner = QPainterPath()
        inner.moveTo(27, 39)
        inner.cubicTo(29, 37, 33, 37, 35, 39)
        painter.drawPath(inner)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(28.5, 43, 5, 5))
        painter.end()


class StatusCard(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statusCard")
        self._language = "pl"
        self._connected = False
        self._detail_text = "Brak połączenia z brokerem MQTT"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)

        self.badge = WifiStatusBadge()
        layout.addWidget(self.badge)

        text = QVBoxLayout()
        text.setSpacing(3)
        self.title = QLabel("Brak połączenia")
        self.title.setObjectName("statusCardTitle")
        self.detail = QLabel("Brak połączenia z brokerem MQTT")
        self.detail.setObjectName("statusCardDetail")
        text.addWidget(self.title)
        text.addWidget(self.detail)
        layout.addLayout(text, 1)

        divider = QFrame()
        divider.setObjectName("statusVerticalDivider")
        divider.setFixedWidth(1)
        layout.addWidget(divider)

        metrics = QVBoxLayout()
        metrics.setSpacing(8)
        uptime_row = QHBoxLayout()
        uptime_row.addWidget(QLabel("Czas działania"))
        self.uptime = QLabel("00:00:00")
        self.uptime.setObjectName("metricValue")
        uptime_row.addWidget(self.uptime)
        messages_row = QHBoxLayout()
        messages_row.addWidget(QLabel("Wiadomości"))
        self.messages = QLabel("0")
        self.messages.setObjectName("metricValue")
        messages_row.addWidget(self.messages)
        metrics.addLayout(uptime_row)
        metrics.addLayout(messages_row)
        layout.addLayout(metrics)

    def update_status(self, connected: bool, detail: str, uptime: str, messages: int) -> None:
        self._connected = connected
        self._detail_text = detail
        self.badge.set_connected(connected)
        title = "Połączono z Home Assistant" if connected else "Brak połączenia"
        self.title.setText(translate(title, self._language))
        self.detail.setText(translate(detail, self._language))
        self.uptime.setText(uptime)
        self.messages.setText(f"{messages:,}".replace(",", " "))

    def set_language(self, language: str) -> None:
        self._language = language
        self.update_status(
            self._connected,
            self._detail_text,
            self.uptime.text(),
            int(self.messages.text().replace(" ", "") or "0"),
        )
