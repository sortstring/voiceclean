# voiceclean

Real-time acoustic echo cancellation (AEC) and voice activity detection (VAD) for voice agents.

Built for telephony (8 kHz PSTN audio), works at any sample rate. No external C libraries — pure Python + numpy.

| Feature | How it works | Library |
|---------|-------------|---------|
| **AEC** | Cross-correlation echo detection + spectral masking | numpy (built-in) |
| **VAD** | Neural voice activity detection, <1 ms per chunk on CPU | [Silero VAD](https://github.com/snakers4/silero-vad) (ONNX) |

## Why this exists

Voice agents that call people over PSTN have an echo problem: the bot's TTS audio plays through the phone speaker, couples back through the mic, and gets transcribed as user input. The bot starts responding to its own words.

Some telephony providers (like Twilio) perform echo cancellation on their infrastructure. Others (like Exotel) don't. Commercial solutions like ai-coustics ($149/mo) provide noise suppression and VAD but not echo cancellation.

voiceclean provides AEC + VAD as a single open-source package — free, no API keys, no network calls.

**Tested in production** on both Twilio and Exotel with real PSTN calls in Hindi, English, and Nepali.

## Quick install

```bash
pip install voiceclean
```

No system dependencies. No C libraries. Just numpy + soxr + onnxruntime.

## Quick example

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

## Audio format

All audio is **PCM int16 mono** (signed 16-bit little-endian, single channel). This is the standard format for telephony audio and what Pipecat's frame processors use internally.

## Next steps

- [Getting Started](getting-started.md) — install and run your first echo cancellation
- [How AEC Works](how-aec-works.md) — understand the cross-correlation approach
- [API Reference](api/voiceclean.md) — full class and method documentation
- [Pipecat Guide](pipecat-guide.md) — integrate with a Pipecat voice agent pipeline
