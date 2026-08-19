"""Global hotkeys: hold-to-talk chords, a hands-free toggle, and cancel.

All bindings share one low-level hook (`ghostwriter.keys`), which reports key *up* as well as
key down. That is the main simplification over the previous implementation: hold-to-talk used
to start a thread per press that polled `is_pressed` every 20 ms, because the old library only
surfaced the press edge. Releases now arrive as events like everything else.

Matching is on virtual-key codes, so "right ctrl" binds Right Ctrl and nothing else — see the
note atop `keys/windows.py` for why scan codes could not do this.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import keys

log = logging.getLogger(__name__)

# A second tap within this long after the first tap's release arms a gated hold. Anything
# slower is two unrelated, ordinary keypresses.
DOUBLE_TAP_WINDOW = 0.4

# Chords that arm only on a double-tap-then-hold. A bare Ctrl is held for every Ctrl+C and
# Ctrl+V, so arming on the first press-down would start dictation on all of them.
GATED = frozenset({"ctrl", "control", "left ctrl", "right ctrl", "left control", "right control"})


def exclusively_pressed(chord: str) -> bool:
    """True when no modifier outside the chord is held.

    Without this, ctrl+shift+space would also fire a ctrl+space binding, since every key of the
    narrower chord is genuinely down.
    """
    covered = keys.covered_modifiers(chord)
    return not any(
        modifier not in covered and keys.is_pressed(modifier) for modifier in keys.MODIFIERS
    )


def needs_double_tap(chord: str) -> bool:
    """True for a bare-modifier chord that would otherwise fire on ordinary shortcuts."""
    parts = keys.chord_parts(chord)
    return len(parts) == 1 and parts[0] in GATED


@dataclass
class Binding:
    """One configured hotkey and the live state of its hold."""

    chord: str
    kind: str  # "hold" | "toggle" | "cancel" | "tap"
    mode: str = ""
    suppress: bool = True
    gated: bool = False
    held: bool = False
    armed: bool = False
    last_up: float | None = None
    modifiers: tuple[str, ...] = field(default_factory=tuple)
    trigger: str = ""
    callback: Callable[[], None] | None = None

    @classmethod
    def build(
        cls,
        chord: str,
        kind: str,
        mode: str = "",
        suppress: bool = True,
        callback: Callable[[], None] | None = None,
    ) -> "Binding":
        parts = keys.chord_parts(chord)
        if not parts:
            raise keys.UnknownKey(f"empty chord {chord!r}")
        # Resolve every part now. Left to the hook callback, an unrecognised name would raise
        # on the first matching keystroke instead — inside the one place that must never throw.
        for part in parts:
            keys.vk(part)
        return cls(
            chord=chord,
            kind=kind,
            mode=mode,
            suppress=suppress,
            gated=needs_double_tap(chord),
            modifiers=parts[:-1],
            trigger=parts[-1],
            callback=callback,
        )

    def modifiers_held(self) -> bool:
        return all(keys.is_pressed(name) for name in self.modifiers)


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
        self.suppress = True
        self._bindings: list[Binding] = []
        self._lock = threading.Lock()
        self._hook: keys.Hook | None = None

    # --- registration ----------------------------------------------------

    def register(self, hotkeys: dict) -> None:
        """Bind the configured chords and install the hook.

        `hotkeys.suppress` decides whether a bound key still reaches the focused app.
        Suppressed is the better default — you do not want Right Alt opening menus while you
        dictate — but it takes the key from every other program for as long as Ghostwriter
        runs, so it has to be switchable.
        """
        self.suppress = bool(hotkeys.get("suppress", True))
        bindings: list[Binding] = []

        for mode, key in (("paste", "push_to_talk"), ("send", "push_to_talk_send")):
            chord = hotkeys.get(key)
            if chord:
                bindings.append(self._build(chord, "hold", mode=mode))

        toggle = hotkeys.get("toggle")
        if toggle:
            bindings.append(self._build(toggle, "toggle"))

        cancel = hotkeys.get("cancel")
        if cancel:
            # Never suppressed: Esc must keep working normally everywhere else.
            bindings.append(self._build(cancel, "cancel", suppress=False))

        with self._lock:
            # Transient bindings outlive a re-register: an utterance in flight keeps its stop
            # key even if the settings window rewrites the configured chords underneath it.
            temporary = [b for b in self._bindings if b.kind == "tap"]
            live = {(b.chord, b.kind): b for b in self._bindings}
            fresh = [b for b in bindings if b is not None]
            for binding in fresh:
                # Carry the hold state of an unchanged chord. Without this, re-registering
                # while a key is down loses `held`, so its release is ignored and a recording
                # started by it never stops.
                previous = live.get((binding.chord, binding.kind))
                if previous is not None:
                    binding.held = previous.held
                    binding.armed = previous.armed
                    binding.last_up = previous.last_up
            self._bindings = fresh + temporary
        if self._hook is None:
            self._hook = keys.Hook(self._on_event)
            self._hook.start()

    def _build(self, chord: str, kind: str, mode: str = "", suppress: bool = True, callback=None):
        try:
            return Binding.build(
                chord, kind, mode=mode, suppress=suppress and self.suppress, callback=callback
            )
        except keys.UnknownKey:
            log.warning("ignoring unknown hotkey %r", chord)
            return None

    def add_temporary(self, chord: str, callback: Callable[[], None]):
        """Bind a key for as long as one utterance lasts, then hand it straight back.

        Deliberately not suppressed: this is bound for the whole utterance, and swallowing a
        key system-wide for that long is indistinguishable from a broken keyboard.
        """
        binding = self._build(chord, "tap", suppress=False, callback=callback)
        if binding is None:
            return None
        with self._lock:
            self._bindings.append(binding)
        return binding

    def remove_temporary(self, binding) -> None:
        if binding is None:
            return
        with self._lock:
            if binding in self._bindings:
                self._bindings.remove(binding)

    def reregister(self, hotkeys: dict) -> None:
        """Swap in a new set of chords without tearing down the hook.

        Used when settings change at runtime; the hook itself is expensive to reinstall and
        Windows treats a re-hook as a fresh registration at the end of the chain.
        """
        self.register(hotkeys)

    def unregister(self) -> None:
        with self._lock:
            self._bindings = []
        if self._hook is not None:
            self._hook.stop()
            self._hook = None

    # --- dispatch --------------------------------------------------------

    def _on_event(self, event: keys.KeyEvent) -> bool:
        """Hook callback. Returns True to pass the key through to the focused app.

        Runs on the hook thread under Windows' ~300 ms budget, so it only compares and hands
        real work to other threads.
        """
        with self._lock:
            bindings = list(self._bindings)

        passthrough = True
        for binding in bindings:
            if not event.matches(binding.trigger):
                continue
            if not self._handle(binding, event):
                passthrough = False
        return passthrough

    def _handle(self, binding: Binding, event: keys.KeyEvent) -> bool:
        if event.down:
            return self._on_down(binding)
        return self._on_up(binding)

    def _on_down(self, binding: Binding) -> bool:
        if binding.kind == "hold" and binding.held:
            return not binding.suppress  # Key auto-repeat, not a new press.
        if not binding.modifiers_held() or not exclusively_pressed(binding.chord):
            return True

        if binding.kind == "cancel":
            self._fire(self.on_cancel)
            return True  # Esc always reaches the app too.

        if binding.kind == "tap":
            if binding.callback is not None:
                self._fire(binding.callback)
            return not binding.suppress

        if binding.kind == "toggle":
            self._fire(self.on_toggle)
            return not binding.suppress

        if binding.gated and not binding.armed:
            # A lone tap, or an ordinary Ctrl+<key> press: leave it alone entirely. Only a
            # second tap soon after the first tap's release starts dictation.
            recent = (
                binding.last_up is not None
                and time.monotonic() - binding.last_up <= DOUBLE_TAP_WINDOW
            )
            if not recent:
                return True
            binding.armed = True

        binding.held = True
        self._fire(self.on_press, binding.mode)
        return not binding.suppress

    def _on_up(self, binding: Binding) -> bool:
        if binding.kind != "hold":
            return True
        if not binding.held:
            if binding.gated:
                binding.last_up = time.monotonic()  # May prime the next tap as a double-tap.
            return True
        binding.held = False
        binding.armed = False
        binding.last_up = None  # Require a fresh double-tap before arming again.
        self._fire(self.on_release, binding.mode)
        return not binding.suppress

    def _fire(self, callback: Callable, *args) -> None:
        """Run a callback off the hook thread, so a slow one cannot get the hook torn down."""

        def run() -> None:
            try:
                callback(*args)
            except Exception:  # noqa: BLE001 - a callback error must not kill the hook
                log.exception("hotkey callback failed")

        threading.Thread(target=run, daemon=True).start()
