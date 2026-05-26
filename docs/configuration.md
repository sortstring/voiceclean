# Configuration

## AEC parameters

```python
from voiceclean.aec import AEC

aec = AEC(
    sample_rate=8000,            # Audio sample rate in Hz
    chunk_ms=40,                 # Analysis chunk size (ms)
    buffer_ms=800,               # Reference buffer length (ms)
    correlation_threshold=0.15,  # Echo detection threshold
    suppress_db=-30.0,           # Echo suppression depth (dB)
)
```

### `sample_rate`

Audio sample rate in Hz. Must match the sample rate of both the mic and reference audio. For telephony, this is almost always **8000 Hz**.

### `chunk_ms`

Size of each analysis chunk in milliseconds. The AEC processes audio in chunks of this size.

- **Larger** = more reliable correlation (more samples to compare), but more latency
- **Smaller** = lower latency, but correlation may be noisy
- **Default: 40 ms** — good balance for telephony

At 8 kHz, 40 ms = 320 samples per chunk.

### `buffer_ms`

Length of the reference ring buffer in milliseconds. This must be long enough to cover the **maximum expected echo delay** — the round-trip time for audio to travel from your server to the phone speaker and back through the mic.

- **Typical PSTN:** 100–500 ms
- **Default: 800 ms** — covers most paths with margin
- **International calls:** increase to 1200–1600 ms if you see echo leaking through

At 8 kHz, 800 ms = 6400 samples.

### `correlation_threshold`

Normalized cross-correlation peak above which echo is considered present. Range: 0.0 to 1.0.

- **Lower** = more aggressive echo detection (catches weaker echo, but may false-trigger on speech)
- **Higher** = more conservative (misses weak echo, but fewer false positives)
- **Default: 0.15** — but production testing on Exotel PSTN calls showed that borderline echo (correlation p95 of 0.13–0.15) can slip through. **0.10 is recommended** for telephony deployments. Normal speech correlates at 0.01–0.08, so 0.10 has adequate margin.

!!! tip
    If echo still leaks through at 0.10, try 0.08. If user speech is being suppressed, raise back to 0.15 or 0.20.

### `suppress_db`

How much to attenuate detected echo, in decibels.

- **-30 dB** (default) = reduces echo to ~3% of original volume — effectively inaudible
- **-20 dB** = lighter suppression, some echo residual may be audible
- **-40 dB** = aggressive suppression, but may clip speech in echo bins

## VAD parameters

```python
from voiceclean.vad import VAD

vad = VAD(
    sample_rate=8000,   # Must be 8000 or 16000
    threshold=0.5,      # Speech probability threshold
)
```

### `sample_rate`

Must be **8000** or **16000** Hz. Silero VAD only supports these two rates natively.

### `threshold`

Speech probability above which `is_speech` returns `True`.

- **Lower** (e.g. 0.3) = more sensitive, catches quiet speech but more false positives
- **Higher** (e.g. 0.7) = less sensitive, misses quiet speech but fewer false positives
- **Default: 0.5** — balanced for telephony

## VoiceClean pipeline parameters

```python
from voiceclean import VoiceClean

vc = VoiceClean(
    sample_rate=8000,
    vad_threshold=0.5,
)
```

The `VoiceClean` class chains AEC and VAD together. AEC parameters use their defaults but can be customized by constructing the `AEC` instance separately:

```python
from voiceclean.aec import AEC
from voiceclean.vad import VAD

aec = AEC(sample_rate=8000, buffer_ms=1200, correlation_threshold=0.10)
vad = VAD(sample_rate=8000, threshold=0.4)

# Use them independently
aec.feed_reference(bot_audio)
clean = aec.process(mic_audio)
result = vad.process(clean)
```

## Pipecat filter parameters

```python
from voiceclean.pipecat import VoiceCleanFilter

vc_filter = VoiceCleanFilter(
    sample_rate=8000,
    vad_threshold=0.5,
)
```

See [Pipecat Guide](pipecat-guide.md) for full integration details.
