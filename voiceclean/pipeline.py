"""Combined pipeline: AEC → Denoise → VAD.

The VoiceClean class chains all three components and exposes a single
process() call. Components are optional — if a dependency is missing,
that stage is skipped with a warning.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    audio: bytes
    is_speech: bool
    speech_prob: float


class VoiceClean:
    """Full audio cleanup pipeline: AEC → noise suppression → VAD.

    Args:
        sample_rate: Audio sample rate in Hz (default 8000).
        aec_filter_length: SpeexDSP adaptive filter length in samples.
        aec_frame_size: AEC frame size in samples.
        vad_threshold: Speech probability threshold for VAD.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        aec_filter_length: int = 1600,
        aec_frame_size: int = 160,
        vad_threshold: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate

        self._aec = None
        self._denoiser = None
        self._vad = None

        try:
            from voiceclean.aec import AEC
            self._aec = AEC(
                sample_rate=sample_rate,
                frame_size=aec_frame_size,
                filter_length=aec_filter_length,
            )
        except (ImportError, OSError) as e:
            logger.warning("AEC disabled — libspeexdsp not available: %s", e)

        try:
            from voiceclean.denoise import Denoiser
            self._denoiser = Denoiser(sample_rate=sample_rate)
        except ImportError:
            logger.warning("pyrnnoise not installed — noise suppression disabled")

        try:
            from voiceclean.vad import VAD
            self._vad = VAD(sample_rate=sample_rate, threshold=vad_threshold)
        except ImportError:
            logger.warning("onnxruntime not installed — VAD disabled")

    @property
    def has_aec(self) -> bool:
        return self._aec is not None

    @property
    def has_denoiser(self) -> bool:
        return self._denoiser is not None

    @property
    def has_vad(self) -> bool:
        return self._vad is not None

    def feed_reference(self, audio: bytes) -> None:
        """Feed outgoing (bot) audio as AEC reference signal."""
        if self._aec is not None:
            self._aec.feed_reference(audio)

    def process(self, mic_audio: bytes) -> ProcessResult:
        """Run the full pipeline: AEC → denoise → VAD.

        Args:
            mic_audio: Raw PCM int16 mono bytes from the caller's mic.

        Returns:
            ProcessResult with cleaned audio, is_speech, and speech_prob.
        """
        audio = mic_audio

        if self._aec is not None:
            audio = self._aec.process(audio)

        if self._denoiser is not None:
            denoised = self._denoiser.process(audio)
            if denoised:
                audio = denoised

        is_speech = False
        speech_prob = 0.0
        if self._vad is not None:
            vad_result = self._vad.process(audio)
            is_speech = vad_result.is_speech
            speech_prob = vad_result.speech_prob

        return ProcessResult(
            audio=audio,
            is_speech=is_speech,
            speech_prob=speech_prob,
        )
