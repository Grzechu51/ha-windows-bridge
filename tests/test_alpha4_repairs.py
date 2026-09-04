from __future__ import annotations

import copy
import threading

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_v2_application import runtime
from test_v2_desktop import qt_app
from test_v2_transports import Socket, ha_transport, handshake

from ha_windows_bridge.communication.home_assistant import (
    HomeAssistantConnectionError,
    response_error,
)
from ha_windows_bridge.communication.state import ConnectionState, ConnectionStatus
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig
from ha_windows_bridge.core.events import Event
from ha_windows_bridge.media import MediaArtwork, MediaSnapshot
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.ui.shell import DesktopWindow, Page


def drain(application):
    completed = threading.Event()
    assert application._operations.submit(completed.set)
    assert completed.wait(3)


def test_save_keeps_manually_started_services_running_without_auto_connect():
    app = runtime()
    app.config.auto_connect = False
    try:
        app.start()
        drain(app)
        old_router = app.router
        changed = copy.deepcopy(app.config)
        changed.device_name = "Renamed PC"
        assert app.apply_configuration(changed)
        drain(app)
        assert set(app.supervisor.active) == {"mqtt", "sensors"}
        assert app.router is not old_router and old_router.closed
        assert app._desired_running and not app.config.auto_connect
        assert "Zapisano i zastosowano" in "\n".join(app.diagnostics.snapshot())
    finally:
        assert app.shutdown()


def test_save_does_not_start_stopped_services_even_with_auto_connect():
    app = runtime()
    try:
        changed = copy.deepcopy(app.config)
        changed.auto_connect = True
        app.apply_configuration(changed)
        drain(app)
        assert not app.supervisor.active and not app._desired_running
    finally:
        assert app.shutdown()


def test_failed_save_restores_running_services_and_keeps_old_settings():
    app = runtime()
    try:
        app.start()
        drain(app)
        old_name = app.config.device_name
        def failed(_config):
            raise OSError("write denied")
        app.store.save = failed
        changed = copy.deepcopy(app.config)
        changed.device_name = "Must not apply"
        app.apply_configuration(changed)
        drain(app)
        assert set(app.supervisor.active) == {"mqtt", "sensors"}
        assert app.config.device_name == old_name
    finally:
        assert app.shutdown()


@pytest.mark.parametrize("code,message,expected,state", [
    ("home_assistant_error", "Configure this Direct Windows Bridge in Home Assistant first", "bridge_not_configured", ConnectionState.CONFIGURATION_ERROR),
    ("unauthorized", "Unauthorized", "unauthorized", ConnectionState.AUTH_ERROR),
    ("unknown_command", "Unknown command", "integration_missing", ConnectionState.CONFIGURATION_ERROR),
    ("popup_unavailable", "", "popup_unavailable", ConnectionState.CONFIGURATION_ERROR),
])
def test_ha_retains_actual_configuration_error_instead_of_bad_token(code, message, expected, state):
    socket = Socket(handshake()[:2] + [{"id": 1, "type": "result", "success": False,
                                      "error": {"code": code, "message": message}}])
    transport = ha_transport(socket)
    transport._epoch = transport.machine.begin()
    transport._run()
    assert transport.machine.status.state == state
    assert transport.machine.status.error == expected
    assert socket.closed


def test_bad_token_is_distinct_from_bridge_configuration():
    transport = ha_transport(Socket([{"type": "auth_required"}, {"type": "auth_invalid"}]))
    transport._epoch = transport.machine.begin()
    transport._run()
    assert transport.machine.status.state == ConnectionState.AUTH_ERROR
    assert transport.machine.status.error == "authentication"


@pytest.mark.parametrize("code", ["bridge_busy", "bridge_not_ready", "unknown_error"])
def test_temporary_ha_failures_remain_retryable(code):
    error = response_error({"error": {"code": code, "message": "untrusted secret text"}})
    assert isinstance(error, HomeAssistantConnectionError)
    assert not error.authentication and not error.configuration
    assert "untrusted" not in str(error)


