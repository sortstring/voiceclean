"""voiceclean — Real-time AEC and VAD for voice agents.

Cross-correlation echo cancellation + Silero VAD. Pure Python + numpy,
no external C libraries. Built for telephony (8 kHz PSTN audio), works
at any sample rate.

    pip install voiceclean[all]    # AEC + VAD + Pipecat integration
    pip install voiceclean[silero] # VAD only
"""

__version__ = "0.3.1"

from voiceclean.pipeline import ProcessResult, VoiceClean

__all__ = [
    "VoiceClean",
    "ProcessResult",
    "__version__",
]
