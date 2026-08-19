"""Reads and writes `config.toml` without destroying it.

`config.py`'s `load()` merges the file with built-in `DEFAULTS`. That is right for reading and
useless for writing: dumping the merged result back would flatten every default into the user's
file and delete every comment. This project treats those comments as user-facing documentation —
`config.toml` is the manual — so a settings UI that strips them would be a downgrade on the text
editor it replaces.

tomlkit parses into a document that remembers comments, ordering and whitespace, so setting one
value rewrites one line and leaves the rest byte-identical.

The store deliberately does *not* apply anything. Writing the file is how a setting is applied:
`ConfigWatcher` notices the save and `App.reload_config` does the rest. See the design notes in
`openspec/changes/add-settings-window/design.md`.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import tomlkit

log = logging.getLogger(__name__)


class ConfigStore:
    """A `config.toml` open for editing, preserving everything it does not change."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._document: tomlkit.TOMLDocument = tomlkit.document()
        self._signature: tuple[float, int] | None = None
        self._newline = os.linesep
        self.load()

    # --- reading ---------------------------------------------------------

    def load(self) -> None:
        """Re-read the file, discarding any uncommitted edits held in memory."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            self._document = tomlkit.document()
            self._signature = None
            return
        # Remember how this file ends its lines and normalise for tomlkit, which emits "\n".
        # Without this, saving a CRLF file rewrites every line in it — technically a valid
        # config, but it turns a one-key edit into a whole-file diff.
        self._newline = "\r\n" if b"\r\n" in raw else "\n"
        self._document = tomlkit.parse(raw.decode("utf-8").replace("\r\n", "\n"))
        self._signature = self._stat()

    def get(self, dotted: str, default: Any = None) -> Any:
        """Read a dotted path, e.g. `overlay.wave.enabled`.

        Returns raw file contents only — a key absent from the file reads as `default`, *not*
        as the application's built-in default. Callers that need the effective value should ask
        `ghostwriter.config` for it. Keeping the two apart is what lets the UI tell "unset" from
        "set to the same value as the default", which matters for keys whose absence means
        something, such as the wave colours deriving from the accent.
        """
        node: Any = self._document
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return _unwrap(node)

    def has(self, dotted: str) -> bool:
        sentinel = object()
        return self.get(dotted, sentinel) is not sentinel

    # --- writing ---------------------------------------------------------

    def set(self, dotted: str, value: Any) -> bool:
        """Set a dotted path, creating any missing tables along the way.

        Returns True when the document changed, so a caller can skip a pointless write — and
        with it the reload the file watcher would otherwise trigger.
        """
        parts = dotted.split(".")
        if not parts or not all(parts):
            raise ValueError(f"invalid config path {dotted!r}")

        table: Any = self._document
        for part in parts[:-1]:
            if part not in table:
                # A table the user never wrote. super() keeps it out of the inline-table form
                # tomlkit would otherwise choose, so it renders as a normal [section].
                table[part] = tomlkit.table(is_super_table=False)
            table = table[part]
            if not isinstance(table, dict):
                raise ValueError(f"{dotted!r} traverses a non-table at {part!r}")

        leaf = parts[-1]
        if leaf in table and _unwrap(table[leaf]) == value:
            return False
        table[leaf] = value
        return True

    def unset(self, dotted: str) -> bool:
        """Remove a key so it falls back to the application's default. True if it was there."""
        parts = dotted.split(".")
        table: Any = self._document
        for part in parts[:-1]:
            if not isinstance(table, dict) or part not in table:
                return False
            table = table[part]
        if not isinstance(table, dict) or parts[-1] not in table:
            return False
        del table[parts[-1]]
        return True

    def dumps(self) -> str:
        return tomlkit.dumps(self._document)

    def save(self) -> None:
        """Write the file atomically.

        A partial `config.toml` is worse than a stale one: the running app would read it, fail
        to parse, and report an error for something the user typed correctly. Writing to a
        temporary file in the same directory and replacing gives readers either the whole old
        file or the whole new one. Same directory because `os.replace` is only atomic within a
        filesystem.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = self.dumps().replace("\n", self._newline)
        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        self._signature = self._stat()

    # --- external edits --------------------------------------------------

    def _stat(self) -> tuple[float, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_mtime, stat.st_size

    def changed_on_disk(self) -> bool:
        """True when the file differs from what this store last read or wrote.

        The user may have `config.toml` open in an editor at the same time as the settings
        window. Saving what we loaded would silently discard their edit, so callers check this
        and re-`load()` rather than writing over the top.
        """
        return self._stat() != self._signature


def _unwrap(value: Any) -> Any:
    """Plain Python for a tomlkit node, so callers never handle its wrapper types.

    tomlkit hands back subclasses of str/int/list that carry formatting with them. Comparing or
    JSON-encoding those mostly works and occasionally does not, and letting them past this
    module means every consumer has to know about them.
    """
    if isinstance(value, dict):
        return {key: _unwrap(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item) for item in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value
