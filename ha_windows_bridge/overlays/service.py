"""Qt presentation host for the pure notification engine."""
from __future__ import annotations

from collections import defaultdict
from contextlib import suppress

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .engine import NotificationEngine
from .glass import GlassRenderer
from .positioning import CardSize, PlacementEngine, Rect
from .presentation import NotificationWindow


class OverlayService(QObject):
    received = Signal(object)

    def __init__(self, application):
        super().__init__()
        self.application = application
        self.engine = NotificationEngine()
        self.windows = {}
        self.glass = GlassRenderer(self.windows, application.log)
        self._rendered = {}
        self._retiring = set()
        self._connections = []
        self._screens = []
        self._media_request = 0
        self._closed = False
        self._unsubscribe = application.events.subscribe("*", self.received.emit)
        self.received.connect(self._event, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.media_timer = QTimer(self)
        self.media_timer.setInterval(500)
        self.media_timer.timeout.connect(self.application.request_media_refresh)
        app = QGuiApplication.instance()
        self._connections.extend((app.screenAdded.connect(self._screens_changed),
                                  app.screenRemoved.connect(self._screens_changed)))
        self._screens_changed()
        self._apply_preferences(application.config)

    @staticmethod
    def _apply_preferences(config):
        app = QGuiApplication.instance()
        app.setProperty("bridgeReducedMotion", config.reduced_motion)
        app.setProperty("bridgePopupAnimation", config.overlay_animation)
        app.setProperty("bridgePopupAnimationDuration", config.overlay_animation_duration)

    def _event(self, event):
        if self._closed:
            return
        if event.topic == "overlay.show":
            self.engine.submit(event.data)
            self._sync()
        elif event.topic == "overlay.example":
            self.example(event.data)
        elif event.topic == "overlay.media_example":
            if event.data["request_id"] == self._media_request:
                payload = event.data["payload"]
                payload["data"].update(self._example_options())
                self.engine.submit(payload)
                self._sync()
        elif event.topic == "overlay.media_refresh":
            if self.engine.refresh_media(event.data):
                self._sync()
        elif event.topic == "command.result" and self.media_timer.isActive():
            self.application.request_media_refresh()
        elif event.topic == "overlay.clear" or event.topic == "windows.locked" and event.data:
            self._media_request += 1
            self.engine.submit({"data": {"action": "clear"}})
            self._sync()
        elif event.topic == "configuration.changed":
            self._apply_preferences(event.data)
        elif event.topic == "windows.display_changed":
            self.glass.invalidate()

    def _example_options(self):
        config = self.application.config
        return {"duration": config.overlay_example_duration, "background_effect": config.overlay_background_effect}

    def example(self, pattern):
        request_id = self._media_request + 1
        if pattern == "badges":
            for identifier, icon, value in (("battery", "mdi:battery", "88%"), ("light", "mdi:lightbulb", ""), ("clock", "", "14:01")):
                self.engine.submit({"title": "", "message": value, "data": {
                    "id": "example-" + identifier, "icon": icon, "layout": "badge", "display_mode": "parallel",
                    "duration": self.application.config.overlay_example_duration, "edge_offset": 16}})
        elif pattern == "media":
            if self.application.request_media_example(request_id):
                self._media_request = request_id
            return
        else:
            self.engine.submit({"title": "HA Windows Bridge 2.0",
                                "message": "Twoje powiadomienia. Na Twoim komputerze.",
                                "data": {"id": "example-message", "layout": pattern, "icon": "mdi:home-assistant",
                                         "show_lifetime": True, "pause_on_hover": True, "show_close_button": True,
                                         "edge_offset": 16, **self._example_options()}})
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
        self.glass.sync()
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
                if window._awaiting_glass:
                    if window._target != target:
                        window.stage(target, screens[monitor])
                    continue
                first_appearance = bool(appearing and identifier in appearing)
                needs_background = _options["background_effect"] in {"blur", "liquid"} and window._glass_image.isNull()
                if first_appearance and needs_background and self.glass.can_prime():
                    window.stage(target, screens[monitor])
                    continue
                moving_to_target = window._animation is not None and window._target == target
                if (appearing and identifier in appearing) or (window.pos() != target and not moving_to_target) or not window.isVisible():
                    window.place(target, appearing=first_appearance)

    def _dismiss(self, identifier):
        self.engine.remove(identifier)
        self._sync()

    def _hover(self, identifier, paused):
        self.engine.pause(identifier, paused)
        self._clock_state()

    def _clock_state(self):
        live = any(item.options.get("media_live") for item in self.engine.visible.values())
        if live and not self.media_timer.isActive():
            self.media_timer.start()
        elif not live:
            self.media_timer.stop()
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
                window.set_media_position(self.engine.media_position(identifier), duration)
        self._clock_state()

    def close(self) -> bool:
        self._closed = True
        self._media_request += 1
        self._unsubscribe()
        self.timer.stop()
        self.media_timer.stop()
        glass_stopped = self.glass.close()
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
        return glass_stopped
