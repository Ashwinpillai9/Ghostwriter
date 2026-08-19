"""Watches config.toml and fires once a save has settled.

Editing the file and having nothing happen is the obvious way to be confused by a config, so a
save applies by itself; the tray's reload item is the manual fallback rather than the only
route.

Polling rather than a filesystem-notification API: this checks one file about once a second,
which is cheaper than it sounds and needs no new dependency, and the settle window below is
required either way.

The settle window is the part that matters. Editors do not write a file in one step — many
truncate then write, and some write to a temporary file and rename over the original — so a
naive "mtime changed, reload now" reads a half-written file and reports a syntax error for
something the user typed correctly. Waiting for the file to stop changing avoids that, and is
also what stops a reload firing on every keystroke of an editor that autosaves.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0
# How long the file must hold still before it counts as saved rather than mid-write.
SETTLE_SECONDS = 0.4


def signature(path: Path) -> tuple[float, int] | None:
    """(mtime, size), or None while the file is missing.

    Size is included because a fast editor can rewrite a file within a filesystem's mtime
    resolution; a length change catches what the timestamp misses. Missing is not an error:
    a rename-over-original briefly leaves nothing there.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime, stat.st_size


class ConfigWatcher:
    """Calls `on_change` after `path` is modified and then stops changing."""

    def __init__(
        self,
        path: Path,
        on_change: Callable[[], None],
        poll: float = POLL_SECONDS,
        settle: float = SETTLE_SECONDS,
    ):
        self.path = Path(path)
        self.on_change = on_change
        self.poll = poll
        self.settle = settle
        self._applied = signature(self.path)  # What the running app already reflects.
        self._seen: tuple[float, int] | None = None
        self._stable_for = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="config-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.poll):
            try:
                self.check(self.poll)
            except Exception:  # noqa: BLE001 - a watcher must never take the app down
                log.exception("config watcher failed")

    def check(self, elapsed: float) -> bool:
        """One poll. Returns True if a reload was triggered.

        Split out from the loop so the settle logic can be driven directly in tests instead of
        by sleeping through real time.
        """
        current = signature(self.path)
        if current is None or current == self._applied:
            self._seen = None
            self._stable_for = 0.0
            return False

        if current != self._seen:
            self._seen = current  # Still being written; start the settle window again.
            self._stable_for = 0.0
            return False

        self._stable_for += elapsed
        if self._stable_for < self.settle:
            return False

        # Mark it applied before the callback: a reload that raises should not be retried on
        # every poll, and the user gets the error once rather than once a second.
        self._applied = current
        self._seen = None
        self._stable_for = 0.0
        self.on_change()
        return True
