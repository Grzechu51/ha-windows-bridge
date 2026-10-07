"""Local editor commands fail closed until the cached privacy state is known."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication
from test_v2_desktop import qt_app

from ha_windows_bridge.application.application import Application
from ha_windows_bridge.config import AppConfig
from ha_windows_bridge.core.events import EventBus
from ha_windows_bridge.core.state import StateQuality
from ha_windows_bridge.overlays.service import OverlayService
from ha_windows_bridge.system_monitor import PcContext
from ha_windows_bridge.ui.shell import DesktopWindow


def pump(qt, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt.processEvents()
        if predicate():
            return True
        threading.Event().wait(0.005)
    return bool(predicate())


@pytest.fixture
def preview():
    qt = qt_app()
    raw_reads = []

    def raw_context():
        raw_reads.append(threading.get_ident())
        raise AssertionError("Preview must not start a provider or read Windows")

    app = Application(
        AppConfig(auto_connect=False, start_with_windows=False,
                  auto_check_updates=False, apps=[], overlay_enabled=True,
                  control_master_volume=False, reduced_motion=True),
        SimpleNamespace(save=lambda _config: None),
        SimpleNamespace(is_enabled=lambda: False, set_enabled=lambda _value: None),
        SimpleNamespace(list_audio_applications=lambda **_kwargs: []),
        SimpleNamespace(context_snapshot=raw_context),
        SimpleNamespace(reopen=lambda: None, close=lambda: None),
        object(), events=EventBus(),
    )
    window = DesktopWindow(app)
    overlays = OverlayService(app)
    results = []
    app.events.subscribe("command.result", lambda event: results.append(event.data))
    state = SimpleNamespace(qt=qt, app=app, window=window, overlays=overlays,
                            results=results, raw_reads=raw_reads)
    try:
        yield state
    finally:
        overlays.close()
        window._force_close = True
        window.close()
        window.deleteLater()
        assert app.shutdown()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def observe(preview, context):
    return preview.app.computer_state.observe_provider(
        "desktop_context", context, generation=preview.app._generation,
    )


def click(preview, action="show"):
    before = len(preview.results)
    if action == "show":
        preview.window._preview_overlay()
    else:
        preview.window._update_overlay()
    assert pump(preview.qt, lambda: len(preview.results) > before
                and preview.window._local_overlay_pending_id is None)
    return preview.results[-1]


@pytest.mark.parametrize("action", ["show", "update"])
@pytest.mark.parametrize("language, text", [
    ("pl", "Nie potwierdzono stanu prywatności pulpitu"),
    ("en", "Desktop privacy state is not confirmed"),
])
def test_existing_provider_without_observation_reports_readable_local_result(
    preview, action, language, text,
):
    preview.window.draft.language = language
    providers = preview.app._system_providers
    assert any(provider.source == "desktop_context" for provider in providers)
    assert preview.app.computer_state.snapshot().provider("desktop_context") is None
    responsive = threading.Event()
    QTimer.singleShot(0, responsive.set)

    result = click(preview, action)

    assert responsive.is_set()
    assert result.status == "failed" and result.code == "desktop_context_unavailable"
    assert text in preview.window.overlay_result.text()
    assert text in preview.window.onboarding_result.text()
    assert not preview.overlays.engine.visible and not preview.overlays.windows
    assert not preview.app.supervisor.active
    assert all(not provider.is_alive for provider in providers)
    assert not preview.raw_reads
    assert preview.app.diagnostics.counts()["errors"] == 0


def test_unavailable_cached_privacy_state_does_not_reuse_last_unlocked_value(preview):
    assert observe(preview, PcContext())
    assert preview.app.computer_state.fail_provider(
        "desktop_context", StateQuality.UNAVAILABLE, "temporarily unavailable",
        generation=preview.app._generation,
    )

    result = click(preview)

    assert result.code == "desktop_context_unavailable"
    assert not preview.overlays.windows and not preview.overlays.engine.visible
    assert not preview.raw_reads
    assert preview.app.diagnostics.counts()["errors"] == 0


def test_delayed_successful_observation_requires_explicit_retry_not_gui_wait(preview):
    publish = threading.Event()
    completed = threading.Event()

    def delayed_observation():
        if publish.wait(2):
            observe(preview, PcContext())
        completed.set()

    producer = threading.Thread(target=delayed_observation)
    producer.start()
    try:
        assert click(preview).code == "desktop_context_unavailable"
        assert not completed.is_set() and not preview.overlays.windows
        publish.set()
        assert pump(preview.qt, completed.is_set)
        # A later observation alone never replays an earlier failed command.
        assert not preview.overlays.windows and not preview.overlays.engine.visible
        assert click(preview).status == "succeeded"
        assert pump(preview.qt, lambda: bool(preview.overlays.windows))
        assert not preview.app.supervisor.active and not preview.raw_reads
    finally:
        publish.set()
        producer.join(2)
        assert not producer.is_alive()


def test_repeated_preview_is_retryable_without_starting_services(preview):
    for _ in range(3):
        assert click(preview).code == "desktop_context_unavailable"
    assert observe(preview, PcContext())
    for _ in range(3):
        assert click(preview).status == "succeeded"
        assert pump(preview.qt, lambda: bool(preview.overlays.windows))
        assert len(preview.overlays.engine.visible) == 1
    assert len({result.id for result in preview.results}) == 6
    assert not preview.app.supervisor.active and not preview.raw_reads
    assert preview.app.diagnostics.counts()["errors"] == 0


@pytest.mark.parametrize("context, allow_fullscreen, expected", [
    (PcContext(locked=True), False, "presentation_suppressed"),
    (PcContext(locked=True, fullscreen=True), True, "presentation_suppressed"),
    (PcContext(fullscreen=True), False, "presentation_suppressed"),
    (PcContext(fullscreen=True), True, ""),
])
def test_retry_respects_actual_lock_and_fullscreen_policy(
    preview, context, allow_fullscreen, expected,
):
    preview.app.config.overlay_allow_fullscreen = allow_fullscreen
    assert observe(preview, context)

    result = click(preview)

    assert result.code == expected
    if expected:
        assert result.status == "failed"
        assert not preview.overlays.engine.visible and not preview.overlays.windows
    else:
        assert result.status == "succeeded"
        assert pump(preview.qt, lambda: bool(preview.overlays.windows))
    assert not preview.raw_reads


def test_close_cancels_queued_preview_and_never_displays_after_late_sample(preview):
    entered, release = threading.Event(), threading.Event()

    def hold_queue():
        entered.set()
        release.wait(2)

    assert preview.app.router._worker.submit(hold_queue)
    assert entered.wait(2)
    preview.window._preview_overlay()
    assert preview.window._local_overlay_pending_id is not None
    assert not preview.results
    original_generation = preview.app._generation
    shutdown = []
    closer = threading.Thread(target=lambda: shutdown.append(preview.app.shutdown()))
    closer.start()
    try:
        assert pump(preview.qt, lambda: preview.app.router.closed
                    and preview.app._generation > original_generation)
        # A late result from the original generation cannot make shutdown live again.
        assert not preview.app.computer_state.observe_provider(
            "desktop_context", PcContext(), generation=original_generation,
        )
        release.set()
        closer.join(3)
        assert not closer.is_alive() and shutdown == [True]
        assert pump(preview.qt, lambda: bool(preview.results))
        assert preview.results[-1].status == "cancelled"
        assert preview.results[-1].code == "stopping"
        assert not preview.overlays.engine.visible and not preview.overlays.windows
        assert not preview.app.router._worker.is_alive
        assert not preview.raw_reads
    finally:
        release.set()
        closer.join(3)
