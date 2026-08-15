# Ghostwriter

A local, free Wispr Flow alternative for Windows. Hold a hotkey, talk, release — the text is
transcribed on your GPU and pasted into whatever window has focus. A second hotkey presses
Enter afterwards, which is what makes it useful for CLI tools and coding agents.

Nothing leaves the machine and there is no API key: transcription runs on `faster-whisper`
locally.

## Setup

```powershell
uv python install 3.12
uv venv --python 3.12
uv pip install -e .
```

First run downloads the Whisper model (~1.6 GB) into the Hugging Face cache.

## Run

```powershell
D:\Projects\Ghostwriter\run.ps1    # PowerShell
D:\Projects\Ghostwriter\run.cmd    # cmd.exe
```

Both launchers `cd` to the project directory themselves, so they work from any drive. Running
`.venv\Scripts\python.exe` by hand requires you to be in the project first — and in cmd,
switching drives needs `cd /d D:\Projects\Ghostwriter`, since a bare `cd` to another drive
silently does nothing.

A tray icon appears; the status pill shows above the taskbar while recording.

## The status pill

A 260×46 rounded pill that glows in the colour of whatever it is doing: blue recording, amber
transcribing, green pasted, red failed. Starting a recording plays a half-second activation —
the idle dot blooms, stretches into the 21-bar waveform, and a wave rolls out across the
display behind it.

The recording colour is `overlay.accent` in `config.toml`, and it tints the bars, glow, border,
bloom and wave together. The design's palette is `#38bdf8` blue (the default), `#ef4444` red,
`#22c55e` green and `#a855f7` purple. Only recording uses it — amber still means *working*,
green *done* and red *failed*, so those keep their meaning.

### Tuning it

Every colour and timing lives in `config.toml`, so none of this needs a code edit:

| Where | What |
| --- | --- |
| `[overlay]` | `accent`, `frame_ms` (16 ≈ 60fps), `activate_ms`, `rings_ms`, `hold_ms` |
| `[overlay.colors]` | the per-state colours — `idle`, `transcribing`, `done`, `error`, `moving` |
| `[overlay.wave]` | `enabled`, `crests`, `duration_ms`, `stagger_ms`, `intensity`, `falloff`, `band_steps`, `band_step_px`, `buffer_width`, `overshoot`, `start_radius`, `flash_ms`, `flash_rings`, `halos`, `cores` |

The two you are most likely to reach for: **`intensity`** is peak brightness at the centre of a
crest — past about `1.4` the crests clip and read as flat painted rings rather than light —
and **`falloff`** decides how tightly that light concentrates into the core. **`buffer_width`**
trades crispness against CPU, roughly linearly (960 ≈ 5 ms a frame, 1280 ≈ 7 ms), and
`enabled = false` turns the wave off entirely while leaving the pill alone.

Anything missing, mistyped or out of range logs one warning at startup and falls back to its
default for that key alone — a bad colour never reaches the render loop.

None of that is drawn by Tk. A Tk canvas has no antialiasing, no rounded window, no blur and
no per-element opacity, so each frame is composed with Pillow in `ghostwriter/pill.py` and
handed to Win32's `UpdateLayeredWindow`, which accepts a full alpha channel. Tk still owns the
window, the event loop and the input handling. Transparent pixels are click-through, so the
padding that gives the glow room never swallows a click meant for the window behind it.

**The activation wave** fills whichever display the pill is on. It is a second, click-through
window covering that monitor, so the crests sweep over your other applications without
interrupting anything — they cannot receive a click at all.

Drawing it at display resolution in Pillow costs ~119 ms a frame (8fps). The trick is that the
expensive part was never the pixels, it was doing per-pixel work in Python: the wave is drawn
into a 960px-wide buffer and GDI's `StretchBlt` scales it across the display for ~0.9 ms, with
the fullscreen `UpdateLayeredWindow` costing another ~0.8 ms.

Nothing is blurred, either. A Gaussian blur is priced by area — ~6.7 ms whatever the radius —
which capped the buffer resolution; each crest draws its own falloff as concentric bands, which
is priced by perimeter. A whole frame, pill and wave together, measures ~9 ms against the 16 ms
a 60fps budget allows. The pill's cached chrome is built a frame at a time while it sits idle,
so the first activation animates as smoothly as the tenth.

