from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import comtypes
import psutil
import win32gui
import win32process
from pycaw.callbacks import (
    AudioEndpointVolumeCallback,
    AudioSessionNotification,
    MMNotificationClient,
)
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import (
    AudioUtilities,
    IAudioEndpointVolume,
    IAudioMeterInformation,
    ISimpleAudioVolume,
)

from .windows.com import com_apartment


@dataclass(frozen=True, slots=True)
class AudioApplication:
    process_name: str
    display_name: str
    executable_path: str = ""
    volume: float | None = None
    muted: bool | None = None
    session_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AudioSessionSnapshot:
    volume: float
    muted: bool
    session_count: int = 1
    session_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MicrophoneSnapshot:
    volume: float
    muted: bool
    active: bool
    peak: float = 0.0


@dataclass(frozen=True, slots=True)
class AudioOutputDevice:
    device_id: str
    name: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class AudioProviderSnapshot:
    """One complete, stable-identity observation from the Core Audio owner."""

    endpoint_id: str = ""
    master: AudioSessionSnapshot | None = None
    balance: float | None = None
    sessions: tuple[tuple[str, AudioSessionSnapshot], ...] = ()
    applications: tuple[AudioApplication, ...] = ()
    microphone: MicrophoneSnapshot | None = None
    outputs: tuple[AudioOutputDevice, ...] = ()
    active_process: str = ""
    errors: tuple[str, ...] = ()

    def session_map(self) -> dict[str, AudioSessionSnapshot]:
        return dict(self.sessions)


class _DeviceEvents(MMNotificationClient):
    def __init__(self, changed: Callable[..., None]) -> None:
        super().__init__()
        self.changed = changed

    def on_default_device_changed(self, *_args) -> None:
        self.changed()

    def on_device_added(self, *_args) -> None:
        self.changed()

    def on_device_removed(self, *_args) -> None:
        self.changed()

    def on_device_state_changed(self, *_args) -> None:
        self.changed()

    def on_property_value_changed(self, *_args) -> None:
        self.changed()


class _VolumeEvents(AudioEndpointVolumeCallback):
    def __init__(self, changed: Callable[..., None]) -> None:
        super().__init__()
        self.changed = changed

    def on_notify(self, *_args) -> None:
        self.changed()


class _SessionEvents(AudioSessionNotification):
    def __init__(self, changed: Callable[..., None]) -> None:
        super().__init__()
        self.changed = changed

    def on_session_created(self, _new_session) -> None:
        self.changed()


class _AudioEventSubscription:
    """Core Audio callback lifetime owned by the provider COM apartment."""

    def __init__(self, changed: Callable[..., None]) -> None:
        self.changed = changed
        self.enumerator = AudioUtilities.GetDeviceEnumerator()
        self.device_callback = _DeviceEvents(changed)
        self.enumerator.RegisterEndpointNotificationCallback(self.device_callback)
        self.session_manager = AudioUtilities.GetAudioSessionManager()
        self.session_callback = _SessionEvents(changed)
        self.session_manager.RegisterSessionNotification(self.session_callback)
        # Windows only starts session-created callbacks after first enumeration.
        self.session_manager.GetSessionEnumerator()
        self.endpoint_id = ""
        self.endpoint = None
        self.volume_callback = _VolumeEvents(changed)
        self.refresh_endpoint()

    def refresh_endpoint(self) -> None:
        try:
            device = AudioUtilities.GetSpeakers()
            endpoint_id = str(device.id)
            if endpoint_id == self.endpoint_id:
                return
            if self.endpoint is not None:
                self.endpoint.UnregisterControlChangeNotify(self.volume_callback)
            self.endpoint = device.EndpointVolume
            self.endpoint.RegisterControlChangeNotify(self.volume_callback)
            self.endpoint_id = endpoint_id
        except Exception:
            self.endpoint = None
            self.endpoint_id = ""

    def close(self) -> None:
        if self.endpoint is not None:
            with suppress(Exception):
                self.endpoint.UnregisterControlChangeNotify(self.volume_callback)
        with suppress(Exception):
            self.session_manager.UnregisterSessionNotification(self.session_callback)
        with suppress(Exception):
            self.enumerator.UnregisterEndpointNotificationCallback(self.device_callback)
        self.endpoint = None


