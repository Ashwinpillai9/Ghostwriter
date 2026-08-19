"""Measures your microphone and tells you whether hands-free dictation will stop on its own.

Records your room in silence, then while you speak, and compares the two the way the endpointer
does. Prints a verdict and, if the current settings won't work, the value to use.

    .venv\\Scripts\\python.exe scripts\\mic_check.py
    .venv\\Scripts\\python.exe scripts\\mic_check.py --seconds 10

The measurement itself lives in `ghostwriter/roomcheck.py`, shared with the settings window's
Mic tab so the two cannot disagree about whether a room is usable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostwriter import config as config_module  # noqa: E402
from ghostwriter import roomcheck  # noqa: E402
from ghostwriter.audio import resolve_device  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6.0, help="length of each sample")
    args = parser.parse_args()

    cfg = config_module.load()
    threshold = cfg.get("endpoint.vad_threshold", 0.5)
    timeout = cfg.get("endpoint.silence_timeout_sec", 1.2)
    device = resolve_device(cfg.get("audio.device", ""))

    name = sd.query_devices(device, "input")["name"] if device is not None else "system default"
    print(f"Mic: {name}")
    print(f"Settings: vad_threshold={threshold}  silence_timeout_sec={timeout}\n")

    printed = {"phase": None}

    def on_phase(phase: str, remaining: int) -> None:
        if printed["phase"] != phase:
            printed["phase"] = phase
            if phase == "quiet":
                print(f"1/2  Stay SILENT for {args.seconds:.0f}s — measuring your room.")
            else:
                print(f"\n\n2/2  Now TALK for {args.seconds:.0f}s — say anything.")
        print(f"  {remaining}... ", end="", flush=True)

    report = roomcheck.measure(
        seconds=args.seconds,
        device=device,
        threshold=threshold,
        silence_timeout=timeout,
        on_phase=on_phase,
    )

    print("\n\n--- results ---")
    print(f"  silent room : median speech score {report.quiet_median:.3f}, "
          f"{report.quiet_hit * 100:.0f}% of frames counted as speech")
    print(f"  you talking : median speech score {report.talking_median:.3f}, "
          f"{report.talking_hit * 100:.0f}% of frames counted as speech")
    print(f"  longest quiet stretch: {report.longest_quiet:.2f}s "
          f"(needs {report.needed_quiet:.2f}s to stop)")
    print(f"  loudness: room {report.quiet_rms:.4f}, speech {report.talking_rms:.4f} "
          f"({report.headroom:.0f}x headroom)\n")

    if report.ok:
        print("VERDICT: fine. Dictation will stop on its own when you stop talking.")
    else:
        print(f"VERDICT: {report.message}")

    for key, value in report.suggestions.items():
        current = cfg.get(key)
        if value != current:
            print(f"  Set {key} = {value} in config.toml (currently {current}).")

    if not report.suggestions and not report.ok:
        print(f"  Options: a headset mic, a quieter input, or the stop key "
              f"({cfg.get('endpoint.stop_key')}).")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
