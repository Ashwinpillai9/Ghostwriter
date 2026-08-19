"""What the settings page is allowed to ask Python for.

Every method here is reachable from the page as `pywebview.api.<name>()`. Keep the surface
small and data-shaped: the page decides how things look, this decides what is true.

Reads report *effective* values — the file merged over the application's defaults — because
that is what the user is actually running. Writes go to the file only. The difference matters:
a key absent from `config.toml` still has a value, and writing it back explicitly just to
display it would fill the file with redundant lines the user never asked for.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import config as config_module
from .store import ConfigStore

log = logging.getLogger(__name__)

# Every key the window can edit, grouped the way the tabs are. Declared here rather than
# scattered through the page so that "what is editable" has one answer, and so the page cannot
# invent a path that writes somewhere unexpected.
EDITABLE: dict[str, tuple[str, ...]] = {
    "keys": (
        "hotkeys.push_to_talk",
        "hotkeys.push_to_talk_send",
        "hotkeys.toggle",
        "hotkeys.cancel",
        "hotkeys.suppress",
    ),
    "wakeword": (
        "wakeword.enabled",
        "wakeword.phrase",
        "wakeword.aliases",
        "wakeword.threshold",
        "wakeword.vad_threshold",
        "wakeword.cooldown_sec",
        "wakeword.model",
        "wakeword.device",
        "wakeword.compute_type",
    ),
    "model": (
        "model.name",
        "model.device",
        "model.compute_type",
        "model.language",
        "model.vocabulary",
    ),
    "stopping": (
        "endpoint.silence_timeout_sec",
        "endpoint.vad_threshold",
        "endpoint.silence_threshold",
        "endpoint.min_speech_sec",
        "endpoint.lead_in_sec",
        "endpoint.min_recording_sec",
        "endpoint.max_duration_sec",
        "endpoint.stop_key",
    ),
    "look": (
        "overlay.accent",
        "overlay.frame_ms",
        "overlay.activate_ms",
        "overlay.rings_ms",
        "overlay.hold_ms",
        "overlay.colors.idle",
        "overlay.colors.transcribing",
        "overlay.colors.done",
        "overlay.colors.error",
        "overlay.colors.moving",
        "overlay.wave.enabled",
        "overlay.wave.duration_ms",
        "overlay.wave.intensity",
        "overlay.wave.wavelength",
        "overlay.wave.halos",
        "overlay.wave.cores",
    ),
    "text": (
        "postprocess.remove_fillers",
        "postprocess.voice_commands",
        "postprocess.tidy_sentences",
        "postprocess.replacements",
        "output.paste",
        "output.clipboard_restore_delay",
        "output.sounds",
    ),
    "mic": (
        "audio.device",
        "audio.vad",
        "audio.min_duration_sec",
        "audio.max_duration_sec",
    ),
}

ALL_KEYS: tuple[str, ...] = tuple(key for group in EDITABLE.values() for key in group)


class Bridge:
    """The `pywebview.api` object."""

    def __init__(self, store: ConfigStore):
        self.store = store

    # --- reading ---------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Everything the page needs to render itself."""
        effective = config_module.load(self.store.path)
        return {
            "path": str(self.store.path),
            "values": {key: effective.get(key) for key in ALL_KEYS},
            # Which keys the file states outright. The page uses this to show a value as
            # inherited rather than chosen — an accent that merely matches the default is not
            # the same as one the user picked.
            "explicit": {key: self.store.has(key) for key in ALL_KEYS},
            "restartOnly": list(config_module.RESTART_ONLY),
            "groups": {name: list(keys) for name, keys in EDITABLE.items()},
        }

    def external_change(self) -> bool:
        """True when config.toml has been edited by something other than this window."""
        return self.store.changed_on_disk()

    def reload(self) -> dict[str, Any]:
        """Re-read the file, discarding anything uncommitted, and hand back fresh values."""
        self.store.load()
        return self.load()

    # --- writing ---------------------------------------------------------

    def set(self, path: str, value: Any) -> dict[str, Any]:
        return self.set_many({path: value})

    def set_many(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply a batch of edits and save once.

        Batched because each save triggers a reload in the running application; writing five
        keys individually would reload it five times. The page therefore sends a commit, not a
        keystroke.
        """
        rejected = [path for path in changes if path not in ALL_KEYS]
        if rejected:
            # The page should never construct a path itself. If it did, refuse rather than
            # write somewhere the window was never meant to reach.
            return {"ok": False, "error": f"not editable: {', '.join(sorted(rejected))}"}

        if self.store.changed_on_disk():
            # Someone edited the file while the window was open. Take their version as the
            # base so the edit here does not silently discard theirs.
            log.info("config.toml changed on disk; reloading before write")
            self.store.load()

        touched = [path for path, value in changes.items() if self.store.set(path, value)]
        if not touched:
            return {"ok": True, "changed": [], "restartRequired": []}

        try:
            self.store.save()
        except OSError as exc:
            log.exception("could not write %s", self.store.path)
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "changed": touched,
            "restartRequired": [key for key in touched if key in config_module.RESTART_ONLY],
        }

    def unset(self, path: str) -> dict[str, Any]:
        """Drop a key so it falls back to the application's default."""
        if path not in ALL_KEYS:
            return {"ok": False, "error": f"not editable: {path}"}
        if not self.store.unset(path):
            return {"ok": True, "changed": []}
        try:
            self.store.save()
        except OSError as exc:
            log.exception("could not write %s", self.store.path)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "changed": [path], "restartRequired": []}
