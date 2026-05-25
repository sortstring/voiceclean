# Background

## The PSTN echo problem

When a voice AI agent calls someone over the Public Switched Telephone Network (PSTN), the following happens:

1. The bot's TTS (text-to-speech) audio is sent to the caller's phone
2. The phone's speaker plays the audio
3. The phone's mic picks up the speaker output (acoustic coupling)
4. The mic audio is sent back to the server
5. The STT (speech-to-text) engine transcribes the echo as user input
6. The LLM responds to its own words
7. The cycle repeats — the bot enters a self-conversation loop

This is called **acoustic echo** and it's a fundamental problem in full-duplex telephony.

## How telephony providers handle echo

### Twilio

Twilio performs acoustic echo cancellation on their PSTN infrastructure before delivering audio to your WebSocket (Media Streams). The audio you receive has already had the bot's playback removed. You don't need to handle echo yourself for Twilio calls.

### Exotel

Exotel's Voicebot applet streams raw caller mic audio over the WebSocket without carrier-side AEC. The bot hears its own words echoed back word-for-word. Echo cancellation is explicitly the developer's responsibility.

### Other providers

Each telephony provider handles echo differently. If you're using a provider not listed here, test by placing a call and checking whether the bot's greeting gets transcribed back as user input. If it does, you need client-side AEC.

## Approaches we tried

### Adaptive filtering (SpeexDSP)

SpeexDSP's adaptive echo canceller is the traditional telephony solution. It builds a linear model of the echo path and adapts over time.

**Result:** 99% suppression on synthetic tests, but ~50% failure rate on real PSTN calls. The adaptive filter diverged under non-linear conditions (speaker distortion, codec artifacts, variable delay). Some calls were clean, others echoed the bot's entire greeting back.

### MFCC voice fingerprinting

The idea was to distinguish bot speech from human speech using MFCC (Mel-frequency cepstral coefficients) features — the bot's synthesized voice should have a different spectral signature than a real human voice.

**Result:** At 8 kHz telephony bandwidth (0–4 kHz), the MFCC cosine distance between the bot and the caller was 0.0041. The bot's own self-consistency was 0.0036. Indistinguishable. The narrowband telephony audio doesn't carry enough spectral information to tell voices apart.

### RNNoise (neural noise suppression)

We included RNNoise for background noise suppression. It operates at 48 kHz internally.

**Result:** The double resampling (8k to 48k to 8k) degraded narrowband telephony audio, producing garbled STT transcriptions. Disabled for telephony use cases. AEC alone is sufficient for PSTN audio.

### Cross-correlation (what voiceclean uses)

Instead of modeling the echo path or classifying voices, we use a physical property: **echo is correlated with the reference signal, real speech is not.**

**Result:** Consistent echo suppression on every frame, every call, both Twilio and Exotel. No convergence, no divergence, no intermittent failures. Works through speaker distortion and codec artifacts because correlation survives non-linear transforms.

See [How AEC Works](how-aec-works.md) for the full algorithm description.

## Production results

voiceclean has been tested in production on real PSTN calls:

- **Languages:** Hindi, English, Nepali
- **Telephony providers:** Twilio, Exotel
- **Use case:** AI sales agent taking weekly grocery orders from retailers
- **Call duration:** 1–10 minutes
- **Result:** Echo problem fully solved. Conversations run end-to-end without the bot responding to its own speech.

An unexpected benefit: voiceclean handles **noisy environments** better than expected. In one test, an operator took a sales call in a room where several people were talking loudly in the background. The call completed successfully with an order placed — background voices did not confuse the agent.

## Credits

- **Silero VAD** — [Silero Team](https://github.com/snakers4/silero-vad) (MIT License)
- **numpy** — fundamental array computing
- **soxr** — high-quality audio resampling

## License

MIT — [SortString Solutions](https://github.com/sortstring)
