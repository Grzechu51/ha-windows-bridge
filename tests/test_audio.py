from __future__ import annotations

from ha_windows_bridge.audio import WindowsAudioService


def test_microphone_activity_uses_a_stable_internal_threshold_and_respects_mute() -> None:
    assert WindowsAudioService._microphone_signal_active([0.0, 0.007], False) is False
    assert WindowsAudioService._microphone_signal_active([0.008], False) is True
    assert WindowsAudioService._microphone_signal_active([0.5], True) is False
