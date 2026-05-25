# Pipecat Guide

This guide shows how to integrate voiceclean into a [Pipecat](https://github.com/pipecat-ai/pipecat) voice agent pipeline for real-time echo cancellation and voice activity detection.

## Install

```bash
pip install voiceclean[all]
```

## Overview

voiceclean provides two Pipecat components:

1. **`VoiceCleanFilter`** — a `BaseAudioFilter` that runs AEC on incoming audio
2. **`VoiceCleanVAD`** — a `VADAnalyzer` that provides voice activity detection for turn management

Both are created from a single `VoiceCleanFilter` instance, ensuring they share state.

## Step-by-step integration

### 1. Create the filter

```python
from voiceclean.pipecat import VoiceCleanFilter

vc_filter = VoiceCleanFilter(sample_rate=8000)
```

### 2. Wire as audio input filter

Pass the filter to the transport so it processes all incoming audio:

```python
from pipecat.transports.services.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

transport = FastAPIWebsocketTransport(
    websocket=websocket,
    params=FastAPIWebsocketParams(
        audio_in_filter=vc_filter,
        serializer=serializer,
    ),
)
```

### 3. Create VAD analyzer

```python
vad_analyzer = vc_filter.create_vad_analyzer()
```

Pass this to your pipeline params or turn detection strategy.

### 4. Wire reference collector in the pipeline

The AEC needs the bot's outgoing audio as a reference signal. `vc_filter.reference_collector` is a `FrameProcessor` that captures `OutputAudioRawFrame` bytes before they reach the transport output.

**It must go before `transport.output()` in the pipeline:**

```python
from pipecat.pipeline.pipeline import Pipeline

pipeline = Pipeline([
    transport.input(),
    stt,
    user_transcript_emitter,
    user_aggregator,
    llm,
    tts,
    assistant_transcript_emitter,
    vc_filter.reference_collector,   # captures bot audio for AEC
    transport.output(),
    assistant_aggregator,
])
```

!!! warning "Placement matters"
    If `reference_collector` is placed **after** `transport.output()`, it never sees the outgoing audio frames and AEC has no reference to work with. Echo will not be cancelled.

## Complete example

```python
import asyncio
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.transports.services.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)
from voiceclean.pipecat import VoiceCleanFilter

async def run_call(websocket, serializer, stt, llm, tts):
    # Create filter
    vc_filter = VoiceCleanFilter(sample_rate=8000)

    # Transport with filter
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_filter=vc_filter,
            serializer=serializer,
        ),
    )

    # VAD
    vad_analyzer = vc_filter.create_vad_analyzer()

    # Pipeline
    pipeline = Pipeline([
        transport.input(),
        stt,
        llm,
        tts,
        vc_filter.reference_collector,
        transport.output(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            vad_analyzer=vad_analyzer,
        ),
    )

    runner = PipelineRunner()
    await runner.run(task)
```

## Using alongside other audio filters

voiceclean is designed to coexist with other audio filter providers. You can select which filter to use per call:

```python
if audio_filter == "voiceclean":
    from voiceclean.pipecat import VoiceCleanFilter

    vc_filter = VoiceCleanFilter(sample_rate=8000)
    audio_in_filter = vc_filter
    vad_analyzer = vc_filter.create_vad_analyzer()
    reference_collector = vc_filter.reference_collector

elif audio_filter == "aic":
    from pipecat.audio.filters.aic_filter import AICFilter

    aic_filter = AICFilter(license_key=key, model_id="quail-l-8khz")
    audio_in_filter = aic_filter
    vad_analyzer = aic_filter.create_vad_analyzer()
    reference_collector = None
```

If `reference_collector` is not `None`, include it in the pipeline before `transport.output()`.

## Telephony provider compatibility

| Provider | AEC needed? | Why |
|----------|-------------|-----|
| **Twilio** | Optional | Twilio performs carrier-side AEC. voiceclean adds extra protection and handles noisy environments better. |
| **Exotel** | Required | Exotel streams raw mic audio without AEC. Without voiceclean, the bot hears its own echo. |

## Troubleshooting

### Echo still present

1. Verify `reference_collector` is in the pipeline **before** `transport.output()`
2. Check that audio is actually flowing through the collector (add a log in `_ReferenceCollector.process_frame`)
3. Try lowering `correlation_threshold` to 0.10

### No barge-in (user can't interrupt the bot)

1. Verify `vad_analyzer` is passed to `PipelineParams`
2. Check that `num_frames_required()` returns the correct value (256 at 8 kHz)
3. Ensure VAD is not running inside `filter()` — VAD should only run in `voice_confidence()`

### User speech suppressed

1. Try raising `correlation_threshold` to 0.20
2. Check that `suppress_db` is not too aggressive (default -30 is fine for most cases)
