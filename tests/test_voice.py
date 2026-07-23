"""Voice: the VAD-based natural-pause recording loop. Deferred imports
inside the module (sounddevice, openwakeword's VAD) are faked via
sys.modules since neither has real audio hardware to talk to in CI."""

import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

import voice.voice as v
import config


@pytest.fixture(autouse=True)
def fast_vad_config(monkeypatch):
    monkeypatch.setitem(config.CONFIG, "voice_max_wait_seconds", 0.3)
    monkeypatch.setitem(config.CONFIG, "voice_silence_seconds", 0.3)
    monkeypatch.setitem(config.CONFIG, "voice_max_recording_seconds", 0.6)


def _install_fake_sounddevice(monkeypatch, read_fn):
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return read_fn(n)

    fake_sd = MagicMock()
    fake_sd.InputStream.return_value = FakeStream()
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    return fake_sd


def test_gives_up_quietly_when_nobody_speaks(monkeypatch):
    _install_fake_sounddevice(monkeypatch, lambda n: (np.zeros((n, 1), dtype="int16"), None))

    jarvis_voice = v.JarvisVoice.__new__(v.JarvisVoice)
    fake_vad = MagicMock()
    fake_vad.predict.return_value = 0.0
    monkeypatch.setattr(jarvis_voice, "_get_vad", lambda: fake_vad)

    result = jarvis_voice._listen_until_silence()
    assert result == ""


def test_stops_promptly_after_a_natural_pause(monkeypatch):
    call_count = [0]

    def read_fn(n):
        call_count[0] += 1
        return np.ones((n, 1), dtype="int16"), None

    _install_fake_sounddevice(monkeypatch, read_fn)

    jarvis_voice = v.JarvisVoice.__new__(v.JarvisVoice)
    scores = [0.9] * 5 + [0.1] * 15  # 5 speech frames, then silence
    fake_vad = MagicMock()
    fake_vad.predict.side_effect = lambda chunk: scores[call_count[0] - 1] if call_count[0] - 1 < len(scores) else 0.1
    monkeypatch.setattr(jarvis_voice, "_get_vad", lambda: fake_vad)
    monkeypatch.setattr(jarvis_voice, "_transcribe", lambda rec: "test transcript")

    result = jarvis_voice._listen_until_silence()

    assert result == "test transcript"
    # 5 speech frames + 10 silence frames (0.3s / 0.03s per frame) = 15
    assert call_count[0] == 15


def test_continuous_speech_hits_the_max_duration_safety_cap(monkeypatch):
    call_count = [0]

    def read_fn(n):
        call_count[0] += 1
        return np.ones((n, 1), dtype="int16"), None

    _install_fake_sounddevice(monkeypatch, read_fn)

    jarvis_voice = v.JarvisVoice.__new__(v.JarvisVoice)
    fake_vad = MagicMock()
    fake_vad.predict.return_value = 0.9  # never pauses
    monkeypatch.setattr(jarvis_voice, "_get_vad", lambda: fake_vad)
    monkeypatch.setattr(jarvis_voice, "_transcribe", lambda rec: "capped transcript")

    result = jarvis_voice._listen_until_silence()

    assert result == "capped transcript"
    # 0.6s max / 0.03s per frame = 20 frames exactly
    assert call_count[0] == 20


def test_listen_dispatches_to_fixed_duration_when_given(monkeypatch):
    jarvis_voice = v.JarvisVoice.__new__(v.JarvisVoice)
    calls = []
    monkeypatch.setattr(jarvis_voice, "_listen_fixed_duration", lambda d: calls.append(("fixed", d)) or "fixed result")
    monkeypatch.setattr(jarvis_voice, "_listen_until_silence", lambda: calls.append(("vad",)) or "vad result")

    assert jarvis_voice.listen() == "vad result"
    assert jarvis_voice.listen(duration=10) == "fixed result"
    assert calls == [("vad",), ("fixed", 10)]
