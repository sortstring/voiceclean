# AEC

Cross-correlation based acoustic echo cancellation.

```python
from voiceclean.aec import AEC
```

## `AEC`

```python
class AEC(
    sample_rate: int = 8000,
    chunk_ms: int = 40,
    buffer_ms: int = 800,
    correlation_threshold: float = 0.15,
    suppress_db: float = -30.0,
)
```

Maintains a circular buffer of recent reference (bot) audio. For each mic chunk, computes normalized cross-correlation against the reference. When correlation exceeds the threshold, applies spectral masking to suppress the echo while preserving uncorrelated signal (real user speech).

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sample_rate` | `int` | `8000` | Audio sample rate in Hz |
| `chunk_ms` | `int` | `40` | Analysis chunk size in milliseconds |
| `buffer_ms` | `int` | `800` | Reference buffer length in milliseconds. Must cover max echo delay. |
| `correlation_threshold` | `float` | `0.15` | Normalized cross-correlation above which echo is detected |
| `suppress_db` | `float` | `-30.0` | Echo suppression depth in dB |

See [Configuration](../configuration.md) for tuning guidance.

### Methods

#### `feed_reference`

```python
def feed_reference(self, audio: bytes) -> None
```

Feed bot's outgoing audio into the reference ring buffer. The buffer is circular — old audio is overwritten as new audio arrives.

**Parameters:**

- `audio` — Raw PCM int16 mono bytes. Can be any length; internally buffered and written in chunk-sized pieces.

#### `process`

```python
def process(self, mic_audio: bytes) -> bytes
```

Process mic audio: detect and suppress echo. Audio is internally buffered and processed in `chunk_ms`-sized pieces.

**Parameters:**

- `mic_audio` — Raw PCM int16 mono bytes from the caller's mic.

**Returns:** Cleaned PCM int16 mono bytes. May be empty if not enough audio has accumulated for a complete chunk.

**Behavior:**

- If no reference audio has been fed yet, mic audio passes through unchanged.
- If the mic chunk has near-zero energy (silence), it passes through unchanged.
- If cross-correlation with the reference is below `correlation_threshold`, the chunk passes through unchanged.
- If echo is detected, spectral masking suppresses echo-dominated frequency bins.

## Example

```python
from voiceclean.aec import AEC

aec = AEC(
    sample_rate=8000,
    buffer_ms=1200,              # longer buffer for international calls
    correlation_threshold=0.10,  # more aggressive detection
)

# Feed reference continuously
aec.feed_reference(bot_tts_audio)

# Process mic audio
clean_audio = aec.process(mic_audio)
```

## Thread safety

`feed_reference()` and `process()` are thread-safe. The reference ring buffer is protected by a lock. It is safe to call `feed_reference()` from one thread (e.g., the output audio path) and `process()` from another (e.g., the input audio path).
