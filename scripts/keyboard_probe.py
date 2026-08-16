"""Dumps every raw keyboard event, so a real physical keypress can be inspected.

Written to diagnose hotkeys that don't fire as expected. Synthesised presses do not reliably
reproduce what a real keypress sends (Right Alt's AltGr handling is the sharpest example), so
watching a real one is the only way to know what a given machine actually does.

    .venv\\Scripts\\python.exe scripts\\keyboard_probe.py
    .venv\\Scripts\\python.exe scripts\\keyboard_probe.py --seconds 15

Press the key in question a few times, alone and combined with other keys, then read the
output. What matters:

- **vk** is what bindings match on. Right Ctrl must show 163 (`VK_RCONTROL`) where Left Ctrl
  shows 162 — that difference is what lets "right ctrl" be bound on its own.
- **scan** is shown only for contrast: both Ctrls report 29, which is why matching on scan
  codes could never tell them apart.
- **inj** marks an injected (synthetic) event. Ghostwriter's own keystrokes are tagged and
  skipped by its bindings, so they should not appear as real presses here.

Paste the output back if a binding needs pointing at a different event.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ghostwriter import keys  # noqa: E402

WATCH = ("ctrl", "left ctrl", "right ctrl", "alt", "right alt", "shift", "windows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=12.0)
    args = parser.parse_args()

    print(f"Watching every keystroke for {args.seconds:.0f}s. Press the key you care about")
    print("a few times, on its own and combined with other keys held. Ctrl+C stops early.\n")
    print(f"{'t (s)':>7}  {'event':<5} {'vk':>4} {'scan':>6}  {'ext':<3} {'inj':<3} name")
    print("-" * 62)

    started = time.perf_counter()
    last_summary = [0.0]

    def on_event(event: keys.KeyEvent) -> bool:
        elapsed = time.perf_counter() - started
        name = _name_for(event.vk)
        print(
            f"{elapsed:7.3f}  {'down' if event.down else 'up':<5} {event.vk:>4} "
            f"{event.scan:>6}  {'yes' if event.extended else '-':<3} "
            f"{'yes' if event.injected else '-':<3} {name}"
        )
        if elapsed - last_summary[0] > 0.05:
            held = [n for n in WATCH if keys.is_pressed(n)]
            if held:
                print(f"         held: {', '.join(held)}")
            last_summary[0] = elapsed
        return True  # Never swallow anything; this is a read-only probe.

    hook = keys.Hook(on_event)
    hook.start()
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        hook.stop()
    return 0


def _name_for(vk: int) -> str:
    """Best-effort reverse lookup, for reading the dump rather than for matching."""
    for name in (
        "right ctrl", "left ctrl", "right alt", "left alt", "right shift", "left shift",
        "left windows", "right windows", "esc", "space", "enter", "tab", "backspace",
        "delete", "up", "down", "left", "right",
    ):
        if keys.vk(name) == vk:
            return name
    if 0x30 <= vk <= 0x5A:
        return repr(chr(vk).lower())
    return f"vk {vk}"


if __name__ == "__main__":
    raise SystemExit(main())
