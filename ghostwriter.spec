# PyInstaller build. Run with:  pyinstaller ghostwriter.spec --noconfirm
#
# onedir, never onefile: onefile re-extracts its whole payload to a temporary directory on
# *every* launch, and this payload is large. For something meant to start with Windows that is
# a visible delay every single time.
#
# The NVIDIA CUDA runtime is excluded. It is 1.94 GB of a 2.23 GB payload and useless without an
# NVIDIA card, so `ghostwriter/bootstrap.py` fetches it on first run and only where it will
# actually be used. Everyone else gets a ~350 MB download and CPU transcription, which
# `Transcriber._load` already falls back to.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# Native dependencies PyInstaller's analysis does not fully trace on its own.
hidden = [
    "ctranslate2",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "sounddevice",
    "_sounddevice_data",
    "pystray._win32",
    "PIL._tkinter_finder",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
    "tomlkit",
]

datas = [
    # The settings window is HTML/CSS/JS on disk, not importable code, so it has to be named.
    ("ghostwriter/settings/ui", "ghostwriter/settings/ui"),
    # Shipped as the template a first run copies to %APPDATA%; its comments are the manual.
    ("config.toml", "."),
]
datas += collect_data_files("faster_whisper")      # the bundled Silero VAD model
datas += collect_data_files("sounddevice")
datas += collect_data_files("webview")

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

analysis = Analysis(
    ["ghostwriter/__main__.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    # Fetched at first run into the per-user runtime directory instead of shipped.
    excludes=["nvidia", "pytest", "tkinter.test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Ghostwriter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No console: this is a tray application, and one window flashing up at logon every day
    # would be its most memorable feature.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Ghostwriter",
)
