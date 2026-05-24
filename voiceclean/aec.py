"""Acoustic Echo Cancellation via libspeexdsp (ctypes).

Two-stage pipeline:
  1. Echo canceller (adaptive filter) — removes the bulk of the echo
  2. Preprocessor (residual echo suppression) — catches what the
     adaptive filter misses, especially during double-talk

The preprocessor is linked to the echo canceller via
SPEEX_PREPROCESS_SET_ECHO_STATE so it has access to the canceller's
internal state for informed residual suppression. This is the
recommended usage from the SpeexDSP documentation.

Requires: libspeexdsp-dev installed on the system.
    sudo apt install libspeexdsp-dev   (Debian/Ubuntu)
"""
from __future__ import annotations

import ctypes
import ctypes.util
import threading


def _load_speexdsp():
    path = ctypes.util.find_library("speexdsp")
    if path is None:
        raise ImportError(
            "libspeexdsp not found. Install it:\n"
            "  sudo apt install libspeexdsp-dev   (Debian/Ubuntu)\n"
            "  brew install speexdsp               (macOS)"
        )
    return ctypes.cdll.LoadLibrary(path)


# SpeexDSP preprocessor constants
_SPEEX_PREPROCESS_SET_DENOISE = 0
_SPEEX_PREPROCESS_SET_NOISE_SUPPRESS = 18
_SPEEX_PREPROCESS_SET_ECHO_SUPPRESS = 20
_SPEEX_PREPROCESS_SET_ECHO_SUPPRESS_ACTIVE = 22
_SPEEX_PREPROCESS_SET_ECHO_STATE = 24


