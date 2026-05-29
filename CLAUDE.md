# Working principles

1. Don't assume. Don't hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. NEVER JUMP TO CONCLUSIONS. NEVER CONFIDENTLY ASSERT SOMETHING YOU ARE NOT SURE ABOUT.
5. NEVER ASSUME EXTERNAL SERVICE BEHAVIOR. Only assert what is verified against official docs or live tests.

---

# Honest production status (read this before recommending voiceclean)

Extended testing on real Hindi/English calls (Twilio + Exotel, Sarvam + Azure + Deepgram STT) on 2026-05-28 / 29 surfaced two reproducible failure modes that the README's "tested in production" phrasing did not previously reflect. **Both are documented in detail below.** If a downstream user reports STT garbling or fragmented turns with voiceclean enabled, the cause is almost certainly one of these two; don't blame their STT provider until you have ruled them out.

## Failure mode 1 — AEC damages user speech when caller repeats bot vocabulary

Reproducible across multiple callees, multiple handsets, multiple acoustic environments. Same callee, same downstream Azure STT, same `+919454777614` test handset:

- **Call CAa8b0aff7… (voiceclean, hi-IN, Azure)** — Sarvam batch on the recording reads the caller channel as "इस हफ्ते मुझे आप कोक डेढ़ लीटर का दस केस…" (clean). The live Azure STT, which received the *post-voiceclean* audio in real time, transcribed it as "इस हफ्ते मुझे आप को डेढ़ लीटर का 10 केस… इस फ्लाइट डेढ़ लीटर… घंटा ऑरेंज…". Coke → "आप को" (eaten), Sprite → "फ्लाइट", Fanta → "घंटा".
- **Call CA8c4a6b2d… (voiceclean, hi-IN, Azure, 2026-05-29 02:32 UTC)** — same handset. Live Azure heard "फ्लाइट दे दीजिए। रिटर्न 10 के और पांटा ऑरेंज के लिए टेड लीटर का बीच केस" — Sprite → "फ्लाइट", "डेढ़ लीटर 10 केस" → "रिटर्न 10 के", Fanta → "पांटा", "डेढ़ लीटर" → "टेड लीटर", "बीस केस" → "बीच केस".
- **Same handset two minutes later on AIC (CAe2f1b4…)** — live Azure heard "कोक/स्प्राइट/फैंटा/डेढ़ लीटर" cleanly. Only mishearing was Coke → "कोख", which is well within Azure STT's normal Hindi error rate.

The signature is consistent. Hard consonants and brand names get warped; common Hindi words are unaffected.

**Why it happens.** Cross-correlation between the user's mic chunk and the 800 ms reference buffer crosses the suppression threshold whenever the user repeats a word the bot has recently spoken — because the user's audio shares spectral content with the reference, not because there is acoustic echo. The spectral mask then suppresses bins where the reference dominates, stripping the very formants that distinguish "Coke" from "ok" or "Sprite" from "Flight".

**What has been tried.** v0.3.4 added two gates (EMR ≥ 0.5, per-bin `echo_ratio > 1.0`) and a softer suppression curve. These reduce but do not eliminate the damage. The fundamental issue is that 8 kHz telephony bandwidth does not carry enough spectral information to distinguish bot-bleed echo from user repeating bot vocabulary; cross-correlation alone is not a sufficient discriminator.

**What we don't know.** Whether a stricter EMR (e.g., 4.0), a lag-window restriction (only consider lags 30–300 ms), or a switch to coherence-based detection would close it. We did not have time to validate any of these in production.

## Failure mode 2 — VAD fragments streaming STT (partial fix in v0.3.6)

`VoiceCleanVAD` shipped with `stop_secs=0.0` to minimise barge-in latency. Pipecat's Sarvam and Deepgram STT services finalise their current utterance on every `VADUserStoppedSpeakingFrame`, which at `stop_secs=0.0` fires at every gap between words. The streaming STT then commits one fragment per word.

Concrete evidence — call 457a6a8b…, en-US, Sarvam streaming STT, voiceclean filter, dumped IN/OUT PCM at the actual live sample rate:

- **Sarvam batch STT on the OUT.pcm file** → "I want Coke 1.5 liter 10 cases, Fanta orange 1.5 liter 20 cases and Sprite 1.5 liter 30 cases." (clean)
- **Sarvam streaming STT on the same audio during the live call** → 15 fragments: "Phone | I want to cook | 1.5 | Hello | 10 cases | Fine | Orange | 1.5 liter | Sweetheart | Yes | Okay | Condition | Spright | 1.5 | 5 liter | Okay, Sir"

