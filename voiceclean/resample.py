"""High-quality resampling via soxr.

Used internally to bridge between telephony sample rates (8 kHz) and
RNNoise's required 48 kHz. Not part of the public API but can be
used standalone if needed.
"""
from __future__ import annotations

import numpy as np
import soxr


def resample(audio: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample PCM int16 mono audio between sample rates.

    Returns empty bytes if from_rate == to_rate (no-op).
    """
    if from_rate == to_rate or len(audio) == 0:
        return audio

    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
    resampled = soxr.resample(samples, from_rate, to_rate)
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()
