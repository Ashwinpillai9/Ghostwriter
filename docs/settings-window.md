# Settings window — implementation spec

Status: **not started.** Everything it depends on is built and merged or on `feat/reload-config`.

This is the working document for building Ghostwriter's settings window. It exists so the work
can be picked up cold, without the conversation it came from. It records the decisions *and the
reasons*, so they don't get re-litigated or accidentally reversed.

---

## 1. Why

`config.toml` is currently the only way to change anything. It is a good config file — heavily
commented, every knob explained — but it is still a text file, and several settings (wake-word
thresholds, the endpointer, mic levels) genuinely want a live preview to tune.

A design already exists. It was explored across three shell concepts and converged on one.

**Design source:** Claude Design project `a3d574e4-9f2b-4bd3-9bc5-5169ebe5b53c`,
file `Ghostwriter Settings.dc.html`.
Open with the `claude_design` MCP (`DesignSync`, `get_file`), or at
`https://claude.ai/design/p/a3d574e4-9f2b-4bd3-9bc5-5169ebe5b53c`.

The file contains three turns. **Turn 3 is the one to build**; turns 1–2 are the exploration that
led to it and are useful only as rationale.

| Turn | What it is |
| --- | --- |
| `t1` (`1a`/`1b`/`1c`) | Three shell concepts, Hotkeys section built out in each |
| `t2` (`2a`/`2b`/`2c`) | Chrome/navigation options. **`2c` was chosen** and is also the Keys tab |
| `t3` (`3a`–`3f`) | The other six tabs, built inside `2c`'s shell |

---

## 2. The foundation (already built — do not rebuild)

The settings window is deliberately the *last* piece. Everything underneath it exists:

| Piece | Where | What it gives the settings window |
| --- | --- | --- |
| `App.reload_config()` | `ghostwriter/app.py` | Single apply path. Re-reads the file, applies everything live that can be, returns labels of what needs a restart. |
| `App.RESTART_ONLY` | `ghostwriter/app.py` | The four keys that genuinely need a restart. |
| `ConfigWatcher` | `ghostwriter/watcher.py` | **Saving `config.toml` auto-applies.** Polls (mtime, size), waits for the file to settle. |
| `Overlay.apply_style()` | `ghostwriter/overlay.py` | Live restyle, safe from any thread; the swap lands on the Tk thread. |
| `HotkeyManager.reregister()` | `ghostwriter/hotkeys.py` | Rebind without reinstalling the hook; carries hold state so a rebind mid-hold is safe. |
| `ghostwriter/keys/` | | Platform seam for input. `codes.py` is OS-neutral. |
| `style.wave_colors()` | `ghostwriter/style.py` | Wave crests derive from `overlay.accent`. |

### The consequence that shapes the whole design

**Because `ConfigWatcher` exists, the settings UI needs no IPC back to the running app.**

It writes `config.toml`; the app notices within ~0.5 s and applies it. That removes the hardest
part of a settings UI — the two-way channel — entirely. Build it as a standalone process that
only touches the file.

Everything else it needs (mic level, room check, model cache status) it can do for itself
without the app's help. See §6 for the one exception.

---

## 3. Architecture

**pywebview, in a separate process from the main app.**

### Why pywebview

- **The design is already HTML/CSS.** It transfers close to 1:1 instead of being re-derived as
  hand-drawn Tk Canvas widgets. The mockup has rounded cards, custom sliders with glow, chips,
  toggles, a pill-shaped tab dock, gradient preview panes and level meters — that is roughly
  seven custom widget classes in Tk, and they would never quite match.
- **It uses the OS's built-in webview**, not a bundled browser: WebView2 (ships with Windows 11)
  and WKWebView on macOS. This is the distinction from Electron; the footprint is small.
- **Cross-platform for free**, which matters given the macOS goal.
- Iterating on look is editing CSS, not redrawing canvas geometry.

### Why a separate process

- Tk's `mainloop` owns the main thread (`overlay.py` says so explicitly). pywebview's event loop
  also wants the main thread — a hard Cocoa requirement on macOS. Two blocking loops, one thread.
- A crash in the settings UI cannot take down dictation.
- With `ConfigWatcher` in place there is nothing to coordinate, so process separation costs
  almost nothing.

