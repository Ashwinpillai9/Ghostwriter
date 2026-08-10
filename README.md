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

| Hotkey | Action |
| --- | --- |
| Hold `Ctrl+Space` | Dictate, paste on release — review it, then press Enter yourself |
| `Ctrl+Shift+D` | Toggle hands-free recording on/off |
| `Esc` | Discard the recording in progress |

All of these, plus the model and vocabulary, are configurable in `config.toml`.

## Wake word (hands-free)

Listening is on by default. Say the wake phrase, talk, and stop — the transcript is pasted
without you touching the keyboard. The utterance ends on whichever comes first:

- **Silence** — `endpoint.silence_timeout_sec` (default 1.2s) of quiet.
- **The stop key** — `Down` by default, when you want to cut it off immediately. This keeps
  the audio and transcribes it; `Esc` still discards.

Say the wake word with nothing after it and the recording is dropped silently after
`endpoint.lead_in_sec`.

Detection runs an openWakeWord ONNX model on the CPU over 80 ms frames — the Whisper GPU
model is only touched once the phrase fires, so idling costs almost nothing. The tray menu has
a **Listening for "…"** checkbox to mute the mic listener instantly.

Tuning knobs in `[endpoint]`: raise `silence_threshold` in a noisy room, raise
`silence_timeout_sec` if it cuts you off while you think.

### Training the "hey ghostwriter" wake word

openWakeWord has no pretrained model for "hey ghostwriter", so until you train one Ghostwriter
falls back to `wakeword.fallback_model` (`hey_jarvis` by default) and says so at startup. The
training config already exists at `models/hey_ghostwriter_training.yaml`; regenerate it with
`.venv\Scripts\python.exe scripts\train_wakeword.py` if you change the phrase.

Training needs a GPU and several GB of negative-audio datasets, so use the free Colab notebook:

1. Open [the openWakeWord training notebook][notebook].
2. **Runtime > Change runtime type > T4 GPU.** The free tier is enough.
3. Run the first setup cell, then restart the runtime if it asks.
4. Upload `models/hey_ghostwriter_training.yaml` via the file pane on the left, and set the
   notebook's config path to `./hey_ghostwriter_training.yaml`.
5. **Runtime > Run all.** Budget about an hour — most of it is dataset downloads, not training.
6. Download the resulting `hey_ghostwriter.onnx` from `my_custom_model/` in the file pane.
7. Save it to `models\hey_ghostwriter.onnx` and restart Ghostwriter.

It is picked up automatically, with no config edit. You know it worked when the startup banner
changes from `Say "hey jarvis"` to `Say "hey ghostwriter"`.

If it mishears you afterwards, lower `wakeword.threshold` toward 0.35 before retraining — that
costs nothing. If that isn't enough, retrain with `n_samples: 20000` and
`augmentation_rounds: 2`.

Any phrase works: `--phrase "hey scribe" --output models/hey_scribe.onnx`, then point
`wakeword.model_path` at it. The filename is also what the UI calls the phrase.

[notebook]: https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb

Text is never submitted for you — the transcript is pasted and left at the cursor so you can
read it and hit Enter yourself. If you later want a hands-free "dictate and send" key, set
`hotkeys.push_to_talk_send` to a chord (it is empty, and therefore disabled, by default).

Hotkeys are matched exclusively: a chord like `Ctrl+Shift+Space` will not also fire a
`Ctrl+Space` binding, even though `keyboard` on its own would let it. Note that `Ctrl+Space`
is IntelliSense in VS Code and set-mark in readline-based shells — both are suppressed while
Ghostwriter runs.

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
.venv\Scripts\python.exe -m pytest tests -q     # rules, endpointing, wake-word flow
.venv\Scripts\python.exe scripts\smoke_test.py  # model loads and decodes on GPU
.venv\Scripts\python.exe scripts\tts_test.py    # end-to-end, no microphone needed
```

`tts_test.py` synthesizes a phrase with Windows SAPI and transcribes it, so you can verify
the whole pipeline without speaking.

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
- **Wake word fires on its own.** Raise `wakeword.threshold` toward 0.7.
- **Wake word never fires.** Lower it toward 0.35, and check the tray checkbox is on. Remember
  you are saying the *fallback* phrase until you train the custom model.
- **It cuts me off mid-sentence.** Raise `endpoint.silence_timeout_sec`, or raise
  `endpoint.silence_threshold` if room noise is masking your pauses.
