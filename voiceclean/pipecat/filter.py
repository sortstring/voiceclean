"""Pipecat BaseAudioFilter implementation for voiceclean.

VoiceCleanFilter is wired as `audio_in_filter` on the transport. It
runs AEC + noise suppression on every incoming audio chunk.

For AEC to work, the bot's outgoing audio must be captured as a
reference signal. VoiceCleanFilter.reference_collector is a lightweight
FrameProcessor that should be inserted in the pipeline just before
transport.output(). It copies outgoing audio into a shared buffer that
the AEC reads from during filter().
"""
from __future__ import annotations

from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import (
    FilterControlFrame,
    FilterEnableFrame,
    Frame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceclean.pipeline import VoiceClean
from voiceclean.pipecat.vad import VoiceCleanVAD


class _ReferenceCollector(FrameProcessor):
    """Captures outgoing audio frames for AEC reference.

    Insert this in the pipeline before transport.output(). It passes
    all frames through unchanged — it only copies audio bytes into the
    VoiceClean pipeline's AEC reference buffer.
    """

    def __init__(self, vc: VoiceClean):
        super().__init__()
        self._vc = vc

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame):
            self._vc.feed_reference(frame.audio)
        await self.push_frame(frame, direction)


class VoiceCleanFilter(BaseAudioFilter):
    """Pipecat audio input filter backed by voiceclean.

    Provides AEC + noise suppression on the input audio path, and
    exposes a VAD analyzer for turn detection.

    Usage:
        vc_filter = VoiceCleanFilter(sample_rate=8000)

        transport = FastAPIWebsocketTransport(
            params=FastAPIWebsocketParams(
                audio_in_filter=vc_filter,
                serializer=serializer,
            ),
        )

        # Insert in pipeline before transport.output():
        pipeline = Pipeline([
            transport.input(),
            ...
            vc_filter.reference_collector,
            transport.output(),
        ])

        # VAD for turn detection:
        vad = vc_filter.create_vad_analyzer()
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        aec_filter_length: int = 1600,
        aec_frame_size: int = 160,
        vad_threshold: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate
        self._vc = VoiceClean(
            sample_rate=sample_rate,
            aec_filter_length=aec_filter_length,
            aec_frame_size=aec_frame_size,
            vad_threshold=vad_threshold,
        )
        self._bypass = False
        self._ref_collector = _ReferenceCollector(self._vc)

    @property
    def reference_collector(self) -> FrameProcessor:
        """FrameProcessor to insert before transport.output() in the pipeline."""
        return self._ref_collector

    def create_vad_analyzer(
        self,
        *,
        speech_hold_duration: float | None = None,
        sensitivity: float | None = None,
        **kwargs,
    ) -> VoiceCleanVAD:
        """Create a VAD analyzer that shares this filter's VoiceClean instance."""
        return VoiceCleanVAD(
            vc=self._vc,
            sample_rate=self._sample_rate,
        )

    async def start(self, sample_rate: int):
        self._sample_rate = sample_rate

    async def stop(self):
        pass

    async def process_frame(self, frame: FilterControlFrame):
        if isinstance(frame, FilterEnableFrame):
            self._bypass = not frame.enable

    async def filter(self, audio: bytes) -> bytes:
        if self._bypass or len(audio) == 0:
            return audio

        result = self._vc.process(audio)
        return result.audio
