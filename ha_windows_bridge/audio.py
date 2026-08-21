from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import comtypes
import psutil
import win32gui
import win32process
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
from pycaw.pycaw import (
    AudioUtilities,
    IAudioEndpointVolume,
    IAudioMeterInformation,
    ISimpleAudioVolume,
)


@dataclass(frozen=True, slots=True)
class AudioApplication:
    process_name: str
    display_name: str
    executable_path: str = ""
    volume: float | None = None
    muted: bool | None = None


@dataclass(frozen=True, slots=True)
class AudioSessionSnapshot:
    volume: float
    muted: bool


@dataclass(frozen=True, slots=True)
class MicrophoneSnapshot:
    volume: float
    muted: bool
    active: bool


@dataclass(frozen=True, slots=True)
class AudioOutputDevice:
    device_id: str
    name: str
    is_default: bool = False


@contextmanager
def com_scope() -> Iterator[None]:
    comtypes.CoInitialize()
    try:
        yield
    finally:
        comtypes.CoUninitialize()


class WindowsAudioService:
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
                )
            except Exception:
                return None

    @staticmethod
    def _microphone_signal_active(peaks: list[float], muted: bool) -> bool:
        return not muted and any(peak > 0.0005 for peak in peaks)

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
                        AudioOutputDevice(device.id, device.FriendlyName or device.id, device.id == default_id)
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

    def list_audio_applications(self) -> list[AudioApplication]:
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
                    executable = process.exe()
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
        return sorted(found.values(), key=lambda app: app.display_name.lower())

    def session_snapshot(self, process_names: list[str]) -> dict[str, AudioSessionSnapshot]:
        requested = {name.lower() for name in process_names}
        snapshot: dict[str, AudioSessionSnapshot] = {}
        if not requested:
            return snapshot
        with com_scope():
            try:
                sessions = AudioUtilities.GetAllSessions()
            except Exception:
                return snapshot
            for session in sessions:
                process = session.Process
                if process is None:
                    continue
                try:
                    key = process.name().lower()
                except psutil.Error:
                    continue
                if key not in requested or key in snapshot:
                    continue
                state = self._read_session_state(session)
                if state is not None:
                    snapshot[key] = state
        return snapshot

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
        except (psutil.Error, OSError):
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
