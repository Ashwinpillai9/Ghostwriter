# Ghostwriter

Local push-to-talk dictation for Windows. See README.md for what it does and how to run it.

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
- **`keyboard` resolves `"right alt"` to both Alt scan codes.** Side-specific keys are bound by
  scan code, or a suppressed binding swallows Left Alt and `Alt+Tab` with it.
- **Windows' low-level keyboard hook reports Left and Right Ctrl with the same scan code.**
  `keyboard.key_to_scan_codes("right ctrl")` claims otherwise, but that table is synthesised
  from a separate WinAPI pass and doesn't match what a live keypress actually sends — confirmed
  with `scripts/keyboard_probe.py`: a real Right Ctrl press shows `scan_code=29`, identical to
  Left Ctrl. `add_hotkey` and `is_pressed` match on that same integer, so no scan-code spec can
  bind Right Ctrl alone. Only `event.name` tells them apart (it uses the hook's extended-key
  flag internally), so `hotkeys._bind_right_ctrl_hold` uses a raw `keyboard.hook()` and matches
  on name instead of going through `add_hotkey`. It also arms only on a double-tap-then-hold,
  not a single press — Right Ctrl is the key held for every `Ctrl+C`/`Ctrl+V`, and a single-tap
  binding fired dictation on all of them.
- **A loudness gate cannot detect speech on an auto-gain laptop mic.** Both the wake word and
  the endpointer use Silero VAD; see the comments atop `wakeword_whisper.py` and `endpoint.py`.
  `scripts/mic_check.py` measures a room and prints the threshold to use.
- **Silero's LSTM state is zeroed on every call.** Score a short window and a silent room reads
  0.8; give it a second of audio and judge only the last quarter and it reads 0.02.
- **Speech is continuous, noise is spiky.** Use the median over a window, never the max — about
  1% of frames spike in a quiet room and a max lets any one of them win.
