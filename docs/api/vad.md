# VAD

Voice activity detection backed by Silero VAD (ONNX).

```python
from voiceclean.vad import VAD
```

Requires: `pip install onnxruntime`

## `VAD`

```python
class VAD(
    sample_rate: int = 8000,
    threshold: float = 0.5,
)
```

Silero VAD is an ONNX model (~2 MB) that runs in <1 ms per chunk on CPU. Supports 8 kHz and 16 kHz natively.

The model is downloaded automatically on first use to `~/.cache/voiceclean/silero_vad.onnx`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sample_rate` | `int` | `8000` | Audio sample rate. Must be 8000 or 16000. |
| `threshold` | `float` | `0.5` | Speech probability threshold |

### Methods

#### `process`

```python
def process(self, audio: bytes) -> VADResult
```

Detect speech in audio. Buffers audio internally and returns the VAD result for the most recent complete frame.

**Frame sizes:**

- 8000 Hz: 256 samples (32 ms)
- 16000 Hz: 512 samples (32 ms)

**Parameters:**

- `audio` — Raw PCM int16 mono bytes at the configured sample rate.

**Returns:** `VADResult`

#### `reset`

```python
def reset(self) -> None
```

Reset internal LSTM state and audio buffer. Call between conversations to avoid state leaking across calls.

## `VADResult`

```python
@dataclass
class VADResult:
    is_speech: bool
    speech_prob: float
```

| Field | Type | Description |
|-------|------|-------------|
| `is_speech` | `bool` | `True` if `speech_prob >= threshold` |
| `speech_prob` | `float` | Speech probability from 0.0 to 1.0 |

## Example

```python
from voiceclean.vad import VAD

vad = VAD(sample_rate=8000, threshold=0.5)

result = vad.process(audio_chunk)
if result.is_speech:
    print(f"Speech detected (confidence: {result.speech_prob:.2f})")

# Between calls, reset state
vad.reset()
```

## Model details

| Property | Value |
|----------|-------|
| Model | Silero VAD v5 |
| Format | ONNX |
| Size | ~2 MB |
| Inference time | <1 ms per frame (CPU) |
| Internal state | LSTM, shape (2, 1, 128) |
| Source | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) |
| License | MIT |
