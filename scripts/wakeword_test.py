"""Verifies the no-training wake word without a microphone.

Synthesizes each phrase with Windows SAPI, feeds the audio to the real detector, and reports
whether it fired. Positives must fire, negatives must not.

    .venv\\Scripts\\python.exe scripts\\wakeword_test.py
    .venv\\Scripts\\python.exe scripts\\wakeword_test.py --phrase "hey scribe"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostwriter import config as config_module  # noqa: E402
from ghostwriter.wakeword_whisper import WhisperWakeWordListener  # noqa: E402

POSITIVES = [
    "Hey ghost",
    "Hey ghost, open the config file",
    "Hey, ghost.",
]
NEGATIVES = [
    "Let me check the ghost writer branch",
    "The host is down again",
    "Run the test suite and commit",
]


def synthesize(text: str) -> np.ndarray:
    wav_path = Path(tempfile.gettempdir()) / "ghostwriter_wake.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav_path}'); $s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    with wave.open(str(wav_path), "rb") as handle:
        rate, frames = handle.getframerate(), handle.readframes(handle.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != 16000:  # crude linear resample, good enough for a smoke test
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    return audio


def main() -> int:
    cfg = config_module.load()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase", default=cfg.get("wakeword.phrase", "hey ghost"))
    args = parser.parse_args()

    listener = WhisperWakeWordListener(
        on_detect=lambda: None,
        phrase=args.phrase,
        aliases=cfg.get("wakeword.aliases", []),
        model_name=cfg.get("wakeword.model", "tiny.en"),
        device_type=cfg.get("wakeword.device", "cpu"),
        compute_type=cfg.get("wakeword.compute_type", "int8"),
        threshold=cfg.get("wakeword.threshold", 0.8),
    )
    listener.load()

    positives = [args.phrase.capitalize(), *POSITIVES] if args.phrase != "hey ghost" else POSITIVES
    failures = 0
    for text, expected in [(p, True) for p in positives] + [(n, False) for n in NEGATIVES]:
        fired = listener._heard(synthesize(text))  # noqa: SLF001 - this is its own test harness
        ok = fired == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  fired={fired!s:<5} {text!r}")

    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
