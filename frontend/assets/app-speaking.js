/* Zivon explain-back island (F6): recorder, consent gate, result, delete.
 *
 * The server renders the page and the last saved result; this file only owns
 * the parts a server cannot: the microphone, the 45 s timer, the transient
 * upload, and the DOM built from the API's validated JSON.
 *
 * Contracts it must keep:
 * - no audio retention: PCM lives in this tab until the one POST finishes;
 *   nothing is written to localStorage or IndexedDB;
 * - consent first: the mic button starts disabled and capture only begins
 *   after the device consent record says "granted"; the same
 *   `localStorage["zivon.consent"]` key and `PUT /v1/consent` record the
 *   decision as the lesson voice gate;
 * - text only in the DOM: transcripts, feedback, and model answers are set
 *   with `textContent`; no innerHTML with server or student text;
 * - same origin only: `/v1/speaking/*` and `/v1/consent`, never a third party.
 * - accessible: mic state via `aria-pressed`, a polite status line, a timer
 *   that announces only start/ten-seconds/stop, canvas is decorative.
 */
(function () {
  "use strict";

  var CONSENT_KEY = "zivon.consent";
  var CONSENT_RECORD_KEY = "zivon.consent_record";
  var DEVICE_KEY = "zivon.device_pseudo_id";
  var TARGET_RATE = 16000;
  var WAVE_BARS = 72;
  var MIN_RECORD_SECONDS = 0.8;
  var CONFIRM_DELETE = "Delete this transcript and feedback? This cannot be undone.";

  var BOOK_LABELS = {
    "ncert-science-9": "NCERT Science Class 9",
    "ncert-science-10": "NCERT Science Class 10"
  };

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function storageGet(key) {
    try {
      return window.localStorage ? window.localStorage.getItem(key) : null;
    } catch (e) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(key, String(value));
        return true;
      }
    } catch (e) {}
    return false;
  }

  function uuidV4() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    var bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    var hex = [];
    for (var j = 0; j < bytes.length; j += 1) {
      hex.push((bytes[j] + 0x100).toString(16).slice(1));
    }
    return (
      hex.slice(0, 4).join("") + "-" + hex.slice(4, 6).join("") + "-" +
      hex.slice(6, 8).join("") + "-" + hex.slice(8, 10).join("") + "-" +
      hex.slice(10, 16).join("")
    );
  }

  function deviceId() {
    var stored = storageGet(DEVICE_KEY);
    if (stored && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored)) {
      return stored;
    }
    var created = uuidV4();
    storageSet(DEVICE_KEY, created);
    return created;
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? String(meta.getAttribute("content") || "") : "";
  }

  function consentState() {
    var value = storageGet(CONSENT_KEY);
    return value === "granted" || value === "declined" ? value : "missing";
  }

  function recordConsent(action, guardianChecked) {
    var granted = action === "granted";
    var now = new Date().toISOString();
    storageSet(CONSENT_KEY, granted ? "granted" : "declined");
    storageSet(CONSENT_RECORD_KEY, JSON.stringify({
      device_pseudo_id: deviceId(),
      consent_version: consentVersion(),
      guardian_flag: Boolean(guardianChecked),
      action: granted ? "granted" : "declined",
      ts: now
    }));
    try {
      if (typeof window.CustomEvent === "function") {
        window.dispatchEvent(new window.CustomEvent("zivon:consent-changed", {
          detail: { action: granted ? "granted" : "declined" }
        }));
      }
    } catch (e) {}
    if (typeof fetch !== "function") return Promise.resolve(null);
    return fetch("/v1/consent", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_pseudo_id: deviceId(),
        consent_version: consentVersion(),
        notice_version: noticeVersion(),
        guardian_flag: Boolean(guardianChecked),
        action: granted ? "granted" : "declined",
        source: "overlay",
        ts: now
      })
    }).catch(function () { return null; });
  }

  function noticeVersion() {
    var root = $("[data-speaking-recorder]");
    return (root && root.getAttribute("data-consent-notice-version")) || "zivon-voice-notice-v1";
  }

  function consentVersion() {
    var root = $("[data-speaking-recorder]");
    return (root && root.getAttribute("data-consent-version")) || "v1";
  }

  function setText(el, value) {
    if (el) el.textContent = value == null ? "" : String(value);
  }

  function formatClock(ms) {
    var total = Math.max(0, Math.round(ms / 1000));
    var minutes = Math.floor(total / 60);
    var seconds = total % 60;
    return (minutes < 10 ? "0" : "") + minutes + ":" + (seconds < 10 ? "0" : "") + seconds;
  }

  function now() {
    return window.performance && typeof window.performance.now === "function"
      ? window.performance.now()
      : Date.now();
  }

  function resampleTo16k(input, srcRate) {
    if (!input || !input.length) return new Float32Array(0);
    if (!srcRate || srcRate === TARGET_RATE) return input;
    var ratio = srcRate / TARGET_RATE;
    var outLen = Math.floor(input.length / ratio);
    var out = new Float32Array(outLen);
    for (var i = 0; i < outLen; i += 1) {
      var pos = i * ratio;
      var i0 = Math.floor(pos);
      var frac = pos - i0;
      var a = input[i0] !== undefined ? input[i0] : 0;
      var b = input[i0 + 1] !== undefined ? input[i0 + 1] : a;
      out[i] = a + (b - a) * frac;
    }
    return out;
  }

  function float32ToPcm16(samples) {
    var out = new Uint8Array(samples.length * 2);
    var view = new DataView(out.buffer);
    for (var i = 0; i < samples.length; i += 1) {
      var sample = samples[i];
      if (sample > 1) sample = 1;
      else if (sample < -1) sample = -1;
      view.setInt16(i * 2, sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767), true);
    }
    return out;
  }

  function encodeWav(chunks) {
    var total = 0;
    for (var i = 0; i < chunks.length; i += 1) total += chunks[i].length;
    var buffer = new ArrayBuffer(44 + total);
    var view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + total, true);
    writeAscii(view, 8, "WAVE");
    writeAscii(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); /* PCM */
    view.setUint16(22, 1, true); /* mono */
    view.setUint32(24, TARGET_RATE, true);
    view.setUint32(28, TARGET_RATE * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, total, true);
    var offset = 44;
    for (var j = 0; j < chunks.length; j += 1) {
      new Uint8Array(buffer, offset, chunks[j].length).set(chunks[j]);
      offset += chunks[j].length;
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  function writeAscii(view, offset, text) {
    for (var i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  }

  /* ---------------------------- recorder ---------------------------- */

  function initRecorder() {
    var root = $("[data-speaking-recorder]");
    if (!root) return;

    var promptId = root.getAttribute("data-prompt-id") || "";
    var language = root.getAttribute("data-language") || "en";
    var maxSeconds = clamp(Number(root.getAttribute("data-max-seconds")) || 45, 10, 60);
    var speechAvailable = root.getAttribute("data-speech-available") === "true";
    var isMock = root.getAttribute("data-mock") === "true";

    var mic = $("[data-speaking-mic]", root);
    var micLabel = $("[data-speaking-mic-label]", root);
    var timer = $("[data-speaking-timer]", root);
    var timeStatus = $("[data-speaking-time-status]", root);
    var status = $("[data-speaking-status]", root);
    var canvas = $("[data-speaking-wave]", root);
    var consentCard = $("[data-speaking-consent]", root);
    var consentOff = $("[data-speaking-consent-off]", root);
    var guardianBox = $("[data-consent-guardian]", root);
    var continueBtn = $("[data-consent-continue]", root);
    var declineBtn = $("[data-consent-decline]", root);
    var reviewBtn = $("[data-speaking-consent-review]", root);
    var resultRegion = $("[data-speaking-result-region]", root);
    var resultTemplate = $("[data-speaking-result-template]");
    var placeholder = $("[data-speaking-result-placeholder]", resultRegion || document);

    var state = "idle";
    var mediaStream = null;
    var audioCtx = null;
    var captureSource = null;
    var captureProcessor = null;
    var captureSink = null;
    var pcmChunks = [];
    var levels = [];
    var startedAt = 0;
    var timerId = null;
    var tenAnnounced = false;
    var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var nav = typeof navigator !== "undefined" ? navigator : null;
    var supported = Boolean(
      nav && nav.mediaDevices && typeof nav.mediaDevices.getUserMedia === "function" &&
      (window.AudioContext || window.webkitAudioContext)
    );

    function clamp(value, min, max) {
      return Math.min(max, Math.max(min, value));
    }

    function setStatus(text) {
      setText(status, text);
    }

    function setTimer(remainingMs) {
      setText(timer, formatClock(remainingMs));
    }

    function disableMic(reason) {
      if (!mic) return;
      mic.disabled = true;
      mic.setAttribute("aria-pressed", "false");
      setText(micLabel, "Start recording");
      if (reason) setStatus(reason);
    }

    function enableMic() {
      if (!mic) return;
      mic.disabled = false;
    }

    function refreshConsent() {
      var current = consentState();
      if (!supported || !speechAvailable) {
        // Never ask a child for microphone consent on a device/deployment that
        // cannot record: the notice above already states why the mic is off.
        if (consentCard) consentCard.hidden = true;
        if (consentOff) consentOff.hidden = true;
        disableMic(
          !supported
            ? "This browser cannot record audio. You can still read the prompt and any earlier attempt."
            : "Recording is not configured on this deployment. Nothing will capture audio."
        );
        return;
      }
      if (current === "granted") {
        if (consentCard) consentCard.hidden = true;
        if (consentOff) consentOff.hidden = true;
        enableMic();
        if (state === "idle") setStatus("Ready when you are. Press start and speak for up to " + maxSeconds + " seconds.");
        return;
      }
      if (current === "declined") {
        if (consentCard) consentCard.hidden = true;
        if (consentOff) consentOff.hidden = false;
        disableMic("Voice is off on this device. Review the notice if you want to turn it on.");
        return;
      }
      if (consentCard) consentCard.hidden = false;
      if (consentOff) consentOff.hidden = true;
      disableMic("Allow voice on this device to record. The notice explains what is kept.");
    }

    if (guardianBox && continueBtn) {
      guardianBox.addEventListener("change", function () {
        continueBtn.disabled = !guardianBox.checked;
      });
    }
    if (continueBtn) {
      continueBtn.addEventListener("click", function () {
        if (!guardianBox || !guardianBox.checked) return;
        recordConsent("granted", true);
        state = "idle";
        refreshConsent();
        if (mic) {
          try { mic.focus(); } catch (e) {}
        }
      });
    }
    if (declineBtn) {
      declineBtn.addEventListener("click", function () {
        recordConsent("declined", false);
        state = "idle";
        refreshConsent();
      });
    }
    if (reviewBtn) {
      reviewBtn.addEventListener("click", function () {
        if (consentOff) consentOff.hidden = true;
        if (consentCard) consentCard.hidden = false;
        if (guardianBox) {
          try { guardianBox.focus(); } catch (e) {}
        }
      });
    }

    function teardownGraph() {
      if (captureProcessor) {
        try { captureProcessor.onaudioprocess = null; } catch (e) {}
        try { captureProcessor.disconnect(); } catch (e) {}
      }
      if (captureSource) {
        try { captureSource.disconnect(); } catch (e) {}
      }
      if (captureSink) {
        try { captureSink.disconnect(); } catch (e) {}
      }
      if (mediaStream) {
        try {
          var tracks = typeof mediaStream.getTracks === "function" ? mediaStream.getTracks() : [];
          tracks.forEach(function (track) { try { track.stop(); } catch (e) {} });
        } catch (e) {}
      }
      if (audioCtx && typeof audioCtx.close === "function") {
        try { audioCtx.close(); } catch (e) {}
      }
      captureProcessor = null;
      captureSource = null;
      captureSink = null;
      mediaStream = null;
      audioCtx = null;
    }

    function stopTimers() {
      if (timerId !== null) {
        window.clearInterval(timerId);
        timerId = null;
      }
    }

    function tick() {
      var elapsed = now() - startedAt;
      var remaining = maxSeconds * 1000 - elapsed;
      setTimer(Math.max(0, remaining));
      if (!tenAnnounced && remaining <= 10000) {
        tenAnnounced = true;
        setText(timeStatus, "10 seconds left.");
      }
      if (remaining <= 0) stopRecording();
    }

    function drawWave() {
      if (!canvas || typeof canvas.getContext !== "function") return;
      var ctx = canvas.getContext("2d");
      if (!ctx) return;
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      var cssWidth = canvas.clientWidth || 640;
      var cssHeight = 64;
      if (canvas.width !== Math.round(cssWidth * dpr) || canvas.height !== Math.round(cssHeight * dpr)) {
        canvas.width = Math.round(cssWidth * dpr);
        canvas.height = Math.round(cssHeight * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssWidth, cssHeight);
      ctx.strokeStyle = "#5a5748";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, cssHeight / 2);
      ctx.lineTo(cssWidth, cssHeight / 2);
      ctx.stroke();
      if (!levels.length) return;
      var shown = levels.slice(-WAVE_BARS);
      var gap = 2;
      var barWidth = Math.max(2, (cssWidth - gap * shown.length) / shown.length);
      ctx.fillStyle = "#1c1b18";
      for (var i = 0; i < shown.length; i += 1) {
        var amplitude = Math.max(0.02, Math.min(1, shown[i])) * (cssHeight * 0.82);
        var x = i * (barWidth + gap);
        ctx.fillRect(x, (cssHeight - amplitude) / 2, barWidth, amplitude);
      }
      if (!reducedMotion) {
        ctx.fillStyle = "#1f3a9e";
        var lastX = (shown.length - 1) * (barWidth + gap);
        ctx.fillRect(lastX, 2, barWidth, cssHeight - 4);
      }
    }

    function pushLevel(samples) {
      var peak = 0;
      for (var i = 0; i < samples.length; i += 1) {
        var value = samples[i] < 0 ? -samples[i] : samples[i];
        if (value > peak) peak = value;
      }
      levels.push(peak);
      if (levels.length > WAVE_BARS * 2) levels = levels.slice(-WAVE_BARS);
    }

    function requestMic() {
      var ladder = [
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: 16000 } },
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } },
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }
      ];
      function attempt(index) {
        return nav.mediaDevices.getUserMedia(ladder[index]).catch(function (error) {
          var name = error && error.name ? String(error.name) : "";
          if (index + 1 < ladder.length && (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError")) {
            return attempt(index + 1);
          }
          throw error;
        });
      }
      return attempt(0);
    }

    function startRecording() {
      if (state === "recording") {
        stopRecording();
        return;
      }
      if (state === "processing") return;
      if (consentState() !== "granted" || !supported || !speechAvailable) {
        refreshConsent();
        return;
      }
      state = "permission";
      if (mic) mic.disabled = true;
      setStatus("Asking for the microphone…");
      requestMic().then(function (stream) {
        mediaStream = stream;
        var Ctor = window.AudioContext || window.webkitAudioContext;
        audioCtx = new Ctor();
        if (audioCtx.state === "suspended" && typeof audioCtx.resume === "function") {
          audioCtx.resume().catch(function () {});
        }
        if (typeof audioCtx.createScriptProcessor !== "function") {
          throw new Error("capture-unsupported");
        }
        var srcRate = audioCtx.sampleRate || 48000;
        captureSource = audioCtx.createMediaStreamSource(mediaStream);
        captureProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
        captureProcessor.onaudioprocess = function (event) {
          if (state !== "recording" || !captureProcessor) return;
          var channel = event && event.inputBuffer && typeof event.inputBuffer.getChannelData === "function"
            ? event.inputBuffer.getChannelData(0) : null;
          if (!channel || !channel.length) return;
          var down = resampleTo16k(channel, srcRate);
          pcmChunks.push(float32ToPcm16(down));
          pushLevel(down);
          drawWave();
        };
        captureSink = audioCtx.createGain();
        captureSink.gain.value = 0;
        captureSource.connect(captureProcessor);
        captureProcessor.connect(captureSink);
        if (audioCtx.destination && typeof captureSink.connect === "function") {
          captureSink.connect(audioCtx.destination);
        }
        pcmChunks = [];
        levels = [];
        tenAnnounced = false;
        startedAt = now();
        state = "recording";
        if (mic) {
          mic.disabled = false;
          mic.setAttribute("aria-pressed", "true");
          setText(micLabel, "Stop and check");
        }
        setTimer(maxSeconds * 1000);
        setStatus("Recording. Speak for up to " + maxSeconds + " seconds; press stop when you finish.");
        setText(timeStatus, "Recording started.");
        timerId = window.setInterval(tick, 200);
        drawWave();
      }).catch(function (error) {
        teardownGraph();
        state = "idle";
        var name = error && error.name ? String(error.name) : "";
        if (name === "NotAllowedError" || name === "SecurityError") {
          disableMic("The microphone is blocked. Allow it in your browser's site settings, then press start again.");
        } else if (name === "NotFoundError" || name === "DevicesNotFoundError") {
          disableMic("No microphone was found on this device.");
        } else if (name === "NotReadableError" || name === "TrackStartError") {
          disableMic("The microphone is busy in another app. Close it and press start again.");
        } else if (name === "OverconstrainedError" || name === "ConstraintNotSatisfiedError") {
          disableMic("The microphone cannot meet the recording settings on this device.");
        } else {
          disableMic("The recorder could not start. Try again, or use a different browser.");
        }
      });
    }

    function stopRecording() {
      if (state !== "recording") return;
      stopTimers();
      var elapsed = clamp(now() - startedAt, 0, maxSeconds * 1000);
      state = "processing";
      teardownGraph();
      if (mic) {
        mic.disabled = true;
        mic.setAttribute("aria-pressed", "false");
        setText(micLabel, "Checking…");
      }
      setTimer(Math.max(0, maxSeconds * 1000 - elapsed));
      setText(timeStatus, "Recording stopped.");
      if (elapsed < MIN_RECORD_SECONDS * 1000 || !pcmChunks.length) {
        state = "idle";
        refreshConsent();
        setStatus("That was too short. Press start and speak for a few seconds.");
        setTimer(maxSeconds * 1000);
        return;
      }
      setStatus("Saving your recording. The audio is sent once, transcribed, and not kept.");
      postAttempt(encodeWav(pcmChunks), elapsed);
    }

    function resetControls() {
      state = "idle";
      stopTimers();
      pcmChunks = [];
      levels = [];
      setTimer(maxSeconds * 1000);
      drawWave();
      if (!mic) return;
      mic.setAttribute("aria-pressed", "false");
      setText(micLabel, "Start recording");
      if (consentState() === "granted" && supported && speechAvailable) {
        mic.disabled = false;
      } else {
        mic.disabled = true;
      }
    }

    function postAttempt(blob, durationMs) {
      if (typeof fetch !== "function") {
        resetControls();
        setStatus("This browser cannot send the recording. Nothing was saved.");
        return;
      }
      var url = "/v1/speaking/attempts?prompt_id=" + encodeURIComponent(promptId) +
        "&language=" + encodeURIComponent(language);
      fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "audio/wav",
          "X-CSRF-Token": csrfToken(),
          "X-Device-Id": deviceId()
        },
        body: blob
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          return { ok: response.ok, status: response.status, body: body };
        });
      }).then(function (result) {
        if (!result.ok) {
          resetControls();
          handleError(result.status, result.body);
          return;
        }
        showResult(result.body, durationMs);
        resetControls();
        setStatus(result.body.mock ? "Demo result ready. Read the transcript and sample feedback below." : "Feedback ready.");
      }).catch(function () {
        resetControls();
        setStatus("The recording could not be sent. Check your connection and try again. Nothing was saved.");
      });
    }

    function handleError(httpStatus, body) {
      var code = body && body.code ? String(body.code) : "";
      if (code === "E-CONSENT-REQUIRED" || code === "E-CONSENT-STALE") {
        if (consentCard) consentCard.hidden = false;
        if (consentOff) consentOff.hidden = true;
        disableMic("Voice consent needs to be recorded again on this device before the next recording is sent. Nothing was saved.");
        return;
      }
      if (code === "E-QUOTA-EXHAUSTED") {
        setStatus("Voice is resting for today's limit. Nothing was recorded. Typing and reading still work.");
        return;
      }
      if (code === "E-RATE-LIMIT") {
        setStatus("Too many attempts in a minute. Wait a moment, then try again. Nothing was saved.");
        return;
      }
      if (code === "E-AUTH-REQUIRED" || httpStatus === 401) {
        setStatus("Your session expired. Sign in again; nothing was saved.");
        return;
      }
      if (code === "E-SPEAKING-UNAVAILABLE") {
        setStatus("Speech-to-text is not configured on this deployment. Nothing was recorded.");
        return;
      }
      if (code === "E-SPEAKING-NO-SPEECH") {
        setStatus("I didn't catch any words. Move a little closer to the microphone and try again.");
        return;
      }
      if (code === "E-SPEAKING-AUDIO" || code === "E-SPEAKING-AUDIO-SIZE") {
        setStatus("That recording could not be read. Try again with a shorter clip.");
        return;
      }
      setStatus("The recording could not be processed. Nothing was saved. Try again.");
    }

    function showResult(payload, durationMs) {
      if (!resultTemplate || !resultTemplate.content || !resultRegion) return;
      var card = resultTemplate.content.firstElementChild.cloneNode(true);
      var attempt = payload.attempt || {};
      var prompt = payload.prompt || {};
      var evaluation = payload.evaluation || null;
      var attemptId = String(attempt.attempt_id || "");
      card.setAttribute("data-attempt-id", attemptId);
      setText($('[data-field="when"]', card), "Just now" + (durationMs ? " · " + Math.round(durationMs / 1000) + " s" : ""));
      var mockNotice = $('[data-field="mock-notice"]', card);
      if (mockNotice) mockNotice.hidden = !payload.mock;
      var evaluationBox = $('[data-field="evaluation"]', card);
      var unavailable = $('[data-field="unavailable"]', card);
      if (evaluation) {
        if (unavailable) unavailable.hidden = true;
        setText($('[data-field="band"]', card), evaluation.band_label || "");
        setText(
          $('[data-field="count"]', card),
          (evaluation.ideas_present || 0) + " of " + (evaluation.ideas_total || 0) + " key ideas covered"
        );
        setText($('[data-field="went-well"]', card), evaluation.what_went_well || "");
        setText($('[data-field="next-step"]', card), evaluation.next_step || "");
        var ideasList = $('[data-field="ideas"]', card);
        if (ideasList) {
          (evaluation.key_ideas || []).forEach(function (idea) {
            var row = document.createElement("li");
            row.className = "speak-idea " + (idea.present ? "speak-idea--present" : "speak-idea--missing");
            var mark = document.createElement("span");
            mark.className = "speak-idea-mark";
            mark.textContent = idea.present ? "Covered" : "Missing";
            var text = document.createElement("span");
            text.className = "speak-idea-text";
            text.lang = prompt.language || "en";
            text.textContent = idea.text || "";
            row.appendChild(mark);
            row.appendChild(text);
            if (idea.present && idea.evidence) {
              var evidence = document.createElement("q");
              evidence.className = "speak-idea-evidence";
              evidence.textContent = idea.evidence;
              row.appendChild(evidence);
            }
            ideasList.appendChild(row);
          });
        }
      } else {
        if (evaluationBox) evaluationBox.hidden = true;
        if (unavailable) unavailable.hidden = false;
      }
      var transcriptNode = $('[data-field="transcript"]', card);
      setText(transcriptNode, attempt.transcript || "");
      if (transcriptNode) transcriptNode.lang = attempt.language || "en";
      var model = $('[data-field="model"]', card);
      if (model) {
        var hasAnswer = Boolean(prompt.model_answer);
        model.hidden = !hasAnswer;
        if (hasAnswer) {
          var modelNode = $('[data-field="model-answer"]', card);
          setText(modelNode, prompt.model_answer);
          if (modelNode) modelNode.lang = prompt.language || "en";
          setText($('[data-field="model-source"]', card), modelSource(prompt.model_answer_source));
        }
      }
      var radios = $$("input[data-self-check]", card);
      var savedChoice = attempt.self_check && attempt.self_check.choice ? attempt.self_check.choice : "";
      radios.forEach(function (radio) {
        radio.name = "speak-self-check-" + attemptId;
        radio.checked = radio.value === savedChoice;
      });
      $$("[data-speaking-result-card]", resultRegion).forEach(function (old) {
        old.parentNode.removeChild(old);
      });
      if (placeholder) placeholder.hidden = true;
      resultRegion.insertBefore(card, resultRegion.firstChild);
      try { card.focus(); } catch (e) {}
    }

    function modelSource(source) {
      if (!source || typeof source !== "object") return "";
      var parts = [];
      if (source.book_id) parts.push(BOOK_LABELS[source.book_id] || humanize(source.book_id));
      if (source.section) parts.push("§" + source.section);
      if (source.example) parts.push(String(source.example));
      return parts.length ? "Source: " + parts.join(" · ") : "";
    }

    function humanize(value) {
      return String(value || "").replace(/[-_]+/g, " ").trim();
    }

    if (mic) {
      mic.addEventListener("click", startRecording);
    }
    window.addEventListener("pagehide", function () {
      stopTimers();
      teardownGraph();
    });
    refreshConsent();
    setTimer(maxSeconds * 1000);
    drawWave();
    if (!supported) {
      disableMic("This browser cannot record audio. You can still read the prompt and any earlier attempt.");
    } else if (!speechAvailable) {
      disableMic("Recording is not configured on this deployment. Nothing will capture audio.");
    }
    if (isMock) {
      setStatus("Demo mode: the AI scorer is not connected. A recording attempt returns a labelled sample.");
    }
  }

  /* ------------------------- result/history actions ------------------------- */

  function findAttemptId(node) {
    var holder = node && node.closest ? node.closest("[data-speaking-attempt-row], [data-speaking-result-card]") : null;
    return holder ? String(holder.getAttribute("data-attempt-id") || "") : "";
  }

  function statusFor(node) {
    var holder = node && node.closest ? node.closest("[data-speaking-attempt-row], [data-speaking-result-card]") : null;
    if (holder && holder.hasAttribute("data-speaking-result-card")) {
      return $("[data-speaking-result-status]", holder);
    }
    return $("[data-speaking-history-status]");
  }

  function deleteAttempt(button) {
    var attemptId = findAttemptId(button);
    if (!attemptId) return;
    if (!window.confirm(CONFIRM_DELETE)) return;
    var holder = button.closest("[data-speaking-attempt-row], [data-speaking-result-card]");
    var status = statusFor(button);
    button.disabled = true;
    fetch("/v1/speaking/attempts/" + encodeURIComponent(attemptId), {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken() }
    }).then(function (response) {
      if (response.ok || response.status === 404) {
        if (holder && holder.parentNode) holder.parentNode.removeChild(holder);
        var region = $("[data-speaking-result-region]");
        var placeholder = $("[data-speaking-result-placeholder]", region || document);
        if (placeholder && region && !$("[data-speaking-result-card]", region)) {
          placeholder.hidden = false;
        }
        var pageStatus = $("[data-speaking-history-status]");
        if (pageStatus) setText(pageStatus, "Deleted. The transcript and feedback are gone; the audio was never stored.");
        var attemptList = $("[data-speaking-attempt-list]");
        if (attemptList) {
          var remaining = attemptList.querySelectorAll("[data-speaking-attempt-row]").length;
          var listTitle = $("[data-speaking-history-list-title]");
          if (listTitle) {
            listTitle.textContent = remaining + " saved " + (remaining === 1 ? "attempt" : "attempts");
          }
          var emptyNote = $("[data-speaking-history-empty]");
          if (emptyNote) emptyNote.hidden = remaining !== 0;
          attemptList.hidden = remaining === 0;
        }
      } else {
        button.disabled = false;
        if (status) setText(status, "The attempt could not be deleted. It is still saved; try again.");
      }
    }).catch(function () {
      button.disabled = false;
      if (status) setText(status, "The attempt could not be deleted. Check your connection and try again.");
    });
  }

  function saveSelfCheck(button) {
    var card = button.closest("[data-speaking-result-card]");
    if (!card) return;
    var attemptId = String(card.getAttribute("data-attempt-id") || "");
    var status = $("[data-speaking-result-status]", card);
    var radios = $$("input[data-self-check]", card);
    var chosen = null;
    radios.forEach(function (radio) { if (radio.checked) chosen = radio.value; });
    if (!attemptId || !chosen) {
      if (status) setText(status, "Pick one of the three notes first.");
      return;
    }
    button.disabled = true;
    fetch("/v1/speaking/attempts/" + encodeURIComponent(attemptId), {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ choice: chosen })
    }).then(function (response) {
      button.disabled = false;
      if (status) {
        setText(status, response.ok
          ? "Saved. This note is only for you and is not a grade."
          : "The note could not be saved. Try again.");
      }
    }).catch(function () {
      button.disabled = false;
      if (status) setText(status, "The note could not be saved. Check your connection and try again.");
    });
  }

  function initActions() {
    document.addEventListener("click", function (event) {
      var target = event.target;
      if (!target || !target.closest) return;
      var deleteButton = target.closest("[data-speaking-delete]");
      if (deleteButton) {
        event.preventDefault();
        deleteAttempt(deleteButton);
        return;
      }
      var saveButton = target.closest("[data-speaking-self-check-save]");
      if (saveButton) {
        event.preventDefault();
        saveSelfCheck(saveButton);
      }
    });
  }

  function init() {
    initRecorder();
    initActions();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.ZivonSpeaking = {
    getConsentState: consentState,
    recordConsent: recordConsent,
    init: init
  };
})();
