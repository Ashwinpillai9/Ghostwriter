## 1. Config store

- [ ] 1.1 Add `tomlkit` to `pyproject.toml` dependencies
- [ ] 1.2 Write `ghostwriter/settings/store.py`: load `config.toml` with tomlkit, dotted-path `get`/`set`, atomic `save` (temp file then replace)
- [ ] 1.3 Create a missing section or key on `set` rather than failing
- [ ] 1.4 Detect external modification so an open window can reload rather than clobber
- [ ] 1.5 Tests: comments and ordering survive a set+save; untouched keys are byte-identical; a missing table is created; a save is atomic
- [ ] 1.6 Test against the real `config.toml`, not only a synthetic fixture — this is what caught the DEFAULTS-shadowing bug in the wave colours

## 2. Window shell

- [ ] 2.1 Add `pywebview` to `pyproject.toml` dependencies
- [ ] 2.2 Create `ghostwriter/settings/` as a process entry point runnable standalone (`python -m ghostwriter.settings`)
- [ ] 2.3 Build the shell from the design: 900x640, dark palette, pill-shaped tab dock, seven empty tabs
- [ ] 2.4 Decide window chrome — frameless to match the design, or standard OS title bar. Record the decision in `design.md`
- [ ] 2.5 Python/JS bridge: read config, write config, and push a value-changed event to the page
- [ ] 2.6 Write on commit (blur, Enter, slider release), never per keystroke
- [ ] 2.7 Reload the page's values when `config.toml` changes underneath the window
- [ ] 2.8 Add a "Settings" tray item in `app.py` that launches the process, focusing the existing window if one is open

## 3. Keys tab

- [ ] 3.1 Rows for push-to-talk, hands-free toggle, dictate-and-send, cancel, and the suppress toggle
- [ ] 3.2 Capture a binding by pressing it, distinguishing left from right modifiers via `ghostwriter/keys/codes.py`
- [ ] 3.3 Cancelling a capture leaves the previous binding unchanged
- [ ] 3.4 Show the double-tap requirement for bare-modifier bindings, per `hotkeys.GATED`
- [ ] 3.5 Do not build the mockup's "Clashes with VS Code" warning — another application's global hotkey registrations are not detectable

## 4. Stopping tab

- [ ] 4.1 Render the timings as the design's readable sentence with inline editable numbers
- [ ] 4.2 Word `min_recording_sec` as an absolute floor, not merely a delay on the silence ending
- [ ] 4.3 Sliders for `vad_threshold` and `min_speech_sec`, plus the `stop_key` control
- [ ] 4.4 Link "Check my room" through to the Mic tab

## 5. Text tab

- [ ] 5.1 Toggles for `remove_fillers`, `voice_commands`, `tidy_sentences`
- [ ] 5.2 Editable table for `[postprocess.replacements]` with add and remove
- [ ] 5.3 Paste-versus-type control and `clipboard_restore_delay`

## 6. Look tab

- [ ] 6.1 Accent swatch, hex field and the four palette choices
- [ ] 6.2 Per-state colour list for `[overlay.colors]`
- [ ] 6.3 Live pill preview rendered through `ghostwriter/pill.py`'s `Frame`/`chrome()`, not reimplemented in CSS
- [ ] 6.4 Wave toggle and its sliders
- [ ] 6.5 Present the accent as the wave's colour control; expose `halos`/`cores` only as an advanced override, since they now derive from the accent
- [ ] 6.6 Reject an invalid hex colour and keep the previous value

## 7. Mic tab

- [ ] 7.1 Extract measurement logic from `scripts/mic_check.py` into `ghostwriter/roomcheck.py`
- [ ] 7.2 Rewrite `scripts/mic_check.py` to import it; confirm its output and verdicts are unchanged
- [ ] 7.3 Device dropdown from `sounddevice.query_devices()`
- [ ] 7.4 Live level meter on the settings process's own stream — never touching the app's recorder or listener
- [ ] 7.5 Release the audio stream when the tab is left or the window closes
- [ ] 7.6 Room measurement reporting noise, speech and headroom, suggesting thresholds with accept or decline

## 8. Wake word tab

- [ ] 8.1 Phrase field and alias chips with add and remove
- [ ] 8.2 Sliders for `threshold` and `vad_threshold`, and the `cooldown_sec` control
- [ ] 8.3 "Try it": record a few seconds, decode with `tiny.en`, score with `wakeword_whisper.matches_phrase`
- [ ] 8.4 Report both what was heard and the match score against the configured threshold
- [ ] 8.5 Indicate progress while the wake model reloads, since that takes seconds
- [ ] 8.6 Leave the running app's listener working after the test finishes

## 9. Model tab

- [ ] 9.1 List models with size and downloaded-or-not, via `huggingface_hub.scan_cache_dir()`
- [ ] 9.2 Resolve repo ids the way `Transcriber._load` does: `transcribe.MODEL_ALIASES` first, then `faster_whisper.utils._MODELS`, then the raw name
- [ ] 9.3 GPU availability badge from `ctranslate2.get_cuda_device_count()`
- [ ] 9.4 Device and compute-type controls
- [ ] 9.5 Vocabulary chips for `model.vocabulary`, which applies live
- [ ] 9.6 Restart-required bar naming the pending settings, driven by `App.RESTART_ONLY`
- [ ] 9.7 Do not implement in-app downloading; state that the model downloads on next use

## 10. Verification

- [ ] 10.1 `pytest tests -q` green
- [ ] 10.2 Per tab: change a value, confirm `config.toml` keeps its comments, and confirm the running app applies it without a restart
- [ ] 10.3 Confirm a `[model]` change is named as restart-required and the loaded model is untouched until restart
- [ ] 10.4 Confirm a settings-process crash leaves dictation, hotkeys and the overlay working
- [ ] 10.5 Confirm an edit made in an external editor while the window is open is reflected, not clobbered
- [ ] 10.6 Update `README.md` and `CLAUDE.md` to describe the settings window
- [ ] 10.7 Archive this change (`openspec archive add-settings-window`) so its spec becomes part of the project's main specs
