"""voiceclean — Real-time AEC, noise suppression, and VAD for voice agents.

Wraps SpeexDSP (AEC), RNNoise (noise suppression), and Silero VAD into
a single package with a clean API. Each component is optional — install
only what you need.

    pip install voiceclean[all]     # everything
    pip install voiceclean[speexdsp]  # AEC only
    pip install voiceclean[rnnoise]   # noise suppression only
    pip install voiceclean[silero]    # VAD only
"""

__version__ = "0.1.1"

from voiceclean.pipeline import ProcessResult, VoiceClean

__all__ = [
    "VoiceClean",
    "ProcessResult",
    "__version__",
]
