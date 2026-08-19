# Ghostwriter

A local, free Wispr Flow alternative for Windows. Hold a hotkey, talk, release — the text is
transcribed and pasted into whatever window has focus. A second hotkey presses Enter afterwards,
which is what makes it useful for CLI tools and coding agents.

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

Run one of the launchers rather than `python` directly — they `cd` into the project first, so
they work from any drive.

A tray icon appears; the status pill shows above the taskbar while recording.

## Models

Three models, each doing a different job:

| Purpose | Model | Runs on | Config |
| --- | --- | --- | --- |
| Dictation (transcribes your speech) | `model.name`, default `large-v3-turbo` (~1.6 GB) | GPU (`cuda`/`float16`), auto-falls back to CPU `int8` | `[model]` |
| Wake-word check ("hey ghost") | `tiny.en` (~75 MB) | CPU only, always | `[wakeword]` |
| Voice activity (start/stop detection) | Silero VAD | CPU, bundled with `faster-whisper` | `[endpoint]`, `[wakeword]` |

Drop `model.name` to `small.en` or `base.en` for faster, less accurate dictation. See "GPU
notes" for the CUDA fallback, and "Wake word" for why that one stays on the CPU.

## The status pill

A rounded pill above the taskbar that glows by state: blue recording, amber transcribing, green
pasted, red failed. Colors, animation timing and the activation wave are all tunable in
`config.toml` under `[overlay]`, `[overlay.colors]` and `[overlay.wave]` — a bad or missing key
just logs a warning and falls back to its default, never crashes the render loop.

**Moving it:** drag it whenever it's visible, or use the tray menu's **Move overlay** to bring
it up on demand. Position is remembered and works across multiple monitors.

| Hotkey | Action |
| --- | --- |
| Double-tap `Right Ctrl`, hold the second tap | Dictate, paste on release — review it, then press Enter yourself |
| `Ctrl+Shift+D` | Toggle hands-free recording on/off |
| `Esc` | Discard the recording in progress |

Right Ctrl is the default because no editor, shell or browser binds it. A single tap — including
one held for an ordinary `Ctrl+C`/`Ctrl+V` — is never suppressed and never starts dictation; only
a **second** tap within 0.4s of the first tap's release arms it. Hold that second tap to record,
release to stop and paste.

All of this, plus the model and vocabulary, is configurable in `config.toml`.

**Applying changes:** just save `config.toml`. Ghostwriter notices about half a second later and
applies almost everything live — hotkeys, wake word, endpointing, overlay colours and animation,
vocabulary, post-processing and the microphone — then says so on the pill. The tray menu's
**Reload config** does the same on demand.

Only the dictation model (`model.name`, `model.device`, `model.compute_type`) and
`audio.sample_rate` need a restart. The pill names them when you save, so you are not left
wondering why nothing happened. A file with a syntax error is reported on the pill and ignored;
the running config is left alone until you fix it.

## Wake word (hands-free)

Say **"hey ghost"**, talk, and stop — the transcript is pasted without touching the keyboard.
Works out of the box, nothing to train.

The utterance ends on whichever comes first:

- **Silence** — `endpoint.silence_timeout_sec` (default 1.2s) of quiet.
- **The stop key** — `Down` by default, to cut it off immediately and still transcribe. `Esc`
  discards instead.

But never before `endpoint.min_recording_sec` (default 4s), which is an absolute floor — a
pause to think, or taking a moment to start, will not cut you off. Raise it for long-form
dictation; the cost is that an accidental wake word holds the microphone open for that long,
until you press the stop key or `Esc`.

Say the wake word with nothing after it and the recording drops silently once that floor and
`endpoint.lead_in_sec` have both passed.

The tray menu has a **Listening for "…"** checkbox to mute the mic listener, and
`wakeword.enabled = false` turns it off for good.

**If it never stops on its own**, run `scripts\mic_check.py` — it records you silent then
talking, and tells you either "fine" or the exact `endpoint.vad_threshold` to set. (Detection
uses a voice-activity model, not raw loudness, because a laptop mic's automatic gain makes a
fixed volume threshold unreliable.)

Other tuning knobs in `[endpoint]`: raise `vad_threshold` if a noisy room holds the recording
open, lower it if you get cut off mid-sentence, and raise `silence_timeout_sec` if it cuts you
off while you think.

**Changing the phrase** is a one-line edit — set `wakeword.phrase` and restart, nothing to
train or download. Add spellings to `wakeword.aliases` if the fuzzy match misses your phrasing;
run `scripts\wakeword_test.py --phrase "…"` to check. In a quiet room the decoder is idle; in a
noisy one it wakes at most once every 2s for ~180ms of one core.

