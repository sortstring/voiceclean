# How AEC Works

## The echo problem

When a voice agent calls someone over PSTN, the bot's TTS audio plays through the phone's speaker. The phone's mic picks up that audio (acoustic coupling) and sends it back to the server. The STT engine transcribes it as user speech. The LLM responds to its own words. The bot enters a self-conversation loop.

```
Bot speaks: "Hello! How can I help you?"
Mic picks up: "Hello! How can I help you?"    ← echo
STT transcribes: "Hello how can I help you"   ← treated as user input
LLM responds to its own greeting
```

## Two approaches to AEC

### Adaptive filtering (SpeexDSP, WebRTC AEC3)

Traditional AEC builds a **linear model** of the echo path — it tries to predict what the echo will sound like and subtract it from the mic signal. The model adapts over time as the echo path changes.

**Problems in practice:**

- Needs time to **converge** — the first few hundred milliseconds are unprotected
- Can **diverge** under non-linear conditions (speaker distortion, codec artifacts)
- **Double-talk** (user and bot speaking simultaneously) confuses the estimator
- Intermittent failures: works on one call, fails on the next

We tested SpeexDSP extensively. It showed 99% suppression on synthetic audio but failed on roughly 50% of real PSTN calls.

### Cross-correlation (voiceclean's approach)

voiceclean doesn't model the echo path. It uses a simpler physical property: **echo is correlated with the reference signal. Real speech is not.**

## Algorithm

For each chunk of mic audio (default 40 ms):

### Step 1: Cross-correlation

Compute normalized cross-correlation between the mic chunk and a ring buffer of recent reference (bot) audio using FFT:

```
xcorr = IFFT( FFT(mic) * conj(FFT(reference)) )
normalized = |xcorr| / sqrt(mic_energy * ref_energy)
peak = max(normalized)
```

If `peak < correlation_threshold` (default 0.15), no echo is present — the audio passes through unchanged.

### Step 2: Lag detection

If echo is detected, the lag (time offset) of the peak tells us where in the reference buffer the echo originates:

```
lag = argmax(normalized)
```

This lag corresponds to the round-trip delay through the PSTN network (typically 100–500 ms).

### Step 3: Spectral masking

Extract the reference segment at the detected lag and compute spectral masks:

```
mic_spectrum = FFT(mic_chunk)
ref_spectrum = FFT(reference_at_lag)

echo_ratio = |ref_spectrum| / (|mic_spectrum| + epsilon)
```

Frequency bins where echo dominates (high `echo_ratio`) are suppressed. Bins with uncorrelated energy (real user speech) are preserved. The suppression strength scales with correlation confidence.

```
         echo detected
              │
              ▼
┌─────────────────────────┐
│   Spectral Masking      │
│                         │
│   Echo bins → suppress  │
│   Speech bins → keep    │
└─────────────────────────┘
              │
              ▼
      cleaned audio
```

## Why this works better than adaptive filtering

| Property | Adaptive filter | Cross-correlation |
|----------|----------------|-------------------|
| Convergence | Needs time to learn echo path | Stateless — works on first frame |
| Non-linear echo | Fails (linear model assumption) | Works (correlation survives distortion) |
| Consistency | Intermittent failures | Same answer every time |
| Double-talk | Struggles to separate signals | Correlation is per-frequency — can preserve uncorrelated speech bins |
| Dependencies | Requires C library (libspeexdsp) | Pure numpy |

## Signal flow

```
Bot TTS audio ──► feed_reference() ──► reference ring buffer
                                              │
                                    cross-correlation (FFT)
                                              │
                                         peak > threshold?
                                          ╱           ╲
                                       Yes             No
                                        │               │
                                  spectral mask    pass through
                                        │               │
                                        ▼               ▼
Caller mic audio ──► process() ──────────────────► clean audio
```

## Limitations

- **Not a noise suppressor.** voiceclean suppresses echo (audio correlated with the reference). Uncorrelated background noise passes through. For noise suppression, use a dedicated tool (ai-coustics, RNNoise, etc.).
- **Requires a reference signal.** AEC only works if you feed the bot's outgoing audio via `feed_reference()`. Without it, all audio passes through unchanged.
- **Latency.** The 40 ms chunk size adds ~40 ms of processing latency. This is negligible for telephony (PSTN round-trip is already 100–500 ms) but matters for ultra-low-latency applications.
