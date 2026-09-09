from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import threading
import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Any

MAX_ARTWORK_BYTES = 1024 * 1024
ARTWORK_CACHE_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class MediaArtwork:
    data: bytes = b""
    content_type: str = ""
    digest: str = ""


@dataclass(frozen=True, slots=True)
class MediaCapabilities:
    play: bool = False
    pause: bool = False
    stop: bool = False
    next: bool = False
    previous: bool = False
    seek: bool = False

    def enabled_names(self) -> list[str]:
        return [
            name
            for name in ("play", "pause", "stop", "next", "previous", "seek")
            if getattr(self, name)
        ]


@dataclass(frozen=True, slots=True)
class MediaSnapshot:
    state: str = "idle"
    title: str = ""
    artist: str = ""
    album_title: str = ""
    album_artist: str = ""
    source_app: str = ""
    session_id: str = ""
    duration: float = 0.0
    position: float = 0.0
    capabilities: MediaCapabilities = MediaCapabilities()
    artwork: MediaArtwork = MediaArtwork()
    supported: bool = True
    error: str = ""


def _seconds(value: Any) -> float:
    try:
        return max(0.0, float(value.total_seconds()))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _playback_state(status: Any) -> str:
    name = getattr(status, "name", str(status)).rsplit(".", 1)[-1].lower()
    if name == "playing":
        return "playing"
    if name == "paused":
        return "paused"
    return "idle"


