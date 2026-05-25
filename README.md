# voiceclean

Real-time acoustic echo cancellation (AEC), noise suppression, and voice activity detection (VAD) for voice agents. Built for telephony (8 kHz PSTN audio), works at any sample rate. No external C libraries — pure Python + numpy.

| Feature | How it works | Library |
|---------|-------------|---------|
| **AEC** | Cross-correlation echo detection + spectral masking. Detects echo by correlating mic audio against a reference buffer of bot output, then suppresses the correlated component. No adaptive filters, no convergence issues. | numpy (built-in) |
| **VAD** | Neural voice activity detection. <1 ms per chunk on CPU, 8 kHz native support, ~2 MB ONNX model. | [Silero VAD](https://github.com/snakers4/silero-vad) |

## Why this exists

Voice agents that call people over PSTN have an echo problem: the bot's TTS audio plays through the phone speaker, couples back through the mic, and gets transcribed as user input. The bot starts responding to its own words.

Some telephony providers (like Twilio) perform echo cancellation on their infrastructure. Others (like Exotel) don't. And even Twilio's AEC isn't perfect — in noisy environments, the audio quality degrades.

Commercial solutions like ai-coustics ($149/mo) provide noise suppression and VAD but not echo cancellation. voiceclean provides AEC + VAD as a single open-source package — free, no API keys, no network calls.

**Tested in production** on both Twilio and Exotel with real PSTN calls in Hindi, English, and Nepali. Handles noisy environments (multiple people talking in the background) where commercial alternatives fail.

## Install

```bash
pip install voiceclean
```

No system dependencies. No C libraries. Just numpy + soxr + onnxruntime.

## Quick start

### Standalone

```python
from voiceclean import VoiceClean

vc = VoiceClean(sample_rate=8000)

# Feed the bot's outgoing audio as AEC reference
vc.feed_reference(bot_pcm_bytes)

# Process the caller's mic audio
result = vc.process(mic_pcm_bytes)
result.audio        # cleaned PCM bytes (echo removed)
result.is_speech    # bool — is the caller speaking?
result.speech_prob  # float 0.0–1.0
```

### Individual components

```python
from voiceclean.aec import AEC
from voiceclean.vad import VAD

# Echo cancellation
aec = AEC(sample_rate=8000)
aec.feed_reference(bot_audio)
clean = aec.process(mic_audio)

# Voice activity detection
vad = VAD(sample_rate=8000, threshold=0.5)
result = vad.process(audio)  # result.is_speech, result.speech_prob
```

### Pipecat integration

voiceclean plugs into [Pipecat](https://github.com/pipecat-ai/pipecat) as a `BaseAudioFilter` + `VADAnalyzer`. The `reference_collector` FrameProcessor captures outgoing audio for the AEC reference signal.

```python
from voiceclean.pipecat import VoiceCleanFilter

vc_filter = VoiceCleanFilter(sample_rate=8000)

# Wire as audio input filter on the transport
transport = FastAPIWebsocketTransport(
    websocket=websocket,
    params=FastAPIWebsocketParams(
        audio_in_filter=vc_filter,
        serializer=serializer,
    ),
)

# VAD for turn detection
vad_analyzer = vc_filter.create_vad_analyzer()

# Build pipeline — reference_collector MUST go before transport.output()
pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,
    llm,
    tts,
    # ... other processors ...
    vc_filter.reference_collector,   # captures outgoing audio for AEC
    transport.output(),
    assistant_aggregator,
])
```

## How AEC works

Echo cancellation needs two audio streams:

1. **Reference signal** — what the bot is sending to the speaker (outgoing TTS audio)
2. **Mic signal** — what the caller's mic picks up (user speech + echo of the bot)

For each chunk of mic audio, voiceclean:

1. Computes **normalized cross-correlation** (via FFT) against a ring buffer of recent reference audio
2. If the peak correlation exceeds the threshold → echo is present at that lag
3. Applies **spectral masking**: frequency bins where echo dominates are suppressed, bins with uncorrelated energy (real speech) are preserved
4. If correlation is below threshold → no echo → audio passes through unchanged

```
Bot TTS audio ──► feed_reference() ──► reference ring buffer
                                              │
                                    cross-correlation
                                              │
Caller mic audio ──► process() ──► spectral masking ──► clean audio
```

This approach is fundamentally different from adaptive-filter AEC (like SpeexDSP or WebRTC AEC3):

| | Adaptive filter (SpeexDSP) | Cross-correlation (voiceclean) |
|---|---|---|
| **How it works** | Builds a linear model of the echo path, adapts over time | Detects echo presence by correlation, suppresses via spectral mask |
| **Convergence** | Needs time to adapt; can diverge | No convergence — stateless per-chunk |
| **Consistency** | Intermittent failures (~50% of calls in our testing) | Consistent on every frame |
| **Non-linear echo** | Fails (linear model can't represent speaker distortion) | Works (correlation survives non-linear distortion) |
| **Dependencies** | Requires libspeexdsp (C library) | Pure numpy |

## Audio format

All audio is **PCM int16 mono** (signed 16-bit little-endian, single channel). This is the standard format for telephony audio and what Pipecat's frame processors use internally.

## AEC parameters

```python
AEC(
    sample_rate=8000,           # Audio sample rate in Hz
    chunk_ms=40,                # Analysis chunk size (ms). Larger = more reliable, more latency
    buffer_ms=800,              # Reference buffer length (ms). Must cover max echo delay
    correlation_threshold=0.15, # Cross-correlation above which echo is detected
    suppress_db=-30.0,          # How much to suppress detected echo (dB)
)
```

For most telephony applications, the defaults work well. Increase `buffer_ms` if you're on a high-latency PSTN path (e.g., international calls).

## Credits

- **Silero VAD** — [Silero Team](https://github.com/snakers4/silero-vad) (MIT License)

## License

MIT — [SortString Solutions](https://github.com/sortstring)
