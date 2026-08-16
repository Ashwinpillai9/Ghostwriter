"""Dumps every raw keyboard event for a while, so a real physical keypress can be inspected.

Written to diagnose hotkeys that don't fire as expected: `keybd_event`/`SendInput`-simulated
presses do not reliably reproduce what a real keypress sends (Right Alt's AltGr handling is
the sharpest example), so the only way to know what a given machine actually does is to watch
a real keypress.

    .venv\\Scripts\\python.exe scripts\\keyboard_probe.py
    .venv\\Scripts\\python.exe scripts\\keyboard_probe.py --seconds 15

Press the key in question a few times, alone and combined with other keys, then read the
output. What matters:

- A clean press shows a "down" then an "up" with a stable `scan_code`, and nothing else.
- For Right Ctrl specifically: a real press should show `scan_code=57373` (sometimes 57629).
  If you see `scan_code=29` instead, that is Left Ctrl's own code — this machine's Right Ctrl
  is somehow reporting as Left Ctrl, or you pressed the wrong key.
- For Right Alt: a `scan_code=541` event named "alt gr" bracketing your press, or a press that
  produces no matching "down" at all, means the real event got swallowed by Windows' AltGr
  handling before this hook ever saw it.

Paste the output back so the hotkey binding can be pointed at the right event.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import keyboard  # noqa: E402

CHECK = ("ctrl", "alt", "shift", "windows", "alt gr")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=12.0)
    args = parser.parse_args()

    print(f"Watching every keystroke for {args.seconds:.0f}s. Press the key you care about")
    print("a few times, on its own and combined with other keys held. Ctrl+C stops early.\n")
    print(f"{'t (s)':>7}  {'event':<6} {'scan_code':>9}  name")
    print("-" * 50)

    started = time.perf_counter()
    last_summary = 0.0

    def on_event(event) -> None:
        nonlocal last_summary
        t = time.perf_counter() - started
        print(f"{t:7.3f}  {event.event_type:<6} {event.scan_code:>9}  {event.name!r}")
        if t - last_summary > 0.05:
            held = [name for name in CHECK if _safe_is_pressed(name)]
            if held:
                print(f"         is_pressed: {', '.join(held)}")
            last_summary = t

    keyboard.hook(on_event)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    return 0


def _safe_is_pressed(name: str) -> bool:
    try:
        return keyboard.is_pressed(name)
    except Exception:  # noqa: BLE001 - a name this script doesn't recognise just isn't held
        return False


if __name__ == "__main__":
    raise SystemExit(main())
