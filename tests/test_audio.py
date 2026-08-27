from __future__ import annotations

from ha_windows_bridge.audio import WindowsAudioService


def test_microphone_activity_uses_configurable_sensitivity_and_respects_mute() -> None:
    assert WindowsAudioService._microphone_signal_active([0.0, 0.0006], False, 100) is True
    assert WindowsAudioService._microphone_signal_active([0.0, 0.0004], False, 100) is False
    assert WindowsAudioService._microphone_signal_active([0.01], False, 100) is True
    assert WindowsAudioService._microphone_signal_active([0.01], False, 1) is False
    assert WindowsAudioService._microphone_signal_active([0.5], True, 100) is False