@contextmanager
def com_scope() -> Iterator[None]:
    # Session-created callbacks require MTA. The shared helper balances a
    # newly-owned MTA and safely borrows an existing Qt STA when necessary.
    with com_apartment():
        yield


class WindowsAudioService:
    def subscribe(self, changed: Callable[..., None]) -> Callable[[], None]:
        subscription = _AudioEventSubscription(changed)

        def unsubscribe() -> None:
            subscription.close()

        # Provider refreshes this after a default endpoint event so volume
        # notifications move from the old endpoint to the new endpoint.
        unsubscribe.refresh = subscription.refresh_endpoint  # type: ignore[attr-defined]
        return unsubscribe

    def provider_snapshot(
        self,
        *,
        include_processes: tuple[str, ...] = (),
        include_sessions: bool = False,
        include_microphone: bool = False,
        include_outputs: bool = False,
    ) -> AudioProviderSnapshot:
        """Enumerate every requested audio capability once in one COM apartment."""

        errors: list[str] = []
        endpoint_id = ""
        master = None
        balance = None
        sessions: dict[str, list[AudioSessionSnapshot]] = {}
        applications: dict[str, AudioApplication] = {}
        microphone = None
        outputs: tuple[AudioOutputDevice, ...] = ()
        with com_scope():
            try:
                speakers = AudioUtilities.GetSpeakers()
                endpoint_id = str(speakers.id)
                endpoint = speakers.EndpointVolume
                master = AudioSessionSnapshot(
                    float(endpoint.GetMasterVolumeLevelScalar()),
                    bool(endpoint.GetMute()),
                )
                if int(endpoint.GetChannelCount()) >= 2:
                    left = float(endpoint.GetChannelVolumeLevelScalar(0))
                    right = float(endpoint.GetChannelVolumeLevelScalar(1))
                    peak = max(left, right)
                    balance = (
                        0.0
                        if peak <= 0.0001
                        else max(-1.0, min(1.0, (right - left) / peak))
                    )
            except Exception:
                errors.append("master")

            if include_sessions or include_processes:
                try:
                    enumerated = AudioUtilities.GetAllSessions()
                except Exception as exc:
                    raise RuntimeError("Core Audio session enumeration failed") from exc
                for index, session in enumerate(enumerated):
                    process = session.Process
                    if process is None:
                        continue
                    try:
                        process_name = process.name()
                        key = process_name.casefold()
                        state = self._read_session_state(session)
                        if state is None:
                            continue
                        stable_id = str(
                            getattr(session, "InstanceIdentifier", "")
                            or getattr(session, "Identifier", "")
                            or f"{int(getattr(session, 'ProcessId', 0) or 0)}:{index}"
                        )
                        state = AudioSessionSnapshot(
                            state.volume,
                            state.muted,
                            session_ids=(stable_id,),
                        )
                        sessions.setdefault(key, []).append(state)
                        try:
                            executable = process.exe()
                        except (psutil.Error, OSError):
                            executable = ""
                        applications.setdefault(
                            key,
                            AudioApplication(
                                process_name,
                                Path(executable).stem
                                or process_name.removesuffix(".exe"),
                                executable,
                            ),
                        )
                    except (psutil.Error, OSError):
                        continue

            grouped = {
                key: AudioSessionSnapshot(
                    volume=max(item.volume for item in values),
                    muted=all(item.muted for item in values),
                    session_count=len(values),
                    session_ids=tuple(
                        stable_id
                        for item in values
                        for stable_id in item.session_ids
                    ),
                )
                for key, values in sessions.items()
            }
            for key, state in grouped.items():
                item = applications[key]
                applications[key] = AudioApplication(
                    item.process_name,
                    item.display_name,
                    item.executable_path,
                    state.volume,
                    state.muted,
                    state.session_ids,
                )

            missing = {
                name.casefold()
                for name in include_processes
                if name.casefold() not in applications
            }
            if missing:
                for process in psutil.process_iter(["name", "exe"], ad_value=None):
                    info = process.info
                    name, executable = info.get("name") or "", info.get("exe") or ""
                    key = name.casefold()
                    if key in missing and executable:
                        applications[key] = AudioApplication(
                            name,
                            Path(executable).stem,
                            executable,
                        )
                        missing.remove(key)
                        if not missing:
                            break

            if include_microphone:
                try:
                    device = AudioUtilities.GetMicrophone()
                    endpoint_interface = device.Activate(
                        IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None
                    )
                    endpoint = endpoint_interface.QueryInterface(IAudioEndpointVolume)
                    meter_interface = device.Activate(
                        IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None
                    )
                    meter = meter_interface.QueryInterface(IAudioMeterInformation)
                    muted = bool(endpoint.GetMute())
                    peaks = [float(meter.GetPeakValue())]
                    microphone = MicrophoneSnapshot(
                        float(endpoint.GetMasterVolumeLevelScalar()),
                        muted,
                        self._microphone_signal_active(peaks, muted),
                        max(peaks, default=0.0),
                    )
                except Exception:
                    errors.append("microphone")

            if include_outputs:
                try:
                    devices = AudioUtilities.GetAllDevices(
                        EDataFlow.eRender.value,
                        DEVICE_STATE.ACTIVE.value,
                    )
                    outputs = tuple(
                        sorted(
                            (
                                AudioOutputDevice(
                                    device.id,
                                    device.FriendlyName or device.id,
                                    device.id == endpoint_id,
                                )
                                for device in devices
                            ),
                            key=lambda item: item.name.casefold(),
                        )
                    )
                except Exception:
                    errors.append("outputs")

        return AudioProviderSnapshot(
            endpoint_id=endpoint_id,
            master=master,
            balance=balance,
            sessions=tuple(sorted(grouped.items())),
            applications=tuple(
                sorted(applications.values(), key=lambda item: item.display_name.casefold())
            ),
            microphone=microphone,
            outputs=outputs,
            active_process=self.get_active_process_name() or "",
            errors=tuple(errors),
        )

    def get_master_snapshot(self) -> AudioSessionSnapshot | None:
        with com_scope():
            try:
                endpoint = AudioUtilities.GetSpeakers().EndpointVolume
                return AudioSessionSnapshot(
                    float(endpoint.GetMasterVolumeLevelScalar()),
                    bool(endpoint.GetMute()),
                )
            except Exception:
                return None

    def get_master_volume(self) -> float | None:
        snapshot = self.get_master_snapshot()
        return snapshot.volume if snapshot else None

    def set_master_volume(self, volume: float) -> bool:
        volume = max(0.0, min(1.0, volume))
        with com_scope():
            try:
                AudioUtilities.GetSpeakers().EndpointVolume.SetMasterVolumeLevelScalar(volume, None)
                return True
            except Exception:
                return False

    def get_master_mute(self) -> bool | None:
        snapshot = self.get_master_snapshot()
        return snapshot.muted if snapshot else None

    def set_master_mute(self, muted: bool) -> bool:
        with com_scope():
            try:
                AudioUtilities.GetSpeakers().EndpointVolume.SetMute(bool(muted), None)
                return True
            except Exception:
                return False

    def get_master_balance(self) -> float | None:
        """Return stereo balance from -1 (left) to +1 (right)."""
        with com_scope():
            try:
                endpoint = AudioUtilities.GetSpeakers().EndpointVolume
                if int(endpoint.GetChannelCount()) < 2:
                    return None
                left = float(endpoint.GetChannelVolumeLevelScalar(0))
                right = float(endpoint.GetChannelVolumeLevelScalar(1))
                peak = max(left, right)
                if peak <= 0.0001:
                    return 0.0
                return max(-1.0, min(1.0, (right - left) / peak))
            except Exception:
                return None

    def set_master_balance(self, balance: float) -> bool:
        balance = max(-1.0, min(1.0, balance))
        with com_scope():
            try:
                endpoint = AudioUtilities.GetSpeakers().EndpointVolume
                if int(endpoint.GetChannelCount()) < 2:
                    return False
                master = float(endpoint.GetMasterVolumeLevelScalar())
                left = master * (1.0 - max(0.0, balance))
                right = master * (1.0 + min(0.0, balance))
                endpoint.SetChannelVolumeLevelScalar(0, left, None)
                endpoint.SetChannelVolumeLevelScalar(1, right, None)
                return True
            except Exception:
                return False

    def get_microphone_snapshot(self) -> MicrophoneSnapshot | None:
        with com_scope():
            try:
                device = AudioUtilities.GetMicrophone()
                endpoint_interface = device.Activate(
                    IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None
                )
                endpoint = endpoint_interface.QueryInterface(IAudioEndpointVolume)
                meter_interface = device.Activate(
                    IAudioMeterInformation._iid_, comtypes.CLSCTX_ALL, None
                )
                meter = meter_interface.QueryInterface(IAudioMeterInformation)
                muted = bool(endpoint.GetMute())
                peaks = [float(meter.GetPeakValue())]
                for _ in range(2):
                    time.sleep(0.01)
                    peaks.append(float(meter.GetPeakValue()))
                return MicrophoneSnapshot(
                    float(endpoint.GetMasterVolumeLevelScalar()),
                    muted,
                    self._microphone_signal_active(peaks, muted),
                    max(peaks, default=0.0),
                )
            except Exception:
                return None

    @staticmethod
    def _microphone_signal_active(peaks: list[float], muted: bool) -> bool:
        return not muted and any(peak >= 0.008 for peak in peaks)

    def set_microphone_volume(self, volume: float) -> bool:
        return self._set_microphone_endpoint(volume=volume)

    def set_microphone_mute(self, muted: bool) -> bool:
        return self._set_microphone_endpoint(muted=muted)

    @staticmethod
    def _set_microphone_endpoint(volume: float | None = None, muted: bool | None = None) -> bool:
        with com_scope():
            try:
                device = AudioUtilities.GetMicrophone()
                interface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
                endpoint = interface.QueryInterface(IAudioEndpointVolume)
                if volume is not None:
                    endpoint.SetMasterVolumeLevelScalar(max(0.0, min(1.0, volume)), None)
                if muted is not None:
                    endpoint.SetMute(bool(muted), None)
                return True
            except Exception:
                return False

    def list_output_devices(self) -> list[AudioOutputDevice]:
        with com_scope():
            try:
                default_id = AudioUtilities.GetSpeakers().id
                devices = AudioUtilities.GetAllDevices(
                    EDataFlow.eRender.value,
                    DEVICE_STATE.ACTIVE.value,
                )
                return sorted(
                    (
                        AudioOutputDevice(
                            device.id, device.FriendlyName or device.id, device.id == default_id
                        )
                        for device in devices
                    ),
                    key=lambda item: item.name.lower(),
                )
            except Exception:
                return []

    def set_output_device(self, device_name_or_id: str) -> bool:
        target = device_name_or_id.casefold()
        with com_scope():
            try:
                devices = AudioUtilities.GetAllDevices(
                    EDataFlow.eRender.value,
                    DEVICE_STATE.ACTIVE.value,
                )
                device = next(
                    (
                        item
                        for item in devices
                        if item.id.casefold() == target
                        or (item.FriendlyName or "").casefold() == target
                    ),
                    None,
                )
                if device is None:
                    return False
                AudioUtilities.SetDefaultDevice(
                    device.id,
                    [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications],
                )
                return True
            except Exception:
                return False

    def list_audio_applications(self, *, include_processes=()) -> list[AudioApplication]:
        found: dict[str, AudioApplication] = {}
        with com_scope():
            for session in AudioUtilities.GetAllSessions():
                process = session.Process
                if process is None:
                    continue
                try:
                    process_name = process.name()
                    key = process_name.lower()
                    state = self._read_session_state(session)
                    try:
                        executable = process.exe()
                    except (psutil.Error, OSError):
                        executable = ""
                    display_name = Path(executable).stem or process_name.removesuffix(".exe")
                    if key not in found and state is not None:
                        found[key] = AudioApplication(
                            process_name,
                            display_name,
                            executable,
                            state.volume,
                            state.muted,
                        )
                except (psutil.Error, OSError):
                    continue
        # Configured programs may be running without an audio session yet. Resolve
        # only those names, so icons do not require playing sound or remote access.
        missing = {name.casefold() for name in include_processes} - found.keys()
        if missing:
            for process in psutil.process_iter(["name", "exe"], ad_value=None):
                info = process.info
                name, executable = info.get("name") or "", info.get("exe") or ""
                key = name.casefold()
                if key in missing and executable:
                    found[key] = AudioApplication(name, Path(executable).stem, executable)
                    missing.remove(key)
                    if not missing:
                        break
        return sorted(found.values(), key=lambda app: app.display_name.lower())

    def session_snapshot(self, process_names: list[str]) -> dict[str, AudioSessionSnapshot]:
        requested = {name.lower() for name in process_names}
        collected: dict[str, list[AudioSessionSnapshot]] = {}
        if not requested:
            return {}
        with com_scope():
            try:
                sessions = AudioUtilities.GetAllSessions()
            except Exception:
                return {}
            for session in sessions:
                process = session.Process
                if process is None:
                    continue
                try:
                    key = process.name().lower()
                except psutil.Error:
                    continue
                if key not in requested:
                    continue
                state = self._read_session_state(session)
                if state is not None:
                    collected.setdefault(key, []).append(state)
        return {
            key: AudioSessionSnapshot(
                volume=max(state.volume for state in states),
                muted=all(state.muted for state in states),
                session_count=len(states),
            )
            for key, states in collected.items()
        }

    @staticmethod
    def count_audio_sessions() -> int:
        """Return the number of process-backed Windows mixer sessions."""
        with com_scope():
            try:
                sessions = AudioUtilities.GetAllSessions()
            except Exception:
                return 0
            total = 0
            for session in sessions:
                process = session.Process
                if process is None:
                    continue
                try:
                    process.name()
                except psutil.Error:
                    continue
                if WindowsAudioService._read_session_state(session) is not None:
                    total += 1
            return total

    def volume_snapshot(self, process_names: list[str]) -> dict[str, float]:
        return {name: state.volume for name, state in self.session_snapshot(process_names).items()}

    def get_volume(self, process_name: str) -> float | None:
        return self.volume_snapshot([process_name]).get(process_name.lower())

    def get_mute(self, process_name: str) -> bool | None:
        snapshot = self.session_snapshot([process_name]).get(process_name.lower())
        return snapshot.muted if snapshot else None

    def set_volume(self, process_name: str, volume: float) -> bool:
        target = process_name.lower()
        volume = max(0.0, min(1.0, volume))
        found = False
        with com_scope():
            try:
                sessions = AudioUtilities.GetAllSessions()
            except Exception:
                return False
            for session in sessions:
                process = session.Process
                if process is None:
                    continue
                try:
                    if process.name().lower() != target:
                        continue
                    control = session._ctl.QueryInterface(ISimpleAudioVolume)
                    control.SetMasterVolume(volume, None)
                    found = True
                except (psutil.Error, OSError, COMError):
                    continue
                except (AttributeError, TypeError, ValueError):
                    continue
        return found

    def set_mute(self, process_name: str, muted: bool) -> bool:
        target = process_name.lower()
        found = False
        with com_scope():
            try:
                sessions = AudioUtilities.GetAllSessions()
            except Exception:
                return False
            for session in sessions:
                process = session.Process
                if process is None:
                    continue
                try:
                    if process.name().lower() != target:
                        continue
                    control = session._ctl.QueryInterface(ISimpleAudioVolume)
                    control.SetMute(bool(muted), None)
                    found = True
                except (psutil.Error, OSError, COMError):
                    continue
                except (AttributeError, TypeError, ValueError):
                    continue
        return found

    @staticmethod
    def get_active_process_name() -> str | None:
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name()
        except (psutil.Error, OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _read_session_state(session) -> AudioSessionSnapshot | None:
        try:
            control = session._ctl.QueryInterface(ISimpleAudioVolume)
            return AudioSessionSnapshot(
                float(control.GetMasterVolume()),
                bool(control.GetMute()),
            )
        except Exception:
            return None


try:
    from _ctypes import COMError
except ImportError:  # pragma: no cover - only relevant outside Windows
    COMError = OSError
