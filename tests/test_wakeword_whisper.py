"""The no-training wake word: phrase matching and burst detection.

No microphone and no model — the VAD and the decoder are both stubbed, so what is under test
is the logic that decides *when* to spend a decode and whether the result counts as a hit.
"""

import threading
import time

import numpy as np
import pytest

from ghostwriter import wakeword_whisper as ww
from ghostwriter.wakeword_whisper import matches_phrase, normalize

PHRASE = "hey ghost"
ALIASES = ["hey goast", "hey gost", "hey ghosts", "hey ghost writer"]


def heard(text: str) -> bool:
    return matches_phrase(text, PHRASE, ALIASES)


@pytest.mark.parametrize(
    "text",
    [
        "Hey, ghost.",
        "hey ghost",
        " HEY GHOST! ",
        "Hey ghosts.",  # An alias: Whisper pluralises it constantly.
        "hey goast",
        "Okay, hey ghost.",  # Leading noise still fires.
        "Hey gost!",
    ],
)
def test_variants_of_the_phrase_fire(text):
    assert heard(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "...",
        "Thanks for watching!",  # Whisper's favourite hallucination on near-silence.
        "let me check the ghost writer branch",
        "hey there",
        "the host is down",
    ],
)
def test_unrelated_speech_does_not_fire(text):
    assert not heard(text)


def test_fuzzy_window_tolerates_a_misspelt_phrase():
    # One wrong letter, never listed as an alias.
    assert heard("hey ghosty")


def test_normalize_strips_punctuation_and_case():
    assert normalize("Hey, Ghost!!") == "hey ghost"


class Driver:
    """Runs the real detection loop over a scripted speech/silence pattern."""

    def __init__(self, pattern: str, transcript: str = "hey ghost"):
        self.listener = ww.WhisperWakeWordListener(on_detect=self.fired, phrase=PHRASE)
        self.listener._speech_flags = self.flags  # noqa: SLF001
        self.listener._heard = lambda audio: bool(audio.size) and heard(transcript)  # noqa: SLF001
        self.flag_source = iter(pattern)
        self.detections = 0
        self.decodes = 0

    def fired(self):
        self.detections += 1

    def flags(self, chunk):  # noqa: ARG002 - the audio itself is irrelevant here
        self.decodes += 1
        return np.array(
            [next(self.flag_source, ".") == "s" for _ in range(ww.FRAMES_PER_CHUNK)]
        )

    def run(self, chunks: int) -> "Driver":
        listener = self.listener
        listener._running.set()  # noqa: SLF001
        worker = threading.Thread(target=listener._detect_loop, daemon=True)  # noqa: SLF001
        worker.start()
        for _ in range(chunks):
            listener._frames.put(np.zeros(ww.FRAME_SAMPLES, dtype=np.float32))  # noqa: SLF001
        deadline = time.time() + 5
        while not listener._frames.empty() and time.time() < deadline:  # noqa: SLF001
            time.sleep(0.01)
        time.sleep(0.05)
        listener._running.clear()  # noqa: SLF001
        worker.join(timeout=2)
        return self


# One character per 32 ms VAD frame: "s" is speech, "." is silence.
SPEECH = "s" * 16  # ~0.5s, comfortably past MIN_BURST_SEC
SILENCE = "." * 16  # ~0.5s, comfortably past HANGOVER_SEC


def test_a_speech_burst_followed_by_silence_fires_once():
    driver = Driver(SILENCE + SPEECH + SILENCE * 4).run(chunks=12)
    assert driver.detections == 1


def test_silence_alone_never_reaches_the_decoder():
    driver = Driver("." * 400).run(chunks=12)
    assert driver.detections == 0


def test_a_blip_too_short_to_be_a_phrase_is_ignored():
    # ~100 ms of noise, under MIN_BURST_SEC.
    driver = Driver(SILENCE + "sss" + SILENCE * 4).run(chunks=12)
    assert driver.detections == 0


def test_continuous_speech_still_gets_checked_periodically():
    # A long monologue never produces a silence boundary; MAX_BURST_SEC forces the check so
    # the phrase can be said mid-sentence.
    driver = Driver("s" * 400).run(chunks=12)
    assert driver.detections >= 1


def test_cooldown_suppresses_a_repeat_of_the_same_phrase():
    driver = Driver((SPEECH + SILENCE) * 3).run(chunks=12)
    assert driver.detections == 1, "the cooldown must swallow the immediate repeats"