def friendly_media_source(value: Any) -> str:
    """Turn an executable or Windows AUMID into a short user-facing app name."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.casefold()
    known = (
        ("spotify", "Spotify"),
        ("chrome", "Chrome"),
        ("msedge", "Microsoft Edge"),
        ("microsoftedge", "Microsoft Edge"),
        ("firefox", "Firefox"),
        ("vlc", "VLC"),
        ("tidal", "TIDAL"),
        ("foobar2000", "foobar2000"),
    )
    for fragment, name in known:
        if fragment in lowered:
            return name
    candidate = raw.rsplit("!", 1)[-1]
    candidate = PureWindowsPath(candidate).name.removesuffix(".exe").removesuffix(".EXE")
    if candidate.casefold() == "app" and "!" in raw:
        package = raw.split("_", 1)[0].rsplit(".", 1)[-1]
        candidate = package or candidate
    return candidate or "Odtwarzacz Windows"


def _timeline_position(timeline, state, duration, now=None):
    position = _seconds(timeline.position)
    updated = getattr(timeline, "last_updated_time", None)
    if state == "playing" and isinstance(updated, datetime):
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        elapsed = ((now or datetime.now(UTC)) - updated).total_seconds()
        if 0 <= elapsed <= 86400:
            position += elapsed
    return min(position, duration) if duration else position


def _image_content_type(data: bytes, reported: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


async def _read_artwork(reference: Any) -> MediaArtwork:
    """Read a GSMTC thumbnail without exposing a local file or web server."""
    if reference is None:
        return MediaArtwork()

    from winrt.windows.storage.streams import DataReader

    stream = await reference.open_read_async()
    reader = None
    try:
        size = int(stream.size)
        if size <= 0 or size > MAX_ARTWORK_BYTES:
            return MediaArtwork()
        reader = DataReader(stream.get_input_stream_at(0))
        loaded = int(await reader.load_async(size))
        if loaded <= 0 or loaded > MAX_ARTWORK_BYTES:
            return MediaArtwork()
        output = bytearray(loaded)
        reader.read_bytes(output)
        data = bytes(output)
        content_type = _image_content_type(data, str(getattr(stream, "content_type", "") or ""))
        if content_type == "application/octet-stream":
            return MediaArtwork()
        return MediaArtwork(
            data=data,
            content_type=content_type,
            digest=hashlib.sha256(data).hexdigest(),
        )
    finally:
        if reader is not None:
            with suppress(Exception):
                reader.close()
        with suppress(Exception):
            stream.close()


class _AsyncRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._submission_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name="windows-media-control",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._ready.set)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def call(self, coroutine: Coroutine[Any, Any, Any], timeout: float = 3.0) -> Any:
        with self._submission_lock:
            if self._closing.is_set():
                coroutine.close()
                raise RuntimeError("Media runner is closed")
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise

    def schedule(self, callback: Callable[[], None]) -> bool:
        """Queue non-blocking callback work on the WinRT owner loop."""

        with self._submission_lock:
            if self._closing.is_set():
                return False
            self._loop.call_soon_threadsafe(callback)
            return True

    def close(self) -> bool:
        with self._submission_lock:
            if not self._closing.is_set():
                self._closing.set()
                self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        return not self._thread.is_alive()


class WindowsMediaService:
    """Reads and controls the active Windows System Media Transport session."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger(__name__)
        self._runner_lock = threading.RLock()
        self._closed = False
        self._runner: _AsyncRunner | None = None
        self._manager: Any = None
        self._import_error = ""
        self._artwork_key: tuple[str, ...] | None = None
        self._artwork_checked_at = 0.0
        self._artwork = MediaArtwork()
        self._change_callbacks: set[Callable[..., None]] = set()
        self._manager_event_tokens: list[
            tuple[str, object, Callable[..., None]]
        ] = []
        self._session_event_tokens: list[
            tuple[str, object, Callable[..., None]]
        ] = []
        self._event_session: Any = None
        self._lifecycle_token = 0
        self._session_key: tuple[str, int] | None = None
        self._session_identity = ""
        self._session_sequence = 0
        self._callback_error = ""

    def _ensure_runner(self) -> _AsyncRunner | None:
        with self._runner_lock:
            if self._closed:
                return None
            if self._import_error:
                return None
            if self._runner is None:
                try:
                    from winrt.windows.media.control import (  # noqa: F401
                        GlobalSystemMediaTransportControlsSessionManager,
                    )
                except Exception as exc:
                    self._import_error = str(exc)
                    self.log.warning("Windows Media Control jest niedostępne: %s", exc)
                    return None
                self._runner = _AsyncRunner()
            return self._runner

    async def _manager_async(self) -> Any:
        if self._manager is None:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )

            self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        return self._manager

    def subscribe(self, changed: Callable[..., None]) -> Callable[[], None]:
        runner = self._ensure_runner()
        if runner is None:
            return lambda: None
        runner.call(self._subscribe_async(changed))

        def unsubscribe() -> None:
            current = self._ensure_runner()
            if current is None:
                return
            current.call(self._unsubscribe_async(changed))

        return unsubscribe

    async def _subscribe_async(self, changed: Callable[..., None]) -> None:
        self._change_callbacks.add(changed)
        try:
            manager = await self._manager_async()
            if not self._manager_event_tokens:
                self._lifecycle_token += 1
                token = self._lifecycle_token
                def current_callback(
                    _sender,
                    _args,
                    current=token,
                ):
                    self._queue_owner_change(current, rebind=True)

                def sessions_callback(
                    _sender,
                    _args,
                    current=token,
                ):
                    self._queue_owner_change(current, rebind=True)
                registered: list[
                    tuple[str, object, Callable[..., None]]
                ] = []
                try:
                    registered.append(
                        (
                            "current",
                            manager.add_current_session_changed(current_callback),
                            current_callback,
                        )
                    )
                    registered.append(
                        (
                            "sessions",
                            manager.add_sessions_changed(sessions_callback),
                            sessions_callback,
                        )
                    )
                    self._manager_event_tokens = registered
                    self._rebind_session_events(
                        manager.get_current_session(),
                        token,
                    )
                except Exception:
                    self._manager_event_tokens = registered
                    self._remove_event_handlers()
                    raise
            self._callback_error = ""
        except Exception:
            self._change_callbacks.discard(changed)
            raise

    async def _unsubscribe_async(self, changed: Callable[..., None]) -> None:
        self._change_callbacks.discard(changed)
        if not self._change_callbacks:
            self._lifecycle_token += 1
            self._remove_event_handlers()

    def _queue_owner_change(self, token: int, *, rebind: bool) -> None:
        with self._runner_lock:
            if self._closed or token != self._lifecycle_token:
                return
            runner = self._runner
        if runner is not None:
            runner.schedule(lambda: self._owner_change(token, rebind=rebind))

    def _owner_change(self, token: int, *, rebind: bool) -> None:
        if (
            self._closed
            or token != self._lifecycle_token
            or not self._change_callbacks
        ):
            return
        try:
            if rebind:
                manager = self._manager
                if manager is None:
                    return
                self._rebind_session_events(
                    manager.get_current_session(),
                    token,
                )
            self._callback_error = ""
        except Exception as exc:
            self._callback_error = str(exc) or "callback_rebind_failed"
            self.log.exception("GSMTC callback rebind failed")
        self._notify_changed()

    def _notify_changed(self) -> None:
        for callback in tuple(self._change_callbacks):
            try:
                callback()
            except Exception:
                self.log.debug("GSMTC change callback failed", exc_info=True)

    def _rebind_session_events(self, session: Any, token: int) -> None:
        if session is self._event_session:
            return
        registered: list[tuple[str, object, Callable[..., None]]] = []
        if session is not None:
            def callback(
                _sender,
                _args,
                current=token,
            ):
                self._queue_owner_change(current, rebind=False)

            try:
                registered.append(
                    (
                        "media",
                        session.add_media_properties_changed(callback),
                        callback,
                    )
                )
                registered.append(
                    (
                        "playback",
                        session.add_playback_info_changed(callback),
                        callback,
                    )
                )
                registered.append(
                    (
                        "timeline",
                        session.add_timeline_properties_changed(callback),
                        callback,
                    )
                )
            except Exception:
                self._remove_session_tokens(session, registered)
                raise
        try:
            self._remove_session_handlers()
        except Exception:
            rollback_errors = self._remove_session_tokens(session, registered)
            if rollback_errors:
                self.log.error(
                    "GSMTC new-session rollback also failed"
                )
            raise
        self._event_session = session
        self._session_event_tokens = registered
        if session is not None:
            self._stable_session_identity(session)

    def _remove_session_handlers(self) -> None:
        session = self._event_session
        errors = self._remove_session_tokens(
            session,
            self._session_event_tokens,
        )
        self._session_event_tokens.clear()
        self._event_session = None
        if errors:
            raise RuntimeError("GSMTC session callback cleanup failed")

    @staticmethod
    def _remove_session_tokens(
        session: Any,
        tokens: list[tuple[str, object, Callable[..., None]]],
    ) -> list[BaseException]:
        errors: list[BaseException] = []
        for kind, token, _callback in tokens:
            if session is None:
                break
            try:
                if kind == "media":
                    session.remove_media_properties_changed(token)
                elif kind == "playback":
                    session.remove_playback_info_changed(token)
                else:
                    session.remove_timeline_properties_changed(token)
            except Exception as exc:
                errors.append(exc)
        return errors

    def _remove_event_handlers(self) -> None:
        errors: list[BaseException] = []
        try:
            self._remove_session_handlers()
        except Exception as exc:
            errors.append(exc)
        manager = self._manager
        for kind, token, _callback in self._manager_event_tokens:
            if manager is None:
                break
            try:
                if kind == "current":
                    manager.remove_current_session_changed(token)
                else:
                    manager.remove_sessions_changed(token)
            except Exception as exc:
                errors.append(exc)
        self._manager_event_tokens.clear()
        if errors:
            raise RuntimeError("GSMTC callback cleanup failed")

    @staticmethod
    def _native_session_key(session: Any) -> tuple[str, int]:
        source = str(getattr(session, "source_app_user_model_id", "") or "")
        try:
            native_hash = hash(session)
        except Exception:
            native_hash = id(session)
        return source, native_hash

    def _stable_session_identity(self, session: Any) -> str:
        key = self._native_session_key(session)
        if key != self._session_key:
            self._session_sequence += 1
            digest = hashlib.sha256(
                f"{key[0]}:{key[1]}:{self._session_sequence}".encode()
            ).hexdigest()[:24]
            self._session_key = key
            self._session_identity = f"gsmtc:{digest}"
        return self._session_identity

    async def _snapshot_async(self) -> MediaSnapshot:
        if self._callback_error:
            raise RuntimeError(self._callback_error)
        manager = await self._manager_async()
        session = manager.get_current_session()
        if session is None:
            self._session_key = None
            self._session_identity = ""
            return MediaSnapshot()

        playback = session.get_playback_info()
        controls = playback.controls
        timeline = session.get_timeline_properties()
        try:
            properties = await session.try_get_media_properties_async()
        except Exception:
            properties = None

        source_identifier = str(session.source_app_user_model_id or "")
        session_identity = self._stable_session_identity(session)
        artwork = await self._artwork_async(properties, source_identifier)
        duration = max(_seconds(timeline.end_time), _seconds(timeline.max_seek_time))
        state = _playback_state(playback.playback_status)
        position = _timeline_position(timeline, state, duration)
        return MediaSnapshot(
            state=state,
            title=str(getattr(properties, "title", "") or ""),
            artist=str(getattr(properties, "artist", "") or ""),
            album_title=str(getattr(properties, "album_title", "") or ""),
            album_artist=str(getattr(properties, "album_artist", "") or ""),
            source_app=friendly_media_source(source_identifier),
            session_id=session_identity,
            duration=round(duration, 3),
            position=round(position, 3),
            capabilities=MediaCapabilities(
                play=bool(controls.is_play_enabled or controls.is_play_pause_toggle_enabled),
                pause=bool(controls.is_pause_enabled or controls.is_play_pause_toggle_enabled),
                stop=bool(controls.is_stop_enabled),
                next=bool(controls.is_next_enabled),
                previous=bool(controls.is_previous_enabled),
                seek=bool(controls.is_playback_position_enabled),
            ),
            artwork=artwork,
        )

    async def _artwork_async(self, properties: Any, source_app: str) -> MediaArtwork:
        key = (
            source_app,
            str(getattr(properties, "title", "") or ""),
            str(getattr(properties, "artist", "") or ""),
            str(getattr(properties, "album_title", "") or ""),
        )
        now = time.monotonic()
        if self._artwork_key == key and now - self._artwork_checked_at < ARTWORK_CACHE_SECONDS:
            return self._artwork

        self._artwork_key = key
        self._artwork_checked_at = now
        try:
            self._artwork = await _read_artwork(getattr(properties, "thumbnail", None))
        except Exception:
            self.log.debug("Nie można odczytać miniatury multimediów Windows", exc_info=True)
            self._artwork = MediaArtwork()
        return self._artwork

    def snapshot(self) -> MediaSnapshot:
        runner = self._ensure_runner()
        if runner is None:
            return MediaSnapshot(supported=False, error=self._import_error or "WinRT unavailable")
        try:
            return runner.call(self._snapshot_async())
        except Exception as exc:
            self._manager = None
            self.log.debug("Nie można odczytać sesji multimedialnej Windows", exc_info=True)
            return MediaSnapshot(supported=False, error=str(exc))

    async def _execute_async(
        self,
        action: str,
        value: float | None = None,
        session_id: str = "",
    ) -> bool:
        manager = await self._manager_async()
        session = manager.get_current_session()
        if session is None:
            return False
        current_key = self._native_session_key(session)
        if (
            not session_id
            or current_key != self._session_key
            or self._session_identity != session_id
        ):
            return False
        actions = {
            "play": session.try_play_async,
            "pause": session.try_pause_async,
            "stop": session.try_stop_async,
            "next": session.try_skip_next_async,
            "previous": session.try_skip_previous_async,
        }
        if action == "seek":
            if value is None or value < 0:
                return False
            return bool(await session.try_change_playback_position_async(round(value * 10_000_000)))
        callback = actions.get(action)
        return bool(await callback()) if callback else False

    def execute(
        self,
        action: str,
        value: float | None = None,
        *,
        session_id: str = "",
    ) -> bool:
        runner = self._ensure_runner()
        if runner is None:
            return False
        try:
            return bool(runner.call(self._execute_async(action, value, session_id)))
        except Exception:
            self._manager = None
            self.log.debug("Nie można wykonać komendy multimedialnej %s", action, exc_info=True)
            return False

    def close(self) -> bool:
        with self._runner_lock:
            self._closed = True
            self._lifecycle_token += 1
            runner = self._runner
        stopped = True
        cleanup_ok = True
        if runner is not None:
            try:
                runner.call(self._close_async(), timeout=1.0)
            except Exception:
                cleanup_ok = False
                self.log.exception("GSMTC callback cleanup failed")
            stopped = runner.close()
            with self._runner_lock:
                if not runner._thread.is_alive():
                    self._runner = None
                self._manager = None
        return stopped and cleanup_ok

    async def _close_async(self) -> None:
        self._change_callbacks.clear()
        self._remove_event_handlers()

    def reopen(self) -> None:
        with self._runner_lock:
            if self._runner is not None and self._runner._thread.is_alive():
                if self._closed:
                    raise RuntimeError("Previous media runner is still stopping")
                return
            self._runner = None
            self._closed = False
