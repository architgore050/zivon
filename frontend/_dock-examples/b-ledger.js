(function () {
  "use strict";

  var params = new URLSearchParams(window.location.search);
  var dock = document.getElementById("dock");
  var transcriptEl = document.getElementById("transcript");
  var stateSel = document.getElementById("stateSel");
  var micBtn = document.getElementById("mic");
  var stripMic = document.getElementById("stripMic");
  var field = document.getElementById("field");
  var form = document.getElementById("composer");
  var ledger = document.getElementById("ledger");
  var hints = document.getElementById("hints");
  var stripWho = document.getElementById("stripWho");
  var stripLine = document.getElementById("stripLine");
  var langChip = document.getElementById("langChip");
  var jumpBtn = null;

  var TURNS = [
    { role: "you",   time: "10:41", text: "Sir, impulse aur change in momentum same kyun hote hain? Formula nahi samajh raha." },
    { role: "tutor", time: "10:41", text: "Achha sawaal. Pehle ye socho — bat aur ball ka contact kitni der tak chalta hai?" },
    { role: "you",   time: "10:42", text: "Bahut kam sir, 0.15 second jaisa." },
    { role: "tutor", time: "10:42", text: "Haan. Chhota time, bada force. Ab force × time karo — yahi impulse hai. Newton ka doosra law F = Δp/Δt hai; palat do to F·Δt = Δp. Left side impulse, right side change in momentum." },
    { role: "you",   time: "10:43", text: "रुक रुक sir — matlab dono same cheez hai?" },
    { role: "tutor", time: "10:43", text: "Bilkul same. Ek hi quantity ke do naam — force × time jo momentum badle, wahi impulse hai." }
  ];
  var PENDING_A = "Haan — agar ball pehle rest par thi, to ab uska momentum 60 kg·m/s hai. Unit alag dikhti hai, quantity ek hi hai.";
  var PARTIAL_Q = "sir, ek baat clear karo…";
  var LANGUAGE = ["Hinglish", "हिंदी", "English"];
  var langIndex = 0;
  var state = "idle";
  var stick = true;
  var timers = [];

  function later(fn, ms) { timers.push(window.setTimeout(fn, ms)); }
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function nowTime() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function lastTutor() {
    for (var i = TURNS.length - 1; i >= 0; i--) if (TURNS[i].role === "tutor") return TURNS[i];
    return null;
  }
  function visibleTurns() {
    var list = TURNS.slice();
    if (state === "listening") {
      list.push({ role: "you", time: "now", text: PARTIAL_Q, draft: true });
    }
    return list;
  }
  function bars() {
    var out = '<span class="bars" aria-hidden="true">';
    for (var i = 0; i < 5; i++) out += '<span class="bar"></span>';
    return out + "</span>";
  }
  function statusRow() {
    var label = "";
    var body = "";
    if (state === "thinking") { label = "Tutor"; body = '<span class="sweep" aria-hidden="true"></span><span>Soch rahe hain…</span>'; }
    else if (state === "speaking") { label = "Tutor"; body = bars() + "<span>Bol rahe hain · mic se roko</span>"; }
    else if (state === "listening") { label = "You"; body = bars() + "<span>Sun rahe hain · band karne ke liye mic dabao</span>"; }
    else if (state === "mic-denied") { label = "Tutor"; body = '<span class="stamp">MIC OFF</span><span>Lesson chalta rahega — type karke poochho.</span>'; }
    else return "";
    return '<div class="row row-note status" role="status"><div class="row-margin"><span class="who">' + label + "</span></div>" +
           '<p class="said">' + body + "</p></div>";
  }
  function noticeRow() {
    if (state === "reconnecting") {
      return '<div class="note-row" role="status"><strong>Reconnecting…</strong> Link wapas aa raha hai. Jo type karoge woh queue mein rahega.</div>';
    }
    if (state === "offline") {
      return '<div class="note-row" role="status"><strong>Offline.</strong> Type karo — message queue ho jayega. Lesson padhta rahega.</div>';
    }
    return "";
  }

  function heading() {
    return '<h2 class="page-heading">Doubts' +
      '<svg viewBox="0 0 92 7" preserveAspectRatio="none" aria-hidden="true"><path d="M1 5 C18 2.6 34 5.4 50 3.2 C64 1.4 79 4.6 91 2.4" fill="none" stroke="#1F3A9E" stroke-width="2.6" stroke-linecap="round"/></svg>' +
      "</h2><p class=\"page-meta\">Laws of Motion · b-13 worked example</p>";
  }

  function render() {
    var list = visibleTurns();
    var html = heading();
    if (!list.length) {
      html += '<p class="note-row">AI tutor — it sees this page, not your room. Voice is transcribed; audio is not kept.</p>';
    }
    list.forEach(function (t, i) {
      var isTutor = t.role === "tutor";
      var isLast = i === list.length - 1;
      html += '<div class="row row-' + t.role + (t.draft ? " is-draft" : "") + '">';
      html += '<div class="row-margin"><span class="who">' + (isTutor ? "Tutor" : "You") + "</span><time>" + esc(t.time) + "</time></div>";
      html += '<p class="said">' + esc(t.text);
      if (t.queued) html += '<span class="queued">queued</span>';
      if (t.live || t.draft || (isTutor && isLast && state === "speaking")) html += '<span class="caret" aria-hidden="true"></span>';
      html += "</p>";
      if (isTutor && isLast && !t.draft) {
        html += '<div class="row-tools">' +
                '<button class="tool tool-icon" type="button" data-act="retry" aria-label="Retry" title="Retry">' +
                '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">' +
                '<path d="M20 11a8 8 0 1 0-2.3 5.7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
                '<path d="M20 5v6h-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
                '</svg></button></div>';
      }
      html += "</div>";
    });
    html += noticeRow();
    html += statusRow();
    html += '<button class="jump" type="button" id="jump">Latest ↓</button>';
    transcriptEl.innerHTML = html;
    jumpBtn = document.getElementById("jump");
    if (jumpBtn) jumpBtn.addEventListener("click", function () { stick = true; scrollBottom(); });

    transcriptEl.querySelectorAll('[data-act="retry"]').forEach(function (btn) {
      btn.addEventListener("click", function () { retry(); });
    });

    var lt = lastTutor();
    if (state === "listening") { stripWho.textContent = "You"; stripLine.textContent = "Sun rahe hain…"; }
    else if (state === "thinking") { stripWho.textContent = "Tutor"; stripLine.textContent = "Soch rahe hain…"; }
    else if (state === "offline") { stripWho.textContent = "Tutor"; stripLine.textContent = "Offline — type karo, queue ho jayega"; }
    else { stripWho.textContent = "Tutor"; stripLine.textContent = lt ? lt.text : "Poochho kuch bhi is page se"; }

    if (stick) scrollBottom();
  }

  function scrollBottom() {
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    if (jumpBtn) jumpBtn.classList.remove("is-on");
  }

  function setState(next) {
    clearTimers();
    state = next;
    dock.setAttribute("data-state", next);
    if (stateSel.value !== next) stateSel.value = next;
    var disabled = next === "text-only" || next === "mic-denied" || next === "offline" || next === "reconnecting";
    var pressed = next === "listening";
    [micBtn, stripMic].forEach(function (b) {
      b.disabled = disabled;
      b.setAttribute("aria-pressed", pressed ? "true" : "false");
      b.setAttribute("aria-label", pressed ? "Stop listening" : "Start listening");
    });
    ledger.hidden = next !== "text-only";
    hints.hidden = next !== "mic-denied";
    if (next === "text-only" || next === "mic-denied" || next === "offline") {
      later(function () { try { field.focus(); } catch (e) {} }, 60);
    }
    render();
  }

  function retry() {
    if (TURNS.length && TURNS[TURNS.length - 1].role === "tutor") TURNS.pop();
    setState("thinking");
    later(function () {
      TURNS.push({ role: "tutor", time: nowTime(), text: PENDING_A });
      setState("speaking");
      later(function () { setState("idle"); }, 2400);
    }, 1400);
  }

  function micToggle() {
    if (state === "listening") {
      TURNS.push({ role: "you", time: nowTime(), text: PARTIAL_Q });
      setState("thinking");
      later(function () {
        TURNS.push({ role: "tutor", time: nowTime(), text: PENDING_A });
        setState("speaking");
        later(function () { setState("idle"); }, 2600);
      }, 1400);
      return;
    }
    setState("listening");
  }

  micBtn.addEventListener("click", micToggle);
  stripMic.addEventListener("click", function (ev) { ev.stopPropagation(); micToggle(); });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var text = field.value.trim();
    if (!text) return;
    field.value = "";
    if (state === "offline" || state === "reconnecting") {
      TURNS.push({ role: "you", time: nowTime(), text: text, queued: true });
      stick = true;
      render();
      return;
    }
    TURNS.push({ role: "you", time: nowTime(), text: text });
    setState("thinking");
    later(function () {
      TURNS.push({ role: "tutor", time: nowTime(), text: PENDING_A });
      setState("speaking");
      later(function () { setState("idle"); }, 2400);
    }, 1500);
  });

  hints.querySelectorAll(".hint").forEach(function (btn) {
    btn.addEventListener("click", function () { field.value = btn.textContent.trim(); field.focus(); });
  });

  document.getElementById("stripOpen").addEventListener("click", function () { setView("expanded"); });
  document.getElementById("collapseBtn").addEventListener("click", function () { setView("collapsed"); });
  document.getElementById("tab").addEventListener("click", function () { setView("collapsed"); });

  function setView(v) {
    dock.setAttribute("data-view", v);
    document.querySelectorAll(".demo-views button").forEach(function (b) {
      b.classList.toggle("is-on", b.getAttribute("data-view") === v);
    });
  }
  document.querySelectorAll(".demo-views button").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
  });

  stateSel.addEventListener("change", function () { setState(stateSel.value); });

  langChip.addEventListener("click", function () {
    langIndex = (langIndex + 1) % LANGUAGE.length;
    langChip.textContent = LANGUAGE[langIndex];
    langChip.setAttribute("aria-label", "Language: " + LANGUAGE[langIndex] + ". Change language");
  });

  document.getElementById("anchorChip").addEventListener("click", function () {
    var card = document.querySelector(".taped");
    if (!card) return;
    card.style.outline = "3px solid var(--pen-blue)";
    card.style.outlineOffset = "4px";
    card.scrollIntoView({ block: "center", behavior: "smooth" });
    later(function () { card.style.outline = ""; card.style.outlineOffset = ""; }, 1600);
  });

  transcriptEl.addEventListener("scroll", function () {
    var gap = transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight;
    stick = gap < 32;
    if (jumpBtn) jumpBtn.classList.toggle("is-on", !stick);
  });

  if (params.get("still") === "1") dock.setAttribute("data-still", "true");
  setView(params.get("view") || "expanded");
  setState(params.get("state") || "idle");
})();