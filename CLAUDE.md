# Ghostwriter

Local push-to-talk dictation for Windows. See README.md for what it does and how to run it.

## Branch workflow

Every feature, bug fix or improvement starts on its own branch — never commit to `main`.

1. `git checkout -b <type>/<short-description>` before the first edit. Types: `feat/`, `fix/`,
   `chore/`.
2. Commit as usual. The branch is pushed automatically (see below).
3. Open a PR with `gh pr create` when the work is done and tested.
4. **Wait for the user's approval before merging.** Once they approve, merge the PR
   (`gh pr merge --squash --delete-branch`) and return to `main`.

Two hooks in `.claude/settings.json` enforce the mechanical half of this:

- `.claude/hooks/require-branch.sh` (PreToolUse on Edit/Write) denies edits to any file whose
  repo is on `main` or `master`. Files outside a git repo are unaffected.
- `.claude/hooks/auto-push.sh` (PostToolUse on `git *`) pushes the current branch whenever it
  is ahead of its remote, setting the upstream on first push. It never pushes a protected
  branch, and skips a diverged branch rather than force-pushing over someone else's work.

Neither hook can decide *when* a PR should merge — that is the approval step above, and it
stays a judgement call.

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
  blurring it across the full wave-sized surface cost ~44 ms a frame. Keep an eye on the frame
  budget when touching `pill.py`.
- **Tk's `winfo_screenwidth` is the primary monitor only.** Multi-monitor positioning has to go
  through the Win32 virtual-desktop metrics; see `ghostwriter/overlay.py`.
- **`winfo_x`/`winfo_y` go stale while a window is withdrawn.** The overlay tracks its own
  position instead.
- **`keyboard` resolves `"right alt"` to both Alt scan codes.** Side-specific keys are bound by
  scan code, or a suppressed binding swallows Left Alt and `Alt+Tab` with it.
- **A loudness gate cannot detect speech on an auto-gain laptop mic.** The wake word uses
  Silero VAD; see the comment at the top of `ghostwriter/wakeword_whisper.py`.
