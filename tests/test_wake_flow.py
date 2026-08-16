"""Exercises the wake-word utterance flow with the microphone, GPU and clipboard stubbed."""

import threading
import time

import numpy as np
import pytest

from ghostwriter import app as app_module


class FakeRecorder:
    """Stands in for the real Recorder: scripted loudness, no audio device."""

    def __init__(self):
        self.sample_rate = 16000
        self.level = 0.0
        self.recording = False
        self.started = 0

    def start(self):
        self.recording = True
        self.started += 1

    def stop(self):
        self.recording = False
        return np.zeros(16000, dtype=np.float32)


class FakeWake:
    def __init__(self):
        self.paused = 0
        self.resumed = 0
        self.model_name = "hey_ghost"
        self.listening = True

    def pause(self):
        self.paused += 1

    def resume(self):
        self.resumed += 1

    def stop(self):
        self.listening = False


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "beep", lambda kind: None)
    monkeypatch.setattr(app_module.keyboard, "add_hotkey", lambda *a, **k: object())
    monkeypatch.setattr(app_module.keyboard, "remove_hotkey", lambda *a, **k: None)

    application = app_module.App.__new__(app_module.App)
    application.cfg = app_module.config_module.load(tmp_path / "missing.toml")
    application.sounds = False
    application.min_duration = 0.0
    application.recorder = FakeRecorder()
    application.wake = FakeWake()
    application.overlay = type("O", (), {"set_state": lambda self, *a: None})()
    application.jobs = app_module.queue.Queue()
    application.toggle_active = False
    application.cancelled = False
    application.wake_active = False
    application._stop_requested = False
    application._stop_key_handle = None
    application.endpointer = app_module.SilenceEndpointer(
        level_source=lambda: application.recorder.level,
        silence_timeout=0.1,
        threshold=0.01,
        min_speech=0.02,
        lead_in=0.3,
        max_duration=5.0,
    )
    return application


def test_wake_records_then_queues_a_job(wired):
    wired.recorder.level = 0.5  # Speaking.

    def go_quiet():
        time.sleep(0.15)
        wired.recorder.level = 0.0

    threading.Thread(target=go_quiet, daemon=True).start()
    wired._wake_utterance()

    assert wired.recorder.started == 1
    assert wired.wake.paused == 1, "listener must release the mic while recording"
    assert wired.wake.resumed == 1, "listener must reclaim the mic afterwards"
    assert not wired.jobs.empty(), "silence should end the utterance and queue a transcription"


def test_silence_after_wake_word_queues_nothing(wired):
    wired.recorder.level = 0.0  # You never spoke.
    wired._wake_utterance()

    assert wired.recorder.started == 1
    assert wired.jobs.empty()
    assert wired.wake.resumed == 1


def test_stop_key_transcribes_rather_than_cancelling(wired):
    wired.recorder.level = 0.5

    def press_stop():
        time.sleep(0.1)
        wired._stop_now()

    threading.Thread(target=press_stop, daemon=True).start()
    wired._wake_utterance()

    assert not wired.jobs.empty(), "the stop key must keep the audio, not discard it"


def test_wake_is_ignored_while_already_recording(wired):
    wired.recorder.recording = True
    wired.on_wake()
    time.sleep(0.05)
    assert wired.recorder.started == 0
