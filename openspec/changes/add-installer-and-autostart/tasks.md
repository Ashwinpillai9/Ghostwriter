## 1. One executable

- [ ] 1.1 Add `--settings [path]` to `ghostwriter.app:main`, dispatching to the settings window
- [ ] 1.2 Change `App.open_settings` to relaunch `sys.executable --settings` when frozen, keeping `-m ghostwriter.settings` when running from source
- [ ] 1.3 Add a `frozen` helper (`getattr(sys, "frozen", False)`) somewhere shared, since several modules need to branch on it
- [ ] 1.4 Tests: the launch argument is built correctly for both frozen and source, without spawning anything

## 2. Where things live

- [ ] 2.1 Decide and document the installed layout: program files under `%LOCALAPPDATA%\Ghostwriter`, config under `%APPDATA%\Ghostwriter`
- [ ] 2.2 Teach `config.default_config_path()` to use the per-user location when frozen, and the repo copy when running from source
- [ ] 2.3 Write a default `config.toml`, comments and all, on first run when none exists
- [ ] 2.4 Tests: path resolution for both frozen and source; a missing config is created rather than crashing

## 3. First-run bootstrap

- [ ] 3.1 Write `ghostwriter/bootstrap.py`
- [ ] 3.2 Detect an NVIDIA GPU without CUDA present, via `nvidia-smi` or `Win32_VideoController`
- [ ] 3.3 Fetch and unpack the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` wheels pinned in `pyproject.toml`, only when an NVIDIA GPU is present
- [ ] 3.4 Trigger the model download early, so the wait lands where the user expects it
- [ ] 3.5 Report progress on the overlay pill rather than appearing to hang
- [ ] 3.6 On failure, say what could not be fetched, keep running, and retry next start — never require reinstalling
- [ ] 3.7 Record what succeeded, so a normal start does no network work at all
- [ ] 3.8 Extend `cuda_paths.ensure()` to look where the bootstrap unpacks, not only in `site-packages`
- [ ] 3.9 Tests: GPU detection is stubbed both ways; a failed fetch degrades rather than raising; a completed bootstrap is not repeated

## 4. Auto-start

- [ ] 4.1 Write `ghostwriter/autostart.py`: `is_enabled()`, `enable()`, `disable()`, `available()`
- [ ] 4.2 Register a logon task with highest privileges (`schtasks /create /sc onlogon /rl highest`)
- [ ] 4.3 Read the real state from the system on every query — never cache it, and never store it in `config.toml`
- [ ] 4.4 `available()` returns false when running from source, so the UI can say so instead of offering a broken switch
- [ ] 4.5 Handle declined elevation: report it, leave auto-start off, keep the app running
- [ ] 4.6 Tests: `schtasks` is stubbed; enable, disable, query, an externally deleted task, and a refused elevation

## 5. Auto-start in the settings window

- [ ] 5.1 Add `autostart_state` / `set_autostart` to `settings/bridge.py`, kept apart from the `config.toml` keys
- [ ] 5.2 Add the row to the Keys tab, reading its state from the system rather than from config
- [ ] 5.3 Show the state as unavailable, with a reason, when running from source
- [ ] 5.4 Return the switch to off and explain when elevation is declined
- [ ] 5.5 Tests: the toggle does not write `config.toml`; the state comes from `autostart`, not a stored value

## 6. The build

- [ ] 6.1 Add `pyinstaller` as a build-time dependency
- [ ] 6.2 Write `ghostwriter.spec`: onedir, windowed, `ghostwriter/settings/ui/*` as data, an icon
- [ ] 6.3 Exclude the `nvidia/*` packages from the bundle
- [ ] 6.4 Name the hidden imports PyInstaller misses for `ctranslate2`, `onnxruntime`, `sounddevice` and `pywebview`
- [ ] 6.5 Confirm the built app runs **on a machine that never had Python** — a build that works only where it was built is not a build
- [ ] 6.6 Record the produced size, and check it against the ~350 MB the small-installer decision assumed

## 7. install.ps1

- [ ] 7.1 Fetch the latest release archive and unpack it to `%LOCALAPPDATA%\Ghostwriter`
- [ ] 7.2 Stop a running copy before replacing its files
- [ ] 7.3 Create a Start Menu shortcut
- [ ] 7.4 Register auto-start, enabled by default
- [ ] 7.5 Start Ghostwriter when the install finishes
- [ ] 7.6 `-Update`: same path, leaving `config.toml` and downloaded models untouched
- [ ] 7.7 `-Uninstall`: stop it, remove program files, remove the logon task and the shortcut, keep personal data and say where it is
- [ ] 7.8 `-Uninstall -Purge`: also remove the config and the downloaded models
- [ ] 7.9 Fail safely: a broken download must leave any existing installation working

## 8. Release and docs

- [ ] 8.1 Document the one-liner in `README.md`, replacing the manual setup as the primary route
- [ ] 8.2 Document `uv tool install` as the developer route, and running from source as the contributor route
- [ ] 8.3 Say plainly that the build is unsigned and what SmartScreen will show
- [ ] 8.4 Note in `CLAUDE.md` that frozen and source builds differ in config path, settings launch and CUDA discovery — the three places they can drift
- [ ] 8.5 Update the troubleshooting entry about elevated windows, which auto-start now fixes

## 9. Verification

- [ ] 9.1 `pytest tests -q` green
- [ ] 9.2 Install on a machine with no Python and confirm dictation works end to end
- [ ] 9.3 Confirm the first-run fetch: GPU present, and GPU absent
- [ ] 9.4 Confirm first run with no internet degrades and retries rather than breaking
- [ ] 9.5 Log out and back in; confirm Ghostwriter is running and its tray icon is there
- [ ] 9.6 With an admin terminal focused, press the dictation hotkey and confirm it records — the limitation this is meant to fix
- [ ] 9.7 Toggle auto-start off in Settings, log out and in, confirm it did not start; toggle back on
- [ ] 9.8 Delete the task in Task Scheduler and confirm Settings reports auto-start as off
- [ ] 9.9 Re-run the installer over an existing install; confirm `config.toml` and its comments survive and models are not re-fetched
- [ ] 9.10 Uninstall; confirm nothing runs, nothing is scheduled, and personal data is where it said it would be
- [ ] 9.11 Archive this change
