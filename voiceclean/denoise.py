"""Neural noise suppression via RNNoise.

RNNoise operates at 48 kHz internally (480 samples per frame). This
wrapper handles resampling from the caller's sample rate (typically
8 kHz) to 48 kHz and back transparently.

Requires: pip install pyrnnoise
"""
from __future__ import annotations

import numpy as np

from voiceclean.resample import resample


# RNNoise native parameters
_RNNOISE_RATE = 48000
_RNNOISE_FRAME_SAMPLES = 480
_RNNOISE_FRAME_BYTES = _RNNOISE_FRAME_SAMPLES * 2  # int16


class Denoiser:
    """Noise suppression backed by RNNoise.

    Args:
        sample_rate: Input/output sample rate in Hz. Audio is resampled
            to 48 kHz internally for RNNoise processing.
    """

    def __init__(self, sample_rate: int = 8000) -> None:
        try:
            from pyrnnoise import RNNoise
        except ImportError:
            raise ImportError(
                "pyrnnoise is required for noise suppression. "
                "Install it: pip install pyrnnoise"
            )

        self._sample_rate = sample_rate
        self._rnnoise = RNNoise(sample_rate=sample_rate)

    def process(self, audio: bytes) -> bytes:
        """Remove background noise from audio.

        Args:
            audio: Raw PCM int16 mono bytes at self._sample_rate.

        Returns:
            Denoised PCM int16 mono bytes at self._sample_rate.
        """
        if len(audio) == 0:
            return audio

        samples = np.frombuffer(audio, dtype=np.int16)
        # denoise_chunk expects [channels, samples] — mono = [1, N]
        chunk = samples.reshape(1, -1)

        out_chunks = []
        for _prob, denoised in self._rnnoise.denoise_chunk(chunk):
            out_chunks.append(denoised.flatten().astype(np.int16).tobytes())

        if not out_chunks:
            return b""

        return b"".join(out_chunks)
