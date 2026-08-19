## Context

Ghostwriter is a Python tray application. The overlay owns Tk's `mainloop` on the main thread and draws itself with Pillow, pushing frames through Win32's `UpdateLayeredWindow` — a pipeline that is well tuned (about 3.9 ms per frame, roughly a quarter of the 60 fps budget) and deliberately not up for renegotiation here.

Three pieces landed before this change and shape every decision below:

- `App.reload_config()` re-reads `config.toml` and applies everything that can change without a restart, returning the labels of anything that cannot.
- `ConfigWatcher` watches the file and calls that automatically once a save settles, so **writing the file is already how a setting gets applied**.
- `Overlay.apply_style()` swaps the overlay's look at runtime, parking the change for the Tk thread to collect.

The design to build is Claude Design project `a3d574e4-9f2b-4bd3-9bc5-5169ebe5b53c`, file `Ghostwriter Settings.dc.html`, turn `t3`, in the shell chosen as `2c`: a 900x640 dark window with a pill-shaped tab dock on top and a mirror of the real status pill in the bottom-right corner.

## Goals / Non-Goals

**Goals**

- Every setting in `config.toml` is reachable and labelled in plain language.
- Tuning something with a physical dimension — mic level, wake-word sensitivity, endpoint timings, colours — has live feedback.
- `config.toml` survives editing as the readable, commented file it is today.
- Honest about restarts: name what is pending rather than silently doing nothing.
- Do not disturb the overlay, the hook, or the dictation path.

**Non-Goals**

- Replacing `config.toml`. It stays authoritative and hand-editable; the window is one more editor.
- Downloading models in-app. Status only.
- A settings-specific IPC or RPC layer. The file is the channel.
- Reworking the overlay's rendering. Explicitly out of scope.
- macOS support in this change. The seams exist; using them is separate work.

## Decisions

### The file is the API

The settings window writes `config.toml` and nothing else. `ConfigWatcher` already picks a save up within about half a second and `reload_config` applies it.

This is the decision everything else follows from. A settings UI's hardest part is normally the two-way channel to the running process; here it does not exist, because it already does not need to. It also means the window works when the app is not running, and that hand-editing and window-editing are the same operation.

*Alternative considered:* a socket or named-pipe channel for direct apply. Rejected — more moving parts for a faster path nobody asked for, and it would create a second way to apply settings that could drift from the file.

### pywebview, in its own process

The design is already HTML and CSS. Rebuilding it as hand-drawn Tk canvas widgets means roughly seven custom widget types — rounded cards, sliders with glow, chips, toggles, a pill-shaped dock, level meters — that would never quite match and would need maintaining on two platforms later. pywebview renders the design nearly as authored, and uses the operating system's built-in webview (WebView2 on Windows 11, WKWebView on macOS) rather than bundling a browser.

A separate process is required rather than merely convenient: Tk's `mainloop` holds the main thread, and pywebview's event loop wants the main thread too — a hard requirement on macOS. Two blocking loops cannot share one thread. Process separation also means a settings crash cannot take dictation down.

*Alternatives considered:* Tk with hand-drawn widgets (worst fidelity, most code, poorest macOS story); Qt/PySide6 (~150-200 MB, disproportionate for seven tabs of settings); Electron (bundles a browser, fails the lightweight goal structurally).

*Accepted cost:* two UI paradigms in one codebase — Tk plus Pillow for the overlay, web for settings. This is a real maintenance cost, accepted because the two have genuinely different requirements: one is a 60 fps always-on HUD needing per-pixel alpha, the other is an occasional dense form.

### tomlkit for writing

`config.py`'s `load()` merges the file with built-in `DEFAULTS`, which is right for reading and useless for writing: dumping it back would flatten every default into the user's file and destroy the comments, which this project treats as documentation. `tomlkit` round-trips comments and formatting, so only the keys actually touched are edited.

Writes are atomic — temp file, then replace. `ConfigWatcher` already tolerates the file briefly not existing and its settle window collapses a rename-over-original into one reload.

### Write on commit, not on keystroke

Because a save triggers a reload, writing on every keystroke or slider pixel would reload the app continuously. Values are written when committed — blur, Enter, slider release — which also keeps the file's history clean.

### Reuse the real renderers rather than reimplementing them

The Look tab's pill preview renders through `ghostwriter/pill.py`'s existing `Frame` and `chrome()` and displays the result, rather than approximating the pill in CSS. A CSS copy would drift from the real pill the first time either changed.

Similarly, the Mic tab's room measurement uses logic extracted from `scripts/mic_check.py` into `ghostwriter/roomcheck.py`, imported by both, rather than duplicated. And the wake-word test scores with `wakeword_whisper.matches_phrase`, the same function the listener uses.

### The live status pill is optional

The mirrored pill in the bottom-right corner is the one element wanting the app's runtime state — is it listening, what model is loaded. Options, cheapest first: omit it; derive the static parts from config alone; have the app write a small status file the window polls.

Start by omitting it. Do not build a socket for it.

## Risks / Trade-offs

**Two writers, one file.** The user may have `config.toml` open in an editor while the window is open. `ConfigWatcher` handles external edits for the running app, and the window reloads on external change, but a genuine simultaneous write will have a last-writer-wins outcome. Accepted: the window is explicitly not the sole owner of the file.

**Reload latency is visible.** A change takes roughly half a second to appear, because it goes through the file and the watcher's settle window. Slower than a direct call would be, and the settle window cannot be removed — it is what stops a half-written file being read. Acceptable for a settings screen.

**A wake-word rebuild is slow.** Changing the wake model reloads it, which takes seconds. It is still applied live, but the UI must say it is working rather than appearing to hang.

**Two new dependencies.** `tomlkit` is small and does one job. `pywebview` relies on the platform webview being present — WebView2 ships with Windows 11, so this is safe for the current target, but it is a runtime assumption worth stating.

**Second UI paradigm.** Contributors now need both Tk/Pillow and web. Mitigated by the strict split: the overlay never becomes web, the settings window never becomes Tk.

**The design has drifted from the code.** Two places to correct while building, both from changes made after the mockup was drawn:
- Wave crest colours are now derived from `overlay.accent`; `halos`/`cores` no longer live in `config.toml`. The Look tab must present the accent as the control, with the explicit colours as an advanced override.
- `min_recording_sec` is now an absolute floor on a hands-free recording, not merely a delay on the silence-based ending. The Stopping tab's sentence must say so.

Also drop the mockup's "Clashes with VS Code" hotkey warning: there is no way to detect another application's global hotkey registrations, so that warning cannot be backed by anything real.
