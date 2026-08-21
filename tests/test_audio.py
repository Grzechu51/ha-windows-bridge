from __future__ import annotations

from ha_windows_bridge.audio import WindowsAudioService


def test_microphone_activity_uses_low_peak_threshold_and_respects_mute() -> None:
    assert WindowsAudioService._microphone_signal_active([0.0, 0.0006], False) is True
    assert WindowsAudioService._microphone_signal_active([0.0, 0.0004], False) is False
    assert WindowsAudioService._microphone_signal_active([0.5], True) is False
