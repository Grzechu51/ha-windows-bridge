from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import threading
import time
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass
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

    def close(self) -> None:
        with self._submission_lock:
            if not self._closing.is_set():
                self._closing.set()
                self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)


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

    async def _snapshot_async(self) -> MediaSnapshot:
        manager = await self._manager_async()
        session = manager.get_current_session()
        if session is None:
            return MediaSnapshot()

        playback = session.get_playback_info()
        controls = playback.controls
        timeline = session.get_timeline_properties()
        try:
            properties = await session.try_get_media_properties_async()
        except Exception:
            properties = None

        source_app = str(session.source_app_user_model_id or "")
        artwork = await self._artwork_async(properties, source_app)
        duration = max(_seconds(timeline.end_time), _seconds(timeline.max_seek_time))
        position = (
            min(_seconds(timeline.position), duration) if duration else _seconds(timeline.position)
        )
        return MediaSnapshot(
            state=_playback_state(playback.playback_status),
            title=str(getattr(properties, "title", "") or ""),
            artist=str(getattr(properties, "artist", "") or ""),
            album_title=str(getattr(properties, "album_title", "") or ""),
            album_artist=str(getattr(properties, "album_artist", "") or ""),
            source_app=source_app,
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

    async def _execute_async(self, action: str, value: float | None = None) -> bool:
        manager = await self._manager_async()
        session = manager.get_current_session()
        if session is None:
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

    def execute(self, action: str, value: float | None = None) -> bool:
        runner = self._ensure_runner()
        if runner is None:
            return False
        try:
            return bool(runner.call(self._execute_async(action, value)))
        except Exception:
            self._manager = None
            self.log.debug("Nie można wykonać komendy multimedialnej %s", action, exc_info=True)
            return False

    def close(self) -> None:
        with self._runner_lock:
            self._closed = True
            if self._runner is not None:
                self._runner.close()
                if not self._runner._thread.is_alive():
                    self._runner = None
                self._manager = None

    def reopen(self) -> None:
        with self._runner_lock:
            if self._runner is not None and self._runner._thread.is_alive():
                if self._closed:
                    raise RuntimeError("Previous media runner is still stopping")
                return
            self._runner = None
            self._closed = False