Text is never submitted for you — it's pasted and left at the cursor so you can read it and hit
Enter yourself. For a hands-free "dictate and send" key, set `hotkeys.push_to_talk_send` to a
chord (empty/disabled by default).

Hotkeys match exclusively — `Ctrl+Shift+Space` won't also fire a `Ctrl+Space` binding — and a
bound key is suppressed from every other app while Ghostwriter runs (`hotkeys.suppress = false`
to hand a clashing key back).

## How text gets delivered

The transcript goes onto the clipboard, `Ctrl+V` is sent, and the previous clipboard contents
are restored ~0.35s later. More reliable than simulated typing and handles Unicode correctly.

- Only *text* clipboard contents are restored; a copied image is lost.
- If pastes occasionally come out empty, raise `output.clipboard_restore_delay`.
- Set `output.paste = false` to fall back to character-by-character typing for apps that block
  paste.

## Post-processing

Raw Whisper output is cleaned with local rules only — no LLM, no added latency:

- Spoken punctuation: "comma", "period", "new line", "open paren", …
- Filler removal: "um", "uh", "you know", …
- Capitalisation and trailing punctuation
- Literal find/replace from `[postprocess.replacements]` — for CLI names Whisper mangles

Words in `model.vocabulary` bias decoding toward your terminology as an initial prompt; prefer
that over `replacements` where it works.

## GPU notes

Targets an RTX 50-series (Blackwell) card: `model.compute_type` must be `float16` —
`int8_float16` crashes with `CUBLAS_STATUS_NOT_SUPPORTED` on this architecture.

If CUDA fails for any reason, it falls back to CPU `int8` automatically (slower, but it works),
and a startup warmup surfaces GPU problems immediately rather than on your first dictation.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q        # rules, endpointing, hotkeys, wake word
.venv\Scripts\python.exe scripts\smoke_test.py     # model loads and decodes on GPU
.venv\Scripts\python.exe scripts\tts_test.py       # end-to-end, no microphone needed
.venv\Scripts\python.exe scripts\wakeword_test.py  # the wake word actually fires, and only then
.venv\Scripts\python.exe scripts\mic_check.py      # will dictation stop on its own in your room
.venv\Scripts\python.exe scripts\keyboard_probe.py # what a real keypress actually sends
```

`tts_test.py` and `wakeword_test.py` synthesize speech with Windows SAPI, so you can verify the
pipeline without talking.

## Autostart

Put a shortcut to `run.ps1` in `shell:startup`, or use Task Scheduler with "Run at logon" for a
hidden start.

## Troubleshooting

- **Hotkeys do nothing in an elevated window.** Windows blocks input from a lower-privilege
  process. Run Ghostwriter as administrator too.
- **A key stops working in other apps while Ghostwriter runs.** Bound keys are suppressed by
  default. Set `hotkeys.suppress = false` to hand them back, or rebind the clashing key.
- **First dictation is slow.** Model load takes a few seconds; recordings made before it
  finishes are queued, not dropped.
- **Wrong microphone.** Set `audio.device` to part of the device name (applies to both the
  wake-word listener and the recorder).
- **Right Alt does nothing** (if configured as `push_to_talk`). Some laptops map it to AltGr;
  that's handled, but a suppressed Right Alt still can't type `@`/`€` on those layouts — bind
  something else. This is why `right ctrl` is the default instead.
- **Right Ctrl does nothing.** It needs a double-tap, then hold the second tap — a single press
  is deliberately ignored. If a genuine double-tap-and-hold still does nothing, run
  `scripts\keyboard_probe.py` and press it a few times; if it prints `name='ctrl'` or
  `name='left ctrl'` for a press you're sure was the right-hand key, a keyboard-utility app
  (Razer Synapse, Logitech Options, a laptop's Fn-key software) is remapping it before Windows
  sees it — check there.
- **Wake word fires on its own.** Raise `wakeword.threshold` toward 0.9.
- **Wake word never fires.** Lower it toward 0.7, check the tray checkbox is on, and run
  `scripts\wakeword_test.py` to see what the decoder actually hears.
- **Wake word listener uses noticeable CPU.** Raise `wakeword.vad_threshold` toward 0.8.
- **It cuts me off mid-sentence.** Raise `endpoint.silence_timeout_sec`, or
  `endpoint.silence_threshold` if room noise is masking your pauses.
