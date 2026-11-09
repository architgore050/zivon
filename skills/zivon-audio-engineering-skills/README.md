---
name: zivon-audio-engineering-skills
description: Audio discipline for the realtime voice loop and the build-time narration stage (EX1-VOICE, EX8-NARRATION). Covers Opus transport, browser capture/playback, echo/ducking, low-end Android quirks, static audio-asset engineering, and batch TTS generation.
consumed-by: SP1, EX1-VOICE, EX8-NARRATION, EX5-FRONT
sources:
  - https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API
  - https://developer.mozilla.org/en-US/docs/Web/API/MediaStream_Recording_API
  - https://datatracker.ietf.org/doc/html/rfc6716 (Opus)
  - https://opus-codec.org/ (Xiph)
  - https://webrtc.org/getting-started/echo-cancellation
  - https://docs.livekit.io/ (audio engineering guides)
  - https://docs.pipecat.ai/ (audio frames / transport)
---

# Zivon Audio Engineering Skills

The audio discipline behind BOTH the realtime voice loop (EX1-VOICE) and the
build-time narration stage (EX8-NARRATION). Anything here that touches the
browser also applies to EX5-FRONT.

## 1. Opus encode/decode and low-bandwidth transport [V]

- Opus (RFC 6716) is the IETF standard audio codec: 6 kb/s to 510 kb/s, frame
  sizes 2.5–60 ms, designed for interactive speech AND music. It sweeps the
  low-bitrate range that matters for cellular voice (8–24 kb/s) where MP3/AAC
  fall apart. [V: rfc6716 §1]
- Choose frame sizes 20 ms for speech over jittery networks (good
  packet-loss-robustness tradeoff); 10 ms only when latency budget <150 ms RTT.
- Tune FEC (`useinbandfec=1`), DTX (`usedtx=1` for half-duplex-ish turns), and
  bitrate by measured network profile, not by default.
- Server→client chunks must be scheduled, not dribbled: buffer ≥2–3 frames
  before starting playback (jitter buffer), target 60–120 ms of buffered audio,
  top up on each frame arrival, and clock the schedule off
  `AudioContext.currentTime`, never wall time. [V: MDN Web Audio — AudioContext]

## 2. getUserMedia / MediaRecorder constraints and gotchas [V]

- Always specify constraints explicitly: `{ echoCancellation, noiseSuppression,
  autoGainControl, channelCount: 1, sampleRate: 16000|48000 }`. Do NOT rely on
  browser defaults — they vary per platform. [V: MDN MediaDevices.getUserMedia]
- `MediaRecorder` is for recording (file blobs); for realtime streaming prefer
  raw `AudioWorklet` frames or `AudioContext` → `MediaStreamAudioSourceNode`.
  MediaRecorder's per-platform codec/container is not guaranteed (Safari: caf;
  Chrome: webm/ogg).
- Handle `OverconstrainedError` gracefully: fall back through a constraint
  ladder instead of failing the call.
- Autoplay policy: AudioContext starts `suspended`; resume on the first user
  gesture. Preflight this in the UI (a "tap to start" affordance), not in the
  audio layer.

## 3. Echo paths, ducking, and barge-in [V/C]

- Speaker→mic acoustic echo is the #1 voice-loop killer. Baseline: browser AEC
  (`echoCancellation: true`) + WebRTC AEC3-style processing; test on real
  hardware, not headsets. [V: WebRTC echo-cancellation material]
- Backend-spec A-11 / ADR-0010 requires client-side ducking: when the agent
  speaks, duck the mic gain; when the user barges in, duck the agent stream.
  Implement ducking in the gain graph (`GainNode`), never by muting tracks —
  muting breaks AEC reference signal.
- Barge-in/VAD: client-side VAD gate (e.g. energy + WebRTC VAD) to detect user
  speech over agent playback; emit interrupt event server-side so the agent
  stops generating. VAD hangover ~300–500 ms to avoid clipping word tails.

## 4. Low-end Android audio quirks [C]

- Output latency on budget Android is 100–300 ms (audio HAL + Bluetooth stack);
  Bluetooth adds another 100–200 ms and often forces mSBC/SBC profile changes.
- Consequences: never hard-schedule playback deadlines <150 ms ahead; expose a
  latency calibration probe (play a tick, measure round trip); prefer wired or
  A2DP-stable paths for the voice loop; degrade gracefully to text mode.
- `MediaRecorder` on older WebViews silently downmixes to 8 kHz mono — pin
  constraints and verify actual track settings via `getSettings()`.

## 5. Static audio-asset engineering [V]

- Content-hash naming: `<slug>.<contenthash>.opus`; immutable cache headers
  (`Cache-Control: public, max-age=31536000, immutable`).
- HEAD probes before full GET to validate content-length/ETag cheaply.
- Support HTTP Range requests for scrubbing; verify `Accept-Ranges: bytes` and
  206 responses (backend-spec ST-04). [C: backend-spec ST-04]
- Transcode ladder: 24 kb/s Opus for narration, 64 kb/s for music bed; store
  one source master, derive at build time.

## 6. Batch / build-time TTS generation patterns [C]

- Per-item, resumable jobs: each script/chapter is a separate work item with
  its own idempotency key and output path; a manifest tracks
  `(item_id, status, hash, cost_units)` so reruns skip completed items.
- Rate limits: respect provider RPM/TPS with a token bucket + exponential
  backoff on 429/5xx; jitter the backoff; cap retries and record terminal
  failures instead of infinite retry.
- Cost metering: log tokens/characters per item into the manifest; emit a
  build summary (total cost, per-item cost, retry count) — EX8-NARRATION feeds
  this into budget guards (see backend-spec ADR-0015).

## Evidence tags

- [V] verified against primary source (RFC/IETF, MDN, Xiph, WebRTC, vendor docs)
- [S] synthesized from practitioner material (LiveKit/Pipecat engineering pages)
- [C] constrained by internal backend-spec (A-11, ADR-0010, ST-04, ADR-0015)

## Licence / vendoring

No third-party content is vendored into this bundle; all references are
linked, not copied. Licence: internal Zivon use.
