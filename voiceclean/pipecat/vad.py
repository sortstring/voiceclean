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

    Args:
        vc: Shared VoiceClean instance — the same one wired into the
            VoiceCleanFilter, so AEC/VAD analyse the same audio.
        sample_rate: Audio sample rate in Hz.
        confidence: Silero confidence above which a frame counts as
            speech. Default 0.5.
        start_secs: How long confidence must stay above ``confidence``
            before emitting "speech started". 0.0 = react instantly.
            Default 0.0 (low-latency turn start).
        stop_secs: How long confidence must stay below ``confidence``
            before emitting "speech stopped". Raised from 0.0 to 0.2 in
            v0.3.6 — at 0.0 the VAD signalled "stopped" at every
            inter-word pause, which fragmented streaming-STT utterances
            into one-word chunks and produced noise transcription.
            Pipecat's own default is 0.2; ai-coustics uses 0.05. Keep
            this above ~0.15 unless you have a specific reason to
            sacrifice STT quality for ~200 ms of turn-end latency.
        min_volume: Minimum audio volume to count as speech. 0.0
            disables the gate (Silero confidence is already a strong
            speech signal). Default 0.0.
    """

    def __init__(
        self,
        vc: VoiceClean,
        sample_rate: int = 8000,
        *,
        confidence: float = 0.5,
        start_secs: float = 0.0,
        stop_secs: float = 0.2,
        min_volume: float = 0.0,
    ) -> None:
        params = VADParams(
            confidence=confidence,
            start_secs=start_secs,
            stop_secs=stop_secs,
            min_volume=min_volume,
        )
        super().__init__(sample_rate=sample_rate, params=params)
        self._vc = vc

    def num_frames_required(self) -> int:
        # Silero VAD needs 256 samples at 8kHz (32ms) or 512 at 16kHz
        if self.sample_rate >= 16000:
            return 512
        return 256

    def voice_confidence(self, buffer: bytes) -> float:
        if not self._vc.has_vad:
            return 0.0

        vad_result = self._vc._vad.process(buffer)
        return vad_result.speech_prob
