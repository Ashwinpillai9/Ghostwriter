"""Verifies the model loads on the GPU and decodes without cuBLAS errors."""

import time

import numpy as np

from ghostwriter.postprocess import clean
from ghostwriter.transcribe import Transcriber

t0 = time.time()
tr = Transcriber(name="large-v3-turbo", device="cuda", compute_type="float16")
print(f"model load: {time.time() - t0:.1f}s")

audio = (0.02 * np.random.randn(16000 * 3)).astype("float32")
t0 = time.time()
out = tr.transcribe(audio)
print(f"decode: {time.time() - t0:.2f}s -> {out!r}")

sample = "um so run the tests comma then uh commit new line get hub actions should pass"
print("postprocess:", clean(sample, {"replacements": {"get hub": "GitHub"}}))
