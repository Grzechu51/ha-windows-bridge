"""Qt presentation host for the pure notification engine."""
from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import suppress

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from .engine import NotificationEngine
from .glass import GlassRenderer
from .models import LifecycleReason
from .monitors import monitor_label, resolve_screen, screen_id
from .positioning import CardSize, PlacementEngine, Rect
from .presentation import NotificationWindow


class OverlayService(QObject):
    received = Signal(object)

    def __init__(self, application):
        super().__init__()
        self.application = application
        self.engine = getattr(application, "notifications", None) or NotificationEngine()
        self.windows = {}
        self.glass = GlassRenderer(self.windows, application.log)
        self._rendered = {}
        self._tokens = {}
        self._retiring = set()
        self._connections = []
        self._screens = []
        self._media_request = 0
        self._closed = False
        self._locked = False
        self._suspended = False
        self._wakeup_lock = threading.RLock()
        self._wakeup_pending = False
        topics = (
            "overlay.show", "overlay.example",
            "overlay.media_example", "overlay.media_refresh", "overlay.clear",
            "command.result", "configuration.changed", "windows.display_changed",
            "computer_state.changed",
        )
        self._unsubscribers = [
            application.events.subscribe(topic, self.received.emit) for topic in topics
        ]
        self._unsubscribers.extend((
            application.events.subscribe("overlay.wakeup", self._queue_wakeup),
            application.events.subscribe("windows.locked", self._policy_event),
            application.events.subscribe("windows.power_changed", self._policy_event),
        ))
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
        elif event.topic == "overlay.wakeup":
            with self._wakeup_lock:
                self._wakeup_pending = False
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
        elif event.topic == "overlay.clear":
            self._media_request += 1
            self.engine.submit({"data": {"action": "clear"}})
            self._sync()
        elif event.topic == "configuration.changed":
            self._apply_preferences(event.data)
            if event.data.reduced_motion:
                for window in (*self.windows.values(), *self._retiring):
                    window.reduce_motion()
        elif event.topic == "windows.display_changed":
            self.glass.invalidate()
            self._screens_changed()
        elif event.topic in {
            "computer_state.changed", "windows.locked", "windows.power_changed",
        }:
            self._sync()

    def _queue_wakeup(self, event):
        with self._wakeup_lock:
            if self._closed or self._wakeup_pending:
                return
            self._wakeup_pending = True
        self.received.emit(event)

    def _policy_event(self, event):
        if self._closed:
            return
        if event.topic == "windows.locked":
            self._locked = bool(event.data)
        elif event.topic == "windows.power_changed":
            self._suspended = event.data == "suspend"
        if self._locked or self._suspended:
            reason = LifecycleReason.SUSPENDED if self._suspended else LifecycleReason.LOCKED
            self.engine.suppress(reason)
        self.received.emit(event)

    def _presentation_allowed(self):
        if self._locked or self._suspended:
            return False
        try:
            context = self.application._system_view.context_snapshot()
        except (AttributeError, RuntimeError):
            return True
        return not context.locked and (
            self.application.config.overlay_allow_fullscreen or not context.fullscreen
        )

    def _lifecycle(self, result, item=None):
        self.application.publish_notification_lifecycle(result)

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
        screens = QGuiApplication.screens()
        previous_ids = {screen_id(screen) for screen in self._screens}
        for screen in screens:
            if screen not in self._screens:
                self._screens.append(screen)
                self._connections.extend((screen.availableGeometryChanged.connect(self._display_changed),
                                          screen.logicalDotsPerInchChanged.connect(self._display_changed)))
        self._screens = [screen for screen in self._screens if screen in screens]
        current_ids = {screen_id(screen) for screen in screens}
        removed_ids = previous_ids - current_ids
        if removed_ids:
            visible = self.engine.snapshot()[0]
            for identifier, notification in visible.items():
                if notification.options.get("monitor_id") in removed_ids:
                    self.engine.begin_retire(
                        identifier, notification.token,
                        LifecycleReason.DISPLAY_REMOVED,
                    )
        monitor_names = [
            monitor_label(screen_id(screen), index)
            for index, screen in enumerate(screens)
        ]
        self.application.monitors[:] = monitor_names
        self.application.events.emit("overlay.monitors_changed", tuple(monitor_names))
        self._display_changed()

    def _display_changed(self, *_args):
        self.engine.release_deferred()
        self._sync()

    def _sync(self):
        visible, _pending, _retiring = self.engine.snapshot()
        if not QGuiApplication.screens():
            for identifier in tuple(visible):
                self.engine.defer(identifier, visible[identifier].token)
            visible, _pending, _retiring = self.engine.snapshot()
        if not self._presentation_allowed():
            reason = LifecycleReason.LOCKED if self._locked or self._suspended else LifecycleReason.FULLSCREEN
            for identifier, notification in visible.items():
                self.engine.begin_retire(identifier, notification.token, reason)
                if identifier not in self.windows:
                    self.engine.finish_retire(identifier, notification.token)
            visible, _pending, _retiring = self.engine.snapshot()
        for identifier, notification in _retiring.items():
            if identifier not in self.windows and not any(
                getattr(window, "_token", None) == notification.token
                for window in self._retiring
            ):
                self.engine.finish_retire(identifier, notification.token)
        for identifier in tuple(self.windows):
            if identifier not in visible:
                retired = self.windows.pop(identifier)
                self._retiring.add(retired)
                token = self._tokens.pop(identifier, 0)
                retired.destroyed.connect(
                    lambda _object=None, window=retired, key=identifier, generation=token:
                    self._retired(window, key, generation)
                )
                retired.retire()
                self._rendered.pop(identifier, None)
        new = set()
        for identifier, notification in visible.items():
            window = self.windows.get(identifier)
            if window is None:
                try:
                    window = NotificationWindow(notification.options, token=notification.token)
                except (MemoryError, RuntimeError, ValueError, OSError):
                    self.application.log.exception("Nie można wyrenderować nakładki %s", identifier)
                    self.engine.begin_retire(
                        identifier, notification.token, LifecycleReason.RENDER_ERROR
                    )
                    self.engine.finish_retire(identifier, notification.token)
                    continue
                window.displayed.connect(self._displayed)
                window.dismissed.connect(self._dismiss)
                window.hovered.connect(self._hover)
                window.action.connect(lambda action: self.application.command("media.control", {"action": action}))
                self.windows[identifier] = window
                new.add(identifier)
            elif (self._rendered.get(identifier) != notification.options
                  or self._tokens.get(identifier) != notification.token):
                generation_changed = self._tokens.get(identifier) != notification.token
                window.update_notification(notification.options, token=notification.token)
                if generation_changed and not notification.displayed:
                    new.add(identifier)
            self._rendered[identifier] = notification.options.copy()
            self._tokens[identifier] = notification.token
        self._place(appearing=new, visible=visible)
        self.glass.sync()
        self._clock_state()
        self._publish_lifecycle()

    def _publish_lifecycle(self):
        for result in self.engine.drain_lifecycle():
            self._lifecycle(result)

    def _place(self, *_args, appearing=None, visible=None):
        screens = QGuiApplication.screens()
        if not screens:
            return
        visible = visible or self.engine.snapshot()[0]
        groups = defaultdict(list)
        for identifier, window in self.windows.items():
            notification = visible.get(identifier)
            if notification is None:
                continue
            options = notification.options
            monitor_id = str(options.get("monitor_id", ""))
            screen = resolve_screen(
                screens, monitor_id, options["monitor"],
                QGuiApplication.primaryScreen(),
            )
            if screen is None:
                continue
            resolved_id = screen_id(screen)
            if not monitor_id and self.engine.bind_monitor(
                    identifier, notification.token, resolved_id):
                options["monitor_id"] = resolved_id
            groups[screen].append((identifier, window, options))
        for screen, group in groups.items():
            area = screen.availableGeometry()
            cards = []
            for identifier, window, options in group:
                window.constrain_width(max(52, area.width() - options["edge_offset"] * 2))
                cards.append(CardSize(identifier, window.width(), window.height(), options["corner"], options["layout"] == "badge", options["edge_offset"]))
            positions = PlacementEngine().place(Rect(area.x(), area.y(), area.width(), area.height()), cards)
            for identifier, window, _options in group:
                notification = visible[identifier]
                if not self.engine.token_matches(identifier, notification.token):
                    if self.windows.get(identifier) is window:
                        self.windows.pop(identifier)
                        self._retiring.add(window)
                        window.destroyed.connect(
                            lambda _object=None, retired=window, key=identifier,
                            generation=notification.token:
                            self._retired(retired, key, generation)
                        )
                        window.dispose()
                        self._rendered.pop(identifier, None)
                        self._tokens.pop(identifier, None)
                    continue
                handle = window.windowHandle()
                if handle is not None:
                    handle.setScreen(screen)
                if identifier not in positions:
                    self.engine.defer(identifier, notification.token)
                    self.windows.pop(identifier).dispose()
                    self._rendered.pop(identifier, None)
                    continue
                position = positions[identifier]
                target = QPoint(position.x, position.y)
                if window._awaiting_glass:
                    if window._target != target:
                        window.stage(target, screen)
                    continue
                first_appearance = bool(appearing and identifier in appearing)
                needs_background = _options["background_effect"] in {"blur", "liquid"} and window._glass_image.isNull()
                if first_appearance and needs_background and self.glass.can_prime():
                    window.stage(target, screen)
                    continue
                moving_to_target = window._animation is not None and (
                    window._target == target or window._motion_phase == "enter"
                )
                if (appearing and identifier in appearing) or (window.pos() != target and not moving_to_target) or not window.isVisible():
                    window.place(target, appearing=first_appearance)

    def _displayed(self, identifier, token):
        result = self.engine.mark_displayed(identifier, token)
        if result.disposition.value == "displayed":
            self._clock_state()
            self._publish_lifecycle()

    def _retired(self, window, identifier, token):
        self._retiring.discard(window)
        if self.engine.finish_retire(identifier, token):
            self._sync()

    def _dismiss(self, identifier, token):
        if self.engine.remove(identifier, token):
            self._sync()

    def _hover(self, identifier, token, paused):
        if self.engine.pause(identifier, paused, token):
            self._clock_state()

    def _clock_state(self):
        visible = self.engine.snapshot()[0]
        live = any(item.options.get("media_live") for item in visible.values())
        if live and not self.media_timer.isActive():
            self.media_timer.start()
        elif not live:
            self.media_timer.stop()
        if self.engine.needs_clock:
            smooth = any(item.deadline is not None and item.options["show_lifetime"] for item in visible.values())
            self.timer.setInterval(50 if smooth else 500)
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        before = self.engine.snapshot()[0]
        self.engine.tick()
        visible = self.engine.snapshot()[0]
        if tuple(visible) != tuple(before):
            self._sync()
            visible = self.engine.snapshot()[0]
        for identifier, window in tuple(self.windows.items()):
            item = visible.get(identifier)
            if item is None or window._token != item.token:
                continue
            frame = self.engine.presentation_state(identifier, item.token)
            if frame is None or window._token != item.token:
                continue
            lifetime, duration, position = frame
            window.lifetime.setValue(round(lifetime * 1000))
            if duration:
                window.set_media_position(position, duration)
        self._clock_state()
        self._publish_lifecycle()

    def close(self) -> bool:
        self._closed = True
        self._media_request += 1
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
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
        self.engine.shutdown()
        self._publish_lifecycle()
        return glass_stopped
