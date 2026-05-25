# Pipecat Integration

voiceclean integrates with [Pipecat](https://github.com/pipecat-ai/pipecat) as a `BaseAudioFilter` and `VADAnalyzer`.

```python
from voiceclean.pipecat import VoiceCleanFilter, VoiceCleanVAD
```

Requires: `pip install voiceclean[pipecat]`

## `VoiceCleanFilter`

```python
class VoiceCleanFilter(BaseAudioFilter):
    def __init__(
        self,
        sample_rate: int = 8000,
        vad_threshold: float = 0.5,
    )
```

Pipecat audio input filter backed by voiceclean. Provides AEC on the input audio path and exposes a VAD analyzer for turn detection.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sample_rate` | `int` | `8000` | Audio sample rate in Hz |
| `vad_threshold` | `float` | `0.5` | Speech probability threshold for VAD |

### Properties

#### `reference_collector`

```python
@property
def reference_collector(self) -> FrameProcessor
```

A lightweight `FrameProcessor` that captures `OutputAudioRawFrame` bytes for the AEC reference signal. **Must be inserted in the pipeline before `transport.output()`.**

The collector passes all frames through unchanged — it only copies audio bytes into the AEC reference buffer. Zero impact on the output path.

### Methods

#### `create_vad_analyzer`

```python
def create_vad_analyzer(self, **kwargs) -> VoiceCleanVAD
```

Create a `VADAnalyzer` that shares this filter's internal VoiceClean instance. The VAD and AEC share state, ensuring the VAD processes audio after echo has been removed.

**Returns:** `VoiceCleanVAD` instance

#### `filter`

```python
async def filter(self, audio: bytes) -> bytes
```

Called by Pipecat's transport for each incoming audio chunk. Runs AEC on the audio and returns the cleaned result.

## `VoiceCleanVAD`

```python
class VoiceCleanVAD(VADAnalyzer):
    def __init__(
        self,
        vc: VoiceClean,
        sample_rate: int = 8000,
    )
```

Pipecat `VADAnalyzer` backed by voiceclean's Silero VAD. Created via `VoiceCleanFilter.create_vad_analyzer()` — you don't normally construct this directly.

### Methods

#### `num_frames_required`

```python
def num_frames_required(self) -> int
```

Returns the number of audio samples needed per VAD frame:

- 8000 Hz: **256 samples** (32 ms)
- 16000 Hz: **512 samples** (32 ms)

#### `voice_confidence`

```python
def voice_confidence(self, buffer: bytes) -> float
```

Returns speech probability (0.0–1.0) for the given audio buffer.

## Pipeline wiring

See [Pipecat Guide](../pipecat-guide.md) for the complete integration walkthrough.

```python
vc_filter = VoiceCleanFilter(sample_rate=8000)

transport = FastAPIWebsocketTransport(
    websocket=websocket,
    params=FastAPIWebsocketParams(
        audio_in_filter=vc_filter,
        serializer=serializer,
    ),
)

vad_analyzer = vc_filter.create_vad_analyzer()

pipeline = Pipeline([
    transport.input(),
    stt,
    user_aggregator,
    llm,
    tts,
    # ... other processors ...
    vc_filter.reference_collector,   # MUST go before transport.output()
    transport.output(),
    assistant_aggregator,
])
```
