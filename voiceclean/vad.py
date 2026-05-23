"""Voice Activity Detection via Silero VAD.

Silero VAD is an ONNX model (~2 MB) that runs in <1 ms per chunk on
CPU. Supports 8 kHz and 16 kHz natively — no resampling needed for
telephony audio.

Requires: pip install onnxruntime
The Silero model is downloaded automatically on first use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np


_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
_CACHE_DIR = Path.home() / ".cache" / "voiceclean"
_MODEL_PATH = _CACHE_DIR / "silero_vad.onnx"


@dataclass
class VADResult:
    is_speech: bool
    speech_prob: float


class VAD:
    """Voice activity detector backed by Silero VAD (ONNX).

    Args:
        sample_rate: Audio sample rate in Hz. Must be 8000 or 16000.
        threshold: Speech probability threshold. Default 0.5.
    """

    def __init__(self, sample_rate: int = 8000, threshold: float = 0.5) -> None:
        if sample_rate not in (8000, 16000):
            raise ValueError(f"Silero VAD supports 8000 or 16000 Hz, got {sample_rate}")

        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for VAD. "
                "Install it: pip install onnxruntime"
            )

        self._sample_rate = sample_rate
        self._threshold = threshold

        model_path = self._ensure_model()
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(str(model_path), sess_options=opts)

        # Silero VAD internal state — newer models use a single `state`
        # tensor (2, 1, 128) instead of separate h/c (2, 1, 64).
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

        # Frame size: Silero expects 512 samples at 16 kHz or 256 at 8 kHz
        self._frame_samples = 512 if sample_rate == 16000 else 256
        self._frame_bytes = self._frame_samples * 2
        self._buffer = bytearray()

    def _ensure_model(self) -> Path:
        if _MODEL_PATH.exists():
            return _MODEL_PATH

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        import urllib.request
        urllib.request.urlretrieve(_MODEL_URL, str(_MODEL_PATH))
        return _MODEL_PATH

    def process(self, audio: bytes) -> VADResult:
        """Detect speech in audio.

        Buffers audio internally and returns the VAD result for the
        most recent complete frame. If not enough audio has accumulated
        for a frame, returns is_speech=False.

        Args:
            audio: Raw PCM int16 mono bytes at self._sample_rate.

        Returns:
            VADResult with is_speech and speech_prob.
        """
        self._buffer.extend(audio)

        prob = 0.0
        while len(self._buffer) >= self._frame_bytes:
            frame = bytes(self._buffer[: self._frame_bytes])
            self._buffer = self._buffer[self._frame_bytes :]

            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            samples = samples.reshape(1, -1)

            ort_inputs = {
                "input": samples,
                "state": self._state,
                "sr": np.array(self._sample_rate, dtype=np.int64),
            }
            out, self._state = self._session.run(None, ort_inputs)
            prob = float(out[0][0])

        return VADResult(is_speech=prob >= self._threshold, speech_prob=prob)

    def reset(self) -> None:
        """Reset internal state (call between conversations)."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._buffer = bytearray()
