"""Loads config.toml, falling back to built-in defaults for anything missing."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "hotkeys": {
        "push_to_talk": "right alt",
        "push_to_talk_send": "",
        "toggle": "ctrl+shift+d",
        "cancel": "esc",
    },
    "wakeword": {
        "enabled": True,
        "backend": "whisper",
        "phrase": "hey ghost",
        "aliases": ["hey goast", "hey gost", "hey ghosts", "hey ghost writer"],
        "threshold": 0.8,
        "vad_threshold": 0.5,
        "model": "tiny.en",
        "device": "cpu",
        "compute_type": "int8",
        "cooldown_sec": 2.0,
        "model_path": "",
        "fallback_model": "hey_jarvis",
    },
    "endpoint": {
        "silence_timeout_sec": 1.2,
        "silence_threshold": 0.012,
        "min_speech_sec": 0.4,
        "lead_in_sec": 2.0,
        "max_duration_sec": 60.0,
        "stop_key": "down",
    },
    "model": {
        "name": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "float16",
        "language": "en",
        "vocabulary": [],
    },
    "audio": {
        "sample_rate": 16000,
        "min_duration_sec": 0.35,
        "max_duration_sec": 300.0,
        "vad": True,
        "device": "",
    },
    "output": {
        "paste": True,
        "clipboard_restore_delay": 0.35,
        "sounds": True,
    },
    "postprocess": {
        "remove_fillers": True,
        "voice_commands": True,
        "tidy_sentences": True,
        "replacements": {},
    },
}


class Config:
    """Dotted-path accessor over the merged config dict."""

    def __init__(self, data: dict[str, Any], path: Path | None = None):
        self.data = data
        self.path = path

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, dotted: str) -> Any:
        return self.get(dotted)


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.toml"


def load(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if path.exists():
        with path.open("rb") as handle:
            user = tomllib.load(handle)
    else:
        user = {}
    return Config(_merge(DEFAULTS, user), path)
