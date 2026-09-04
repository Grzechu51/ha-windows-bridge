"""Qt presentation host for the pure notification engine."""
from __future__ import annotations

from collections import defaultdict
from contextlib import suppress

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .engine import NotificationEngine
from .positioning import CardSize, PlacementEngine, Rect
from .presentation import NotificationWindow


class OverlayService(QObject):
    received = Signal(object)

    def __init__(self, application):
        super().__init__()
        self.application = application
        self.engine = NotificationEngine()
        self.windows = {}
        self._rendered = {}
        self._retiring = set()
        self._connections = []
        self._screens = []
        self._unsubscribe = application.events.subscribe("*", self.received.emit)
        self.received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        app = QGuiApplication.instance()
        self._connections.extend((app.screenAdded.connect(self._screens_changed),
                                  app.screenRemoved.connect(self._screens_changed)))
        self._screens_changed()

    def _event(self, event):
        if event.topic == "overlay.show":
            self.engine.submit(event.data)
            self._sync()
        elif event.topic == "overlay.example":
            self.example(event.data)
        elif event.topic == "overlay.clear" or event.topic == "windows.locked" and event.data:
            self.engine.submit({"data": {"action": "clear"}})
            self._sync()
        elif event.topic == "configuration.changed":
            QGuiApplication.instance().setProperty("bridgeReducedMotion", event.data.reduced_motion)

    def example(self, pattern):
        if pattern == "badges":
            for identifier, icon, value in (("battery", "mdi:battery", "88%"), ("light", "mdi:lightbulb", ""), ("clock", "", "14:01")):
                self.engine.submit({"title": "", "message": value, "data": {
                    "id": "example-" + identifier, "icon": icon, "layout": "badge", "display_mode": "parallel",
                    "duration": 8, "edge_offset": 16}})
        else:
            self.engine.submit({"title": "HA Windows Bridge 2.0",
                                "message": "Twoje powiadomienia. Na Twoim komputerze.",
                                "data": {"id": "example-message", "layout": pattern, "icon": "mdi:home-assistant",
                                         "show_lifetime": True, "pause_on_hover": True, "show_close_button": True,
                                         "edge_offset": 16, "duration": 8,
                                         "progress": 42 if pattern == "media" else None}})
        self._sync()

    def _screens_changed(self, *_args):
        for screen in QGuiApplication.screens():
            if screen not in self._screens:
                self._screens.append(screen)
                self._connections.extend((screen.availableGeometryChanged.connect(self._display_changed),
                                          screen.logicalDotsPerInchChanged.connect(self._display_changed)))
        self._display_changed()

    def _display_changed(self, *_args):
        self.engine.release_deferred()
        self._sync()

    def _sync(self):
        for identifier in tuple(self.windows):
            if identifier not in self.engine.visible:
                retired = self.windows.pop(identifier)
                self._retiring.add(retired)
                retired.destroyed.connect(lambda _object=None, window=retired: self._retiring.discard(window))
                retired.retire()
                self._rendered.pop(identifier, None)
        new = set()
        for identifier, notification in self.engine.visible.items():
            window = self.windows.get(identifier)
            if window is None:
                window = NotificationWindow(notification.options)
                window.dismissed.connect(self._dismiss)
                window.hovered.connect(self._hover)
                window.action.connect(lambda action: self.application.command("media.control", {"action": action}))
                self.windows[identifier] = window
                new.add(identifier)
            elif self._rendered.get(identifier) != notification.options:
                window.update_notification(notification.options)
            self._rendered[identifier] = notification.options.copy()
        self._place(appearing=new)
        self._clock_state()

    def _place(self, *_args, appearing=None):
        screens = QGuiApplication.screens()
        if not screens:
            return
        groups = defaultdict(list)
        for identifier, window in self.windows.items():
            options = self.engine.visible[identifier].options
            groups[min(options["monitor"], len(screens) - 1)].append((identifier, window, options))
        for monitor, group in groups.items():
            area = screens[monitor].availableGeometry()
            cards = []
            for identifier, window, options in group:
                window.constrain_width(max(52, area.width() - options["edge_offset"] * 2))
                cards.append(CardSize(identifier, window.width(), window.height(), options["corner"], options["layout"] == "badge", options["edge_offset"]))
            positions = PlacementEngine().place(Rect(area.x(), area.y(), area.width(), area.height()), cards)
            for identifier, window, _options in group:
                if identifier not in positions:
                    self.engine.defer(identifier)
                    self.windows.pop(identifier).dispose()
                    self._rendered.pop(identifier, None)
                    continue
                position = positions[identifier]
                target = QPoint(position.x, position.y)
                if (appearing and identifier in appearing) or window.pos() != target or not window.isVisible():
                    window.place(target, appearing=bool(appearing and identifier in appearing))

    def _dismiss(self, identifier):
        self.engine.remove(identifier)
        self._sync()

    def _hover(self, identifier, paused):
        self.engine.pause(identifier, paused)
        self._clock_state()

    def _clock_state(self):
        if self.engine.needs_clock:
            smooth = any(item.deadline is not None and item.options["show_lifetime"] for item in self.engine.visible.values())
            self.timer.setInterval(50 if smooth else 500)
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        before = tuple(self.engine.visible)
        self.engine.tick()
        if tuple(self.engine.visible) != before:
            self._sync()
        for identifier, window in self.windows.items():
            window.lifetime.setValue(round(self.engine.lifetime(identifier) * 1000))
            duration = self.engine.visible[identifier].options["media_duration"]
            if duration:
                window.progress.setValue(round(self.engine.media_position(identifier) / duration * 100))
        self._clock_state()

    def close(self):
        self._unsubscribe()
        self.timer.stop()
        for connection in self._connections:
            with suppress(RuntimeError):
                QObject.disconnect(connection)
        self._connections.clear()
        for window in self.windows.values():
            window.dispose()
        self.windows.clear()
        for window in tuple(self._retiring):
            window.dispose()
        self._retiring.clear()
        self.engine.visible.clear()
        self.engine.pending.clear()