### Known cost, accepted

Two UI paradigms in one codebase — Tk + Pillow for the overlay, web for settings. This is a real
maintenance cost. It was accepted because the overlay's Pillow/`UpdateLayeredWindow` pipeline is
genuinely good (research found it *better* than what Tauri/winit currently expose) and must not
be touched, while the settings window is the opposite kind of problem.

### Rejected, with reasons

| Option | Why not |
| --- | --- |
| Tk + hand-rolled Canvas widgets | ~7 custom widget classes; will never match the design; worst of the options on macOS. |
| Qt / PySide6 | ~150–200 MB dependency. Contradicts "lightweight" for seven tabs of settings. |
| Electron | Bundles a browser. Fails "lightweight" structurally. |
| Rewrite the app in Rust/Tauri | Investigated in depth and rejected — see §9. |

---

## 4. Layout (shell `2c`)

900 × 640. Dark, dense, quiet.

```
┌──────────────────────────────────────────────────────────┐
│ ▍ghostwriter                              ─   ▢   ✕      │  36px title strip
├──────────────────────────────────────────────────────────┤
│        ╭─────────────────────────────────────────╮       │
│        │ Keys │Wake word│Model│Stopping│Look│Text│Mic│    │  pill-shaped dock
│        ╰─────────────────────────────────────────╯       │
│                                                          │
│   <active tab content, 46px side padding>                │
│                                                          │
│                                                          │
│                          ╭──────────────────────────╮    │
│                          │ ▂▅▃▆▂ ready · large-v3   │    │  live status pill,
│                          ╰──────────────────────────╯    │  bottom-right
└──────────────────────────────────────────────────────────┘
```

The bottom-right pill deliberately mirrors the real overlay pill — the window shows you what is
on your desktop.

### Palette (from the mockup)

| Token | Value |
| --- | --- |
| Window background | `#141519` |
| Panel / card | `#191b20` |
| Input well | `#101115` |
| Chip | `#24272e` |
| Text | `#e8e9ec` |
| Muted text | `rgba(232,233,236,.45)` |
| Hairline border | `rgba(255,255,255,.07)` |
| Accent | `#38bdf8` (fill `rgba(56,189,248,.16)`, text `#bae6fd`) |
| Warning / restart | `#f59e0b` |
| Success | `#22c55e` |

Fonts: Segoe UI Variable Display / Segoe UI for prose; JetBrains Mono for values, keys and hex.

### Window chrome — decide before starting

The mockup draws its own title bar (`─ ▢ ✕`). An earlier decision chose a **standard OS title
bar** instead, to avoid reimplementing drag/minimize/Alt-Tab — but that was decided when the
plan was a Tk window. pywebview supports frameless windows more readily, so this is worth
revisiting. Frameless is closer to the design; standard chrome is less work and less to get
wrong. **Not settled.**

---

## 5. The tabs

Each maps to one `config.toml` section. "Live" means `reload_config` already applies it with no
restart.

### Keys → `[hotkeys]` — live
Rows: Push to talk (`Right Ctrl ×2`), Hands-free toggle (`Ctrl+Shift+D`), Dictate + Enter
(unset, "click to set"), Cancel (`Esc`), and a "Hide keys from other apps" toggle (`suppress`).
Advanced: double-tap window (0.4 s), raw TOML.

> **Drop the mockup's "Clashes with VS Code" warning.** There is no way to detect another
> application's global hotkey registrations, so that warning cannot be backed by anything real.

### Wake word → `[wakeword]` — live
Enable toggle; phrase field; alias chips with `×` and `+ add`; "How close a match"
(`threshold`, 0.80); "What counts as speech" (`vad_threshold`, 0.50); "Wait after firing"
(`cooldown_sec`, 2.0). Green **Try it** panel: records a few seconds, shows the waveform and the
match score against the phrase.

`phrase`/`aliases`/`threshold`/`vad_threshold`/`cooldown_sec` apply by assignment.
`model`/`device`/`compute_type` rebuild the listener — still live, but costs a model load
(seconds), so the UI should say so.

**Try it** needs its own `tiny.en` load in the settings process. Reuse
`wakeword_whisper.matches_phrase` for scoring rather than reimplementing it.

