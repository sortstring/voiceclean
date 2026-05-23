"""Pipecat VADAnalyzer implementation backed by voiceclean's Silero VAD."""
from __future__ import annotations

import numpy as np
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams

from voiceclean.pipeline import VoiceClean


class VoiceCleanVAD(VADAnalyzer):
    """VAD analyzer that queries voiceclean's Silero VAD.

    Designed to share a VoiceClean instance with VoiceCleanFilter so the
    same audio pipeline (AEC → denoise → VAD) feeds both the filter and
    the turn detector.
    """

    def __init__(
        self,
        vc: VoiceClean,
        sample_rate: int = 8000,
    ) -> None:
        params = VADParams(
            confidence=0.5,
            start_secs=0.0,
            stop_secs=0.0,
            min_volume=0.0,
        )
        super().__init__(sample_rate=sample_rate, params=params)
        self._vc = vc

    def num_frames_required(self) -> int:
        # 10 ms windows to match AIC VAD's cadence
        return int(self.sample_rate * 0.01) if self.sample_rate > 0 else 160

    def voice_confidence(self, buffer: bytes) -> float:
        if not self._vc.has_vad:
            return 0.0

        vad_result = self._vc._vad.process(buffer)
        return vad_result.speech_prob
