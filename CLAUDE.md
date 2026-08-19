# Ghostwriter

Local push-to-talk dictation for Windows. See README.md for what it does and how to run it.

## Planned work

- **Settings window** — designed but not built. The spec is `docs/settings-window.md`; read it
  before starting anything in that area. It records the architecture (pywebview in a separate
  process, driven entirely through `config.toml`) and the decisions not to reverse.

## Branch workflow

Every feature, bug fix or improvement starts on its own branch — never commit to `main`.

1. `git checkout -b <type>/<short-description>` before the first edit. Types: `feat/`, `fix/`,
   `chore/`.
2. Commit as usual. The branch is pushed automatically (see below).
3. **Stop there and hand the branch to the user to test.** Every change ends with concrete
   testing steps: the exact command to run, what to do once it is running, and what a correct
   result looks like — including what to check that automated tests cannot cover. Never end a
   change with just "tests pass".
4. **Do not run `gh pr create` until the user has tested the branch and asked for a PR.**
   Passing tests are not approval; neither is "the work looks done". Wait to be told.
5. Once they approve the PR and are ready to land it, merge it
   (`gh pr merge --squash --delete-branch`) and return to `main`.

Steps 3–5 are two separate gates, and the user opens each one. Automated checks never
substitute for either.

Two hooks in `.claude/settings.json` enforce the mechanical half of this:

- `.claude/hooks/require-branch.sh` (PreToolUse on Edit/Write) denies edits to any file whose
  repo is on `main` or `master`. Files outside a git repo are unaffected.
- `.claude/hooks/auto-push.sh` (PostToolUse on `git *`) pushes the current branch whenever it
  is ahead of its remote, setting the upstream on first push. It never pushes a protected
  branch, and skips a diverged branch rather than force-pushing over someone else's work.

Neither hook can decide *when* a PR should be opened or merged. Both of those are the user's
calls, above, and no hook enforces them.

## Testing

```powershell
.venv\Scripts\python.exe -m pytest tests -q        # unit tests, no mic or GPU needed
.venv\Scripts\python.exe scripts\wakeword_test.py  # wake word, via Windows SAPI
.venv\Scripts\python.exe scripts\smoke_test.py     # GPU model loads and decodes
```

Tests must pass before a PR. The audio, GPU and clipboard paths are stubbed in `tests/`, so a
green suite does not prove the app works end to end — run it (`run.ps1`) for anything touching
hotkeys, the microphone or the overlay.

## Things that bite

- **`App.reload_config` is the single apply path for a settings change.** The tray's reload item
  and any settings UI both go through it, so "what does changing this actually do" is answered
  in one place and is testable without a UI (`tests/test_reload.py`). It works because the hot
  paths read config values fresh per call rather than snapshotting them, so applying a change is
  usually just assignment. Adding a setting means teaching `_apply_*` about it — otherwise it
  silently needs a restart. Genuinely restart-only keys are listed in `App.RESTART_ONLY` and
  reported back to the caller rather than applied.
- **A save must settle before it is applied.** `watcher.py` polls `config.toml`'s (mtime, size)
  and waits for it to stop changing, because editors do not write a file in one step — several
  truncate then write, others write a temp file and rename over the original. Reloading on the
  first change reads a half-written file and reports a syntax error for something typed
  correctly. The same window collapses an editor that autosaves per keystroke into one reload.
- **`Overlay.apply_style` must land on the Tk thread.** It can destroy and rebuild the wave's
  Toplevel, so a swap is parked in `_pending_style` and collected by the next tick, the same way
  status updates go through `events`. Calling it from a worker thread is safe; mutating
  `overlay.style` directly is not.
- **Tk draws none of the pill.** Frames are composed with Pillow (`ghostwriter/pill.py`) and
  pushed via `UpdateLayeredWindow`; Tk only supplies the window, the loop and the input. The
  bitmap must be premultiplied BGRA (`tobytes("raw", "BGRa")`) or every antialiased edge picks
  up a bright halo.
- **Blur cost is priced by area.** The pill's chrome is rendered on a small tile and pasted in;
  blurring it across a larger surface cost ~44 ms a frame. Keep an eye on the frame budget when
  touching `pill.py`.
- **Overlay look and timing belong in `style.py`, not in constants.** `OverlayStyle`/`WaveStyle`
  are built from `config.toml` and validated per key, so a typo warns once at startup instead
  of raising inside the render loop. Add new knobs there rather than as module constants.
- **Never draw full-screen in Pillow.** The activation wave is drawn into a 960px buffer and
  scaled up by GDI's `StretchBlt` (~0.9 ms). Doing the same work at display resolution in
  Python is ~119 ms a frame, and it blocks the Tk loop, so the drag and status updates freeze
  with it.
- **Tk's `winfo_screenwidth` is the primary monitor only.** Multi-monitor positioning has to go
  through the Win32 virtual-desktop metrics; see `ghostwriter/overlay.py`.
- **`winfo_x`/`winfo_y` go stale while a window is withdrawn.** The overlay tracks its own
  position instead.
- **Match keys on virtual-key codes, never scan codes.** Left and Right Ctrl share scan code 29
  — confirmed with `scripts/keyboard_probe.py` — so no scan-code spec can bind Right Ctrl alone.
  `KBDLLHOOKSTRUCT.vkCode` *is* sided (`VK_RCONTROL` 163 vs `VK_LCONTROL` 162), which is why
  `ghostwriter/keys/` owns a `WH_KEYBOARD_LL` hook rather than using a library. This replaced
  the `keyboard` package, whose scan-code matching made side-specific binds impossible.
- **Right Ctrl arms only on a double-tap-then-hold.** It is the key held for every `Ctrl+C` and
  `Ctrl+V`, and a single-tap binding fired dictation on all of them. `hotkeys.GATED` lists the
  bare-modifier chords this applies to.
- **The hook callback has ~300 ms before Windows silently unhooks it** (`LowLevelHooksTimeout`),
  and a dead hook is indistinguishable from a broken keyboard. `HotkeyManager._on_event` only
  compares; every callback is dispatched to its own thread by `_fire`.
- **Synthetic keystrokes must be tagged or they feed back.** `keys.windows.SIGNATURE` goes into
  `dwExtraInfo` on everything we send, and the hook skips events carrying it — otherwise the
  `Ctrl+V` used to paste would re-trigger our own Ctrl binding.
- **A loudness gate cannot detect speech on an auto-gain laptop mic.** Both the wake word and
  the endpointer use Silero VAD; see the comments atop `wakeword_whisper.py` and `endpoint.py`.
  `scripts/mic_check.py` measures a room and prints the threshold to use.
- **Silero's LSTM state is zeroed on every call.** Score a short window and a silent room reads
  0.8; give it a second of audio and judge only the last quarter and it reads 0.02.
- **Speech is continuous, noise is spiky.** Use the median over a window, never the max — about
  1% of frames spike in a quiet room and a max lets any one of them win.
