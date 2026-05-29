"""Pipecat BaseAudioFilter implementation for voiceclean.

VoiceCleanFilter is wired as `audio_in_filter` on the transport. It
runs AEC + noise suppression on every incoming audio chunk.

For AEC to work, the bot's outgoing audio must be captured as a
reference signal. VoiceCleanFilter.reference_collector is a lightweight
FrameProcessor that should be inserted in the pipeline just before
transport.output(). It copies outgoing audio into a shared buffer that
the AEC reads from during filter().

Debug dump
----------
Set the ``VOICECLEAN_DEBUG_DUMP_DIR`` env var to a writable directory to
have the filter dump three raw PCM streams per call:

  - ``vc_<ts>_<pid>_<id>_in.pcm``  — mic audio BEFORE the AEC
  - ``vc_<ts>_<pid>_<id>_out.pcm`` — mic audio AFTER the AEC (what STT sees)
  - ``vc_<ts>_<pid>_<id>_ref.pcm`` — bot audio fed as AEC reference

Format: signed 16-bit little-endian PCM, mono, at the filter's sample
rate (default 8000 Hz). Convert with::

    ffmpeg -f s16le -ar 8000 -ac 1 -i vc_<...>_out.pcm vc_<...>_out.wav

Use this to verify whether voiceclean is altering the audio in ways
that affect downstream STT — comparing in vs out at the actual live
sample rate, without recording-format round-trip artefacts.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

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

logger = logging.getLogger(__name__)


class _DebugDump:
    """Three append-only PCM files capturing AEC input, output, and reference.

    All writes are best-effort — I/O failure is logged once and then
    silently dropped, so a full disk never aborts a live call.
    """

    def __init__(self, dir_path: str, sample_rate: int) -> None:
        d = Path(dir_path)
        d.mkdir(parents=True, exist_ok=True)
        # Unique-enough suffix for concurrent calls in the same process.
        # Avoids requiring the caller (agent) to know about voiceclean's
        # file layout. Timestamps in agent logs let you match to call sid.
        ts = time.strftime("%Y%m%d_%H%M%S")
        suffix = f"{ts}_{os.getpid()}_{id(self) & 0xFFFF:04x}"
        self._sample_rate = sample_rate
        self._paths = {
            "in":  d / f"vc_{suffix}_in.pcm",
            "out": d / f"vc_{suffix}_out.pcm",
            "ref": d / f"vc_{suffix}_ref.pcm",
        }
        self._fhs = {k: open(p, "wb") for k, p in self._paths.items()}
        self._warned = False
        logger.info(
            "voiceclean: debug dump active sr=%d  files=%s",
            sample_rate, ", ".join(str(p) for p in self._paths.values()),
        )

    def _write(self, key: str, audio: bytes) -> None:
        fh = self._fhs.get(key)
        if fh is None:
            return
        try:
            fh.write(audio)
        except Exception as exc:
            if not self._warned:
                logger.warning("voiceclean debug dump write failed (%s): %r", key, exc)
                self._warned = True

    def feed_in(self, audio: bytes) -> None:
        self._write("in", audio)

    def feed_out(self, audio: bytes) -> None:
        self._write("out", audio)

    def feed_ref(self, audio: bytes) -> None:
        self._write("ref", audio)

    def close(self) -> None:
        for fh in self._fhs.values():
            try:
                fh.close()
            except Exception:
                pass
        self._fhs.clear()


class _ReferenceCollector(FrameProcessor):
    """Captures outgoing audio frames for AEC reference.

    Insert this in the pipeline before transport.output(). It passes
    all frames through unchanged — it only copies audio bytes into the
    VoiceClean pipeline's AEC reference buffer.
    """

    def __init__(self, vc: VoiceClean, dump: _DebugDump | None = None):
        super().__init__()
        self._vc = vc
        self._dump = dump

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, OutputAudioRawFrame):
            self._vc.feed_reference(frame.audio)
            if self._dump is not None:
                self._dump.feed_ref(frame.audio)
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
        vad_threshold: float = 0.5,
        **aec_kwargs,
    ) -> None:
        self._sample_rate = sample_rate
        self._vc = VoiceClean(
            sample_rate=sample_rate,
            vad_threshold=vad_threshold,
            **aec_kwargs,
        )
        self._bypass = False
        # Opt-in debug dump. Triggered by env var so the agent app needs
        # no code changes to capture a session — see module docstring.
        dump_dir = os.environ.get("VOICECLEAN_DEBUG_DUMP_DIR")
        self._dump: _DebugDump | None = None
        if dump_dir:
            try:
                self._dump = _DebugDump(dump_dir, sample_rate)
            except Exception as exc:
                logger.warning(
                    "voiceclean: debug dump disabled (init failed: %r)", exc,
                )
        self._ref_collector = _ReferenceCollector(self._vc, dump=self._dump)

    @property
    def reference_collector(self) -> FrameProcessor:
        """FrameProcessor to insert before transport.output() in the pipeline."""
        return self._ref_collector

    def create_vad_analyzer(
        self,
        *,
        speech_hold_duration: float | None = None,
        sensitivity: float | None = None,
        confidence: float | None = None,
        start_secs: float | None = None,
        stop_secs: float | None = None,
        min_volume: float | None = None,
        **kwargs,
    ) -> VoiceCleanVAD:
        """Create a VAD analyzer that shares this filter's VoiceClean instance.

        Compatibility kwargs (so this can drop-in replace ai-coustics'
        ``create_vad_analyzer``):

          - ``speech_hold_duration`` aliases ``stop_secs`` if the explicit
            ``stop_secs`` is not given. Callers like the agent pipeline
            pass ``speech_hold_duration=0.05`` for AIC; honouring it here
            keeps voiceclean's behaviour predictable from the caller's
            point of view.
          - ``sensitivity`` is accepted and ignored — it's an AIC-only
            concept (Silero confidence is on a different scale).
        """
        vad_kwargs: dict = {}
        if confidence is not None:
            vad_kwargs["confidence"] = confidence
        if start_secs is not None:
            vad_kwargs["start_secs"] = start_secs
        if stop_secs is not None:
            vad_kwargs["stop_secs"] = stop_secs
        elif speech_hold_duration is not None:
            vad_kwargs["stop_secs"] = speech_hold_duration
        if min_volume is not None:
            vad_kwargs["min_volume"] = min_volume
        return VoiceCleanVAD(
            vc=self._vc,
            sample_rate=self._sample_rate,
            **vad_kwargs,
        )

    async def start(self, sample_rate: int):
        self._sample_rate = sample_rate

    async def stop(self):
        if self._dump is not None:
            self._dump.close()
            self._dump = None

    async def process_frame(self, frame: FilterControlFrame):
        if isinstance(frame, FilterEnableFrame):
            self._bypass = not frame.enable

    async def filter(self, audio: bytes) -> bytes:
        if self._bypass or len(audio) == 0:
            return audio

        if self._dump is not None:
            self._dump.feed_in(audio)

        cleaned = audio
        if self._vc._aec is not None:
            cleaned = self._vc._aec.process(cleaned)

        if self._dump is not None:
            self._dump.feed_out(cleaned)
        return cleaned
