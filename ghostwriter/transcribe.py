"""faster-whisper wrapper. The model is loaded once and reused for every utterance."""

from __future__ import annotations

import logging

import numpy as np

from . import cuda_paths

log = logging.getLogger(__name__)

# Short aliases so config.toml doesn't need full HF repo ids.
MODEL_ALIASES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


class Transcriber:
    def __init__(
        self,
        name: str = "large-v3-turbo",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "en",
        vocabulary: list[str] | None = None,
        vad: bool = True,
    ):
        self.language = language or None
        self.vad = vad
        # Whisper biases toward words seen in the prompt, which fixes most jargon misfires.
        self.initial_prompt = ", ".join(vocabulary) if vocabulary else None
        self._model = self._load(MODEL_ALIASES.get(name, name), device, compute_type)

    @staticmethod
    def _load(repo: str, device: str, compute_type: str):
        if device == "cuda":
            cuda_paths.ensure()
        from faster_whisper import WhisperModel

        try:
            model = WhisperModel(repo, device=device, compute_type=compute_type)
            Transcriber._warmup(model)
            return model
        except Exception as exc:
            if device != "cuda":
                raise
            # CUDA problems surface on the first encode, not at construction: missing
            # cuBLAS/cuDNN DLLs, or int8 kernels that Blackwell (sm_120) rejects.
            log.warning("CUDA path failed (%s); falling back to CPU int8", exc)
            return WhisperModel(repo, device="cpu", compute_type="int8")

    @staticmethod
    def _warmup(model) -> None:
        """Force a real encode so CUDA/DLL failures happen at startup, not mid-dictation."""
        silence = np.zeros(16000, dtype=np.float32)
        list(model.transcribe(silence, vad_filter=False, without_timestamps=True)[0])

    def transcribe(self, audio: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=self.vad,
            vad_parameters={"min_silence_duration_ms": 300},
            initial_prompt=self.initial_prompt,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
