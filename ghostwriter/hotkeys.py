"""Global hotkeys: hold-to-talk chords plus a hands-free toggle.

`keyboard.add_hotkey` only reports the press edge, so hold-to-talk is implemented as
"suppressed press edge starts a watcher thread that polls the trigger key until released".
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import keyboard

log = logging.getLogger(__name__)

POLL_INTERVAL = 0.02

# A second tap within this long after the first tap's release arms the Right Ctrl hold.
# Anything slower is treated as two unrelated, ordinary keypresses.
DOUBLE_TAP_WINDOW = 0.4

MODIFIERS = ("ctrl", "shift", "alt", "windows")

# A side-specific name still holds the generic modifier down, so `is_pressed("alt")` is true
# while "right alt" is the trigger. Without this map the default right-alt binding would see
# alt as an *extra* modifier and refuse to fire.
SIDED = {
    "right alt": "alt",
    "left alt": "alt",
    "alt gr": "alt",
    "right ctrl": "ctrl",
    "left ctrl": "ctrl",
    "right shift": "shift",
    "left shift": "shift",
    "right windows": "windows",
    "left windows": "windows",
}


# `keyboard` resolves the name "right alt" to *both* Alt scan codes, because its name table
# only distinguishes the sides as "left menu"/"right menu". Binding the name with suppress=True
# would therefore swallow Left Alt too, killing Alt+Tab. These are the unambiguous names.
UNAMBIGUOUS = {
    "right alt": "right menu",
    "altgr": "right menu",
    "alt gr": "right menu",
    "left alt": "left menu",
}


# Right Ctrl cannot be bound through `add_hotkey` at all: Windows' low-level keyboard hook
# reports Left and Right Ctrl with the *same* raw scan code (29). The bit that actually tells
# them apart — the hook's extended-key flag — is used by this library only to compute
# `event.name`, never folded into the `scan_code` integer that `add_hotkey`, `is_pressed` and
# suppression all match against. Confirmed directly: `scripts/keyboard_probe.py` shows real
# Right Ctrl presses as `scan_code=29, name='right ctrl'`, identical in scan_code to Left Ctrl.
# `key_to_scan_codes("right ctrl")` claims otherwise (57373/57629 alongside 29), but those extra
# codes are synthesised from a WinAPI table-building pass, not from what a live keypress
# actually sends — a binding on them is dead on arrival, which is exactly the "still not
# working" this replaced. `event.name` is the only reliable signal, so this binds Right Ctrl
# with a raw `keyboard.hook()` and matches on name instead of going through `add_hotkey`.
RIGHT_CTRL_SPELLINGS = {"right ctrl", "right control", "rctrl"}


def resolve_key(name: str) -> str | int:
    """A key spec `keyboard` can bind to exactly one physical key.

    Side-specific keys become a scan code, since that is the only representation the library
    treats as unambiguous. Everything else is passed through as the name the user wrote.
    """
    name = name.strip().lower()
    canonical = UNAMBIGUOUS.get(name)
    if canonical is None:
        return name
    try:
        codes = keyboard.key_to_scan_codes(canonical)
    except Exception:  # noqa: BLE001 - unknown on this layout; the name is still worth a try
        return name
    return codes[0] if len(codes) == 1 else name


def resolve_chord(chord: str) -> tuple[str | int, ...]:
    """A chord as key specs `keyboard` reads as "all pressed together".

    A tuple rather than a list because `add_hotkey` uses the spec as a dict key.
    """
    return tuple(resolve_key(part) for part in chord.split("+"))


def trigger_key(chord: str) -> str | int:
    """The non-modifier key in a chord, i.e. the one whose release ends the hold."""
    return resolve_key(chord.split("+")[-1])


def chord_parts(chord: str) -> set[str]:
    return {part.strip().lower() for part in chord.split("+")}


def covered_modifiers(chord: str) -> set[str]:
    """Generic modifiers the chord itself accounts for, including via side-specific names."""
    parts = chord_parts(chord)
    covered = {part for part in parts if part in MODIFIERS}
    covered |= {SIDED[part] for part in parts if part in SIDED}
    # On non-US layouts AltGr *is* the right Alt key and reports as ctrl+alt. Treating ctrl as
    # covered keeps the default binding usable there; the cost is that ctrl+right-alt also
    # fires, which no editor binds anyway.
    if parts & {"right alt", "alt gr"}:
        covered.add("ctrl")
    return covered


def exclusively_pressed(chord: str) -> bool:
    """True when the chord is held and no modifier outside it is.

    `keyboard` fires a hotkey whenever its keys are all down, ignoring extra modifiers, so
    ctrl+shift+space would otherwise also trigger the ctrl+space hotkey.
    """
    covered = covered_modifiers(chord)
    for modifier in MODIFIERS:
        if modifier in covered:
            continue
        try:
            if keyboard.is_pressed(modifier):
                return False
        except Exception:  # noqa: BLE001 - treat hook errors as "no extra modifier"
            continue
    return True


class HotkeyManager:
    def __init__(
        self,
        on_press: Callable[[str], None],
        on_release: Callable[[str], None],
        on_toggle: Callable[[], None],
        on_cancel: Callable[[], None],
    ):
        self.on_press = on_press
        self.on_release = on_release
        self.on_toggle = on_toggle
        self.on_cancel = on_cancel
        self._held: set[str] = set()
        self._lock = threading.Lock()
        self._registered: list = []
        self._hooked: list = []
        self.suppress = True

    def register(self, hotkeys: dict) -> None:
        """Bind the configured chords.

        `hotkeys.suppress` decides whether a bound key still reaches the focused app. Suppressed
        is the better default — you do not want Right Alt opening menus while you dictate — but
        it takes the key away from every other program for as long as Ghostwriter runs, so it
        has to be switchable when that fights with something else.
        """
        self.suppress = bool(hotkeys.get("suppress", True))
        for mode, key in (("paste", "push_to_talk"), ("send", "push_to_talk_send")):
            chord = hotkeys.get(key)
            if chord:
                self._add_hold(chord, mode)

        toggle = hotkeys.get("toggle")
        if toggle:
            self._registered.append(
                keyboard.add_hotkey(
                    resolve_chord(toggle), self._safe(self.on_toggle), suppress=self.suppress
                )
            )

        cancel = hotkeys.get("cancel")
        if cancel:
            # Not suppressed: Esc must keep working normally everywhere else.
            self._registered.append(
                keyboard.add_hotkey(resolve_chord(cancel), self._safe(self.on_cancel))
            )

    def _add_hold(self, chord: str, mode: str) -> None:
        if chord.strip().lower() in RIGHT_CTRL_SPELLINGS:
            self._bind_right_ctrl_hold(chord, mode)
            return

        key = trigger_key(chord)

        def pressed() -> None:
            if not exclusively_pressed(chord):
                return
            with self._lock:
                if mode in self._held:
                    return  # Key auto-repeat, not a new press.
                self._held.add(mode)
            self._safe(self.on_press, mode)()
            threading.Thread(target=self._watch_release, args=(mode, [key]), daemon=True).start()

        self._registered.append(
            keyboard.add_hotkey(resolve_chord(chord), pressed, suppress=self.suppress)
        )

    def _bind_right_ctrl_hold(self, chord: str, mode: str) -> None:
        """Right Ctrl only, matched by `event.name`, and armed by a double-tap rather than a
        single press.

        Right Ctrl is also the key held for every Ctrl+C/Ctrl+V, so arming on the very first
        press-down would start dictation on every one of those. Only a *second* tap within
        DOUBLE_TAP_WINDOW of the first tap's release arms the hold; a lone tap, or an ordinary
        held Ctrl+<key> combo, is never suppressed and passes straight through to whatever app
        has focus.

        This hook fires for every keystroke system-wide, so it must return True (pass through)
        for anything that isn't Right Ctrl, or it would suppress all typing. Only the armed hold
        is suppressed, controlled by `self.suppress` exactly as `add_hotkey(..., suppress=...)`
        would be.
        """
        armed = False
        last_up: float | None = None

        def on_event(event) -> bool:
            nonlocal armed, last_up
            if event.name != "right ctrl":
                return True

            if event.event_type == keyboard.KEY_DOWN:
                if armed:
                    return not self.suppress  # Key auto-repeat, not a new press.
                tapped_again = (
                    last_up is not None and time.monotonic() - last_up <= DOUBLE_TAP_WINDOW
                )
                if not tapped_again or not exclusively_pressed(chord):
                    return True  # A lone tap, or an ordinary Ctrl+<key> press: leave it alone.
                armed = True
                with self._lock:
                    self._held.add(mode)
                threading.Thread(target=self._safe(self.on_press, mode), daemon=True).start()
                return not self.suppress

            if event.event_type == keyboard.KEY_UP:
                if not armed:
                    last_up = time.monotonic()  # May prime the next tap as a double-tap.
                    return True
                armed = False
                last_up = None  # Require a fresh double-tap before arming again.
                with self._lock:
                    self._held.discard(mode)
                threading.Thread(target=self._safe(self.on_release, mode), daemon=True).start()
                return not self.suppress

            return True

        self._hooked.append(keyboard.hook(on_event, suppress=True))

    def _watch_release(self, mode: str, keys: list) -> None:
        released = threading.Event()
        while not released.wait(POLL_INTERVAL):
            try:
                if not any(keyboard.is_pressed(key) for key in keys):
                    break
            except Exception:  # noqa: BLE001 - transient hook errors shouldn't strand the mode
                break
        with self._lock:
            self._held.discard(mode)
        self._safe(self.on_release, mode)()

    @staticmethod
    def _safe(fn: Callable, *args) -> Callable[[], None]:
        def wrapper() -> None:
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 - a callback error must not kill the hook thread
                log.exception("hotkey callback failed")

        return wrapper

    def unregister(self) -> None:
        for handle in self._registered:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:  # noqa: BLE001
                pass
        self._registered.clear()
        for handle in self._hooked:
            try:
                keyboard.unhook(handle)
            except Exception:  # noqa: BLE001
                pass
        self._hooked.clear()
