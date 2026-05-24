# voiceclean

Real-time acoustic echo cancellation (AEC), noise suppression, and voice activity detection (VAD) for voice agents. Built for telephony (8 kHz PSTN audio), works at any sample rate.

Wraps three proven open-source libraries into a single Python package:

| Feature | Library | What it does |
|---------|---------|-------------|
| **AEC** | [SpeexDSP](https://github.com/xiph/speexdsp) | Removes the bot's own speech from the caller's mic signal. Essential when the telephony provider doesn't do carrier-side echo cancellation. |
| **Noise suppression** | [RNNoise](https://github.com/xiph/rnnoise) via [pyrnnoise](https://pypi.org/project/pyrnnoise/) | Neural noise reduction. Best at 48 kHz; for 8 kHz telephony, AEC alone is usually sufficient. |
| **VAD** | [Silero VAD](https://github.com/snakers4/silero-vad) | Detects speech vs silence. <1 ms per chunk on CPU, 8 kHz native support, ~2 MB ONNX model. |

## Why this exists

Cloud telephony providers like Twilio perform echo cancellation on their infrastructure before delivering audio to your WebSocket. Others (like Exotel) don't — the bot's TTS output bleeds through the caller's mic and gets transcribed as user input, creating a self-conversation loop.

Commercial solutions like ai-coustics ($149/mo) provide noise suppression and VAD but not AEC. voiceclean fills that gap with open-source components.

## Install

```bash
pip install voiceclean            # core (numpy + soxr only)
pip install voiceclean[all]       # AEC + noise suppression + VAD + Pipecat integration
pip install voiceclean[silero]    # VAD only
pip install voiceclean[rnnoise]   # noise suppression only
```

**System dependency for AEC** — libspeexdsp must be installed on the host:

```bash
# Debian / Ubuntu
sudo apt install libspeexdsp-dev

# macOS
brew install speexdsp
```

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
from voiceclean.denoise import Denoiser
from voiceclean.vad import VAD

# Echo cancellation
aec = AEC(sample_rate=8000, filter_length=4000)
aec.feed_reference(bot_audio)
clean = aec.process(mic_audio)

# Noise suppression (best at 48 kHz; resamples internally)
denoiser = Denoiser(sample_rate=8000)
clean = denoiser.process(noisy_audio)

# Voice activity detection
vad = VAD(sample_rate=8000, threshold=0.5)
result = vad.process(audio)  # result.is_speech, result.speech_prob
```

### Pipecat integration

voiceclean plugs into [Pipecat](https://github.com/pipecat-ai/pipecat) as a `BaseAudioFilter` + `VADAnalyzer`. The key design: a `reference_collector` FrameProcessor captures outgoing audio for the AEC reference signal.

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
2. **Mic signal** — what the caller's mic picks up (speech + echo of the bot)

SpeexDSP's adaptive filter learns the echo path (including network delay, acoustic coupling, codec artifacts) and subtracts the predicted echo from the mic signal. The async playback/capture API handles delay alignment internally — you don't need to time-synchronize the two streams.

```
Bot TTS audio ──► feed_reference() ──► SpeexDSP learns echo path
                                              │
Caller mic audio ──► process() ─────► SpeexDSP subtracts echo ──► clean audio
```

**Filter length**: Default 4000 samples = 500 ms at 8 kHz. This must cover the full echo round-trip delay (typically 100–500 ms on PSTN). Increase if you hear residual echo on high-latency paths.

## Audio format

All audio is **PCM int16 mono** (signed 16-bit little-endian, single channel). This is the standard format for telephony audio and what Pipecat's frame processors use internally.

## Notes on RNNoise

RNNoise operates at 48 kHz internally. For 8 kHz telephony audio, it resamples up and back (8k → 48k → 8k), which can degrade narrowband speech quality. In telephony applications, **AEC alone is usually sufficient** — the PSTN noise floor is low enough for STT accuracy. The Pipecat filter disables RNNoise by default for this reason.

RNNoise works well for wideband (16 kHz+) applications where the full frequency range benefits from neural denoising.

## Credits

This package wraps open-source libraries by their respective authors:

- **SpeexDSP** — Jean-Marc Valin / [Xiph.Org Foundation](https://xiph.org/) (BSD License)
- **RNNoise** — Jean-Marc Valin / [Xiph.Org Foundation](https://xiph.org/) (BSD-3-Clause License)
- **Silero VAD** — [Silero Team](https://github.com/snakers4/silero-vad) (MIT License)

## License

MIT
