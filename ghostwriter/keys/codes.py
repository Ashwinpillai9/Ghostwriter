"""Key names, virtual-key codes, and what counts as a match.

Virtual-key codes rather than scan codes, because that is the one representation Windows'
low-level hook reports *sided*: a real Right Ctrl press arrives as `VK_RCONTROL` (163) where
Left Ctrl arrives as `VK_LCONTROL` (162), while both share scan code 29. Matching on the vk is
what lets "right ctrl" be bound on its own — see the note atop `windows.py`.

Nothing here touches ctypes or Windows, so all of it is testable without a keyboard.
"""

from __future__ import annotations

# --- virtual-key codes -------------------------------------------------------

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

# The generic modifier a sided key also holds down. `is_pressed("ctrl")` must be true while
# Right Ctrl is held, and `exclusively_pressed` needs to know that "right ctrl" already
# accounts for "ctrl" rather than treating it as an extra modifier being held.
SIDES: dict[str, str] = {
    "left ctrl": "ctrl",
    "right ctrl": "ctrl",
    "left shift": "shift",
    "right shift": "shift",
    "left alt": "alt",
    "right alt": "alt",
    "alt gr": "alt",
    "left windows": "windows",
    "right windows": "windows",
}

MODIFIERS = ("ctrl", "shift", "alt", "windows")

_NAMES: dict[str, int] = {
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "shift": VK_SHIFT,
    "alt": VK_MENU,
    "menu": VK_MENU,
    "left ctrl": VK_LCONTROL,
    "right ctrl": VK_RCONTROL,
    "left control": VK_LCONTROL,
    "right control": VK_RCONTROL,
    "left shift": VK_LSHIFT,
    "right shift": VK_RSHIFT,
    "left alt": VK_LMENU,
    "right alt": VK_RMENU,
    # AltGr is Right Alt; Windows additionally synthesises a Left Ctrl alongside it on the
    # layouts that have it, which `covered_modifiers` accounts for.
    "alt gr": VK_RMENU,
    "altgr": VK_RMENU,
    "windows": VK_LWIN,
    "win": VK_LWIN,
    "left windows": VK_LWIN,
    "right windows": VK_RWIN,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "space": VK_SPACE,
    "enter": VK_RETURN,
    "return": VK_RETURN,
    "tab": VK_TAB,
    "backspace": VK_BACK,
    "delete": VK_DELETE,
    "del": VK_DELETE,
    "insert": VK_INSERT,
    "home": VK_HOME,
    "end": VK_END,
    "page up": VK_PRIOR,
    "page down": VK_NEXT,
    "caps lock": VK_CAPITAL,
    "up": VK_UP,
    "down": VK_DOWN,
    "left": VK_LEFT,
    "right": VK_RIGHT,
}

# a-z and 0-9 map to their ASCII code points as virtual keys; F1-F24 run from 0x70.
_NAMES.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
_NAMES.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
_NAMES.update({str(d): ord("0") + d for d in range(10)})
_NAMES.update({f"f{n}": 0x70 + n - 1 for n in range(1, 25)})

# Which sided codes satisfy a generic name. Bound the other way too, so a binding written as
# "right ctrl" is matched only by Right Ctrl.
_GENERIC_TO_SIDED: dict[int, tuple[int, ...]] = {
    VK_CONTROL: (VK_CONTROL, VK_LCONTROL, VK_RCONTROL),
    VK_SHIFT: (VK_SHIFT, VK_LSHIFT, VK_RSHIFT),
    VK_MENU: (VK_MENU, VK_LMENU, VK_RMENU),
}


class UnknownKey(ValueError):
    """Raised for a key spec that has no virtual-key code on this layout."""


def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def vk(name: str) -> int:
    """The virtual-key code for a key name."""
    key = normalize(name)
    if key not in _NAMES:
        raise UnknownKey(f"unknown key {name!r}")
    return _NAMES[key]


def chord_parts(chord: str) -> tuple[str, ...]:
    """A chord split into normalised key names, e.g. "Ctrl+Shift+D" -> ("ctrl","shift","d")."""
    return tuple(normalize(part) for part in chord.split("+") if part.strip())


def trigger(chord: str) -> str:
    """The non-modifier key whose release ends a hold — the last component."""
    parts = chord_parts(chord)
    if not parts:
        raise UnknownKey("empty chord")
    return parts[-1]


def matches(event_vk: int, name: str) -> bool:
    """True when a hook event's virtual key satisfies a bound key name.

    A generic name accepts either side; a sided name accepts only that side. This asymmetry is
    the whole point — binding "right ctrl" must not fire on Left Ctrl, while a chord written
    "ctrl+shift+d" must still work with whichever Ctrl the user happens to press.
    """
    wanted = vk(name)
    return event_vk in _GENERIC_TO_SIDED.get(wanted, (wanted,))


def covered_modifiers(chord: str) -> set[str]:
    """Generic modifiers the chord already accounts for, including via sided names.

    Without this, the default "right ctrl" binding would see ctrl as an *extra* modifier held
    down and refuse to fire.
    """
    parts = set(chord_parts(chord))
    covered = {part for part in parts if part in MODIFIERS}
    covered |= {SIDES[part] for part in parts if part in SIDES}
    # On non-US layouts AltGr *is* Right Alt and reports as ctrl+alt. Treating ctrl as covered
    # keeps a right-alt binding usable there; the cost is that ctrl+right-alt also fires, which
    # no editor binds anyway.
    if parts & {"right alt", "alt gr", "altgr"}:
        covered.add("ctrl")
    return covered