### Model → `[model]` — **the one restart-required tab**
Radio list per model with size and **downloaded / not on disk**; "Run it on" GPU/CPU; vocabulary
chips; amber footer bar naming what needs a restart.

- Cache status: `huggingface_hub.scan_cache_dir()`. Resolve repo ids the way
  `Transcriber._load` does — `transcribe.MODEL_ALIASES` first (it overrides `large-v3-turbo` to a
  different repo than faster-whisper's own default), then `faster_whisper.utils._MODELS`, then
  the raw name.
- GPU badge: `ctranslate2.get_cuda_device_count()`.
- **No in-app download** (decided). Picking an undownloaded model behaves as today — it downloads
  on first use after restart. The mockup's progress bar is not built.
- `vocabulary` is live (`Transcriber.initial_prompt` is read per call).

### Stopping → `[endpoint]` — live
The mockup writes this as a readable sentence with inline editable numbers, which is the best
idea in the whole design — keep it:

> Stop after `1.2` seconds of quiet, but never before `4.0` seconds have passed — so a pause to
> think doesn't cut you off. Give up after `2.0` seconds if I never start talking, and stop no
> matter what at `60` seconds.

Plus "What counts as you still talking" (`vad_threshold`) with a **Check my room →** link into
the Mic tab, "Stop now key" (`stop_key`), and "Ignore blips shorter than" (`min_speech_sec`).

> `min_recording_sec` is now an **absolute floor** — nothing but `max_duration`, the stop key or
> `Esc` ends a recording before it. The sentence above must reflect that; older wording said it
> only held off the silence-based ending.

### Look → `[overlay]`, `[overlay.colors]`, `[overlay.wave]` — live
Accent swatch + hex + the four palette dots; per-state colours (Waiting / Writing it down /
Pasted / Something went wrong); live pill preview; wave toggle and three sliders (how fast it
crosses, how bright, how many ripples).

- The live preview should **reuse `ghostwriter/pill.py`'s `Frame` and `chrome()`** rather than
  reimplementing the pill's look in CSS — render to PNG, show it. Otherwise the preview and the
  real pill will drift.
- **The mockup predates the wave-colour change.** `halos`/`cores` are now *derived from the
  accent* and absent from `config.toml`. Do not surface them as primary controls; the accent is
  the control. Expose them only under Advanced, as "pin the wave to its own colours".

### Text → `[postprocess]`, `[output]` — live
Filler removal, spoken punctuation, sentence tidying, and the find/replace corrections table
(`[postprocess.replacements]`). Also paste vs type (`output.paste`) and
`clipboard_restore_delay`. Nothing here needs the app — `App.process()` reads the
`[postprocess]` dict fresh per transcription.

### Mic → `[audio]` — live
Device dropdown from `sounddevice.query_devices()`; live level meter; **Check my room** panel
reporting background noise / your voice / headroom / when measured, then suggesting
`endpoint.vad_threshold` and `endpoint.silence_threshold` with *Leave as is* / *Use these*.

- Extract the measurement logic out of `scripts/mic_check.py` into a shared module (suggest
  `ghostwriter/roomcheck.py`) imported by both, rather than duplicating it. The script must keep
  working unchanged.
- The level meter opens its **own** short-lived `InputStream` in the settings process. It must
  not touch the app's recorder or wake listener.

---

## 6. Writing config.toml

### Dependencies

Checked against the current venv:

| Package | Status | Needed for |
| --- | --- | --- |
| `huggingface_hub` | already installed (via faster-whisper) | Model tab cache scan |
| `sounddevice` | already installed | Mic level meter, room check, *Try it* |
| `ctranslate2` | already installed | GPU badge |
| `tomlkit` | **must be added** | Comment-preserving config writes |
| `pywebview` | **must be added** | The window itself |

Only two new dependencies, neither large.

**Use `tomlkit`** for writing.

`config.py`'s `load()` merges with `DEFAULTS`, which is fine for reading and useless for writing:
dumping it back would flatten every default into the user's file and destroy the comments, which
this project treats as documentation rather than clutter. `tomlkit` round-trips comments and
formatting, so only the keys actually touched get edited.

Write a small `store.py` around it:

```python
store = ConfigStore(path)          # parses with tomlkit
store.get("overlay.accent")
store.set("overlay.accent", "#a855f7")
store.save()                       # atomic: temp file + replace
```

Save atomically (write a temp file, then `Path.replace`). `ConfigWatcher` already tolerates the
file briefly not existing, and its settle window means a rename-over-original is applied once.

### One caveat about auto-apply

The watcher applies a save ~0.5 s later. A settings UI that writes on **every** keystroke would
fire a reload per character. Either debounce writes (~500 ms after the user stops), or write on
commit (blur / Enter / slider release). **Write on commit is preferred** — it also keeps
`config.toml`'s history clean.

### The one thing that would need a channel back

The bottom-right **live status pill** ("ready · large-v3-turbo · GPU", listening state, current
level) is the only element needing the app's runtime state. Options, cheapest first:

1. **Omit it initially.** Everything else works standalone.
2. Derive what it can from config alone (model name, device) and drop the live parts.
3. Have the app write a tiny status JSON periodically; the settings process polls it.

Do **not** build a socket/RPC layer for this.

---

## 7. Suggested build order

1. `store.py` + tests — comment-preserving round-trip, atomic save, missing tables created.
2. The shell: window, tab dock, palette, one static tab. Confirm it launches and looks right.
3. **Keys**, then **Stopping** — most direct config mapping, no hardware.
4. **Text**, **Look** — Look needs the `pill.py` preview bridge.
5. **Mic** — needs `roomcheck.py` extraction and a live audio stream.
6. **Wake word** — needs a model load for *Try it*.
7. **Model** — needs the HF cache scan and the restart-required bar.

Tabs are independent; ship them incrementally rather than in one branch. (An earlier plan said
one branch for all seven; that was written before the shell was decided to be a separate
process. Independent tabs are now genuinely shippable one at a time.)

---

## 8. Verification

- `store.py` gets real unit tests: a `config.toml` with comments survives a set+save; untouched
  keys are byte-identical; a missing table is created.
- Follow `tests/test_reload.py`'s example of testing against **the real `config.toml`**, not
  only a synthetic fixture. That is what caught the `DEFAULTS`-shadowing bug in the wave colours.
- The UI itself is not unit-tested, consistent with `overlay.py`/`pill.py`. CLAUDE.md is explicit
  that GUI paths need a real run.
- Per tab, manually: change a value, confirm it lands in `config.toml` with comments intact, and
  confirm the running app picks it up without a restart (or names the restart, for `[model]`).

---

## 9. Decisions already made — do not silently reverse

| Decision | Reason |
| --- | --- |
| **Stay on Python.** Do not rewrite in Rust/Tauri/Qt/C#. | Researched in depth. Pure Python is ~0.07 % of dictation latency and 9 % of the overlay's render loop, which itself runs at 23.5 % of its frame budget. The overlay is the one thing a rewrite would target, and it is where Rust has *nothing* — no crate wraps `UpdateLayeredWindow`, `softbuffer`'s Win32 backend has `// TODO: Support transparency`, `wgpu`'s DX12 backend ignores window alpha, `egui`'s Windows transparency bug is open since 2024. macOS needs the same three swaps (inference backend, overlay presentation, input) in *any* language, so a rewrite is a strict superset of the incremental work. |
| **No in-app model download.** | Status-only is most of the value for a fraction of the machinery. |
| **The overlay stays Pillow + `UpdateLayeredWindow`.** | Currently better than what any alternative ecosystem exposes; Tauri has no per-region click-through at all. |
| **Wave colours derive from the accent.** | A purple pill throwing a blue ripple reads as two unrelated things. |
| **`min_recording_sec` is an absolute floor.** | It previously guarded only the silence branch, so a slow start fell through to `no_speech` at `lead_in` and was *discarded*. |

---

## 10. Open questions

- **Window chrome** — frameless (matches the design) or standard OS title bar (less to get
  wrong)? See §4.
- **The live status pill** — build it, degrade it, or omit it? See §6.
- **Where the window lives** — a tray item ("Settings…"), a hotkey, or both?
- **First-run** — should the settings window open itself the first time Ghostwriter runs?
- **`config.toml` as the single source of truth** — the settings UI writes the same file the user
  may have open in an editor. Two writers, one file. Probably fine (the watcher handles external
  edits), but worth a conscious decision about what happens if both write at once.
