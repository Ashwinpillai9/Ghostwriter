"""Measures your microphone and tells you whether hands-free dictation will stop on its own.

Records your room in silence, then while you speak, and compares the two the way the
endpointer does. Prints a verdict and, if the current settings won't work, the value to use.

    .venv\\Scripts\\python.exe scripts\\mic_check.py
    .venv\\Scripts\\python.exe scripts\\mic_check.py --seconds 10
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostwriter import config as config_module  # noqa: E402
from ghostwriter.audio import resolve_device  # noqa: E402
from ghostwriter.endpoint import VAD_SAMPLES  # noqa: E402

RATE = 16000


def record(seconds: float, device) -> np.ndarray:
    frames: list[np.ndarray] = []
    with sd.InputStream(
        samplerate=RATE, channels=1, dtype="float32", device=device, blocksize=VAD_SAMPLES,
        callback=lambda indata, *_: frames.append(indata[:, 0].copy()),
    ):
        for remaining in range(int(seconds), 0, -1):
            print(f"  {remaining}... ", end="", flush=True)
            time.sleep(1)
    print()
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)


def speech_probability(model, audio: np.ndarray) -> np.ndarray:
    usable = len(audio) - len(audio) % VAD_SAMPLES
    if usable < VAD_SAMPLES:
        return np.zeros(1)
    return np.asarray(model(audio[:usable], num_samples=VAD_SAMPLES)).reshape(-1)


def longest_run(mask: np.ndarray, seconds_each: float) -> float:
    best = run = 0
    for flag in mask:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best * seconds_each


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6.0, help="length of each sample")
    args = parser.parse_args()

    cfg = config_module.load()
    threshold = cfg.get("endpoint.vad_threshold", 0.5)
    timeout = cfg.get("endpoint.silence_timeout_sec", 1.2)
    device = resolve_device(cfg.get("audio.device", ""))

    from faster_whisper.vad import get_vad_model

    model = get_vad_model()
    frame_sec = VAD_SAMPLES / RATE

    print(f"Mic: {sd.query_devices(device, 'input')['name'] if device is not None else 'system default'}")
    print(f"Settings: vad_threshold={threshold}  silence_timeout_sec={timeout}\n")

    print(f"1/2  Stay SILENT for {args.seconds:.0f}s — measuring your room.")
    quiet = speech_probability(model, record(args.seconds, device))
    print(f"\n2/2  Now TALK for {args.seconds:.0f}s — say anything.")
    talking = speech_probability(model, record(args.seconds, device))

    quiet_hit = float((quiet >= threshold).mean())
    talk_hit = float((talking >= threshold).mean())
    gap = longest_run(quiet < threshold, frame_sec)

    print("\n--- results ---")
    print(f"  silent room : median speech score {np.median(quiet):.3f}, "
          f"{quiet_hit * 100:.0f}% of frames counted as speech")
    print(f"  you talking : median speech score {np.median(talking):.3f}, "
          f"{talk_hit * 100:.0f}% of frames counted as speech")
    print(f"  longest quiet stretch: {gap:.2f}s (needs {timeout:.2f}s to stop)\n")

    if gap >= timeout and talk_hit > 0.4:
        print("VERDICT: fine. Dictation will stop on its own when you stop talking.")
        return 0

    if gap < timeout:
        # Pick a threshold above the room's noise but below the speaker's voice.
        for candidate in [round(x, 2) for x in np.arange(threshold, 0.96, 0.05)]:
            if longest_run(quiet < candidate, frame_sec) >= timeout * 1.5:
                if float((talking >= candidate).mean()) > 0.35:
                    print("VERDICT: your room is too noisy for the current threshold.")
                    print(f"  Set endpoint.vad_threshold = {candidate} in config.toml.")
                    return 1
                break
        print("VERDICT: this room's background is too close to speech to separate reliably.")
        print("  Options: use a headset mic, set audio.device to a quieter input, or use the")
        print(f"  stop key ({cfg.get('endpoint.stop_key')}) to end dictation yourself.")
        return 1

    print("VERDICT: your speech is scoring too low — the threshold is above your voice.")
    print(f"  Try lowering endpoint.vad_threshold below {np.median(talking):.2f}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
