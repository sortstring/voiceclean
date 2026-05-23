"""Acoustic Echo Cancellation via libspeexdsp (ctypes).

Wraps libspeexdsp's echo canceller directly via ctypes — the pip
'speexdsp' package is broken on Python 3.12+ (uses removed 'imp' module).

Requires: libspeexdsp-dev installed on the system.
    sudo apt install libspeexdsp-dev   (Debian/Ubuntu)
"""
from __future__ import annotations

import collections
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


class AEC:
    """Acoustic echo canceller backed by libspeexdsp.

    Args:
        sample_rate: Audio sample rate in Hz (typically 8000 for telephony).
        frame_size: Samples per frame. Must match the chunk size fed to
            process(). Default 160 = 20 ms at 8 kHz.
        filter_length: Adaptive filter length in samples. Longer = better
            echo tail coverage but more CPU. Default 1600 = 200 ms at 8 kHz.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        frame_size: int = 160,
        filter_length: int = 1600,
    ) -> None:
        self._lib = _load_speexdsp()

        self._lib.speex_echo_state_init.restype = ctypes.c_void_p
        self._lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.speex_echo_cancellation.restype = None
        self._lib.speex_echo_cancellation.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
        ]
        self._lib.speex_echo_state_destroy.restype = None
        self._lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
        self._lib.speex_echo_ctl.restype = ctypes.c_int
        self._lib.speex_echo_ctl.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)
        ]

        self._state = self._lib.speex_echo_state_init(frame_size, filter_length)
        if not self._state:
            raise RuntimeError("speex_echo_state_init failed")

        # Set sample rate via ctl (SPEEX_ECHO_SET_SAMPLING_RATE = 24)
        rate = ctypes.c_int(sample_rate)
        self._lib.speex_echo_ctl(self._state, 24, ctypes.byref(rate))

        self._sample_rate = sample_rate
        self._frame_size = frame_size
        self._frame_bytes = frame_size * 2  # int16 = 2 bytes/sample
        self._ref_buf = collections.deque(maxlen=sample_rate * 4)
        self._lock = threading.Lock()

    def __del__(self):
        if hasattr(self, "_state") and self._state:
            self._lib.speex_echo_state_destroy(self._state)
            self._state = None

    def feed_reference(self, audio: bytes) -> None:
        """Feed outgoing (bot) audio as the AEC reference signal."""
        with self._lock:
            self._ref_buf.extend(audio)

    def process(self, mic_audio: bytes) -> bytes:
        """Remove echo from mic audio using the stored reference.

        Args:
            mic_audio: Raw PCM int16 mono bytes from the caller's mic.

        Returns:
            Echo-cancelled PCM int16 mono bytes, same length as input.
        """
        out_chunks = []
        offset = 0
        while offset + self._frame_bytes <= len(mic_audio):
            mic_frame = mic_audio[offset : offset + self._frame_bytes]

            with self._lock:
                if len(self._ref_buf) >= self._frame_bytes:
                    ref_bytes = bytes(
                        [self._ref_buf.popleft() for _ in range(self._frame_bytes)]
                    )
                else:
                    ref_bytes = b"\x00" * self._frame_bytes

            mic_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(mic_frame)
            ref_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(ref_bytes)
            out_arr = (ctypes.c_int16 * self._frame_size)()

            self._lib.speex_echo_cancellation(
                self._state, mic_arr, ref_arr, out_arr
            )

            out_chunks.append(bytes(out_arr))
            offset += self._frame_bytes

        if not out_chunks:
            return mic_audio
        return b"".join(out_chunks)
