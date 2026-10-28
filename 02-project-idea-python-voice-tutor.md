# Project Idea: Voice-First Python Tutor for Indian Learners

## One-line Summary
An interactive voice tutor that teaches Python to Indian students and beginners in natural **code-mixed Hindi-English** (and optionally other Indian languages), using Gnani’s Prisma + Timbre + Evon stack.

## Why This Idea Fits the Challenge
- **Voice-first** → plays to Prisma (STT) and Timbre (TTS) strengths
- **Code-mixed speech** is the natural way most Indian students speak about technical topics
- Highly practical and high-impact (skill development / job readiness)
- Easy to demo in 60 seconds
- Can target multiple award categories: Mixed Vibes, Real Deal, Main Character, Demo Day Drop, Jugaad Genius

## Target Users
- College students who are more comfortable speaking in Hindi / Hinglish than pure English
- Self-learners preparing for placements or career switch
- Students in Tier-2 / Tier-3 cities who lack good offline tutors

## Core Experience (MVP)
User calls or opens a web/voice interface and talks to the tutor.

### Supported Interactions
1. **Concept explanation**  
   “Python mein list aur tuple mein kya difference hai?”  
   Tutor explains simply in Hinglish, with examples.

2. **Interactive teaching**  
   Tutor asks questions, waits for spoken answers, gives feedback, and adjusts difficulty.

3. **Live coding help**  
   User describes a problem or pastes/reads code. Tutor helps debug or improve it through conversation.

4. **Practice mode**  
   Tutor gives small exercises (“Write a function that...”) and reviews the user’s spoken or typed solution.

5. **Progress tracking** (lightweight)  
   Remembers what the user has already covered in the current session.

## Technical Stack (Must Use Gnani)
- **Prisma v2.5** → Speech-to-Text (primary strength for code-mixed + noisy audio)
- **Evon v3.3** → Reasoning + pedagogical responses
- **Timbre v2.5** → Natural Indian-accent TTS replies
- Backend: FastAPI or simple Node/Python server
- Frontend: Simple web UI with microphone + optional phone gateway later
- Optional: Basic session memory (Redis or even in-memory for MVP)

## Pedagogical Differentiator
Most coding tutors just answer questions.  
This one should actively **teach**:

- Socratic questioning instead of dumping answers
- Detecting common misconceptions
- Breaking concepts into small spoken steps
- Encouraging the student to speak the answer before revealing it
- Switching freely between Hindi and English based on the student’s comfort

## Scope for 15-Day Build (Realistic MVP)
**Must have**
- Clean voice loop (speak → Prisma → Evon → Timbre → speak)
- Solid system prompt that makes Evon act like a patient Hinglish Python teacher
- 4–5 core topics (variables, lists, loops, functions, basic error handling)
- Simple web interface with mic button
- One polished 60-second demo video

**Nice to have (if time permits)**
- Session memory
- “Practice mode” with exercises
- Basic progress summary at the end of the call
- Support for one more language (e.g. Tamil or Telugu) for Main Character award

**Explicitly out of scope for MVP**
- Full course platform
- Video content
- Advanced code execution sandbox (can be added later)
- Mobile app

## Demo Script (60 seconds)
1. Student speaks in Hinglish: “List comprehension kaise kaam karti hai? Example do.”
2. Tutor explains clearly in natural mixed language + gives a small example.
3. Tutor asks a follow-up question.
4. Student answers (with some hesitation / code-mixing).
5. Tutor gives feedback and suggests next step.
6. Show the GitHub + live link.

## Award Targeting
Primary:
- **Mixed Vibes** (code-mixed voice experience)
- **Real Deal** (skill development for Indian students)
- **Demo Day Drop** (clean 60s video)

Secondary:
- Main Character (if we add a strong regional language)
- Jugaad Genius (if the pedagogical style feels uniquely good)

## Success Metrics for the Build
- Works reliably with noisy / code-mixed audio
- Feels like talking to a helpful senior rather than a chatbot
- Demo is understandable even without technical background
- Can be deployed and shared publicly before the deadline

## Next Immediate Steps
1. Register on the official Gnani challenge page and get API credits
2. Set up basic Prisma → Evon → Timbre voice loop
3. Write a strong system prompt for the teaching personality
4. Build a minimal web UI
5. Record test conversations and iterate on naturalness

---

**Working title suggestions**
- CodeBaat
- PyVaani
- Hinglish Python Tutor
- Bolke Seekho Python
- VoicePy Mentor