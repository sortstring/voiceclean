# voiceclean

[![PyPI](https://img.shields.io/pypi/v/voiceclean)](https://pypi.org/project/voiceclean/)
[![Documentation](https://readthedocs.org/projects/voiceclean/badge/?version=latest)](https://voiceclean.readthedocs.io/en/latest/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Real-time acoustic echo cancellation (AEC) and voice activity detection (VAD) for voice agents. Built for telephony (8 kHz PSTN audio), works at any sample rate. No external C libraries — pure Python + numpy.

**[Documentation](https://voiceclean.readthedocs.io)** | **[PyPI](https://pypi.org/project/voiceclean/)** | **[GitHub](https://github.com/sortstring/voiceclean)**

| Feature | How it works | Library |
|---------|-------------|---------|
| **AEC** | Cross-correlation echo detection + spectral masking. Detects echo by correlating mic audio against a reference buffer of bot output, then suppresses the correlated component. No adaptive filters, no convergence issues. | numpy (built-in) |
| **VAD** | Neural voice activity detection. <1 ms per chunk on CPU, 8 kHz native support, ~2 MB ONNX model. | [Silero VAD](https://github.com/snakers4/silero-vad) |

## Why this exists

Voice agents that call people over PSTN have an echo problem: the bot's TTS audio plays through the phone speaker, couples back through the mic, and gets transcribed as user input. The bot starts responding to its own words.

Some telephony providers (like Twilio) perform echo cancellation on their infrastructure. Others (like Exotel) don't. And even Twilio's AEC isn't perfect — in noisy environments, the audio quality degrades.

Commercial solutions like ai-coustics ($149/mo) provide noise suppression and VAD but not echo cancellation. voiceclean provides AEC + VAD as a single open-source package — free, no API keys, no network calls.

## Status — read this before adopting

After extended production testing on real Hindi/English/Nepali sales calls (Twilio + Exotel, multiple callees, multiple acoustic environments), we have to be honest about two failure modes that we did not catch in our earlier testing. Both reproduce reliably; one is a config bug we believe is fixed in v0.3.6, the other is a deeper algorithmic limit we have not solved.

**1. AEC spectrally damages legitimate user speech when the caller repeats vocabulary the bot just spoke.**
On telephony PSTN audio with shared vocabulary (the bot just listed product names, the retailer repeats them to order), cross-correlation between the user's mic chunk and the reference buffer crosses the suppression threshold not because there is acoustic echo, but because the two share phonemes. The spectral mask then strips the very formants the user just produced. Observed substitutions across many calls, same callee, same downstream STT:

| User said | Downstream STT heard (voiceclean) | Downstream STT heard (no voiceclean) |
|---|---|---|
| "Coke" | "cook" / "कोप देख" / "कोख" / dropped | "Coke" |
| "Sprite" | "Flight" / "Super Right" / "Spright" / "फ्लाइट" / "स्प्राइस" | "Sprite" |
| "Fanta" | "penta" / "Punjab" / "पांटा" / "घंटा" | "Fanta" |
| "1.5 litre" | "टेड लीटर" / "डिजिटल कॉक" / "डिलीटर" | "1.5 litre" |
| "30 cases" | "certificates" / "per tea cases" | "30 cases" |

We attempted a fix in v0.3.4 (Echo-to-Mic ratio gate + softer per-bin mask). It reduces but does not eliminate the damage. The fundamental issue is that the cross-correlation framing cannot distinguish "real echo" from "user repeating bot vocabulary" at 8 kHz telephony bandwidth.

**2. The shipped VAD default (`stop_secs=0.0`) fragments streaming STT on every inter-word pause.**
Pipecat's Sarvam STT and Deepgram STT services call `flush()` / `Finalize` on every `VADUserStoppedSpeakingFrame`. With voiceclean's pre-v0.3.6 VAD wrapper at `stop_secs=0.0`, that frame fires at every gap between words, and the streaming STT commits a fragment per word. A clean "I want Coke 1.5 litre 10 cases, Sprite 1.5 litre 20 cases" arrives at the LLM as 15–22 garbled mini-utterances. Azure STT is the only one of the three that escapes because it ignores Pipecat VAD events and uses its own endpointing. v0.3.6 changes the default to 0.2 (matching Pipecat's own default) but the underlying state machine is still sensitive — pause-heavy speakers still fragment.

**What we recommend right now:**

- If your downstream STT is **Sarvam or Deepgram (streaming)**, voiceclean is not yet ready for your production traffic. Use ai-coustics (or another filter with carrier AEC) until these issues are resolved.
- If your downstream STT is **Azure (streaming)**, the VAD fragmentation issue does not affect you, but the AEC speech-damage issue can still hurt high-overlap conversations.
- If you are doing **research / batch transcription / experimentation**, voiceclean works as advertised in this README and the article.
- If you adopt anyway, set `stop_secs ≥ 0.2` when creating the VAD analyzer, and instrument the per-call stats in your DB so you can see what voiceclean is doing.

The full investigation is in `ARTICLE_DRAFT.md` (post-mortem section). The dev-facing notes are in `CLAUDE.md`.

**Tested in production** on both Twilio and Exotel with real PSTN calls in Hindi, English, and Nepali — but the verdict from that testing is the section above, not the cheerful claim we used to make here.

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
