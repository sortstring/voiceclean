"""Acoustic Echo Cancellation via cross-correlation detection + suppression.

No adaptive filters. No convergence issues. No external C libraries.

The physics: echo is a delayed, attenuated copy of the reference
signal. Cross-correlation between mic audio and the reference buffer
reveals whether echo is present and at what delay. When detected,
the echo component is suppressed via spectral masking.

This replaces the SpeexDSP-based AEC which had intermittent failures
due to adaptive filter divergence and frame balancing issues.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np


class AEC:
    """Cross-correlation based echo cancellation.

    Maintains a circular buffer of recent reference (bot) audio.
    For each mic chunk, computes normalized cross-correlation against
    the reference. When correlation exceeds the threshold, applies
    spectral masking to suppress the echo while preserving any
    uncorrelated signal (real user speech).

    Args:
        sample_rate: Audio sample rate in Hz.
        chunk_ms: Analysis chunk size in milliseconds. Larger chunks
            give more reliable correlation but add latency. Default 40ms.
        buffer_ms: Reference buffer length in milliseconds. Must cover
            the maximum expected echo delay. Default 800ms.
        correlation_threshold: Normalized cross-correlation above which
            echo is considered present. Default 0.15.
        suppress_db: How much to suppress detected echo (dB). Default -30.
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        chunk_ms: int = 40,
        buffer_ms: int = 800,
        correlation_threshold: float = 0.15,
        suppress_db: float = -30.0,
        **kwargs,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_samples = int(sample_rate * chunk_ms / 1000)
        self._chunk_bytes = self._chunk_samples * 2
        self._buffer_samples = int(sample_rate * buffer_ms / 1000)
        self._correlation_threshold = correlation_threshold
        self._suppress_gain = 10.0 ** (suppress_db / 20.0)

        # FFT size for cross-correlation (next power of 2)
        self._fft_size = 1
        while self._fft_size < self._buffer_samples + self._chunk_samples:
            self._fft_size *= 2

        self._lock = threading.Lock()
        # Circular buffer of recent reference audio (float64)
        self._ref_ring = np.zeros(self._buffer_samples, dtype=np.float64)
        self._ref_write_pos = 0
        self._ref_energy_valid = False

        # Buffering for mic and reference input
        self._mic_buf = bytearray()
        self._ref_buf = bytearray()

        # Per-call correlation stats
        self._total_chunks = 0
        self._echo_chunks = 0
        self._peak_correlations: list[float] = []
        self._suppressed_lags: list[int] = []

    def get_stats(self) -> dict:
        """Return per-call correlation statistics."""
        corrs = self._peak_correlations
        if not corrs:
            return {
                "total_chunks": 0,
                "echo_chunks": 0,
                "echo_pct": 0.0,
                "correlation_min": 0.0,
                "correlation_max": 0.0,
                "correlation_mean": 0.0,
                "correlation_p50": 0.0,
                "correlation_p95": 0.0,
                "threshold": self._correlation_threshold,
            }
        arr = np.array(corrs)
        lags = self._suppressed_lags
        lag_arr = np.array(lags) if lags else np.array([], dtype=np.int64)
        lag_stats = {}
        if len(lag_arr) > 0:
            lag_stats = {
                "lag_min_ms": round(float(np.min(lag_arr)) / self._sample_rate * 1000, 1),
                "lag_max_ms": round(float(np.max(lag_arr)) / self._sample_rate * 1000, 1),
                "lag_mean_ms": round(float(np.mean(lag_arr)) / self._sample_rate * 1000, 1),
            }
        return {
            "total_chunks": self._total_chunks,
            "echo_chunks": self._echo_chunks,
            "echo_pct": round(100 * self._echo_chunks / self._total_chunks, 1),
            "correlation_min": round(float(np.min(arr)), 4),
            "correlation_max": round(float(np.max(arr)), 4),
            "correlation_mean": round(float(np.mean(arr)), 4),
            "correlation_p50": round(float(np.median(arr)), 4),
            "correlation_p95": round(float(np.percentile(arr, 95)), 4),
            "threshold": self._correlation_threshold,
            **lag_stats,
        }

    def feed_reference(self, audio: bytes) -> None:
        """Feed bot's outgoing audio into the reference ring buffer."""
        self._ref_buf.extend(audio)
        # Write to ring buffer in chunk-sized pieces
        while len(self._ref_buf) >= self._chunk_bytes:
            chunk = self._ref_buf[:self._chunk_bytes]
            self._ref_buf = self._ref_buf[self._chunk_bytes:]

            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float64)
            n = len(samples)
            pos = self._ref_write_pos

            with self._lock:
                if pos + n <= self._buffer_samples:
                    self._ref_ring[pos:pos + n] = samples
                else:
                    first = self._buffer_samples - pos
                    self._ref_ring[pos:] = samples[:first]
                    self._ref_ring[:n - first] = samples[first:]
                self._ref_write_pos = (pos + n) % self._buffer_samples
                self._ref_energy_valid = True

    def process(self, mic_audio: bytes) -> bytes:
        """Process mic audio: detect and suppress echo."""
        self._mic_buf.extend(mic_audio)
        out_chunks = []

        while len(self._mic_buf) >= self._chunk_bytes:
            chunk = bytes(self._mic_buf[:self._chunk_bytes])
            self._mic_buf = self._mic_buf[self._chunk_bytes:]

            mic = np.frombuffer(chunk, dtype=np.int16).astype(np.float64)

            with self._lock:
                if not self._ref_energy_valid:
                    out_chunks.append(chunk)
                    continue
                ref = self._ref_ring.copy()

            result = self._process_chunk(mic, ref)
            out_chunks.append(
                np.clip(result, -32768, 32767).astype(np.int16).tobytes()
            )

        if not out_chunks:
            return b""
        return b"".join(out_chunks)

    def _process_chunk(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """Core processing: correlate, detect, suppress."""
        mic_energy = np.sum(mic ** 2)
        if mic_energy < 1e-6:
            return mic

        ref_energy = np.sum(ref ** 2)
        if ref_energy < 1e-6:
            return mic

        # Normalized cross-correlation via FFT
        mic_padded = np.zeros(self._fft_size)
        mic_padded[:len(mic)] = mic
        ref_padded = np.zeros(self._fft_size)
        ref_padded[:len(ref)] = ref

        mic_fft = np.fft.rfft(mic_padded)
        ref_fft = np.fft.rfft(ref_padded)

        xcorr = np.fft.irfft(mic_fft * np.conj(ref_fft))

        # Normalize by geometric mean of energies
        norm = np.sqrt(mic_energy * ref_energy)
        if norm < 1e-10:
            return mic
        xcorr_norm = np.abs(xcorr) / norm

        peak_corr = np.max(xcorr_norm)

        self._total_chunks += 1
        self._peak_correlations.append(float(peak_corr))

        if peak_corr < self._correlation_threshold:
            return mic

        # Echo detected — apply spectral suppression
        peak_lag = np.argmax(xcorr_norm)
        self._echo_chunks += 1
        self._suppressed_lags.append(int(peak_lag))

        # Extract the reference segment at the detected lag
        ref_at_lag = np.zeros_like(mic)
        for i in range(len(mic)):
            idx = (peak_lag + i) % len(ref)
            ref_at_lag[i] = ref[idx]

        ref_lag_energy = np.sum(ref_at_lag ** 2)
        if ref_lag_energy < 1e-6:
            return mic

        # Spectral masking: suppress frequency bins where echo dominates
        n_fft = len(mic)
        mic_spec = np.fft.rfft(mic, n_fft)
        ref_spec = np.fft.rfft(ref_at_lag, n_fft)

        mic_mag = np.abs(mic_spec)
        ref_mag = np.abs(ref_spec)

        # Gain mask: reduce bins where reference (echo) is strong
        # relative to the mic signal
        echo_ratio = ref_mag / (mic_mag + 1e-10)

        # Scale by correlation strength — higher correlation = more
        # confident echo detection = more aggressive suppression
        suppression_strength = min(peak_corr / self._correlation_threshold, 3.0)

        gain = np.ones_like(mic_mag)
        echo_bins = echo_ratio > 0.3
        gain[echo_bins] = np.maximum(
            self._suppress_gain,
            1.0 - suppression_strength * echo_ratio[echo_bins],
        )

        result_spec = mic_spec * gain
        result = np.fft.irfft(result_spec, n_fft)

        return result[:len(mic)]
