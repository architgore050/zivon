(function () {
  "use strict";

  var params = new URLSearchParams(window.location.search);
  var dock = document.getElementById("dock");
  var historyEl = document.getElementById("history");
  var heroEl = document.getElementById("hero");
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

  var TURNS = [
    { role: "you",   time: "10:41", text: "Sir, impulse aur change in momentum same kyun hote hain? Formula nahi samajh raha." },
    { role: "tutor", time: "10:41", text: "Achha sawaal. Pehle ye socho — bat aur ball ka contact kitni der tak chalta hai?" },
    { role: "you",   time: "10:42", text: "Bahut kam sir, 0.15 second jaisa." },
    { role: "tutor", time: "10:42", text: "Haan. Chhota time, bada force. Ab force × time karo — yahi impulse hai." },
    { role: "you",   time: "10:43", text: "रुक रुक sir — matlab dono same cheez hai?" },
    { role: "tutor", time: "10:43", text: "Bilkul same. Ek hi quantity ke do naam — force × time jo momentum badle, wahi impulse hai." }
  ];
  var PENDING_A = "Haan — agar ball pehle rest par thi, to ab uska momentum 60 kg·m/s hai. Unit alag dikhti hai, quantity ek hi hai.";
  var PARTIAL_Q = "sir, ek baat clear karo…";
  var LANGUAGE = ["Hinglish", "हिंदी", "English"];
  var langIndex = 0;
  var state = "idle";
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

  /* The hero is the current exchange; everything before it stays in the rail. */
  function currentExchange() {
    var base = TURNS.slice();
    if (state === "listening") {
      return { history: base, you: { time: "now", text: PARTIAL_Q, draft: true }, answer: null };
    }
    var last = base.length ? base[base.length - 1] : null;
    if (state === "thinking") {
      if (last && last.role === "tutor") {
        return { history: base.slice(0, -2), you: base[base.length - 2] || null, answer: null };
      }
      return { history: base.slice(0, -1), you: last, answer: null };
    }
    if (!base.length) return { history: [], you: null, answer: null };
    if (last.role === "tutor") {
      return {
        history: base.slice(0, -2),
        you: base[base.length - 2] || null,
        answer: { text: last.text, live: state === "speaking" }
      };
    }
    return { history: base.slice(0, -1), you: last, answer: null };
  }

  function bars() {
    var out = '<span class="bars" aria-hidden="true">';
    for (var i = 0; i < 5; i++) out += '<span class="bar"></span>';
    return out + "</span>";
  }

  function statusHtml() {
    if (state === "thinking") return '<div class="status" role="status"><span class="sweep" aria-hidden="true"></span><span>Soch rahe hain…</span></div>';
    if (state === "listening") return '<div class="status" role="status">' + bars() + '<span>Sun rahe hain · band karne ke liye mic dabao</span></div>';
    if (state === "speaking") return '<div class="status" role="status">' + bars() + '<span>Bol rahe hain · mic se roko</span></div>';
    if (state === "mic-denied") return '<div class="status" role="status"><span class="stamp">MIC OFF</span><span>Lesson chalta rahega — type karke poochho.</span></div>';
    return "";
  }
  function noticeHtml() {
    if (state === "reconnecting") return '<div class="notice" role="status"><strong>Reconnecting…</strong> Link wapas aa raha hai. Jo type karoge woh queue mein rahega.</div>';
    if (state === "offline") return '<div class="notice" role="status"><strong>Offline.</strong> Type karo — message queue ho jayega. Lesson padhta rahega.</div>';
    return "";
  }

  function render() {
    var ex = currentExchange();
    var hist = ex.history;
    var html = '<p class="hist-label">Earlier</p>';
    if (!hist.length) {
      html += '<p class="hist-empty">Is page se pehla sawaal.</p>';
    } else {
      html += '<ol class="hist-list">';
      hist.forEach(function (t) {
        html += '<li><span class="hw">' + (t.role === "you" ? "You" : "Tutor") + '</span><span class="ht">' + esc(t.text) + "</span></li>";
      });
      html += "</ol>";
    }
    historyEl.innerHTML = html;

    var hero = "";
    if (ex.you) {
      hero += '<div class="asked"><span class="lbl">You</span><p>' + esc(ex.you.text);
      if (ex.you.queued) hero += '<span class="queued">queued</span>';
      if (ex.you.draft) hero += '<span class="caret" aria-hidden="true"></span>';
      hero += "</p></div>";
    }
    if (ex.answer) {
      hero += '<p class="answer">' + esc(ex.answer.text);
      if (ex.answer.live) hero += '<span class="caret" aria-hidden="true"></span>';
      hero += "</p>";
      if (!ex.answer.live) {
        hero += '<div class="tools"><button class="tool" type="button" data-act="copy">Copy</button>' +
                '<button class="tool" type="button" data-act="retry">Retry</button></div>';
      }
    }
    hero += noticeHtml();
    hero += statusHtml();
    heroEl.innerHTML = hero;

    heroEl.querySelectorAll('[data-act="copy"]').forEach(function (btn) {
      btn.addEventListener("click", function () {
        var t = lastTutor();
        if (!t) return;
        var done = function () { btn.textContent = "Copied"; later(function () { btn.textContent = "Copy"; }, 1600); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(t.text).then(done).catch(function () { btn.textContent = "Copy failed"; });
        } else { btn.textContent = "Copy failed"; }
      });
    });
    heroEl.querySelectorAll('[data-act="retry"]').forEach(function (btn) {
      btn.addEventListener("click", function () { retry(); });
    });

    var lt = lastTutor();
    if (state === "listening") { stripWho.textContent = "You"; stripLine.textContent = "Sun rahe hain…"; }
    else if (state === "thinking") { stripWho.textContent = "Tutor"; stripLine.textContent = "Soch rahe hain…"; }
    else if (state === "offline") { stripWho.textContent = "Tutor"; stripLine.textContent = "Offline — type karo, queue ho jayega"; }
    else { stripWho.textContent = "Tutor"; stripLine.textContent = lt ? lt.text : "Poochho kuch bhi is page se"; }

    if (state !== "thinking" && state !== "listening") heroEl.scrollTop = heroEl.scrollHeight;
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

  if (params.get("still") === "1") dock.setAttribute("data-still", "true");
  setView(params.get("view") || "expanded");
  setState(params.get("state") || "idle");
})();