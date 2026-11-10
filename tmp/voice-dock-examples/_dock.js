/* ==========================================================================
   THROWAWAY MOCKUP SCRIPT - tmp/voice-dock-examples/_dock.js
   --------------------------------------------------------------------------
   INERT. Visual mockup only. There is NO network call, NO WebSocket, NO
   getUserMedia, NO AudioContext, NO storage, and NO external resource in
   this file. Every string, latency, level bar and "credit" number is fake
   and hard-coded below. Nothing here is doctrine (§10.12 is founder-gated
   and absent); this file exists to let the founder judge dock SHAPES.
   State names are copied verbatim from frontend/assets/zivon.js so a
   winner maps onto the real client without renaming anything.
   ========================================================================== */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- data */
  /* One fixed conversation. Six turns. Tutor turns are pre-split into
     phrases so the caption can grow phrase by phrase (the behaviour under
     judgement). Hinglish in Latin script + Devanagari, fake on purpose. */
  var CONV = [
    { who: "you", text: "Sir, impulse aur change in momentum same kyun hote hain? Formula nahi samajh raha." },
    { who: "tutor", phrases: [
      "Achha sawaal.",
      "Pehle yeh socho —",
      "bat aur ball ka contact",
      "kitni der tak chalta hai?"
    ] },
    { who: "you", text: "Bahut kam sir, 0.15 second jaisa." },
    { who: "tutor", cutAfter: 7, phrases: [
      "Haan, chhota time,",
      "aur bada force.",
      "Ab force × time karo —",
      "yahi impulse hai.",
      "Newton ka doosra law",
      "F = Δp/Δt hai, ise palat do",
      "to F·Δt = Δp, matlab left side",
      "impulse aur right side change in mo"
    ] },
    { who: "you", text: "रुक रुक sir — matlab left side impulse, right side change in momentum? Same cheez hai na?" },
    { who: "tutor", phrases: [
      "Bilkul same hai.",
      "Formula ek hi quantity ko",
      "do naam deta hai —",
      "force × time jo momentum badle,",
      "wahi impulse hai.",
      "इसलिए दोनों बराबर लिखते हैं।"
    ] }
  ];

  /* the exact state names from frontend/assets/zivon.js */
  var STATES = [
    "idle", "requesting-permission", "connecting", "ready", "listening",
    "endpointing", "thinking", "speaking", "speaking_text", "interrupted",
    "offline", "error:mic-denied", "error:mic-in-use", "error:no-match",
    "error:auth.invalid", "error:version.mismatch", "error:system-error",
    "text_only"
  ];

  var LABEL = {
    "idle": "Mic idle",
    "requesting-permission": "Permission",
    "connecting": "Connecting",
    "ready": "Mic ready",
    "listening": "Listening",
    "endpointing": "Waiting for silence",
    "thinking": "Thinking",
    "speaking": "Tutor speaking",
    "speaking_text": "Tutor · text",
    "interrupted": "Stopped",
    "offline": "Offline",
    "error:mic-denied": "Mic off",
    "error:mic-in-use": "Mic busy",
    "error:no-match": "No match",
    "error:auth.invalid": "Session expired",
    "error:version.mismatch": "Update needed",
    "error:system-error": "Tutor error",
    "text_only": "Voice paused"
  };

  var CANON = {
    "idle": "Hold the mic and speak your doubt.",
    "ready": "Mic ready. Hold to speak.",
    "requesting-permission": "Asking the browser for the mic…",
    "connecting": "Connecting the tutor…",
    "listening": "Listening — keep holding, phir chhod do.",
    "endpointing": "Silence mila — aapki baat khatam hone ka wait.",
    "thinking": "Soch raha hoon…",
    "speaking": "",
    "speaking_text": "Voice dropped — jawab text mein aa raha hai.",
    "interrupted": "You cut in — the tutor stopped mid-word.",
    "offline": "Aap offline hain. Type karo — connection aane par jawab milega.",
    "text_only": "Voice aaj paused hai (credit guard). Type karo — lesson blocked nahi hai.",
    "error:mic-denied": "Mic is off for this page. Type your doubt — the lesson works fine.",
    "error:mic-in-use": "Another app is holding the mic. Type instead, or close that app.",
    "error:no-match": "Samajh nahi aaya. Hold the mic again, ya type kar do.",
    "error:auth.invalid": "Session expired. Type your doubt — the tutor reconnects on its own.",
    "error:version.mismatch": "This page needs a newer tutor build. Type instead — nothing is lost.",
    "error:system-error": "The tutor hit a snag. Type your doubt — the page is not blocked."
  };

  var NOTE = {
    "offline": "<b>No connection.</b> Nothing you type is lost — it is sent when you are back.",
    "text_only": "<b>30 credits / day</b> · voice resets at 00:00. Reading, sims and typing are free and unlimited.",
    "error:mic-denied": "<b>Mic denied.</b> Reading and typing are unaffected — this is not a dead end.",
    "error:mic-in-use": "<b>Mic busy.</b> Held by another tab or app. Typing works meanwhile.",
    "error:no-match": "<b>Not caught.</b> Say it once more, or type — both reach the same tutor.",
    "error:auth.invalid": "<b>Session expired.</b> Typing still queues; the tutor re-authenticates.",
    "error:version.mismatch": "<b>Stale build.</b> Typing still works on the loaded page.",
    "error:system-error": "<b>Tutor error.</b> Page content is unaffected — ask in text."
  };

  var HIGHLIGHT = ["listening", "endpointing", "thinking", "speaking", "speaking_text", "interrupted"];

  /* ------------------------------------------------------------- elements */
  var dock = document.querySelector(".dk");
  if (!dock) return;

  var q = function (sel) { return dock.querySelector(sel); };
  var e = {
    mic: q("[data-mic]"),
    chip: q("[data-chip]"),
    cap: q("[data-caption]"),
    tr: q("[data-transcript]"),
    note: q("[data-note]"),
    textPanel: q("[data-textpanel]"),
    textToggle: q("[data-texttoggle]"),
    form: q("[data-form]"),
    input: q("[data-input]"),
    collapse: q("[data-collapse]"),
    root: dock
  };

  var S = {
    textHeld: false,
    state: "idle",
    turns: [],
    token: 0,
    frozen: false,
    streaming: false,
    textMode: false
  };

  /* --------------------------------------------------- b-13 highlight ring */
  var ring = document.createElement("div");
  ring.className = "hl-ring";
  ring.setAttribute("aria-hidden", "true");
  var tag = document.createElement("span");
  tag.className = "hl-tag";
  tag.textContent = "b-13 · tutor pointing here";
  ring.appendChild(tag);
  document.body.appendChild(ring);

  /* Same-origin (served over http://) we measure b-13 for real. On file://
     the iframe is cross-origin, so the CSS measured-fallback box stands and
     nothing throws. */
  function measureAnchor() {
    var f = document.querySelector("iframe.stage");
    if (!f) return;
    try {
      var d = f.contentDocument;
      if (!d) return;
      var block = d.getElementById("b-13");
      var bar = d.querySelector(".zn-lang-bar");
      if (!block) return;
      var fr = f.getBoundingClientRect();
      var br = block.getBoundingClientRect();
      var barH = bar ? bar.getBoundingClientRect().height : 57;
      ring.style.top = (fr.top + br.top + barH) + "px";
      ring.style.height = Math.max(120, br.height - barH) + "px";
      ring.style.left = (fr.left + br.left) + "px";
      ring.style.right = (fr.right - br.right) + "px";
    } catch (err) { /* cross-origin file:// - keep the measured fallback */ }
  }

  /* ---------------------------------------------------------------- paint */
  function paintCap(text, caret) {
    if (!e.cap) return;
    e.cap.textContent = "";
    e.cap.appendChild(document.createTextNode(text || ""));
    if (caret) {
      var c = document.createElement("span");
      c.className = "dk-caret";
      c.setAttribute("aria-hidden", "true");
      e.cap.appendChild(c);
    }
  }

  function renderTranscript() {
    if (!e.tr) return;
    e.tr.textContent = "";
    S.turns.forEach(function (t) {
      var li = document.createElement("li");
      if (t.cut) li.setAttribute("data-cut", "1");
      var who = document.createElement("span");
      who.className = "who" + (t.who === "tutor" ? " tutor" : "");
      who.textContent = t.who === "tutor" ? "Tutor" : "You";
      li.appendChild(who);
      li.appendChild(document.createTextNode(t.text));
      if (t.cut) {
        var cut = document.createElement("span");
        cut.className = "cut";
        cut.textContent = " ▍cut off";
        li.appendChild(cut);
      }
      e.tr.appendChild(li);
    });
    e.tr.scrollTop = e.tr.scrollHeight;
  }

  function addTurn(who, text) {
    var t = { who: who, text: text, cut: false };
    S.turns.push(t);
    renderTranscript();
    return t;
  }

  function openText(on) {
    if (!e.textPanel) return;
    e.textPanel.classList.toggle("is-open", !!on);
    if (e.textToggle) e.textToggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (on && e.input) {
      setTimeout(function () { try { e.input.focus(); } catch (err) {} }, 40);
    }
  }

  var silenceTimer = null;
  function armSilence() {
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(function () {
      if (S.state === "listening" && !S.frozen) setState("idle");
    }, 4200);
  }

  function setState(state, opts) {
    opts = opts || {};
    S.state = state;
    e.root.setAttribute("data-state", state);
    e.root.setAttribute("aria-busy", state === "thinking" ? "true" : "false");
    if (e.chip) e.chip.textContent = LABEL[state] || state;
    if (e.note) e.note.innerHTML = NOTE[state] || "";
    if (e.mic) {
      e.mic.setAttribute("aria-pressed", state === "listening" ? "true" : "false");
      e.mic.disabled = (state === "text_only" || state === "offline");
    }
    var textFirst = /^error/.test(state) || state === "offline" || state === "text_only";
    if (textFirst && !opts.keepText) openText(true);
    else if (!textFirst && !S.textHeld) openText(false);
    if (opts.caption !== undefined) paintCap(opts.caption, !!opts.caret);
    else if (!S.streaming) paintCap(CANON[state] || "", false);
    ring.classList.toggle("is-on", HIGHLIGHT.indexOf(state) !== -1);
    if (state === "listening" && !S.frozen) armSilence();
    else clearTimeout(silenceTimer);
  }

  /* ------------------------------------------------------------- timeline */
  function pause(ms, my) {
    return new Promise(function (resolve, reject) {
      setTimeout(function () {
        if (my !== S.token) return reject("abort");
        resolve();
      }, ms);
    });
  }

  function streamTutor(i, my) {
    var spec = CONV[i];
    var t = addTurn("tutor", "");
    setState(S.textMode ? "speaking_text" : "speaking", { caption: "" });
    S.streaming = true;
    var p = 0;

    function step() {
      if (my !== S.token) { S.streaming = false; return; }
      if (p >= spec.phrases.length) {
        S.streaming = false;
        paintCap(t.text, false);
        return;
      }
      t.text = t.text ? t.text + " " + spec.phrases[p] : spec.phrases[p];
      var isCutPhrase = (spec.cutAfter === p);
      p += 1;
      renderTranscript();
      paintCap(t.text, !S.textMode && !isCutPhrase);
      setTimeout(function () {
        if (my !== S.token) { S.streaming = false; return; }
        if (isCutPhrase) {
          /* barge-in: the tutor stops mid-word, frozen on screen */
          setTimeout(function () {
            if (my !== S.token) { S.streaming = false; return; }
            S.streaming = false;
            t.cut = true;
            renderTranscript();
            setState("interrupted", { caption: t.text });
          }, 90);
          return;
        }
        step();
      }, 165 + Math.round(Math.random() * 70));
    }
    step();
  }

  function userTurn(i, my, holdMs) {
    setState("listening", { caption: CANON.listening });
    return pause(holdMs, my).then(function () {
      setState("endpointing");
      return pause(780, my);
    }).then(function () {
      setState("thinking");
      addTurn("you", CONV[i].text);
      return pause(1150, my);
    });
  }

  function runScript() {
    S.token += 1;
    var my = S.token;
    S.frozen = false;
    S.textMode = false;
    S.turns = [];
    renderTranscript();
    openText(false);
    setState("idle");

    pause(700, my)
      .then(function () { return userTurn(0, my, 1700); })
      .then(function () { streamTutor(1, my); return pause(4200, my); })
      .then(function () { return userTurn(2, my, 1300); })
      .then(function () { streamTutor(3, my); return pause(3400, my); })
      .then(function () {
        /* the barge-in: tutor is frozen on "change in mo", student speaks */
        setState("listening", { caption: CONV[4].text });
        return pause(1900, my);
      })
      .then(function () {
        setState("endpointing");
        return pause(760, my);
      })
      .then(function () {
        setState("thinking");
        addTurn("you", CONV[4].text);
        return pause(1000, my);
      })
      .then(function () { streamTutor(5, my); return pause(3000, my); })
      .then(function () {
        /* tutor hands the floor back; silence closes to idle without blinking */
        setState("listening");
        return pause(4200, my);
      })
      .then(function () { if (my === S.token) setState("idle"); })
      .catch(function () { /* aborted by interaction */ });
  }

  /* ------------------------------------------------- manual hold-to-talk */
  var manualBusy = false;

  function pressStart() {
    if (e.mic && e.mic.disabled) return;
    S.token += 1;
    S.frozen = false;
    S.streaming = false;
    clearTimeout(silenceTimer);
    setState("listening", { caption: CANON.listening });
  }

  function pressEnd() {
    if (S.state !== "listening" || manualBusy) return;
    manualBusy = true;
    S.token += 1;
    var my = S.token;
    setState("endpointing");
    pause(760, my)
      .then(function () {
        setState("thinking");
        addTurn("you", "Yeh impulse wala part ek baar phir se samjhao sir.");
        return pause(1100, my);
      })
      .then(function () { streamTutor(5, my); return pause(1400, my); })
      .then(function () { manualBusy = false; })
      .catch(function () { manualBusy = false; });
  }

  function askInText(text) {
    S.token += 1;
    var my = S.token;
    S.frozen = false;
    S.streaming = false;
    addTurn("you", text);
    setState("thinking");
    pause(1000, my)
      .then(function () { streamTutor(5, my); })
      .catch(function () {});
  }

  /* ------------------------------------------------------------ dev panel */
  function buildDev() {
    var dev = document.createElement("div");
    dev.className = "dev";
    var btn = document.createElement("button");
    btn.className = "dev-toggle";
    btn.type = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "MOCK · state ▾";
    var body = document.createElement("div");
    body.className = "dev-body";
    body.hidden = true;

    var label = document.createElement("label");
    label.textContent = "state ";
    var sel = document.createElement("select");
    sel.setAttribute("aria-label", "Force a dock state");
    STATES.forEach(function (s) {
      var o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      sel.appendChild(o);
    });
    label.appendChild(sel);

    var replay = document.createElement("button");
    replay.type = "button";
    replay.textContent = "▶ replay";
    var textbtn = document.createElement("button");
    textbtn.type = "button";
    textbtn.textContent = "text mode";
    textbtn.setAttribute("aria-pressed", "false");

    body.appendChild(label);
    body.appendChild(replay);
    body.appendChild(textbtn);
    dev.appendChild(btn);
    dev.appendChild(body);
    document.body.appendChild(dev);

    btn.addEventListener("click", function () {
      body.hidden = !body.hidden;
      btn.setAttribute("aria-expanded", body.hidden ? "false" : "true");
    });

    replay.addEventListener("click", function () {
      sel.value = "";
      runScript();
    });

    textbtn.addEventListener("click", function () {
      S.textMode = !S.textMode;
      textbtn.setAttribute("aria-pressed", S.textMode ? "true" : "false");
      if (S.state === "speaking" || S.state === "speaking_text") {
        setState(S.textMode ? "speaking_text" : "speaking",
          { caption: e.cap ? e.cap.textContent : "" });
      }
    });

    sel.addEventListener("change", function () {
      var v = sel.value;
      if (!v) return;
      S.token += 1;
      S.streaming = false;
      S.frozen = true;
      seedState(v);
    });
  }

  /* a frozen state must still SHOW the thing it claims */
  function seedState(v) {
    if (v === "speaking" || v === "speaking_text") {
      S.turns = [];
      addTurn("you", CONV[0].text);
      var t = addTurn("tutor", CONV[5].phrases.join(" "));
      renderTranscript();
      setState(v, { caption: t.text, caret: v === "speaking" });
      return;
    }
    if (v === "interrupted") {
      S.turns = [];
      addTurn("you", CONV[0].text);
      var cut = addTurn("tutor", CONV[3].phrases.slice(0, CONV[3].cutAfter + 1).join(" "));
      cut.cut = true;
      renderTranscript();
      setState(v, { caption: cut.text });
      return;
    }
    if (v === "idle" || v === "text_only" || /^error/.test(v) || v === "offline") {
      S.turns = [];
      renderTranscript();
      setState(v);
      return;
    }
    if (S.turns.length === 0) addTurn("you", CONV[0].text);
    setState(v);
  }

  /* --------------------------------------------------------------- wiring */
  if (e.mic) {
    e.mic.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      try { e.mic.setPointerCapture(ev.pointerId); } catch (err) {}
      pressStart();
    });
    e.mic.addEventListener("pointerup", function (ev) {
      ev.preventDefault();
      pressEnd();
    });
    e.mic.addEventListener("pointercancel", pressEnd);
    e.mic.addEventListener("keydown", function (ev) {
      if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); pressStart(); }
    });
    e.mic.addEventListener("keyup", function (ev) {
      if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); pressEnd(); }
    });
  }

  if (e.textToggle) {
    e.textToggle.addEventListener("click", function () {
      var openNow = !(e.textPanel && e.textPanel.classList.contains("is-open"));
      S.textHeld = openNow;
      openText(openNow);
    });
  }

  if (e.form) {
    e.form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var v = e.input ? e.input.value.trim() : "";
      if (!v) return;
      e.input.value = "";
      S.textHeld = true;
      askInText(v);
    });
  }

  if (e.collapse) {
    e.collapse.addEventListener("click", function () {
      var collapsed = e.root.classList.toggle("is-collapsed");
      e.collapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
      e.collapse.setAttribute("aria-label", collapsed
        ? "Expand the dock (mic stays available)"
        : "Collapse the dock (mic stays available)");
    });
  }

  document.addEventListener("keydown", function (ev) {
    var tag = (ev.target && ev.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (ev.key === " " && !ev.repeat) { ev.preventDefault(); pressStart(); }
    if (ev.key === "Escape") {
      if (S.state === "speaking" || S.state === "speaking_text") {
        S.token += 1;
        S.streaming = false;
        var last = S.turns.length ? S.turns[S.turns.length - 1] : null;
        setState("interrupted", { caption: last ? last.text : CANON.interrupted });
      }
    }
  });
  document.addEventListener("keyup", function (ev) {
    var tag = (ev.target && ev.target.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (ev.key === " ") { ev.preventDefault(); pressEnd(); }
  });

  /* --------------------------------------------------------------- start */
  buildDev();
  measureAnchor();
  window.addEventListener("resize", measureAnchor);
  setTimeout(runScript, 550);
})();
