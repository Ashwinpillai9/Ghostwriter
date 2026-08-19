## Why

Installing Ghostwriter today means cloning the repo, having Python 3.12 and `uv`, creating a venv, and running `run.ps1` from a terminal. That is fine for the person who wrote it and a barrier for everyone else. There is also no auto-start: the README tells you to make a Startup-folder shortcut by hand.

Both are the difference between a project and something a friend can actually use.

## What Changes

- **A one-line install.** `irm https://.../install.ps1 | iex` fetches a self-contained build, unpacks it under `%LOCALAPPDATA%`, and sets Ghostwriter up. No Python, no repo, no terminal afterwards. The same script updates and uninstalls.
- **The build carries no CUDA.** The NVIDIA runtime is 1.94 GB of a 2.23 GB payload, so it is fetched on first run and only when an NVIDIA card is present. Everyone else gets working CPU dictation and a ~350 MB download instead of ~2.3 GB.
- **First run gets what it needs**, with progress on screen: the CUDA runtime if useful, then the Whisper model.
- **Ghostwriter starts with Windows**, through a Task Scheduler logon task registered at install. **This also fixes a documented limitation** — Windows blocks input from a lower-privilege process, so hotkeys currently do nothing over an elevated window; the task runs with highest privileges, so they work everywhere.
- **A row in the settings window** turns auto-start off and on, so the choice is not locked in at install time.
- **A single executable.** `Ghostwriter.exe --settings` opens the settings window, because a frozen build has no `python -m`.

Not signed. Distribution is to a handful of people who trust the source, so SmartScreen will warn on first run; the release notes will say so. Signing can be added later without reworking any of this.

## Capabilities

### New Capabilities

- `installation`: Getting Ghostwriter onto a Windows machine, keeping it current, and removing it again — including fetching the large optional pieces on first run rather than shipping them.
- `auto-start`: Running Ghostwriter when the user logs in, at a privilege level where its hotkeys actually work.

### Modified Capabilities

- `settings-window`: Gains a control for auto-start, so it can be turned off and on after installation.

## Impact

**New**
- `install.ps1` — install, update and uninstall.
- `ghostwriter.spec` — the PyInstaller build.
- `ghostwriter/autostart.py` — registering, removing and querying the logon task.
- `ghostwriter/bootstrap.py` — the first-run fetch of the CUDA runtime and the model.

**Touched**
- `ghostwriter/app.py` — `open_settings` currently launches `sys.executable -m ghostwriter.settings`, which cannot work in a frozen build; it becomes an argument on the one executable. Plus the first-run bootstrap and a tray item.
- `ghostwriter/settings/` — the auto-start row, and its bridge methods.
- `ghostwriter/cuda_paths.py` — must also look where the bootstrap puts the CUDA runtime, not only in `site-packages`.
- `pyproject.toml` — `pyinstaller` as a build-time dependency.
- `README.md` — install instructions replace the manual setup.

**Not changed**
- Running from source stays exactly as it is. `run.ps1`, the venv and `uv pip install -e .` keep working, and the tests do not care whether the app is frozen.