**Moving the pill.** Drag it whenever it is visible. Since it hides itself when idle, the tray
menu has a **Move overlay** item that brings it up on demand — drag it and let go. The position
is remembered in `overlay_position.json`.

Multiple monitors are supported: drag it to any display. It is clamped to the work area of
whichever monitor it is nearest, so it cannot be lost off-screen or parked under the taskbar.
Tk's own `winfo_screenwidth` describes only the primary monitor, so the bounds come from the
Win32 virtual-desktop metrics instead.

| Hotkey | Action |
| --- | --- |
| Hold `Right Alt` | Dictate, paste on release — review it, then press Enter yourself |
| `Ctrl+Shift+D` | Toggle hands-free recording on/off |
| `Esc` | Discard the recording in progress |

Right Alt is the default because it is the one key on a PC keyboard that nothing else claims:
no editor, shell or browser binds it, so holding it steals nothing. Left Alt is untouched —
`Alt+Tab` and menu access keep working.

All of these, plus the model and vocabulary, are configurable in `config.toml`.

## Wake word (hands-free)

Say **"hey ghost"**, talk, and stop — the transcript is pasted without you touching the
keyboard. It works on a fresh clone with nothing to train and nothing to configure.

The utterance ends on whichever comes first:

- **Silence** — `endpoint.silence_timeout_sec` (default 1.2s) of quiet.
- **The stop key** — `Down` by default, when you want to cut it off immediately. This keeps
  the audio and transcribes it; `Esc` still discards.

Say the wake word with nothing after it and the recording is dropped silently after
`endpoint.lead_in_sec`.

The tray menu has a **Listening for "…"** checkbox to mute the mic listener instantly, and
`wakeword.enabled = false` turns it off for good.

Tuning knobs in `[endpoint]`: raise `silence_threshold` in a noisy room, raise
`silence_timeout_sec` if it cuts you off while you think.

### How it detects the phrase without a trained model

The usual approach — openWakeWord — needs a small ONNX classifier trained per phrase, on a GPU
box with several GB of negative-audio datasets. There is no pretrained "hey ghost", so that
route would leave everyone saying `hey jarvis` until they spent an hour in Colab.

The default `whisper` backend skips that entirely:

1. **Silero VAD** watches the microphone. It is tiny, runs on the CPU, and already ships
   inside `faster-whisper` — no extra dependency.
2. When a burst of speech ends, that ~2.5s of audio goes to **`tiny.en`** (~75 MB, CPU, int8),
   biased toward the phrase with an initial prompt.
3. The transcript is matched against `wakeword.phrase` and `wakeword.aliases`, fuzzily, so
   `"Hey, ghost."` and `"hey ghosts"` both count while `"the ghost writer branch"` does not.

The GPU dictation model is still only touched once the phrase fires. A plain loudness gate was
the obvious cheaper choice and does not work: on a laptop mic array with automatic gain the
idle noise floor alone reads as speech, so the decoder would never stop.

**Changing the phrase** is a one-line edit — set `wakeword.phrase` and restart. Nothing to
train, nothing to download. Add spellings to `wakeword.aliases` if Whisper writes your phrase
a way the fuzzy match misses; run `scripts\wakeword_test.py --phrase "…"` to see what it does.

**Cost.** In a quiet room the decoder is idle. In a noisy one, or on a mic with aggressive
auto-gain, it wakes at most once every 2s for about 180 ms of one core — roughly 9% of a
single core, worst case. Raise `wakeword.vad_threshold` toward 0.8 to cut that down.

### Optional: the openWakeWord backend

