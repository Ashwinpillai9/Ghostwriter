"""Delivers text into whatever window currently has focus."""

from __future__ import annotations

import logging
import threading
import time

import pyperclip

from . import keys

log = logging.getLogger(__name__)


def _release_modifiers() -> None:
    """The hotkey chord may still be physically held; a stuck Shift would break the paste."""
    for key in keys.MODIFIERS:
        try:
            keys.release(key)
        except Exception:  # noqa: BLE001 - best effort, never block the paste
            pass


def paste_text(text: str, press_enter: bool = False, restore_delay: float = 0.35) -> None:
    """Put text on the clipboard, send Ctrl+V, then restore the previous clipboard."""
    if not text:
        return
    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001 - clipboard may hold non-text data
        previous = None

    pyperclip.copy(text)
    _release_modifiers()
    time.sleep(0.02)
    keys.send("ctrl+v")

    if press_enter:
        time.sleep(0.06)
        keys.send("enter")

    if previous is not None:
        # Restore off-thread so the target app has time to read the clipboard first.
        threading.Timer(restore_delay, _restore, args=(previous, text)).start()


def _restore(previous: str, ours: str) -> None:
    try:
        if pyperclip.paste() == ours:
            pyperclip.copy(previous)
    except Exception as exc:  # noqa: BLE001
        log.debug("clipboard restore failed: %s", exc)


def type_text(text: str, press_enter: bool = False) -> None:
    """Character-by-character fallback for windows that block paste."""
    if not text:
        return
    _release_modifiers()
    keys.write(text)
    if press_enter:
        keys.send("enter")
