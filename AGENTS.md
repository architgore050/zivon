# AGENTS.md — Instructions for Coding Agents

You are implementing **Zivon**, a voice-first AI tutor for Indian learners.

This project is being built for the **Great Indian AI Internship Challenge** by Gnani AI. The judges care deeply about real working voice demos that use their models well, especially on code-mixed speech and noisy audio. Keep that perspective in mind in every decision.

---

## Project goal

Build a working voice conversation loop:

1. User speaks (Hindi / English / code-mixed)
2. **Gnani Prisma** transcribes the speech
3. **Gnani Evon** reasons and generates a tutor response
4. **Gnani Timbre** speaks the response back

The product is a patient, clear Physics tutor (Class 9–12) that can later expand to other subjects. Voice is the primary interface.

---

## Non-negotiable constraints

- You **must** use Gnani’s models:
  - **Prisma v2.5** for Speech-to-Text
  - **Timbre v2.5** for Text-to-Speech
  - **Evon v3.3** for reasoning (open-weight LLM)
- Do not replace these with OpenAI, Deepgram, ElevenLabs, or any other provider for the core loop.
- The demo must work end-to-end with real voice input and output.
- Prefer simplicity and reliability over feature count. A solid 60-second demo beats a half-broken multi-feature app.

---

## Architecture guidelines

### Preferred high-level shape

- A Python backend that owns the conversation loop.
- Real-time audio handling (WebSocket or WebRTC).
- LiveKit is a strong option because Gnani provides an official `livekit-plugins-gnani` plugin. Use it if it reduces complexity.
- If you do not use LiveKit, still keep the STT → LLM → TTS pipeline clean and modular.
- Separate concerns:
  - Audio / session management
  - Gnani API clients (Prisma, Timbre)
  - Evon inference / prompting
  - Tutor personality and subject logic
  - Usage / session logging (simple is fine)

### Key design principles

- Low latency matters. Stream where possible.
- Treat code-mixed speech and imperfect audio as normal, not edge cases.
- Keep the tutor personality consistent: patient, clear, encouraging, step-by-step.
- Make it easy to swap or add subjects later (start with Physics).
- Log enough information to debug conversations (transcripts, latency, errors).

---

## Implementation priorities (in order)

1. **Get a working voice loop**  
   Microphone → Prisma → Evon → Timbre → speaker. Even a CLI or simple web page is fine at first.

2. **Harden the core loop**  
   Handle interruptions, silence, partial transcripts, and basic error recovery.

3. **Tutor quality**  
   Good system prompt + Physics knowledge + clear spoken explanations.

4. **Demo packaging**  
   One clean flow that a judge can try in under two minutes. Record a 60-second video of it working.

5. **Polish**  
   Better UI, session memory, multiple subjects, analytics — only after the above are solid.

---

## Coding standards

- Prefer clear, readable Python.
- Use type hints.
- Keep configuration in environment variables (API keys, model names, sample rates, etc.).
- Never commit secrets.
- Write small, focused modules. Avoid giant files.
- Add basic logging from day one.
- When adding dependencies, prefer well-maintained packages and keep the set small.
- Document any non-obvious setup steps in the README.

---

## Gnani-specific notes

- Prisma and Timbre are accessed via Gnani’s API (`api.vachana.ai` / dashboard).
- Evon is open-weight. You will need to run it yourself (or via a compatible inference server). Plan for this early.
- Official LiveKit plugin exists: `livekit-plugins-gnani`. Prefer using it if you go the LiveKit route.
- Programme credits are limited. Be mindful of usage during development and testing.
- The models are strong on Indian languages and code-mixing — lean into that strength in demos and prompts.

---

## What to avoid

- Building complex multi-user systems, billing, or heavy analytics before the core voice loop works.
- Over-engineering authentication, databases, or frontend frameworks early.
- Replacing Gnani models with “better” alternatives.
- Long, feature-heavy demos. Judges watch many submissions — clarity wins.
- Ignoring latency. A slow tutor feels broken even if the answers are good.

---

## Definition of done for the MVP

- A user can open the app / page, speak a Physics question in natural or code-mixed speech, and hear a clear spoken explanation.
- The full pipeline uses Prisma + Evon + Timbre.
- The experience works reasonably well with some background noise and mixed language.
- There is a short, understandable demo video of the above.
- The README clearly states that the project is built on Gnani’s models for the Great Indian AI Internship Challenge.

---

## When in doubt

Ask:  
“Does this help us ship a reliable, impressive voice tutor demo that shows off Gnani’s models on real Indian speech?”

If the answer is no, defer it.