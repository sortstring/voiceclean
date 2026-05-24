"""Acoustic Echo Cancellation via libspeexdsp (ctypes).

Uses SpeexDSP's asynchronous playback/capture API which handles the
delay alignment between outgoing (bot) audio and incoming (mic) audio
internally. This is critical for PSTN telephony where the echo
round-trip is 100-500ms.

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


class AEC:
    """Acoustic echo canceller backed by libspeexdsp.

    Uses the asynchronous playback/capture API:
    - feed_reference() calls speex_echo_playback() when the bot sends audio
    - process() calls speex_echo_capture() when mic audio arrives

    SpeexDSP internally manages delay alignment between the two streams,
    so the caller doesn't need to time-synchronize them.

    Args:
        sample_rate: Audio sample rate in Hz (typically 8000 for telephony).
        frame_size: Samples per frame. Default 160 = 20 ms at 8 kHz.
        filter_length: Adaptive filter length in samples. Must cover the
            full echo round-trip delay. Default 4000 = 500 ms at 8 kHz,
            covering typical PSTN echo paths.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        frame_size: int = 160,
        filter_length: int = 4000,
    ) -> None:
        self._lib = _load_speexdsp()

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

        self._state = self._lib.speex_echo_state_init(frame_size, filter_length)
        if not self._state:
            raise RuntimeError("speex_echo_state_init failed")

        # SPEEX_ECHO_SET_SAMPLING_RATE = 24
        rate = ctypes.c_int(sample_rate)
        self._lib.speex_echo_ctl(self._state, 24, ctypes.byref(rate))

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
        if hasattr(self, "_state") and self._state:
            self._lib.speex_echo_state_destroy(self._state)
            self._state = None

    def feed_reference(self, audio: bytes) -> None:
        """Feed outgoing (bot) audio as the AEC reference signal.

        Calls speex_echo_playback() for each frame-sized chunk. SpeexDSP
        internally buffers this and correlates it with future mic audio.
        """
        self._play_buf.extend(audio)
        with self._lock:
            while len(self._play_buf) >= self._frame_bytes:
                frame = bytes(self._play_buf[: self._frame_bytes])
                self._play_buf = self._play_buf[self._frame_bytes :]

                play_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(frame)
                self._lib.speex_echo_playback(self._state, play_arr)
                self._play_frames += 1

    def process(self, mic_audio: bytes) -> bytes:
        """Remove echo from mic audio.

        Calls speex_echo_capture() for each frame-sized chunk. SpeexDSP
        uses the previously-fed playback audio to cancel the echo.
        """
        self._mic_buf.extend(mic_audio)
        out_chunks = []
        with self._lock:
            while len(self._mic_buf) >= self._frame_bytes:
                frame = bytes(self._mic_buf[: self._frame_bytes])
                self._mic_buf = self._mic_buf[self._frame_bytes :]

                # Feed silence as playback when the bot isn't speaking,
                # so SpeexDSP's capture/playback frame counts stay balanced.
                if self._capture_frames >= self._play_frames:
                    self._lib.speex_echo_playback(self._state, self._silence_frame)
                    self._play_frames += 1

                mic_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(frame)
                out_arr = (ctypes.c_int16 * self._frame_size)()

                self._lib.speex_echo_capture(self._state, mic_arr, out_arr)
                out_chunks.append(bytes(out_arr))
                self._capture_frames += 1

        if not out_chunks:
            return b""
        return b"".join(out_chunks)
