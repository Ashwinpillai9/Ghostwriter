## Why

`config.toml` is the only way to change anything about Ghostwriter. It is a well-commented file, but several settings — wake-word thresholds, the endpointer's timings, microphone levels — are impossible to tune by reading. You change a number, restart, talk, and guess whether it helped. A visual editor with live feedback turns that loop from minutes into seconds.

The groundwork is already in place: saving `config.toml` now applies almost everything without a restart, which means a settings UI can be a thin editor over the file rather than a second source of truth.

## What Changes

- A settings window, opened from the tray, with seven tabs: Keys, Wake word, Model, Stopping, Look, Text, Mic.
- Runs as a **separate process** from the dictation app, communicating only by writing `config.toml`. The existing `ConfigWatcher` makes the running app pick changes up.
- Config writes preserve comments and formatting (`tomlkit`), so the file stays the readable, documented artifact it is today.
- Live instrumentation the file cannot give you: a microphone level meter, a room measurement that suggests thresholds, a wake-word match test, and a preview of the status pill in its real colours.
- The Model tab reports which models are on disk and which are not, and names the settings that need a restart instead of pretending they applied.
- Two new dependencies: `tomlkit` and `pywebview`.

Non-breaking. `config.toml` remains hand-editable and authoritative; the window is one more editor of it, not a replacement.

## Capabilities

### New Capabilities

- `settings-window`: A visual editor for Ghostwriter's configuration — presenting every setting in labelled groups, writing changes back to `config.toml` without destroying it, showing live microphone and appearance feedback, and being honest about which changes need a restart.

### Modified Capabilities

None. No existing behaviour changes; `config.toml` keeps its current meaning and the running app keeps applying it the way it already does.

## Impact

**New code**
- `ghostwriter/settings/` — the window, its tabs, and the config store.
- `ghostwriter/roomcheck.py` — microphone measurement extracted from `scripts/mic_check.py` so both use one implementation.

**Touched**
- `ghostwriter/app.py` — a tray item to launch the window.
- `scripts/mic_check.py` — imports the extracted measurement rather than owning it. Behaviour unchanged.
- `pyproject.toml` — adds `tomlkit` and `pywebview`.

**Depended on, not changed**
- `App.reload_config`, `ConfigWatcher`, `Overlay.apply_style`, `HotkeyManager.reregister`, `ghostwriter/keys/`, `ghostwriter/pill.py`.

**Design source**
Claude Design project `a3d574e4-9f2b-4bd3-9bc5-5169ebe5b53c`, file `Ghostwriter Settings.dc.html`. Turn `t3` is the design to build; `2c` is the chosen shell and doubles as the Keys tab.
