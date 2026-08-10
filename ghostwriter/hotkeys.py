"""Global hotkeys: hold-to-talk chords plus a hands-free toggle.

`keyboard.add_hotkey` only reports the press edge, so hold-to-talk is implemented as
"suppressed press edge starts a watcher thread that polls the trigger key until released".
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import keyboard

log = logging.getLogger(__name__)

POLL_INTERVAL = 0.02

MODIFIERS = ("ctrl", "shift", "alt", "windows")


def trigger_key(chord: str) -> str:
    """The non-modifier key in a chord, i.e. the one whose release ends the hold."""
    return chord.split("+")[-1].strip().lower()


def chord_parts(chord: str) -> set[str]:
    return {part.strip().lower() for part in chord.split("+")}


def exclusively_pressed(chord: str) -> bool:
    """True when the chord is held and no modifier outside it is.

    `keyboard` fires a hotkey whenever its keys are all down, ignoring extra modifiers, so
    ctrl+shift+space would otherwise also trigger the ctrl+space hotkey.
    """
    parts = chord_parts(chord)
    for modifier in MODIFIERS:
        if modifier in parts:
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

    def register(self, hotkeys: dict) -> None:
        for mode, key in (("paste", "push_to_talk"), ("send", "push_to_talk_send")):
            chord = hotkeys.get(key)
            if chord:
                self._add_hold(chord, mode)

        toggle = hotkeys.get("toggle")
        if toggle:
            self._registered.append(
                keyboard.add_hotkey(toggle, self._safe(self.on_toggle), suppress=True)
            )

        cancel = hotkeys.get("cancel")
        if cancel:
            # Not suppressed: Esc must keep working normally everywhere else.
            self._registered.append(keyboard.add_hotkey(cancel, self._safe(self.on_cancel)))

    def _add_hold(self, chord: str, mode: str) -> None:
        key = trigger_key(chord)

        def pressed() -> None:
            if not exclusively_pressed(chord):
                return
            with self._lock:
                if mode in self._held:
                    return  # Key auto-repeat, not a new press.
                self._held.add(mode)
            self._safe(self.on_press, mode)()
            threading.Thread(target=self._watch_release, args=(mode, key), daemon=True).start()

        self._registered.append(keyboard.add_hotkey(chord, pressed, suppress=True))

    def _watch_release(self, mode: str, key: str) -> None:
        released = threading.Event()
        while not released.wait(POLL_INTERVAL):
            try:
                if not keyboard.is_pressed(key):
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