class AEC:
    """Acoustic echo canceller backed by libspeexdsp.

    Two-stage: echo canceller + preprocessor with residual echo
    suppression. The preprocessor catches echo leakage that the
    adaptive filter misses (double-talk, filter divergence).

    Args:
        sample_rate: Audio sample rate in Hz (typically 8000 for telephony).
        frame_size: Samples per frame. Default 160 = 20 ms at 8 kHz.
        filter_length: Adaptive filter length in samples. Must cover the
            full echo round-trip delay. Default 4000 = 500 ms at 8 kHz.
        echo_suppress_db: Residual echo suppression for non-active echo
            (dB, negative). Default -60.
        echo_suppress_active_db: Residual echo suppression during
            double-talk (dB, negative). Default -45.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        frame_size: int = 160,
        filter_length: int = 4000,
        echo_suppress_db: int = -60,
        echo_suppress_active_db: int = -45,
    ) -> None:
        self._lib = _load_speexdsp()

        # Echo canceller
        self._lib.speex_echo_state_init.restype = ctypes.c_void_p
        self._lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.speex_echo_playback.restype = None
        self._lib.speex_echo_playback.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16),
        ]
        self._lib.speex_echo_capture.restype = None
        self._lib.speex_echo_capture.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
        ]
        self._lib.speex_echo_state_destroy.restype = None
        self._lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
        self._lib.speex_echo_ctl.restype = ctypes.c_int
        self._lib.speex_echo_ctl.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]

        # Preprocessor
        self._lib.speex_preprocess_state_init.restype = ctypes.c_void_p
        self._lib.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.speex_preprocess_state_destroy.restype = None
        self._lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
        self._lib.speex_preprocess_run.restype = ctypes.c_int
        self._lib.speex_preprocess_run.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16),
        ]

        # Initialize echo canceller
        self._echo_state = self._lib.speex_echo_state_init(frame_size, filter_length)
        if not self._echo_state:
            raise RuntimeError("speex_echo_state_init failed")

        # SPEEX_ECHO_SET_SAMPLING_RATE = 24
        rate = ctypes.c_int(sample_rate)
        self._lib.speex_echo_ctl(self._echo_state, 24, ctypes.byref(rate))

        # Initialize preprocessor and link to echo canceller
        self._preprocess = self._lib.speex_preprocess_state_init(frame_size, sample_rate)
        if not self._preprocess:
            raise RuntimeError("speex_preprocess_state_init failed")

        def _pp_ctl(request: int, value):
            """Helper: speex_preprocess_ctl with explicit void* casting."""
            self._lib.speex_preprocess_ctl(
                ctypes.c_void_p(self._preprocess),
                ctypes.c_int(request),
                value,
            )

        # Link preprocessor to echo canceller for residual echo
        # suppression. SET_ECHO_STATE takes the echo state directly
        # as a void*, not a pointer-to-pointer.
        _pp_ctl(_SPEEX_PREPROCESS_SET_ECHO_STATE,
                ctypes.c_void_p(self._echo_state))

        # Residual echo suppression: how aggressively to suppress
        # echo that the adaptive filter missed (-60 dB)
        suppress = ctypes.c_int(echo_suppress_db)
        _pp_ctl(_SPEEX_PREPROCESS_SET_ECHO_SUPPRESS, ctypes.byref(suppress))

        # During double-talk: less aggressive to preserve real speech (-45 dB)
        suppress_active = ctypes.c_int(echo_suppress_active_db)
        _pp_ctl(_SPEEX_PREPROCESS_SET_ECHO_SUPPRESS_ACTIVE,
                ctypes.byref(suppress_active))

        # Enable noise suppression in the preprocessor
        denoise = ctypes.c_int(1)
        _pp_ctl(_SPEEX_PREPROCESS_SET_DENOISE, ctypes.byref(denoise))
        noise_suppress = ctypes.c_int(-30)
        _pp_ctl(_SPEEX_PREPROCESS_SET_NOISE_SUPPRESS, ctypes.byref(noise_suppress))

        self._sample_rate = sample_rate
        self._frame_size = frame_size
        self._frame_bytes = frame_size * 2
        self._lock = threading.Lock()
        self._play_buf = bytearray()
        self._mic_buf = bytearray()
        self._play_frames = 0
        self._capture_frames = 0
        self._silence_frame = (ctypes.c_int16 * frame_size)()

    def __del__(self):
        if hasattr(self, "_preprocess") and self._preprocess:
            self._lib.speex_preprocess_state_destroy(self._preprocess)
            self._preprocess = None
        if hasattr(self, "_echo_state") and self._echo_state:
            self._lib.speex_echo_state_destroy(self._echo_state)
            self._echo_state = None

    def feed_reference(self, audio: bytes) -> None:
        """Feed outgoing (bot) audio as the AEC reference signal."""
        self._play_buf.extend(audio)
        with self._lock:
            while len(self._play_buf) >= self._frame_bytes:
                frame = bytes(self._play_buf[: self._frame_bytes])
                self._play_buf = self._play_buf[self._frame_bytes :]

                play_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(frame)
                if self._play_frames >= self._capture_frames:
                    self._lib.speex_echo_capture(
                        self._echo_state, self._silence_frame, self._silence_frame,
                    )
                    self._lib.speex_preprocess_run(self._preprocess, self._silence_frame)
                    self._capture_frames += 1
                self._lib.speex_echo_playback(self._echo_state, play_arr)
                self._play_frames += 1

    def process(self, mic_audio: bytes) -> bytes:
        """Remove echo from mic audio.

        Two-stage: echo canceller removes bulk echo, then preprocessor
        applies residual echo suppression + noise suppression.
        """
        self._mic_buf.extend(mic_audio)
        out_chunks = []
        with self._lock:
            while len(self._mic_buf) >= self._frame_bytes:
                frame = bytes(self._mic_buf[: self._frame_bytes])
                self._mic_buf = self._mic_buf[self._frame_bytes :]

                if self._capture_frames >= self._play_frames:
                    self._lib.speex_echo_playback(self._echo_state, self._silence_frame)
                    self._play_frames += 1

                mic_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(frame)
                out_arr = (ctypes.c_int16 * self._frame_size)()

                # Stage 1: adaptive echo cancellation
                self._lib.speex_echo_capture(self._echo_state, mic_arr, out_arr)

                # Stage 2: residual echo suppression + noise suppression
                self._lib.speex_preprocess_run(self._preprocess, out_arr)

                out_chunks.append(bytes(out_arr))
                self._capture_frames += 1

        if not out_chunks:
            return b""
        return b"".join(out_chunks)