def test_overview_contains_connections_and_diagnostics_has_history(tmp_path):
    qt = qt_app()
    config = AppConfig(auto_connect=False, overlay_enabled=True, home_assistant=HomeAssistantConfig(enabled=True, url="http://ha.local", token="secret-value"))
    app = runtime(config)
    app.events.emit("connection.changed", ConnectionStatus("home_assistant", ConnectionState.CONFIGURATION_ERROR, 1, "bridge_not_configured"))
    window = DesktopWindow(app)
    try:
        window.resize(1000, 760)
        window.show()
        qt.processEvents()
        assert window.pages.count() == 6
        assert not any(window.navigation.item(i).text() == "Połączenia" for i in range(window.navigation.count()))
        assert window.pages.widget(Page.OVERVIEW).isAncestorOf(window._fields["home_assistant.url"])
        assert "Dodaj ten komputer" in window.summary.text()
        assert "działa" not in window.summary.text()
        assert "Dodaj ten komputer" in window.logs.toPlainText()
        assert "secret-value" not in window.logs.toPlainText()
        assert window.grab().save(str(tmp_path / "overview.png"))
        window.navigation.setCurrentRow(Page.DIAGNOSTICS)
        for _ in range(10):
            QTest.qWait(20)
            qt.processEvents()
        assert "RAM: —" not in window.resource_usage.text()
        assert window.logs.height() >= 180 and window._page_timer.isActive()
        assert window.diagnostic_status.text()
        assert window.grab().save(str(tmp_path / "diagnostics.png"))
    finally:
        window._force_close = True
        window.close()
        assert app.shutdown()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_media_example_reads_windows_off_gui_thread_and_hides_lifetime():
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False))
    read_on = []
    import base64

    from ha_windows_bridge.overlays.examples import media_artwork
    artwork = MediaArtwork(base64.b64decode(media_artwork().split(",")[1]), "image/png")
    snapshot = MediaSnapshot(state="playing", title="Current song", artist="Actual artist",
                             source_app="Spotify.exe", duration=120, position=30, artwork=artwork)
    app.media.snapshot = lambda: read_on.append(threading.current_thread().ident) or snapshot
    overlays = OverlayService(app)
    try:
        overlays.example("media")
        drain(app)
        qt.processEvents()
        window = overlays.windows["example-media"]
        assert window.title.text() == "Current song"
        assert window.source.text() == "Spotify.exe"
        assert window.media_time.text() == "0:30 / 2:00"
        assert not window._media_image.isNull()
        assert window.lifetime.isHidden()
        assert not overlays.engine.visible["example-media"].options["show_lifetime"]
        assert read_on and read_on[0] != threading.current_thread().ident
    finally:
        overlays.close()
        assert app.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_empty_media_reports_no_session_instead_of_made_up_song():
    app = runtime(AppConfig(auto_connect=False))
    app.media.snapshot = lambda: MediaSnapshot()
    errors, results = [], []
    app.events.subscribe("application.error", lambda event: errors.append(event.data))
    app.events.subscribe("overlay.media_example", lambda event: results.append(event.data))
    try:
        assert app.request_media_example(1)
        drain(app)
        assert not results and "Uruchom odtwarzanie" in errors[0]
    finally:
        assert app.shutdown()


def test_clear_cancels_pending_media_preview():
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False))
    app.media.snapshot = lambda: MediaSnapshot(source_app="Player", title="Song")
    overlays = OverlayService(app)
    try:
        overlays.example("media")
        overlays._event(Event("overlay.clear"))
        drain(app)
        qt.processEvents()
        assert not overlays.windows
    finally:
        overlays.close()
        assert app.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_direct_does_not_connect_when_remote_overlays_are_disabled():
    qt = qt_app()
    app = runtime(AppConfig(auto_connect=False, overlay_enabled=False,
        home_assistant=HomeAssistantConfig(enabled=True, url="http://ha.local", token="token")))
    window = DesktopWindow(app)
    try:
        qt.processEvents()
        assert "home_assistant" not in {service.name for service in app.states.snapshot()}
        assert "Nakładki wyłączone" in window.summary.text()
        assert not app.config.overlay_enabled
    finally:
        window._force_close = True
        window.close()
        assert app.shutdown()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
