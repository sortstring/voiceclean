# VoiceClean

The main pipeline class that chains AEC and VAD together.

```python
from voiceclean import VoiceClean
```

## `VoiceClean`

```python
class VoiceClean(
    sample_rate: int = 8000,
    vad_threshold: float = 0.5,
)
```

Full audio cleanup pipeline: AEC followed by VAD. Components are optional — if `onnxruntime` is not installed, VAD is skipped with a warning.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sample_rate` | `int` | `8000` | Audio sample rate in Hz |
| `vad_threshold` | `float` | `0.5` | Speech probability threshold for VAD |

### Properties

#### `has_aec`

```python
@property
def has_aec(self) -> bool
```

Returns `True` if AEC is available (always `True` since AEC has no optional dependencies).

#### `has_vad`

```python
@property
def has_vad(self) -> bool
```

Returns `True` if VAD is available (`onnxruntime` is installed).

### Methods

#### `feed_reference`

```python
def feed_reference(self, audio: bytes) -> None
```

Feed the bot's outgoing audio as AEC reference signal. Call this every time the bot sends audio to the speaker.

**Parameters:**

- `audio` — Raw PCM int16 mono bytes at the configured sample rate.

#### `process`

```python
def process(self, mic_audio: bytes) -> ProcessResult
```

Run the full pipeline (AEC then VAD) on mic audio.

**Parameters:**

- `mic_audio` — Raw PCM int16 mono bytes from the caller's mic.

**Returns:** `ProcessResult`

## `ProcessResult`

```python
@dataclass
class ProcessResult:
    audio: bytes
    is_speech: bool
    speech_prob: float
```

| Field | Type | Description |
|-------|------|-------------|
| `audio` | `bytes` | Cleaned PCM int16 mono audio (echo removed) |
| `is_speech` | `bool` | Whether the caller is speaking |
| `speech_prob` | `float` | Speech probability from 0.0 to 1.0 |

## Example

```python
from voiceclean import VoiceClean

vc = VoiceClean(sample_rate=8000)

# Audio processing loop
while True:
    bot_audio = get_bot_output()    # TTS audio being sent to caller
    mic_audio = get_mic_input()     # audio from caller's mic

    vc.feed_reference(bot_audio)
    result = vc.process(mic_audio)

    if result.is_speech:
        send_to_stt(result.audio)   # only transcribe when caller is speaking
```
