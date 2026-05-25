# Getting Started

## Installation

### Basic (AEC only)

```bash
pip install voiceclean
```

This installs the core package with AEC support. Dependencies: `numpy`, `soxr`.

### With VAD

```bash
pip install voiceclean[silero]
```

Adds Silero VAD via `onnxruntime`. The ONNX model (~2 MB) is downloaded automatically on first use to `~/.cache/voiceclean/`.

### With Pipecat integration

```bash
pip install voiceclean[pipecat]
```

Adds the `VoiceCleanFilter` and `VoiceCleanVAD` classes for use in Pipecat pipelines.

### Everything

```bash
pip install voiceclean[all]
```

Installs all optional dependencies (Silero VAD + Pipecat integration).

## Basic usage

### Standalone AEC + VAD

```python
from voiceclean import VoiceClean

vc = VoiceClean(sample_rate=8000)

# In your audio processing loop:

# 1. When the bot sends audio to the speaker, feed it as reference
vc.feed_reference(bot_audio_bytes)

# 2. When mic audio arrives, process it
result = vc.process(mic_audio_bytes)

clean_audio = result.audio        # echo removed
is_speaking = result.is_speech    # caller speaking?
confidence  = result.speech_prob  # 0.0–1.0
```

### AEC only (no VAD)

```python
from voiceclean.aec import AEC

aec = AEC(sample_rate=8000)

# Feed reference
aec.feed_reference(bot_audio)

# Process mic audio
clean = aec.process(mic_audio)  # returns bytes
```

### VAD only (no AEC)

```python
from voiceclean.vad import VAD

vad = VAD(sample_rate=8000, threshold=0.5)

result = vad.process(audio_bytes)
print(result.is_speech)    # True/False
print(result.speech_prob)  # 0.0–1.0
```

## Audio format requirements

All audio must be **PCM int16 mono** — signed 16-bit little-endian, single channel. This is the standard format for:

- Twilio Media Streams (G.711 u-law decoded to PCM)
- Exotel Voicebot applet (raw PCM s16le)
- Pipecat internal audio frames (`OutputAudioRawFrame`)

## Supported sample rates

| Component | Supported rates |
|-----------|----------------|
| AEC | Any (tested at 8000, 16000, 48000) |
| VAD | 8000 or 16000 Hz only (Silero VAD limitation) |

For telephony applications, use **8000 Hz** — it matches the PSTN native rate and avoids unnecessary resampling.

## Next steps

- [How AEC Works](how-aec-works.md) — understand the algorithm
- [Configuration](configuration.md) — tune AEC parameters
- [Pipecat Guide](pipecat-guide.md) — integrate with a voice agent pipeline
