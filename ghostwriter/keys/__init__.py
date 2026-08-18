"""Keyboard input: a global hook, key state, and synthetic typing.

The platform seam. Everything above this package talks in key *names* ("right ctrl",
"ctrl+shift+d") and `KeyEvent`s; only the backend below knows about virtual-key codes or an
operating system. Porting to macOS means adding `macos.py` with the same five names — a
`CGEventTap` behind `Hook`, `CGEventSourceKeyState` behind `is_pressed`, `CGEventPost` behind
`send`/`write`/`release` — and one more branch here.

`codes.py` is deliberately platform-neutral and already carries the sided-modifier rules, so it
is shared rather than reimplemented per platform.
"""

from __future__ import annotations

import sys

from .codes import (
    MODIFIERS,
    SIDES,
    UnknownKey,
    chord_parts,
    covered_modifiers,
    matches,
    normalize,
    trigger,
    vk,
)

if sys.platform == "win32":
    from .windows import Hook, KeyEvent, is_pressed, release, send, write
else:  # pragma: no cover - the macOS backend does not exist yet
    raise ImportError(
        f"no keyboard backend for {sys.platform!r}; see ghostwriter/keys/__init__.py"
    )

__all__ = [
    "MODIFIERS",
    "SIDES",
    "Hook",
    "KeyEvent",
    "UnknownKey",
    "chord_parts",
    "covered_modifiers",
    "is_pressed",
    "matches",
    "normalize",
    "release",
    "send",
    "trigger",
    "vk",
    "write",
]