The audio bytes were fine. The chunking destroyed them. VAD simulation at multiple `stop_secs` values on real dumped recordings:

| Call | live frags | @0.0 | @0.05 | @0.2 | @0.5 |
|---|---:|---:|---:|---:|---:|
| #2  vc/hi-IN/Sarvam | 14 | 21 | 15 | 7 | 4 |
| #10 vc/en-US/Deepgram/Exotel | 22 | 35 | 18 | 12 | 7 |
| #16 vc/hi-IN/Deepgram | 15 | 24 | 19 | 15 | 9 |
| #1  vc/hi-IN/Azure (Azure ignores VAD!) | 3 | 23 | 21 | 9 | 6 |

v0.3.6 changes the default to 0.2 (matches Pipecat's own VAD default). Simulation says fragmentation drops 1.5–3× but is not eliminated — order conversations with 3 SKU+qty pairs still produce 7–15 fragments where ideal is 3.

**Azure STT is the only escape.** Pipecat's `AzureSTTService` ignores `VADUserStoppedSpeakingFrame` entirely and uses its own internal endpointing. Confirmed by reading `pipecat/services/azure/stt.py` — it runs `start_continuous_recognition_async()` and only reacts to its own `recognized` callback. That is why voiceclean + Azure produced clean transcripts even on calls where the VAD fired 23 stop events.

## Recommendation to anyone integrating voiceclean today

- Do not deploy voiceclean as the production audio filter for a voice agent that uses **Sarvam or Deepgram streaming STT**. Use AIC or another filter with carrier-side AEC and a more conservative VAD wrapper.
- If your downstream STT is **Azure streaming**, the VAD problem does not affect you, but the AEC speech-damage problem (failure mode 1) can still hurt orders that involve repeating brand names.
- For batch / offline STT use cases, voiceclean works as advertised — the failures above are specific to the streaming-STT integration path.
- If you adopt anyway, set `stop_secs ≥ 0.2` when creating the VAD analyser, and log the per-call `get_stats()` output so the AEC's behaviour is visible in your call records.

This section is intentionally pessimistic about our own package. If a future version genuinely closes the gap, edit it down — but only after a controlled real-call A/B test, not synthetic verification.

---

# What this project is

An open-source Python package providing real-time **acoustic echo cancellation (AEC)** and **voice activity detection (VAD)** for voice AI agents. Published on [PyPI](https://pypi.org/project/voiceclean/) as `voiceclean`, documented at [voiceclean.readthedocs.io](https://voiceclean.readthedocs.io), source at [github.com/sortstring/voiceclean](https://github.com/sortstring/voiceclean). MIT licensed.

Built specifically for telephony (8 kHz PSTN audio). No external C libraries — pure Python + numpy.

## What it does

- **AEC**: detects echo by cross-correlating mic audio against a reference buffer of the bot's outgoing audio, then suppresses echo via spectral masking. No adaptive filters, no convergence, stateless per-chunk.
- **VAD**: Silero VAD (ONNX, ~2 MB) for speech detection. <1 ms per frame on CPU.
- **Pipecat integration**: `VoiceCleanFilter` (BaseAudioFilter) + `VoiceCleanVAD` (VADAnalyzer) drop into a Pipecat pipeline.

## What it does NOT do

- Noise suppression. It suppresses echo (audio correlated with the reference). Uncorrelated background noise passes through.
- Anything telephony-related. It processes raw PCM audio. It knows nothing about Twilio, Exotel, SIP, or WebSockets.

---

# Package structure

```
voiceclean/
├── pyproject.toml         Package metadata, version, dependencies
├── mkdocs.yml             MkDocs config for ReadTheDocs
├── .readthedocs.yaml      ReadTheDocs build config
├── README.md              PyPI long description
├── LICENSE                 MIT
├── docs/                  Documentation source (MkDocs + Material)
│   ├── index.md
│   ├── getting-started.md
│   ├── how-aec-works.md
│   ├── configuration.md
│   ├── pipecat-guide.md
│   ├── background.md
│   └── api/
│       ├── voiceclean.md
│       ├── aec.md
│       ├── vad.md
│       └── pipecat.md
└── voiceclean/            Python package
    ├── __init__.py        Public API: VoiceClean, ProcessResult, __version__
    ├── aec.py             AEC — cross-correlation detection + spectral masking
    ├── vad.py             VAD — Silero VAD via ONNX
    ├── pipeline.py        VoiceClean — chains AEC → VAD
    ├── denoise.py         LEGACY. RNNoise wrapper. Not used in production
    │                      (disabled — double resample 8k→48k→8k degrades
    │                      narrowband audio). Kept for potential future use
    │                      at higher sample rates.
    ├── resample.py        soxr-based resampling (used by denoise.py only)
    └── pipecat/
        ├── __init__.py    Exports VoiceCleanFilter, VoiceCleanVAD
        ├── filter.py      VoiceCleanFilter (BaseAudioFilter) +
        │                  _ReferenceCollector (FrameProcessor)
        └── vad.py         VoiceCleanVAD (VADAnalyzer)
```

---

# How AEC works — the 30-second version

1. Bot's outgoing audio is fed into a **ring buffer** via `feed_reference()`.
2. For each mic chunk (40 ms), compute **normalized cross-correlation** (FFT) against the ring buffer.
3. If the peak correlation exceeds `correlation_threshold` (default 0.15, recommended 0.10 for telephony) → echo is present at that lag.
4. **Spectral masking**: suppress frequency bins where echo dominates; preserve bins with uncorrelated energy (real speech).
5. If correlation is below threshold → no echo → audio passes through unchanged.

No adaptive filters. No convergence. No external C libraries. Pure numpy FFT.

Read `docs/how-aec-works.md` or `voiceclean/aec.py` for the full algorithm.

---

# Key parameters

## AEC (`voiceclean/aec.py`)

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `sample_rate` | 8000 | Audio sample rate in Hz |
| `chunk_ms` | 40 | Analysis chunk size (ms). Larger = more reliable, more latency |
| `buffer_ms` | 800 | Reference ring buffer length (ms). Must cover max echo delay. Increase for international calls. |
| `correlation_threshold` | 0.15 | Cross-correlation above which echo is *considered*. Unchanged from v0.3.3 — real echo on telephony often sits at 0.13–0.20, so raising it would lose echo catches. In v0.3.4 the user-speech-damage failure mode is handled by `min_echo_ratio` instead. |
| `min_echo_ratio` | 0.5 | NEW in v0.3.4. Reference-at-lag energy / mic energy below which a chunk is not considered echo even if correlation crosses threshold. Real echo dominates the mic signal; incidental vocabulary correlation doesn't. Set to 0.0 to restore pre-v0.3.4 detection behaviour. |
| `suppress_db` | -30.0 | Echo suppression depth (dB) floor. -30 = echo bin at ~3% of original. Used as the floor on the per-bin soft-suppression gain. |

## VAD (`voiceclean/vad.py`)

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `sample_rate` | 8000 | Must be 8000 or 16000 (Silero limitation) |
| `threshold` | 0.5 | Speech probability above which `is_speech=True` |

## VAD analyzer (`voiceclean/pipecat/vad.py`, the Pipecat-side wrapper)

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `confidence` | 0.5 | Silero confidence above which a frame counts as speech. |
| `start_secs` | 0.0 | How long confidence must stay above threshold before "speech started" fires. 0 = fire instantly. |
| `stop_secs` | 0.2 | How long confidence must stay below threshold before "speech stopped" fires. **Raised from 0.0 to 0.2 in v0.3.6** — at 0.0 the VAD signalled "stopped" at every inter-word pause, fragmenting streaming-STT utterances into one-word chunks and producing noise transcription. Pipecat's own default is 0.2; ai-coustics uses 0.05. Keep above ~0.15 unless you have a specific reason to sacrifice STT quality for ~200 ms of turn-end latency. |
| `min_volume` | 0.0 | Minimum audio volume to count as speech. Disabled by default (Silero confidence is a strong signal on its own). |

`VoiceCleanFilter.create_vad_analyzer()` now accepts `confidence`, `start_secs`, `stop_secs`, and `min_volume` directly, and aliases `speech_hold_duration` (an ai-coustics-side kwarg the agent passes in some integrations) onto `stop_secs` when no explicit value is given. The `sensitivity` kwarg is accepted for ai-coustics drop-in compatibility and ignored.

---

# Debug dump (v0.3.5+)

`VoiceCleanFilter` honours the env var `VOICECLEAN_DEBUG_DUMP_DIR`. If set to a writable directory, every filter instance writes three raw PCM streams per call:

- `vc_<ts>_<pid>_<id>_in.pcm`  — mic audio BEFORE the AEC
- `vc_<ts>_<pid>_<id>_out.pcm` — mic audio AFTER the AEC (this is what reaches STT)
- `vc_<ts>_<pid>_<id>_ref.pcm` — bot audio fed as the AEC reference

Format: signed 16-bit little-endian, mono, at the filter's configured sample rate (default 8000 Hz). Convert with:

```bash
ffmpeg -f s16le -ar 8000 -ac 1 -i vc_<...>_out.pcm vc_<...>_out.wav
```

Purpose: distinguish "voiceclean damaged the audio" from "downstream STT mis-recognised clean audio". A pre/post diff at the live sample rate is the only reliable way — Twilio dual-channel MP3 recordings round-trip through 8 kHz µ-law → PCM → 22 kHz MP3 and don't show artefacts that may matter to streaming STT.

No agent-app code change is needed to enable it. Set the env var before starting the agent:

```bash
VOICECLEAN_DEBUG_DUMP_DIR=/tmp/vcdump python -m agent.server
```

I/O failures are best-effort: a full disk warns once and silently drops further writes; the live call never aborts because of dump failure.

---

# Audio format

All audio is **PCM int16 mono** (signed 16-bit little-endian, single channel).

Frame sizes:
- AEC: `chunk_ms` × `sample_rate / 1000` samples (default: 320 samples at 8 kHz)
- VAD: 256 samples at 8 kHz, 512 at 16 kHz (Silero requirement)

---

# Thread safety

`AEC.feed_reference()` and `AEC.process()` are thread-safe — the reference ring buffer is protected by a lock. This is necessary because in a Pipecat pipeline, reference audio is fed from the output path (one async task) while mic audio is processed on the input path (another async task).

---

# Dependencies

**Required** (always installed):
- `numpy` — FFT, array operations
- `soxr` — high-quality resampling (used by denoise.py, not by AEC/VAD)

**Optional**:
- `onnxruntime` — required for VAD (`pip install voiceclean[silero]`)
- `pipecat-ai` — required for Pipecat integration (`pip install voiceclean[pipecat]`)

The Silero VAD ONNX model (~2 MB) is auto-downloaded on first use to `~/.cache/voiceclean/silero_vad.onnx`.

---

# Publishing

## PyPI

Version is defined in TWO places — keep them in sync:
1. `pyproject.toml` → `version = "X.Y.Z"`
2. `voiceclean/__init__.py` → `__version__ = "X.Y.Z"`

To publish:
```bash
rm -rf dist/ build/ *.egg-info
python -m build
python -m twine upload dist/*
```

PyPI credentials are in `~/.pypirc`. PyPI does not allow re-uploading the same version — always bump.

## ReadTheDocs

Docs rebuild automatically on every push to `main`. No manual action needed.

---

# History of what was tried and replaced

Understanding what was tried and why it failed prevents re-introducing dead-end approaches.

## SpeexDSP adaptive filter (v0.1.0–v0.2.x)

Traditional telephony AEC. Wrapped `libspeexdsp` via ctypes. Worked perfectly on synthetic tests, failed intermittently (~50% of calls) on real PSTN audio. The adaptive filter diverged under non-linear conditions (speaker distortion, codec artifacts, variable delay). Replaced entirely in v0.3.0.

**Do not re-introduce adaptive filtering.** The failure mode is intermittent and hard to reproduce — it looks like it works until it doesn't on a real call.

## MFCC voice fingerprinting

Attempted to distinguish bot speech from human speech using Mel-frequency cepstral coefficients. At 8 kHz telephony bandwidth (0–4 kHz), the cosine distance between bot and caller was 0.0041 vs self-consistency of 0.0036. Indistinguishable. Narrowband audio doesn't carry enough spectral information.

**Do not re-attempt voice fingerprinting at 8 kHz.**

## RNNoise (neural noise suppression)

Included in v0.1.0 for background noise removal. Operates at 48 kHz internally. The double resampling (8k→48k→8k) degraded narrowband telephony audio, producing garbled STT transcriptions. Disabled for telephony. The code remains in `denoise.py` but is not used.

**Do not re-enable RNNoise for 8 kHz audio.**

## VAD with zero stop-hold (v0.3.0–v0.3.5)

The `VoiceCleanVAD` defaults were `start_secs=0.0 / stop_secs=0.0` — both set deliberately to minimise barge-in latency. In practice this caused the dominant call-quality problem we saw in production: streaming STT (both Sarvam Saaras and Azure) was receiving the user's speech fragmented into one-word utterances, because the VAD emitted "speech stopped" at every inter-word pause.

The give-away was a comparison of in-process behaviour vs offline replay: dumping the post-filter PCM to a file and running it through batch STT produced the correct transcript ("I want Coke 1.5 liter 10 cases, …"), while live streaming STT on the same audio produced fragments ("I want to cook | 1.5 | Hello | 10 cases | Sweetheart | …"). Same bytes, different VAD chunking.

v0.3.6 raises the default `stop_secs` to 0.2 (matching Pipecat's own default), keeps `start_secs=0.0` so barge-in still happens promptly, and exposes the full `VADParams` (`confidence`, `start_secs`, `stop_secs`, `min_volume`) through `create_vad_analyzer()` so a caller can tune them per integration. The agent's `aic_filter.create_vad_analyzer(speech_hold_duration=0.05, ...)` pattern is now honoured by voiceclean too — `speech_hold_duration` aliases `stop_secs` when no explicit value is given.

**Do not set `stop_secs=0` again without verifying that the downstream streaming STT can still produce coherent transcriptions on multi-word user turns.** The latency you save is dwarfed by the recognition damage.

## Single-gate cross-correlation detection (v0.3.0–v0.3.3)

Pre-v0.3.4 the AEC's only check was `peak_corr > correlation_threshold` (default 0.15), after which every frequency bin where `ref_mag > 0.3 * mic_mag` got suppressed by up to -30 dB. This had two real-call failure modes that were reproduced across multiple callers, handsets, and acoustic environments on outbound Coca-Cola Nepal calls (Twilio + Exotel, Hindi + English):

- **Over-suppression.** When the bot had just listed product names (e.g. "Coke, Sprite, Fanta"), the reference buffer carried those phonemes. When the user immediately repeated them ("I want Coke 1.5 litre 10 cases"), cross-correlation crossed 0.15 from phonetic similarity alone — no actual echo. The mask then stripped the very consonants the user produced: "Coke → cook", "Sprite → Flight/Super Right/It's quite", "Fanta → penta/Punjab", "30 cases → certificates".
- **Under-suppression.** On the same calls, real handset-earpiece bleed of the bot's greeting was sometimes not caught — voiceclean transcribed the bot's own words as caller speech ("Hello, I'm an AI assistant calling from Co...").

v0.3.4 adds a second gate (Echo-to-Mic energy Ratio, EMR) between detection and suppression, tightens the per-bin selection from `> 0.3` to `> 1.0`, and switches the suppression curve from cliff-jumping linear to soft (`1 / (1 + s * (ratio - 1))`). The default `correlation_threshold` stays at 0.15 — real-echo correlations sit close to it and raising it loses real catches; the EMR gate is what stops the false-positive case. The stats dict now also reports `emr_blocked_chunks` so you can see how often the EMR gate is vetoing the correlation gate in production.

**Do not re-introduce single-gate detection without a per-call replay test against shared-vocabulary conversation, not just background-noise echo.**

---

# Testing

There are no automated tests. The package is verified by placing real PSTN calls through the voice agent pipeline and checking that:

1. Echo is suppressed (bot's greeting is not transcribed back as user speech)
2. VAD detects real speech (barge-in works — user can interrupt the bot)
3. User speech is not suppressed (the caller's words are transcribed correctly)

If you change the AEC algorithm, test on a real call, not synthetic audio. Every AEC approach we tried showed 99% suppression on synthetic signals. Real speech through real phone hardware is a different world.

---

# Editing gotchas

- **Version in two places.** `pyproject.toml` and `voiceclean/__init__.py` must agree. If they diverge, PyPI shows one version and `voiceclean.__version__` reports another.
- **`denoise.py` and `resample.py` are legacy.** They exist but are not used in the current AEC pipeline. Don't delete them (they're valid code for higher sample rates) but don't wire them into the 8 kHz telephony path.
- **`pipeline.py` still references `aec_filter_length` and `aec_frame_size` in its `__init__`.** These are passed through to `AEC()` via `**kwargs` and silently ignored by the cross-correlation AEC. Harmless but misleading. Could be cleaned up.
- **Silero VAD model version.** The current model uses a `state` tensor of shape `(2, 1, 128)` with input name `"state"`. Older models used separate `h`/`c` tensors of shape `(2, 1, 64)`. If the auto-downloaded model changes upstream, VAD will crash with an ONNX input shape error. The model URL is pinned in `vad.py:_MODEL_URL`.
- **`site/` directory.** Generated by `mkdocs build`. Excluded via `.gitignore`. Don't commit it.
- **`ARTICLE_DRAFT.md`.** A private Medium article draft. Excluded via `.gitignore`. Don't commit it.
