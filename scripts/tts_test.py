"""End-to-end check without a microphone: synthesize speech with Windows SAPI, then decode it."""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from ghostwriter.postprocess import clean
from ghostwriter.transcribe import Transcriber

PHRASE = "Run the test suite comma then commit the changes period"

wav_path = Path(tempfile.gettempdir()) / "ghostwriter_tts.wav"
ps = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    f"$s.SetOutputToWaveFile('{wav_path}'); $s.Speak('{PHRASE}'); $s.Dispose()"
)
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

with wave.open(str(wav_path), "rb") as w:
    rate, frames = w.getframerate(), w.readframes(w.getnframes())
audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
if rate != 16000:  # crude linear resample, good enough for a smoke test
    idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
    audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)

tr = Transcriber(name="large-v3-turbo", device="cuda", compute_type="float16")
raw = tr.transcribe(audio)
print("raw       :", repr(raw))
print("cleaned   :", repr(clean(raw, {})))
sys.exit(0 if raw else 1)
