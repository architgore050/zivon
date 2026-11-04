/* ==========================================================================
   Zivon shared behaviour layer (no framework, no network, no eval).
   --------------------------------------------------------------------------
   Owns four things and nothing else:
   1. quiz wiring for .zn-check blocks (keyboard-native inputs, aria-live
       feedback, retry allowed - this is learning, not testing); feedback
       marks are ✓/✗ plus words (doctrine §10.6: shape and words, not hue)
   2. the ZivonSim runtime that model-built simulations register into
   3. the landing-page course list renderer (reads window.ZIVON_COURSES)
   4. §10.2 ruled-line baseline alignment on lesson pages (ported from the
       doctrine's lesson example fit(): measure where the handwriting baseline
       sits and shift the ruled background under it)
   Plus: the doctrine pen-underline on the page title (one pen mark per page,
   generated, never a CSS text-underline - design-doctrine.md section 4.1).
   ========================================================================== */
(function () {
  "use strict";

  /* ---------------------------- 1. quizzes ------------------------------- */
  function firstNumber(text) {
    var m = /-?\d+(?:\.\d+)?/.exec(String(text));
    return m ? parseFloat(m[0]) : null;
  }

  function wireCheck(fieldset) {
    var format = fieldset.getAttribute("data-format");
    var button = fieldset.querySelector(".zn-check-btn");
    var feedback = fieldset.querySelector(".zn-check-feedback");
    if (!button || !feedback) return;

    button.addEventListener("click", function () {
      var correct;
      if (format === "mcq") {
        var expected = parseInt(fieldset.getAttribute("data-answer-index"), 10);
        var chosen = fieldset.querySelector('input[type="radio"]:checked');
        if (!chosen) {
          feedback.textContent = "Pick an option first.";
          feedback.className = "zn-check-feedback";
          return;
        }
        correct = parseInt(chosen.value, 10) === expected;
      } else {
        var expectedNum = firstNumber(fieldset.getAttribute("data-answer"));
        var got = firstNumber(fieldset.querySelector(".zn-numeric-input").value);
        correct = expectedNum !== null && got !== null &&
          Math.abs(got - expectedNum) <= Math.max(0.01, Math.abs(expectedNum) * 0.01);
      }
      // \u-escaped: charset-proof no matter how the embedding page loads this file
      feedback.textContent = correct ? "\u2713 Correct." : "\u2717 Not yet - try again.";
      feedback.className = correct ? "zn-check-feedback correct" : "zn-check-feedback wrong";
    });
  }

  /* ------------------------- 2. ZivonSim runtime -------------------------- */
  var registry = {};
  var ZivonSim = {
    register: function (id, impl) {
      registry[id] = impl;
      startSim(id, impl);
    }
  };
  window.ZivonSim = ZivonSim;

  function startSim(id, impl) {
    var container = document.querySelector('[data-sim-id="' + id + '"]');
    if (!container) return;
    var canvas = container.querySelector("canvas");
    if (!canvas) return;
    var values = {};
    container.querySelectorAll("[data-control]").forEach(function (input) {
      var key = input.getAttribute("data-control");
      values[key] = parseFloat(input.value);
      var output = input.parentElement.querySelector("output");
      input.addEventListener("input", function () {
        values[key] = parseFloat(input.value);
        if (output) output.textContent = input.value;
      });
    });

    var ctx = {
      canvas: canvas,
      g: canvas.getContext("2d"),
      width: canvas.width,
      height: canvas.height,
      values: values,
      t: 0
    };
    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    try {
      if (typeof impl.init === "function") impl.init(ctx);
    } catch (err) {
      // A broken simulation must be loud, not silent: paint the error on canvas.
      paintError(ctx.g, ctx.width, ctx.height, String(err));
      return;
    }

    if (reduceMotion) {
      try { impl.draw(ctx); } catch (err) { paintError(ctx.g, ctx.width, ctx.height, String(err)); }
      return;
    }
    var t0 = performance.now();
    (function frame(now) {
      ctx.t = (now - t0) / 1000;
      try {
        impl.draw(ctx);
      } catch (err) {
        paintError(ctx.g, ctx.width, ctx.height, String(err));
        return;
      }
      requestAnimationFrame(frame);
    })(t0);
  }

  function paintError(g, w, h, message) {
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#EFE6B8";
    g.fillRect(0, 0, w, h);
    g.fillStyle = "#B3261E";
    g.font = "bold 14px monospace";
    g.fillText("simulation error:", 12, 24);
    wrapText(g, message, 12, 44, w - 24, 16, h);
    g.restore();
    if (window.console && console.error) console.error("ZivonSim:", message);
  }

  function wrapText(g, text, x, y, maxW, lh, h) {
    var words = String(text).split(" ");
    var line = "";
    for (var i = 0; i < words.length; i++) {
      var test = line + words[i] + " ";
      if (g.measureText(test).width > maxW && line) {
        g.fillText(line, x, y);
        line = words[i] + " ";
        y += lh;
        if (y > h - 8) return;
      } else {
        line = test;
      }
    }
    if (y <= h - 8) g.fillText(line, x, y);
  }

  /* --------------------- 3. landing page course list ---------------------- */
  function renderCourses() {
    var list = document.getElementById("zn-courses");
    if (!list || !window.ZIVON_COURSES) return;
    if (!window.ZIVON_COURSES.length) {
      var empty = document.getElementById("zn-empty");
      if (empty) empty.hidden = false;
      return;
    }
    window.ZIVON_COURSES.forEach(function (course) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.className = "zn-card";
      a.href = course.href;
      var title = document.createElement("p");
      title.className = "zn-card-title";
      title.textContent = course.title;
      var chapter = document.createElement("p");
      chapter.className = "zn-card-chapter";
      chapter.textContent = "Chapter: " + course.chapter;
      var meta = document.createElement("p");
      meta.className = "zn-card-meta";
      meta.textContent = course.course_id + " - generated " + course.generated_at;
      a.appendChild(title);
      a.appendChild(chapter);
      a.appendChild(meta);
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  /* -------- doctrine pen underline on the page title (one per page) -------- */
  /* Ported from docs/frontend/design-doctrine-example.html (canonical generator,
     design-doctrine.md section 4.1). Parameters are in em of the underlined font. */
  function penUnderline(el) {
    var CENTER_BELOW_BOX = 0.08;
    function seedFrom(s) {
      var h = 2166136261 >>> 0;
      for (var i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 16777619);
      }
      return h >>> 0;
    }
    function rng(a) {
      return function () {
        a |= 0; a = a + 0x6D2B79F5 | 0;
        var t = Math.imul(a ^ a >>> 15, 1 | a);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
      };
    }
    var fs = parseFloat(getComputedStyle(el).fontSize);
    var text = (el.textContent || "").trim();
    var w = el.getBoundingClientRect().width;
    if (!w || !text) return;
    var L = w + 0.09 * fs + 0.18 * fs, x0 = -0.09 * fs;
    var n = Math.max(4, Math.round(L / (0.45 * fs)));
    var amp = 0.02 * fs, period = 4 * fs, phase = 0.7;
    var rnd = rng(seedFrom(text));
    var top = [], bot = [];
    for (var i = 0; i <= n; i++) {
      var t = i / n, x = x0 + L * t;
      var y = CENTER_BELOW_BOX * fs + amp * Math.sin(2 * Math.PI * (L * t) / period + phase) +
        (rnd() * 2 - 1) * 0.007 * fs;
      var hw = (0.067 + (0.033 - 0.067) * t) * fs / 2;
      top.push([x, y - hw]);
      bot.push([x, y + hw]);
    }
    var d = top.concat(bot.reverse()).map(function (p, idx) {
      return (idx ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2);
    }).join(" ") + " Z";
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "uline");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", Math.ceil(w));
    svg.setAttribute("height", Math.ceil(fs));
    svg.setAttribute("overflow", "visible");
    svg.style.cssText = "position:absolute;left:0;top:100%;pointer-events:none;";
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "var(--pen-blue)");
    svg.appendChild(path);
    el.appendChild(svg);
  }

  /* -------- §10.2 ruled-line baseline alignment (lesson pages only) --------
     Ported from the doctrine's lesson example (fit() in
     docs/frontend/design-doctrine-lesson-example.html): every text block is a
     multiple of 36 px tall, so ONE measurement of the text baseline puts every
     ruled line directly under a baseline; the page re-fits on resize (frame
     adaptation). The title is nudged by at most 18 px so its baseline lands on
     a rule too. The landing shell has no .zn-text blocks and never aligns
     (§10 scope guard). */
  function baselineProbe(el) {
    var probe = document.createElement("span");
    probe.style.cssText = "display:inline-block;width:0;height:0";
    el.prepend(probe);
    var bottom = probe.getBoundingClientRect().bottom - el.getBoundingClientRect().top;
    probe.remove();
    return bottom;
  }
  function alignToRuledLines() {
    var page = document.querySelector(".zn-page:not(.zn-home)");
    var firstBody = page ? page.querySelector(".zn-text p") : null;
    if (!page || !firstBody) return;
    var bodyBaseline = baselineProbe(firstBody);
    var bodyY = firstBody.getBoundingClientRect().top + window.scrollY;
    var offset = (((bodyY + bodyBaseline - 34) % 36) + 36) % 36;
    document.body.style.backgroundPosition = "0 " + offset + "px";
    var title = page.querySelector("h1.zn-title");
    if (title) {
      var titleBaseline = baselineProbe(title);
      var titleY = title.getBoundingClientRect().top + window.scrollY;
      var d = ((((bodyY + bodyBaseline) - (titleY + titleBaseline)) % 36) + 36) % 36;
      if (d > 18) d -= 36;
      title.style.top = d + "px";
    }
  }

  /* ------------------------------- boot ---------------------------------- */
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".zn-check").forEach(wireCheck);
    renderCourses();
    var title = document.querySelector("h1.zn-title");
    if (title) penUnderline(title);
    alignToRuledLines();
    if (document.fonts) {
      // local fonts load with swap: re-measure once the real faces are in
      document.fonts.ready.then(alignToRuledLines);
    }
    window.addEventListener("resize", alignToRuledLines);
  });
})();
