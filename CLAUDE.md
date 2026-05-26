# Working principles

1. Don't assume. Don't hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. NEVER JUMP TO CONCLUSIONS. NEVER CONFIDENTLY ASSERT SOMETHING YOU ARE NOT SURE ABOUT.
5. NEVER ASSUME EXTERNAL SERVICE BEHAVIOR. Only assert what is verified against official docs or live tests.

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
| `correlation_threshold` | 0.15 | Cross-correlation above which echo is detected. Lower = catches weaker echo but more false positives. **0.10 recommended for telephony** — production data showed borderline echo at p95 0.13–0.15 slipping through on ~14% of Exotel calls. Normal speech correlates at 0.01–0.08. |
| `suppress_db` | -30.0 | Echo suppression depth (dB). -30 = echo at ~3% of original. |

## VAD (`voiceclean/vad.py`)

| Parameter | Default | What it controls |
|-----------|---------|-----------------|
| `sample_rate` | 8000 | Must be 8000 or 16000 (Silero limitation) |
| `threshold` | 0.5 | Speech probability above which `is_speech=True` |

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