If you would rather pay nothing at all in a permanently noisy room, train a classifier and set
`wakeword.backend = "openwakeword"`. `scripts\train_wakeword.py` writes the training config
(`models/hey_ghost_training.yaml`); training runs in [the official Colab notebook][notebook]
on a free T4 in about an hour, mostly dataset downloads. Drop the resulting `.onnx` in
`models\`, point `wakeword.model_path` at it, and set `wakeword.threshold` back to `0.5` —
that key means "fuzzy match ratio" for the whisper backend and "model confidence" for this one.

Without a model file this backend falls back to `wakeword.fallback_model` (`hey_jarvis`) and
says so at startup.

[notebook]: https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

Text is never submitted for you — the transcript is pasted and left at the cursor so you can
read it and hit Enter yourself. If you later want a hands-free "dictate and send" key, set
`hotkeys.push_to_talk_send` to a chord (it is empty, and therefore disabled, by default).

Hotkeys are matched exclusively: a chord like `Ctrl+Shift+Space` will not also fire a
`Ctrl+Space` binding, even though `keyboard` on its own would let it. Pick your binding with
that in mind — `Ctrl+Space` is IntelliSense in VS Code and set-mark in readline-based shells,
and a bound key is suppressed everywhere while Ghostwriter runs.

Side-specific keys are bound by scan code rather than by name, because `keyboard` resolves the
name `right alt` to *both* Alt keys; binding the name would swallow Left Alt and with it
`Alt+Tab`. `right alt`, `left alt` and `altgr` are understood in `config.toml`.

## How text gets delivered

The transcript goes onto the clipboard, `Ctrl+V` is sent, and the previous clipboard contents
are restored ~0.35s later. This is far more reliable than simulated typing in terminals and
handles Unicode correctly.

Two caveats:

- Only *text* clipboard contents are restored. If you had an image copied, it is lost.
- If pastes occasionally come out empty, raise `output.clipboard_restore_delay`.

Set `output.paste = false` to fall back to character-by-character typing for apps that block
paste.

## Post-processing

Raw Whisper output is cleaned with local rules only — no LLM, no added latency:

- Spoken punctuation: "comma", "period", "new line", "open paren", …
- Filler removal: "um", "uh", "you know", …
- Capitalisation and trailing punctuation
- Literal find/replace from `[postprocess.replacements]` — the place to fix CLI names and
  jargon that Whisper consistently mangles

Words in `model.vocabulary` are fed to Whisper as an initial prompt, which biases decoding
toward your project's terminology. Prefer this over `replacements` where it works.

## GPU notes

This targets an RTX 50-series (Blackwell, sm_120) card, which has two sharp edges:

- `compute_type` must be `float16`. `int8_float16` crashes with
  `CUBLAS_STATUS_NOT_SUPPORTED` because Blackwell's INT8 tensor cores need padding that
  CTranslate2 doesn't emit.
- CTranslate2 loads `cublas64_12.dll` and cuDNN 9 at runtime but bundles neither. They come
  from the `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` wheels, and `ghostwriter/cuda_paths.py`
  puts their DLL directories on the search path before the model loads.

If CUDA fails for any reason, `Transcriber._load` falls back to CPU `int8` automatically —
much slower, but it still works. The model is warmed up with a dummy decode at startup so
CUDA problems surface immediately rather than on your first dictation.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q        # rules, endpointing, hotkeys, wake word
.venv\Scripts\python.exe scripts\smoke_test.py     # model loads and decodes on GPU
.venv\Scripts\python.exe scripts\tts_test.py       # end-to-end, no microphone needed
.venv\Scripts\python.exe scripts\wakeword_test.py  # the wake word actually fires, and only
```

`tts_test.py` synthesizes a phrase with Windows SAPI and transcribes it, so you can verify
the whole pipeline without speaking. `wakeword_test.py` does the same for the wake word: it
speaks both phrases that should fire and phrases that should not, and reports each verdict.

## Autostart

Put a shortcut to `run.ps1` in `shell:startup`, or use Task Scheduler with "Run at logon" if
you want it hidden.

## Troubleshooting

- **Hotkeys do nothing in an elevated window.** Windows blocks input from a lower-privilege
  process. Run Ghostwriter as administrator too.
- **First dictation is slow.** Model load takes a few seconds; recordings made before it
  finishes are queued, not dropped.
- **Wrong microphone.** Set `audio.device` to part of the device name. It applies to both the
  wake-word listener and the recorder.
- **Right Alt does nothing.** Some laptops map it to AltGr, which reports as Ctrl+Alt; that is
  handled. If your layout uses AltGr to type `@` or `€`, bind something else — a suppressed
  Right Alt cannot also type characters.
- **Wake word fires on its own.** Raise `wakeword.threshold` toward 0.9.
- **Wake word never fires.** Lower it toward 0.7, and check the tray checkbox is on. Run
  `scripts\wakeword_test.py` to see what the decoder actually hears.
- **Wake word listener uses noticeable CPU.** Your mic is never quiet enough for the VAD to
  close. Raise `wakeword.vad_threshold` toward 0.8.
- **It cuts me off mid-sentence.** Raise `endpoint.silence_timeout_sec`, or raise
  `endpoint.silence_threshold` if room noise is masking your pauses.
