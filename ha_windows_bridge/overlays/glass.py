"""Bounded captured-background blur. No work or pixels remain when idle."""
from __future__ import annotations

import hashlib
import threading
import time

from PIL import Image, ImageFilter
from PySide6.QtCore import QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage

from ..runtime.worker import SerialWorker
from ..windows.capture import DesktopDuplicationCapture, on_battery_power


def blur_scene(image):
    small = image.scaled(QSize(320, 240), Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.FastTransformation).convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(small.constBits())
    digest = hashlib.blake2s(pixels, digest_size=12).digest()
    source = Image.frombytes("RGBA", (small.width(), small.height()), pixels)
    blurred = source.filter(ImageFilter.GaussianBlur(8))
    return QImage(blurred.tobytes(), blurred.width, blurred.height, QImage.Format.Format_RGBA8888).copy(), digest


class GlassRenderer(QObject):
    completed = Signal(object, float)

    def __init__(self, windows, logger):
        super().__init__()
        self.windows, self.log = windows, logger
        self.capture = DesktopDuplicationCapture()
        self.worker = SerialWorker("liquid-glass", logger, capacity=2)
        self.timer = QTimer(self)
        self.timer.setInterval(500 if on_battery_power() else 250)
        self.timer.timeout.connect(self.request)
        self.completed.connect(self._accept, Qt.ConnectionType.QueuedConnection)
        self.pending = False
        self.closed = False
        self._cache = {}
        self._warned = False
        self._generation = 0

    def targets(self):
        return {identifier: window for identifier, window in self.windows.items()
                if (window.isVisible() or window._awaiting_glass)
                and window._options["background_effect"] in {"blur", "liquid"}
                and window.capture_excluded}

    @staticmethod
    def can_prime():
        return QGuiApplication.instance().platformName() != "offscreen"

    def sync(self):
        if QGuiApplication.instance().platformName() == "offscreen":
            return
        if self.targets():
            if not self.timer.isActive():
                self.timer.start()
                self.request()
            if any(window._awaiting_glass for window in self.targets().values()):
                QTimer.singleShot(350, self._release_staged)
        elif self.timer.isActive():
            self.timer.stop()
            self._generation += 1
            self.worker.submit(self._release)

    def request(self):
        if self.pending or self.closed:
            return
        screens = QGuiApplication.screens()
        targets = []
        for identifier, window in self.targets().items():
            screen = window.screen()
            if screen not in screens or window._animation is not None and not window._awaiting_glass:
                continue
            region = QRect(window.pos() - screen.geometry().topLeft(), window.size())
            key = (identifier, int(window.winId()), region.x(), region.y(), region.width(), region.height(), screen.name())
            targets.append((key, screens.index(screen), screen.name(), region, window.devicePixelRatioF()))
        if not targets:
            return
        self.pending = True
        generation = self._generation
        def render():
            started = time.perf_counter()
            frames = []
            try:
                for key, index, name, region, scale in targets:
                    image = self.capture.grab_image(index, name, region, scale)
                    if image is None:
                        if not self._warned:
                            self.log.warning("Rozmycie tła jest niedostępne; użyto jednolitego tła")
                            self._warned = True
                        continue
                    blurred, digest = blur_scene(image)
                    if self._cache.get(key) != digest:
                        self._cache[key] = digest
                        frames.append((key, blurred))
                keep = {item[0] for item in targets}
                self._cache = {key: value for key, value in self._cache.items() if key in keep}
            finally:
                self.completed.emit((generation, frames, [item[0] for item in targets]), (time.perf_counter() - started) * 1000)
        if not self.worker.submit(render):
            self.pending = False

    def _accept(self, result, cost):
        self.pending = False
        generation, frames, requested = result
        if self.closed or generation != self._generation:
            return
        if cost > 45:
            self.timer.setInterval(750)
        images = {key: image for key, image in frames}
        for key in requested:
            window = self.windows.get(key[0])
            if window is None or int(window.winId()) != key[1] or not (window.isVisible() or window._awaiting_glass):
                continue
            screen = window.screen()
            region = QRect(window.pos() - screen.geometry().topLeft(), window.size())
            if (region.x(), region.y(), region.width(), region.height(), screen.name()) == key[2:]:
                image = images.get(key)
                if image is not None:
                    window.set_glass_image(image)
                if window._awaiting_glass:
                    window.place(window._target, appearing=True)

    def _release_staged(self):
        if self.closed:
            return
        for window in tuple(self.windows.values()):
            if window._awaiting_glass:
                window.place(window._target, appearing=True)

    def _release(self):
        self.capture.release()
        self._cache.clear()

    def invalidate(self):
        self._generation += 1
        self.worker.submit(self.capture.invalidate)

    def close(self):
        self.closed = True
        self.timer.stop()
        released = threading.Event()
        if self.worker.is_alive:
            self.worker.submit(lambda: (self._release(), released.set()))
            released.wait(2)
        self.worker.close(timeout=2)
