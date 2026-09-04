from __future__ import annotations

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from test_v2_application import runtime
from test_v2_desktop import qt_app

from ha_windows_bridge.audio import AudioApplication, WindowsAudioService
from ha_windows_bridge.config import AppConfig, AudioAppConfig
from ha_windows_bridge.overlays.examples import media_example
from ha_windows_bridge.overlays.media_style import (
    artwork_rect,
    contrast_ratio,
    edge_colour,
    media_palette,
)
from ha_windows_bridge.overlays.models import validated_request
from ha_windows_bridge.overlays.presentation import NotificationWindow
from ha_windows_bridge.ui.shell import DesktopWindow, Page
from ha_windows_bridge.ui.theme import style_for_theme
from ha_windows_bridge.ui_components import AppCard, SettingRow


@pytest.mark.parametrize("colour", ["#693531", "#ebe6cd", "#286f89", "#121414"])
def test_media_palette_matches_artwork_and_preserves_contrast(colour):
    qt_app()
    pixmap = QPixmap(120, 120)
    pixmap.fill(QColor(colour))
    surface, primary, secondary = media_palette(pixmap)
    assert abs(surface.hslHue() - QColor(colour).hslHue()) <= 1
    assert contrast_ratio(primary, surface) >= 4.8
    assert contrast_ratio(secondary, surface) >= 3.6
    if QColor(colour).lightness() >= 145:
        assert surface.lightness() == 205
        assert primary.lightness() < 80
    else:
        assert primary.lightness() > 200


def test_media_samples_left_edge_not_dominant_colour_of_whole_cover():
    qt_app()
    pixmap = QPixmap(240, 240)
    pixmap.fill(QColor("#2233cc"))
    painter = QPainter(pixmap)
    painter.fillRect(QRect(0, 0, 90, 240), QColor("#c04030"))
    painter.end()
    colour = edge_colour(pixmap)
    assert colour.red() > 150 and colour.blue() < 80


@pytest.mark.parametrize("size", [QSize(200, 200), QSize(600, 200), QSize(200, 600)])
def test_entire_cover_fits_right_side_without_cropping(size):
    rect = artwork_rect(QSize(480, 180), size)
    assert rect.right() == 480
    assert rect.width() <= round(480 * .68)
    assert rect.height() <= 180
    assert abs(rect.width() / rect.height() - size.width() / size.height()) < .03


def test_media_has_original_tinted_surface_and_rendered_full_cover(tmp_path):
    qt = qt_app()
    example = media_example()
    window = NotificationWindow(validated_request(example["title"], example["message"], example["data"]))
    try:
        window.show()
        qt.processEvents()
        surface, primary, secondary = window._media_palette
        assert primary.name() in window.title.styleSheet()
        assert secondary.name() in window.message.styleSheet()
        frame = window.grab().toImage()
        dpr = window.devicePixelRatioF()
        pixel = frame.pixelColor(round(6 * dpr), round(window.height() / 2 * dpr))
        assert abs(pixel.red() - surface.red()) <= 2
        assert abs(pixel.green() - surface.green()) <= 2
        assert abs(pixel.blue() - surface.blue()) <= 2
        assert frame.save(str(tmp_path / "media-original-style.png"))
    finally:
        window.dispose()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_setting_text_and_switch_centres_match_and_theme_uses_same_row(theme, tmp_path):
    qt = qt_app()
    qt.setStyleSheet(style_for_theme("", theme))
    application = runtime(AppConfig(auto_connect=False))
    window = DesktopWindow(application)
    try:
        window.resize(820, 740)
        window.show()
        for page in (Page.OVERVIEW, Page.FEATURES, Page.OVERLAYS, Page.SETTINGS):
            window.navigation.setCurrentRow(page)
            qt.processEvents()
            for row in window.pages.widget(page).findChildren(SettingRow):
                assert row.description_label.isHidden()
                assert row.title_label.isEnabled()
                center = row.title_label.mapTo(row, row.title_label.rect().center()).y()
                assert abs(center - row.switch.geometry().center().y()) <= 1
            assert window.pages.widget(page).horizontalScrollBar().maximum() == 0
        row = window.theme_row
        center = row.title_label.mapTo(row, row.title_label.rect().center()).y()
        assert abs(center - window.theme.geometry().center().y()) <= 1
        assert row.layout().contentsMargins() == window._toggles["reduced_motion"].parent().layout().contentsMargins()
        assert window.grab().save(str(tmp_path / f"settings-{theme}.png"))
    finally:
        window._force_close = True
        window.close()
        assert application.shutdown()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_icon_has_constant_logical_size_and_metadata_does_not_redirect_authorized_exe(monkeypatch):
    qt_app()
    app = runtime(AppConfig(apps=[AudioAppConfig("test.exe", "Test", "test", True,
                                                executable_path="old-authorized.exe", allow_remote_start=True)]))
    window = DesktopWindow(app)
    try:
        card = window._cards[0]
        window._update_applications([AudioApplication("test.exe", "Test", sys.executable, .5, False)])
        assert card.config.executable_path == "old-authorized.exe"
        assert card._icon_path == sys.executable
        pixmap = card.avatar.pixmap()
        assert not pixmap.isNull()
        assert max(pixmap.deviceIndependentSize().width(), pixmap.deviceIndependentSize().height()) == pytest.approx(46, abs=.5)
        key = pixmap.cacheKey()
        window._update_applications([AudioApplication("test.exe", "Test", sys.executable, .5, False)])
        assert card.avatar.pixmap().cacheKey() == key
        card.enabled_switch.setChecked(False)
        assert card.avatar_effect.opacity() >= .7
    finally:
        window._force_close = True
        window.close()
        assert app.shutdown()
        window.deleteLater()


def test_icon_trims_padding_before_scaling():
    qt_app()
    image = QImage(256, 256, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(QRect(96, 96, 64, 64), QColor("#62bb93"))
    painter.end()
    result = AppCard._trim_transparent(QPixmap.fromImage(image))
    assert 64 <= result.width() <= 72
    assert result.width() == result.height()


def test_configured_silent_program_gets_icon_metadata_without_being_enabled(monkeypatch):
    monkeypatch.setattr("ha_windows_bridge.audio.com_scope", nullcontext)
    monkeypatch.setattr("ha_windows_bridge.audio.AudioUtilities.GetAllSessions", lambda: [])
    monkeypatch.setattr("ha_windows_bridge.audio.psutil.process_iter", lambda *_a, **_kw: iter([
        SimpleNamespace(info={"name": "unrelated.exe", "exe": "C:/unrelated.exe"}),
        SimpleNamespace(info={"name": "Discord.exe", "exe": "C:/Apps/Discord/Discord.exe"})]))
    result = WindowsAudioService().list_audio_applications(include_processes=["discord.exe"])
    assert len(result) == 1
    assert result[0].executable_path == "C:/Apps/Discord/Discord.exe"
    assert result[0].volume is None and result[0].muted is None
