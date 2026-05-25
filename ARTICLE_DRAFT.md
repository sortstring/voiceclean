# I Built a Free Alternative to $149/mo Echo Cancellation for Voice AI Agents

## The problem nobody warns you about

We build voice AI agents that call people over PSTN — real phone calls, not VoIP. The agent speaks Hindi, English, and Nepali. It calls grocery retailers in Nepal and takes their weekly Coca-Cola orders. A full conversation, with product search, pricing, promotions, and order confirmation.

The pipeline is straightforward: Pipecat orchestrates the call, Azure STT transcribes, Claude thinks, Azure TTS speaks. The telephony leg goes through Twilio or Exotel to reach the PSTN.

Everything worked great until we added Exotel.

The first Exotel call went like this:

```
BOT: Hello! Thanks for calling. How can I help you today?
USR: Hello thanks for calling. How can I?
BOT: No problem! I'm here to help.
USR: No problem, I'm here to help.
```

The bot was talking to itself. The caller's mic was picking up the bot's TTS output from the phone speaker, the STT was transcribing it as user speech, and the LLM was dutifully responding. A perfect feedback loop.

## Why Twilio works and Exotel doesn't

Twilio performs acoustic echo cancellation (AEC) on their infrastructure before delivering audio to your WebSocket. The audio you receive has already had the bot's playback removed. You don't have to think about it.

Exotel's Voicebot applet streams raw mic audio — no carrier-side AEC. What the phone mic hears is what you get, including the bot's own voice bouncing off the phone speaker.

We were using ai-coustics ($149/month) for audio processing. After investigating, we discovered it provides noise suppression and VAD (voice activity detection), but **not echo cancellation**. The echo suppression we'd been attributing to our code was actually Twilio's network doing the work.

## The search for a solution

The obvious answer was SpeexDSP — the telephony industry's go-to AEC for 15 years. We built a Python wrapper using ctypes, wired it into our Pipecat pipeline, and tested.

Synthetic tests looked great: 99% echo suppression. Real calls told a different story. SpeexDSP's adaptive filter diverged on roughly half of all calls. One call would be clean, the next would echo the bot's entire greeting back as user input. The adaptive filter needs time to converge, and PSTN echo paths are non-linear (speaker distortion, codec artifacts, variable delay). When the filter diverges, it passes echo through or — worse — suppresses real user speech.

We tried the two-stage approach recommended by the SpeexDSP docs: echo canceller followed by a preprocessor with residual echo suppression. It helped, but the intermittent failures persisted. The fundamental problem is that an adaptive filter is a statistical estimator. Sometimes it gets the wrong answer.

We also tried MFCC-based voice fingerprinting — the idea that the bot's TTS voice has a different "vocal tract signature" than the caller's real voice, and we could classify each audio frame by whose voice it resembles. Tested against real dual-channel recordings: at 8 kHz, the MFCC cosine distance between the bot and caller was 0.0041. The bot's own self-consistency was 0.0036. Indistinguishable. The 0-4 kHz telephony bandwidth simply doesn't carry enough spectral information to tell voices apart.

## What actually works: cross-correlation

The solution we landed on doesn't try to model the echo path or classify voices. It uses a simpler physical property: **echo is correlated with the reference signal. Real speech is not.**

For each chunk of mic audio (40ms), we compute normalized cross-correlation against a ring buffer of the bot's recent output. If the correlation peak exceeds a threshold, echo is present. We then apply spectral masking — suppressing frequency bins where the echo dominates while preserving bins with uncorrelated energy (the caller's actual speech).

```python
from voiceclean import VoiceClean

vc = VoiceClean(sample_rate=8000)

# When the bot sends audio to the speaker
vc.feed_reference(bot_audio)

# When mic audio arrives
result = vc.process(mic_audio)
# result.audio = cleaned audio (echo removed)
```

No adaptive filter. No convergence. No external C libraries. Pure numpy FFT.

The difference from adaptive filtering is fundamental:

- **SpeexDSP** tries to build a model of the echo path and predict what the echo will sound like. When the model is wrong (non-linear distortion, sudden changes), it fails.
- **Cross-correlation** doesn't model anything. It just asks: "does this mic audio look like a time-shifted copy of what the bot just said?" If yes, suppress. If no, pass through.

This means it works on the first frame. It works after silence. It works through speaker distortion and codec artifacts (correlation survives non-linear transforms). And it gives the same answer every time — no frame where the filter happens to diverge.

## Real-world results

We've been running this on production calls — Hindi sales calls where an AI agent takes weekly grocery orders from retailers. The calls go through both Twilio and Exotel.

The echo problem is solved. But an unexpected benefit showed up: **noise handling**. One of our operators took a sales call in a room where several people were talking loudly in the background. With ai-coustics, this would have been unusable — background voices would trigger the STT and confuse the agent. With voiceclean's cross-correlation approach, only audio correlated with the reference gets suppressed (echo), and the spectral masking naturally attenuates uncorrelated noise in the echo bands. The call went end to end, an order was placed.

The package is called [voiceclean](https://github.com/sortstring/voiceclean). It also includes Silero VAD for voice activity detection, and it integrates with Pipecat as a drop-in audio filter. Install with `pip install voiceclean`. No system dependencies, no API keys, no monthly fees.

## What I learned

1. **Don't assume your audio stack does what you think.** We ran for weeks thinking ai-coustics was handling echo. It was Twilio's network. When we switched to a provider without carrier-side AEC, everything broke.

2. **Adaptive filters are fragile in production.** They work beautifully in synthetic tests and fail unpredictably on real calls. The internet will tell you SpeexDSP is the answer. It isn't, not for PSTN telephony with variable echo paths.

3. **The simplest physical property often wins.** We tried adaptive filtering, residual echo suppression, MFCC voice fingerprinting. What worked was the most basic signal processing concept: correlation. Echo correlates with the reference. Speech doesn't.

4. **Test on real calls, not synthetic audio.** Every AEC approach we tried showed 99% suppression on sine waves. Real speech through real phone hardware is a different world.

---

[voiceclean](https://github.com/sortstring/voiceclean) is MIT-licensed and free on PyPI. If you're building voice agents and dealing with echo, give it a try.
