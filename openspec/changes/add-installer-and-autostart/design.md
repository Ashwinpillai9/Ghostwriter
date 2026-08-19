## Context

Ghostwriter runs from a source checkout: a `uv` venv, `run.ps1`, and a README telling you to make a Startup shortcut by hand. Everything below follows from three measurements and one existing limitation.

**The payload is lopsided.** `site-packages` is 2.23 GB, of which the NVIDIA CUDA runtime is **1.94 GB** and everything else is **0.29 GB**. The Whisper model is another 1.6 GB and already downloads itself on first use.

**CUDA is optional at runtime.** `Transcriber._load` already falls back to CPU `int8` when the CUDA path fails, and that fallback is exercised. A build with no CUDA is a working build.

**Hotkeys are blocked over elevated windows.** Windows does not deliver input to a lower-privilege process, so a normally-launched Ghostwriter goes deaf whenever an admin terminal has focus. The troubleshooting notes describe this as something the user must solve by launching Ghostwriter as administrator themselves.

**Verified while planning:** `nvidia-smi.exe` lives in `System32` (it ships with the driver, not the toolkit) and `Win32_VideoController` lists adapter names — so an NVIDIA card can be detected without any CUDA present, which the first-run fetch depends on.

## Goals / Non-Goals

**Goals**

- One command installs it, on a machine with nothing installed.
- Download what the machine can use, not what some machines can use.
- Start with Windows, and work over elevated windows while doing so.
- The same command updates and removes it.
- Running from source is completely unaffected.

**Non-Goals**

- Code signing. Distribution is to a few people who trust the source; SmartScreen will warn and the release notes will say so. Nothing here prevents adding signing later.
- An MSI, an Add/Remove Programs entry, or a Microsoft Store package.
- Bundling the Whisper model. It is 1.6 GB, `faster-whisper` already fetches it on demand, and it is shared with anything else using the same cache.
- Auto-update. The install command updates; nothing checks for versions on its own.
- macOS or Linux packaging.

## Decisions

### A PowerShell one-liner, not an installer executable

`irm https://.../install.ps1 | iex` is the Windows idiom for developer tools — `uv`, rustup, Bun and Deno all use it — and it avoids a specific problem: an unsigned `.exe` triggers SmartScreen's "Windows protected your PC" for every user, and this will not be signed. A script fetched over HTTPS does not meet the same wall.

It also collapses install, update and uninstall into one artifact, hosted on GitHub Releases with no build infrastructure.

*Alternative considered:* Inno Setup. More familiar to non-technical users and gives an Add/Remove Programs entry, but the SmartScreen warning lands on every user while unsigned, and it is the most build machinery of the options. Worth revisiting if the audience widens.

*Also available for free:* the wheel already includes the settings UI assets, so `uv tool install git+…` works for anyone who has `uv`. Worth documenting as a developer route; not the headline, since it needs Python 3.12 and builds from source.

### PyInstaller onedir, with CUDA excluded

`--onedir`, never `--onefile`: onefile re-extracts its whole payload to a temporary directory on **every launch**, which for a payload this size is a visible delay on something meant to start with Windows.

The `nvidia/*` packages are excluded from the bundle. That takes the download from ~2.3 GB to ~350 MB and is invisible to anyone without an NVIDIA GPU, who gets working CPU dictation.

### First run fetches, rather than the installer bundling

The installer stays small and fast for everyone; the machine that can use CUDA is the only one that downloads it.

Detection uses `nvidia-smi` or `Win32_VideoController` — both available without the CUDA toolkit, confirmed on the development machine. The runtime is then fetched as the same `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` wheels `pyproject.toml` already pins, unpacked beside the program files.

`cuda_paths.ensure()` currently walks `sys.path` for `nvidia/*/bin`. It must also look where the bootstrap unpacks them, since in a frozen build there is no `site-packages` to walk. That is the one existing module this genuinely changes.

The model is left to `faster-whisper`, which already downloads on first use into the shared Hugging Face cache. The bootstrap only triggers it early, so the wait happens once at a moment the user expects rather than on their first dictation.

*Failure is not terminal:* no internet means Ghostwriter says what it could not fetch and runs anyway — on the CPU, or waiting for the model. It retries next start. Reinstalling should never be the remedy for a bad network moment.

### Task Scheduler, not a Run key

A logon task with **run with highest privileges**, because it fixes the elevated-window limitation rather than merely starting the app. A `Run` key or Startup shortcut cannot: both launch unelevated, so hotkeys stay dead over an admin terminal.

The cost is one elevation prompt when auto-start is enabled — at install, or when the settings toggle is switched on. Consent is asked for at the moment the user asks for the thing that needs it, and declining leaves auto-start off rather than half-configured.

Registered per-user (`/tn Ghostwriter`, `/sc onlogon`), so it does not touch other accounts.

### Auto-start state lives in Windows, not in config.toml

Auto-start is the one setting that is **not** written to `config.toml`. It is a property of the machine, and the file is copied between machines and edited by hand. Storing a preference that could disagree with reality invites exactly the confusion the settings window exists to remove.

The settings window therefore queries the task itself. If the user deletes the task in Windows' own tools, Ghostwriter reports auto-start as off, because it is.

### One executable, dispatched by argument

`App.open_settings` currently launches `sys.executable -m ghostwriter.settings`. In a frozen build `sys.executable` is `Ghostwriter.exe` and there is no `-m`, so **this is broken today for any packaged build** — found while planning, not after building.

The fix is `Ghostwriter.exe --settings [config path]`, dispatched in `main()`. One executable, one code path whether frozen or not, and the source route keeps working unchanged.

## Risks / Trade-offs

**SmartScreen will warn.** Unsigned, so the first run shows "Windows protected your PC" and the user must click through. Accepted for a handful of trusted users; documented in the release notes. A certificate is a few hundred dollars a year and can be added without reworking any of this.

**Elevated all the time is a real trade.** Running Ghostwriter with highest privileges is what makes hotkeys work everywhere, and it also means a bug in it runs elevated. Mitigated by it being a local app with no network surface after the first-run fetch — but it is a genuine widening, not a free win.

**First run needs internet.** Unavoidable given the decision not to ship 2 GB. Handled by degrading rather than failing, but a machine that is offline on first run is not usable for dictation until it is not.

**PyInstaller and native dependencies.** `ctranslate2`, `onnxruntime`, `sounddevice` and `pywebview` all carry binaries, and PyInstaller's dependency detection is good but not perfect. Expect to name hidden imports and data files explicitly, and treat "it built" as different from "it runs on a machine that never had Python".

**Two ways to be installed.** From source and installed-from-release will drift unless tested both ways. `cuda_paths` and the settings-window launch are the two places already known to differ.

**The task is per-user.** Someone with several Windows accounts registers it per account. Correct behaviour, but worth stating so it does not read as a bug.
