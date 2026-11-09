/* ==========================================================================
   Zivon shared behaviour layer (no framework, no network, no eval).
   --------------------------------------------------------------------------
   Owns four things and nothing else:
   1. quiz wiring for .zn-check blocks (keyboard-native inputs, aria-live
       feedback, retry allowed - this is learning, not testing); feedback
       marks are ✓/✗ plus words (doctrine §10.6: shape and words, not hue)
   2. the ZivonSim runtime that model-built simulations register into
   3. the landing-page course list renderer (reads window.ZIVON_COURSES)
   4. the LESSON KIT (doctrine §10.2, merged 2026-11-05 from the founder's
       lesson-kit.js): LessonKit.init measures where every line of text
       actually landed (Range client rects + ascent probe), normalises each
       font's baseline to one offset, and draws the ruled lines as SVG under
       the measured baselines - rules are never computed, so they cannot
       drift (fonts, zoom, fallback glyphs, wrapping, resize all covered).
       It also generates the doctrine pen underline (§4.1) on the page title
       and re-draws it on re-wrap. Generated pages get all of this from the
       shell - page code never re-implements or copies the kit.
   The landing shell has no .zn-page:not(.zn-home) paper, so the ruled part
   no-ops there (§10 scope guard); the title pen underline applies everywhere.
   ========================================================================== */
(function () {
  "use strict";

  /* --------------------- 0. routing & localized hook ----------------------
     File-path routing on nginx (spec.md §3.1) plus the reserved localized-route
     hook (spec.md §3.2, DCR-001 deferred; ADR-0009 11-locale model + doctrine
     v1 subset). Exposes canonical URL parsing, screen classification, and
     localized path resolution without any runtime router. */
  var SUPPORTED_LOCALES = [
    "en", "hi", "hi-Latn", "hinglish",
    "en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN",
    "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"
  ];
  var V1_UI_LOCALES = ["en", "hi", "hi-Latn"];

  function parseRoute(pathname) {
    var raw = String(pathname || (window.location && window.location.pathname) || "/");
    var clean = raw.replace(/\/index\.html$/, "/").replace(/\/+$/, "") || "/";
    var parts = clean.split("/").filter(Boolean);
    var locale = "en";
    if (parts.length > 0 && SUPPORTED_LOCALES.indexOf(parts[0]) !== -1) {
      locale = parts.shift();
    }
    if (parts.length === 0) {
      return { screen: "SCR-HOME-01", locale: locale, course_id: null, topic_slug: null, canonical_path: "/" };
    }
    if (parts[0] === "courses" && parts.length >= 3) {
      var cid = parts[1];
      var slug = parts[2];
      return {
        screen: "SCR-LES-01",
        locale: locale,
        course_id: cid,
        topic_slug: slug,
        canonical_path: "/courses/" + cid + "/" + slug + "/"
      };
    }
    if (parts[0] === "404.html" || document.querySelector(".zn-404")) {
      return { screen: "SCR-404-01", locale: "en", course_id: null, topic_slug: null, canonical_path: "/404.html" };
    }
    return { screen: "SCR-404-01", locale: locale, course_id: null, topic_slug: null, canonical_path: clean };
  }

  function buildLocalizedHref(canonicalPath, targetLocale) {
    var norm = String(canonicalPath || "/");
    if (norm.charAt(0) !== "/") norm = "/" + norm;
    norm = norm.replace(/^\/(en|hi|hi-Latn|hinglish|[a-z]{2}-IN)(?=\/|$)/, "") || "/";
    var loc = String(targetLocale || "en");
    if (loc === "hinglish") loc = "hi-Latn";
    if (!loc || loc === "en" || SUPPORTED_LOCALES.indexOf(loc) === -1) {
      return norm;
    }
    return "/" + loc + (norm === "/" ? "/" : norm);
  }

  var ZivonRouter = {
    SUPPORTED_LOCALES: SUPPORTED_LOCALES,
    V1_UI_LOCALES: V1_UI_LOCALES,
    parseRoute: parseRoute,
    currentRoute: function () { return parseRoute(window.location ? window.location.pathname : "/"); },
    buildLocalizedHref: buildLocalizedHref
  };
  window.ZivonRouter = ZivonRouter;

  /* ---------------------------- 1. quizzes ------------------------------- */
  function firstNumber(text) {
    var m = /-?\d+(?:\.\d+)?/.exec(String(text));
    return m ? parseFloat(m[0]) : null;
  }

  var lastCheckState = null;

  function wireCheck(fieldset) {
    var format = fieldset.getAttribute("data-format");
    var button = fieldset.querySelector(".zn-check-btn");
    var feedback = fieldset.querySelector(".zn-check-feedback");
    if (!button || !feedback) return;
    var attempts = 0;
    var blockId = fieldset.id || fieldset.getAttribute("data-block-id") || "check";

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
        var numInput = fieldset.querySelector(".zn-numeric-input");
        var expectedNum = firstNumber(fieldset.getAttribute("data-answer"));
        var got = numInput ? firstNumber(numInput.value) : null;
        correct = expectedNum !== null && got !== null &&
          Math.abs(got - expectedNum) <= Math.max(0.01, Math.abs(expectedNum) * 0.01);
      }
      attempts += 1;
      fieldset.setAttribute("data-attempts", String(attempts));
      fieldset.setAttribute("data-check-state", correct ? "answered-correct" : "answered-wrong");
      lastCheckState = { block_id: blockId, format: String(format || "mcq"), correct: Boolean(correct), attempts: attempts };
      // \u-escaped: charset-proof no matter how the embedding page loads this file
      feedback.textContent = correct ? "\u2713 Correct." : "\u2717 Not yet - try again.";
      feedback.className = correct ? "zn-check-feedback correct" : "zn-check-feedback wrong";
      if (window.ZivonEvents && typeof window.ZivonEvents. recordCheck === "function") {
        window.ZivonEvents.recordCheck(blockId, String(format || "mcq"), Boolean(correct), attempts);
      }
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
    var initialValues = {};
    var mirror = container.querySelector(".zn-sim-read");
    container.querySelectorAll("[data-control]").forEach(function (input) {
      var key = input.getAttribute("data-control");
      var initVal = parseFloat(input.value);
      values[key] = initVal;
      initialValues[key] = initVal;
      var output = input.parentElement ? input.parentElement.querySelector("output") : null;
      input.addEventListener("input", function () {
        values[key] = parseFloat(input.value);
        if (output) output.textContent = input.value;
        updateFallbackMirror();
        if (reduceMotion) {
          try {
            impl.draw(ctx);
            updateFallbackMirror();
          } catch (err) {
            paintError(ctx.g, ctx.width, ctx.height, String(err), container, id);
          }
        }
        if (window.ZivonEvents && typeof window.ZivonEvents.recordSimControl === "function") {
          window.ZivonEvents.recordSimControl(id, key, values[key], input);
        }
      });
    });

    function formatMirrorSummary() {
      var keys = Object.keys(values);
      if (!keys.length) {
        var desc = container.querySelector(".zn-sim-desc");
        return desc && desc.textContent ? desc.textContent.trim() : "Simulation running.";
      }
      return keys.map(function (k) { return k + " = " + values[k]; }).join(", ");
    }

    function updateFallbackMirror() {
      if (!mirror) return;
      if (!mirror.textContent || !mirror.textContent.trim() || mirror.getAttribute("data-auto-mirror") === "true") {
        mirror.setAttribute("data-auto-mirror", "true");
        mirror.textContent = formatMirrorSummary();
      }
    }

    var resetBtn = container.querySelector(".zn-sim-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        container.querySelectorAll("[data-control]").forEach(function (input) {
          var key = input.getAttribute("data-control");
          if (Object.prototype.hasOwnProperty.call(initialValues, key)) {
            input.value = String(initialValues[key]);
            values[key] = initialValues[key];
            var out = input.parentElement ? input.parentElement.querySelector("output") : null;
            if (out) out.textContent = String(initialValues[key]);
          }
        });
        updateFallbackMirror();
        if (reduceMotion) {
          try { impl.draw(ctx); } catch (err) { paintError(ctx.g, ctx.width, ctx.height, String(err), container, id); }
        }
      });
    }

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
      paintError(ctx.g, ctx.width, ctx.height, String(err), container, id);
      return;
    }

    if (reduceMotion) {
      container.setAttribute("data-sim-state", "reduced-motion");
      try {
        impl.draw(ctx);
        updateFallbackMirror();
      } catch (err) {
        paintError(ctx.g, ctx.width, ctx.height, String(err), container, id);
      }
      return;
    }
    container.setAttribute("data-sim-state", "running");
    var t0 = performance.now();
    (function frame(now) {
      ctx.t = (now - t0) / 1000;
      try {
        impl.draw(ctx);
        updateFallbackMirror();
      } catch (err) {
        paintError(ctx.g, ctx.width, ctx.height, String(err), container, id);
        return;
      }
      requestAnimationFrame(frame);
    })(t0);
  }

  function paintError(g, w, h, message, container, simId) {
    if (g) {
      g.save();
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = "#EFE6B8";
      g.fillRect(0, 0, w, h);
      g.fillStyle = "#B3261E";
      g.font = "bold 14px monospace";
      g.fillText("simulation error:", 12, 24);
      wrapText(g, message, 12, 44, w - 24, 16, h);
      g.restore();
    }
    if (container) {
      container.setAttribute("data-sim-state", "error");
      var mirror = container.querySelector(".zn-sim-read");
      if (mirror) {
        mirror.textContent = "simulation error: " + message;
      }
    }
    if (window.console && console.error) console.error("ZivonSim:", message);
    if (window.ZivonEvents && typeof window.ZivonEvents.recordSimError === "function") {
      window.ZivonEvents.recordSimError(simId || "sim", message);
    }
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

  /* --------------------- 3. landing page course list ----------------------
     Renders the same cards as before, grouped by class with a jump-nav.
     The legacy <ul id="zn-courses"> is kept as a list of bare links for
     screen readers and as the no-JS fallback: JS moves the full cards into
     class sections and hides the list. */
  function renderCard(course, reveal) {
    var li = document.createElement("li");
    var a = document.createElement("a");
    a.className = "zn-card";
    a.href = course.href;
    a.setAttribute("data-element-id", "EL-HOME-01-006");
    a.setAttribute("data-course-id", String(course.course_id || ""));
    var title = document.createElement("p");
    title.className = "zn-card-title";
    title.textContent = course.title;
    var chapter = document.createElement("p");
    chapter.className = "zn-card-chapter";
    chapter.textContent = "Chapter: " + course.chapter;
    var meta = document.createElement("p");
    meta.className = "zn-card-meta";
    meta.textContent = course.course_id + " - generated " + course.generated_at;
    [title, chapter, meta].forEach(function (el) { a.appendChild(el); });
    li.appendChild(a);
    return li;
  }

  function renderCourses() {
    var list = document.getElementById("zn-courses");
    var empty = document.getElementById("zn-empty");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!Array.isArray(window.ZIVON_COURSES)) {
      if (window.console && console.error) {
        console.error("ZivonCourses: window.ZIVON_COURSES is missing or invalid");
      }
      if (empty) empty.hidden = false;
      return;
    }
    var byClass = {}, seenOrder = [];
    window.ZIVON_COURSES.forEach(function (course) {
      var cls = (course.class === undefined || course.class === null || course.class === "")
        ? "Other" : String(course.class);
      if (!byClass[cls]) { byClass[cls] = []; seenOrder.push(cls); }
      byClass[cls].push(course);
    });
    /* Numeric classes ascending; anything non-numeric (unclassified) last. */
    var classes = seenOrder.sort(function (a, b) {
      var na = Number(a), nb = Number(b);
      if (isNaN(na) && isNaN(nb)) return 0;
      if (isNaN(na)) return 1;
      if (isNaN(nb)) return -1;
      return na - nb;
    });
    classes.forEach(function (cls) {
      byClass[cls].forEach(function (course) {
        list.appendChild(renderCard(course));
      });
    });
    var sectionsHost = document.getElementById("zn-class-sections");
    var navLinks = document.getElementById("zn-grade-nav-links");
    if (!sectionsHost) return;
    var catalogue = document.getElementById("zn-catalogue");
    if (catalogue) catalogue.hidden = false;
    if (list) list.setAttribute("hidden", "");
    var nav = document.getElementById("zn-grade-nav");
    if (classes.length < 2 && nav) nav.setAttribute("hidden", "");
    classes.forEach(function (cls) {
      var section = document.createElement("section");
      section.className = "zn-class-section";
      section.setAttribute("aria-labelledby", "zn-class-" + cls);
      var heading = document.createElement("h2");
      heading.className = "zn-class-title";
      heading.id = "zn-class-" + cls;
      heading.textContent = cls === "Other" ? "Other topics" : "Class " + cls;
      var ul = document.createElement("ul");
      ul.className = "zn-courses";
      byClass[cls].forEach(function (course) { ul.appendChild(renderCard(course)); });
      section.appendChild(heading);
      section.appendChild(ul);
      sectionsHost.appendChild(section);
      if (navLinks) {
        var jump = document.createElement("a");
        jump.className = "zn-grade-link";
        jump.href = "#zn-class-" + cls;
        jump.textContent = cls === "Other" ? "Other" : "Class " + cls;
        navLinks.appendChild(jump);
      }
    });
  }

  function wireOfflineChip() {
    var chip = document.getElementById("zn-offline-chip");
    if (!chip) return;
    function syncOffline() {
      var isOffline = typeof navigator !== "undefined" && navigator.onLine === false;
      chip.hidden = !isOffline;
    }
    window.addEventListener("online", syncOffline);
    window.addEventListener("offline", syncOffline);
    syncOffline();
  }

  /* ---------------------- 4. LESSON KIT (LessonKit) -----------------------
     Merged 2026-11-05 from the founder's lesson-kit.js (the doctrine's
     rebuilt example runs this same code inline). THE ONE IDEA: never
     calculate where a ruled line should be. READ where the browser actually
     put the text, and draw the rule there.
       rule position  =  measured baseline of a real text line      (anchors)
       gaps           =  the distance between two neighbouring anchors cut
                         into equal steps (a whole number of rows)
       above / below  =  continue at one row pitch from the first / last anchor
     Because every rule is derived from the text itself on every layout pass,
     nothing can drift. Page contract (CSS): --row = the nominal line pitch,
     --rule = rule colour. The paper element is full width; opaque cards on
     top of it hide the rules (their text is skipped as anchors).
     Only change vs the founder's file: the pen path is built with
     createElementNS/setAttribute instead of innerHTML (same output, no HTML
     sink - keeps CodeQL clean). */
  const NS = "http://www.w3.org/2000/svg";
  const qa = (s, r = document) => [...r.querySelectorAll(s)];
  const raf = (() => {
    let q = new Set(), t = 0;
    return (fn) => {
      q.add(fn);
      t ||= requestAnimationFrame(() => { t = 0; const f = [...q]; q.clear(); f.forEach((g) => g()); });
    };
  })();

  /* ---------- measuring primitives (the browser does the maths) ---------- */
  const ascents = new Map();
  function ascentOf(cs) {
    const key = [cs.fontStyle, cs.fontWeight, cs.fontSize, cs.fontFamily, cs.fontStretch].join("|");
    if (ascents.has(key)) return ascents.get(key);
    const s = document.createElement("span"), m = document.createElement("span");
    s.style.cssText = "position:absolute;left:0;top:0;visibility:hidden;white-space:nowrap;line-height:normal";
    Object.assign(s.style, { fontStyle: cs.fontStyle, fontWeight: cs.fontWeight, fontSize: cs.fontSize, fontFamily: cs.fontFamily, fontStretch: cs.fontStretch });
    m.style.cssText = "display:inline-block;width:0;height:0";
    s.textContent = "Hx"; s.append(m); document.body.append(s);
    const r = document.createRange(); r.selectNodeContents(s.firstChild);
    const a = m.getBoundingClientRect().bottom - r.getBoundingClientRect().top;
    s.remove(); ascents.set(key, a); return a;
  }
  /* y (viewport) of the baseline of every rendered line of text under `scope` */
  function textBaselines(scope, skip) {
    const out = [], w = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT), r = document.createRange();
    for (let n; (n = w.nextNode());) {
      if (!n.nodeValue.trim()) continue;
      const el = n.parentElement;
      if (el.closest(skip)) continue;
      const cs = getComputedStyle(el); if (cs.visibility === "hidden") continue;
      const up = ascentOf(cs); r.selectNodeContents(n);
      for (const rc of r.getClientRects()) if (rc.width > 0) out.push(rc.top + up);
    }
    return out.sort((a, b) => a - b);
  }
  /* merge baselines that belong to the same visual line (mixed fonts/inline boxes) */
  function mergeLines(ys, row) {
    const out = [];
    for (const y of ys) {
      const l = out[out.length - 1];
      if (l && y - l.sum / l.n < row * 0.4) { l.sum += y; l.n++; } else out.push({ sum: y, n: 1 });
    }
    return out.map((l) => l.sum / l.n);
  }
  /* a CSS length (var / rem / calc) -> px, resolved by the browser */
  function px(host, css) {
    const p = document.createElement("div");
    p.style.cssText = `position:absolute;visibility:hidden;height:${css}`;
    host.append(p); const h = p.getBoundingClientRect().height; p.remove(); return h;
  }

  /* ---------- baseline normalising: every font's baseline -> the same place inside its line ---------- */
  function lineOffset(textNode) {
    const b = document.createElement("span"), t = document.createElement("span");
    b.style.cssText = "display:inline-block;width:0;height:0;vertical-align:baseline";
    t.style.cssText = "display:inline-block;width:0;height:0;vertical-align:top";
    textNode.before(t, b);
    const d = b.getBoundingClientRect().bottom - t.getBoundingClientRect().top;
    t.remove(); b.remove(); return d;
  }
  const shifts = new WeakMap();
  const fold = (d, row) => { d = ((d % row) + row) % row; return d > row / 2 ? d - row : d; };
  const BLOCKISH = /^(block|list-item|inline-block|flow-root|table-cell)$/;
  function normalize(paper, ref, skip, row) {
    const refNode = textNodeOf(paper.querySelector(ref)); if (!refNode) return;
    const REF = lineOffset(refNode), seen = new Set(), w = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) {                      /* document order: ancestors before descendants */
      const el = n.parentElement;
      if (!n.nodeValue.trim() || seen.has(el) || el.closest(skip)) continue;
      seen.add(el);
      const cs = getComputedStyle(el); if (!BLOCKISH.test(cs.display) || cs.position === "absolute") continue;
      let anc = 0; for (let p = el.parentElement; p && p !== paper; p = p.parentElement) anc += shifts.get(p) || 0;
      const own = -fold(lineOffset(n) - REF, row), want = own - anc;     /* ancestors already moved us by `anc` */
      shifts.set(el, own);
      if (cs.position === "static") el.style.position = "relative";
      el.style.top = Math.abs(want) < 0.01 ? "" : want.toFixed(2) + "px";
    }
  }
  const textNodeOf = (el) => { if (!el) return null; for (const c of el.childNodes) if (c.nodeType === 3 && c.nodeValue.trim()) return c; return null; };

  /* ---------- tool 1: ruled paper ---------- */
  function ruledPaper(o) {
    const paper = document.querySelector(o.paper); if (!paper) return { refresh() {} };
    Object.assign(paper.style, { position: "relative", isolation: "isolate" });   /* rules sit behind content, above the paper colour */
    const svg = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
    svg.setAttribute("aria-hidden", "true"); svg.classList.add("rules");
    svg.style.cssText = "position:absolute;left:0;top:0;width:100%;z-index:-1;pointer-events:none;overflow:visible";
    path.style.fill = "var(--rule)"; svg.append(path); paper.prepend(svg);
    const skip = o.skip || "script,style,svg,button,sup,sub,.card,[data-ruled-skip]";   /* no rules behind opaque cards */
    const skipShift = "script,style,svg,button,sup,sub,[data-ruled-skip]";

    function draw() {
      o.beforeDraw && o.beforeDraw();
      const row = px(paper, "var(--row)");
      normalize(paper, o.ref || "p", skipShift, row);
      const pr = paper.getBoundingClientRect(), W = pr.width;
      /* The rules svg feeds back into scrollHeight: measuring WITH it
         locks in whatever height the previous draw set (on a slower load
         that can be the pre-font-metrics height), leaving an endless
         empty ruled scroll tail under the content. Measure the real
         content height underneath it. */
      svg.style.display = "none";
      const H = paper.scrollHeight;
      svg.style.display = "";
      const dpr = devicePixelRatio || 1, snap = (y) => Math.round(y * dpr) / dpr, th = o.thickness || 2;
      const a = mergeLines(textBaselines(paper, skip), row).map((y) => y - pr.top);
      const ys = [];
      if (a.length) {
        for (let y = a[0]; y >= 0; y -= row) ys.push(y);                          /* above the first line  */
        for (let i = 0; i < a.length - 1; i++) {                                  /* between two real lines */
          const n = Math.max(1, Math.round((a[i + 1] - a[i]) / row)), step = (a[i + 1] - a[i]) / n;
          for (let k = 1; k <= n; k++) ys.push(a[i] + k * step);                  /* ends exactly on the next line */
        }
        for (let y = a[a.length - 1] + row; y < H; y += row) ys.push(y);          /* below the last line   */
      }
      svg.setAttribute("height", H); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      path.setAttribute("d", ys.map((y) => { y = snap(y); return `M0 ${y}H${W}V${y + th}H0Z`; }).join(""));
      mo.takeRecords();                                                           /* ignore our own DOM writes */
    }
    const refresh = () => raf(draw);
    const mo = new MutationObserver(refresh);
    mo.observe(paper, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["open", "hidden", "class", "aria-checked"] });
    new ResizeObserver(refresh).observe(paper);
    document.addEventListener("toggle", refresh, true);                           /* <details> open/close */
    document.fonts && (document.fonts.ready.then(refresh), document.fonts.addEventListener("loadingdone", refresh));
    refresh(); return { refresh, row: () => px(paper, "var(--row)") };
  }

  /* ---------- tool 2: pen underline for key statements ---------- */
  const seedFrom = (s) => { let h = 2166136261 >>> 0; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const rng = (a) => () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  function pen(el) {
    qa(".uline", el).forEach((n) => n.remove());
    const rg = document.createRange(), fs = parseFloat(getComputedStyle(el).fontSize);
    rg.selectNodeContents(el);
    const last = [...rg.getClientRects()].pop(); if (!last) return;
    const m = document.createElement("span"); m.style.cssText = "display:inline-block;width:0;height:0"; el.append(m);
    const baseline = m.getBoundingClientRect().bottom; m.remove();
    const box = el.getBoundingClientRect(), yo = baseline + 0.3 * fs - box.bottom;     /* .3em under the LAST line */
    const len = last.width + 0.27 * fs, x0 = -0.09 * fs, n = Math.max(4, Math.round(len / (0.45 * fs))), R = rng(seedFrom(el.textContent.trim())), top = [], bot = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, y = yo + 0.02 * fs * Math.sin((2 * Math.PI * (len * t)) / (4 * fs) + 0.7) + (R() * 2 - 1) * 0.007 * fs, h = ((0.067 - 0.034 * t) * fs) / 2;
      top.push([x0 + len * t, y - h]); bot.push([x0 + len * t, y + h]);
    }
    const d = top.concat(bot.reverse()).map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ") + "Z";
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("class", "uline"); s.setAttribute("aria-hidden", "true"); s.setAttribute("overflow", "visible");
    s.setAttribute("width", Math.ceil(last.width)); s.setAttribute("height", Math.ceil(fs)); s.style.left = (last.left - box.left) + "px";
    const path = document.createElementNS(NS, "path");                                 /* no innerHTML: same d, no HTML sink */
    path.setAttribute("d", d); path.setAttribute("fill", "#1F3A9E");
    s.append(path); el.append(s);
  }
  function penUnderlines(sel) {
    const ro = new ResizeObserver((es) => es.forEach((e) => pen(e.target)));            /* re-wrap -> redraw */
    const go = () => qa(sel).forEach((el) => { pen(el); ro.observe(el); });
    document.fonts ? document.fonts.ready.then(go) : go();
    document.fonts && document.fonts.addEventListener("loadingdone", () => qa(sel).forEach(pen));
  }

  window.LessonKit = {
    init(o = {}) { const r = ruledPaper({ paper: ".zn-page:not(.zn-home)", ...o }); o.pen !== false && penUnderlines(o.pen || "h1.zn-title"); return r; },
    ruledPaper, pen, px, textBaselines
  };

  /* --------------- 5. language bar chips (visual toggle only) ---------------
     Doctrine §10.5 / example contract: one control switches every string on
     the page; switching CONTENT is shell-owned and lands with i18n-aware
     pages. Until then the kit chrome toggles the selected chip and the
     document lang (visual honesty - the example demonstrates this). */
  function wireLangChips() {
    var row = document.querySelector(".zn-lang-row");
    if (!row) return;
    row.addEventListener("click", function (event) {
      var chip = event.target.closest(".zn-chip");
      if (!chip) return;
      row.querySelectorAll(".zn-chip").forEach(function (c) {
        c.setAttribute("aria-checked", String(c === chip));
      });
    });
  }


  /* --------------- 6. lesson page state & context snapshot ----------------
     Implements:
     - Reserved voice dock mount region (.R9, EL-LES-01-090, spec.md §7 / C5)
       with a lazy loader stub that loads nothing until doctrine §10.12 lands
       (DCR-002 standing guard).
     - Structured <= 4 KB page context snapshot (ADR-0014 / SP1 context.snapshot).
     - Tutor block highlight handler (ADR-0012 / EL-LES-01-056).
     - State matrix inspection & dev override helper (state-matrix.md). */
  function ensureVoiceDockRegion() {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return null;
    var existing = lessonPage.querySelector('[data-element-id="EL-LES-01-090"], .zn-voice-dock-region');
    if (existing) return existing;
    var region = document.createElement("aside");
    region.className = "zn-voice-dock-region";
    region.setAttribute("data-region", "SCR-LES-01.R9");
    region.setAttribute("data-element-id", "EL-LES-01-090");
    region.setAttribute("aria-label", "Voice tutor dock");
    region.hidden = true;
    lessonPage.appendChild(region);
    return region;
  }

  var ZivonVoiceDock = {
    doctrineReady: false, /* DCR-002: design-doctrine.md §10.12 is founder-gated */
    getRegion: ensureVoiceDockRegion,
    lazyMount: function () {
      var region = ensureVoiceDockRegion();
      if (!ZivonVoiceDock.doctrineReady) {
        return { mounted: false, reason: "founder-gated: design-doctrine.md §10.12 absent (DCR-002)" };
      }
      return { mounted: Boolean(region), region: region };
    }
  };
  window.ZivonVoiceDock = ZivonVoiceDock;

  function buildContextSnapshot(explicitBlockId) {
    var route = ZivonRouter.currentRoute();
    var kicker = document.querySelector(".zn-kicker");
    var titleEl = document.querySelector("h1.zn-title");
    var checkedChip = document.querySelector('.zn-lang-row .zn-chip[aria-checked="true"]');
    var langPref = checkedChip ? (checkedChip.getAttribute("data-lang") || checkedChip.textContent.trim()) : (document.documentElement.lang || "en");
    var visibleBlocks = [];
    document.querySelectorAll(".zn-page [id]").forEach(function (el) {
      if (visibleBlocks.length >= 12) return;
      var tag = el.className || el.tagName.toLowerCase();
      var bType = "text";
      if (tag.indexOf("zn-sim") !== -1) bType = "simulation";
      else if (tag.indexOf("zn-check") !== -1) bType = "check";
      else if (tag.indexOf("zn-diagram") !== -1) bType = "diagram";
      else if (tag.indexOf("zn-example") !== -1) bType = "worked_example";
      else if (tag.indexOf("zn-reveal") !== -1) bType = "reveal";
      var h = el.querySelector("h3, legend, figcaption");
      visibleBlocks.push({
        id: el.id,
        type: bType,
        title: h ? h.textContent.trim().slice(0, 80) : el.id
      });
    });

    var simStates = [];
    document.querySelectorAll(".zn-sim[data-sim-id]").forEach(function (simEl) {
      var sid = simEl.getAttribute("data-sim-id");
      var controls = {};
      simEl.querySelectorAll("[data-control]").forEach(function (inp) {
        controls[inp.getAttribute("data-control")] = parseFloat(inp.value);
      });
      var mirror = simEl.querySelector(".zn-sim-read");
      simStates.push({
        block_id: sid,
        controls: controls,
        state_text: mirror ? mirror.textContent.trim().slice(0, 160) : ""
      });
    });

    var docEl = document.documentElement;
    var maxScroll = Math.max(1, (docEl.scrollHeight || 1) - (window.innerHeight || 1));
    var scrollPct = Math.min(100, Math.max(0, Math.round(((window.scrollY || 0) / maxScroll) * 100)));
    var activeBlock = explicitBlockId || (visibleBlocks[0] ? visibleBlocks[0].id : "page");
    var firstSim = simStates[0] || null;

    var snap = {
      topic_id: route.topic_slug || (titleEl ? titleEl.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-") : "topic"),
      course_id: route.course_id || (kicker ? kicker.textContent.trim() : "physics"),
      class: parseInt(String(route.course_id || "9").replace(/\D+/g, ""), 10) || 9,
      chapter: titleEl ? titleEl.textContent.trim().slice(0, 120) : "",
      block_id: activeBlock,
      block_type: firstSim && activeBlock === firstSim.block_id ? "simulation" : "text",
      sim_id: firstSim ? firstSim.block_id : null,
      sim_vars: firstSim ? firstSim.controls : {},
      visible_blocks: visibleBlocks,
      sim_states: simStates,
      last_check: lastCheckState,
      scroll_pct: scrollPct,
      lang_pref: langPref,
      ts: Date.now()
    };

    var json = JSON.stringify(snap);
    if (json.length > 4096) {
      snap.visible_blocks = snap.visible_blocks.slice(0, 4);
      snap.sim_states = snap.sim_states.slice(0, 2);
    }
    return snap;
  }

  function highlightBlocks(blockIds) {
    document.querySelectorAll(".zn-tutor-highlight").forEach(function (el) {
      el.classList.remove("zn-tutor-highlight");
    });
    if (!Array.isArray(blockIds)) return;
    blockIds.forEach(function (bid) {
      var target = document.getElementById(String(bid));
      if (target) target.classList.add("zn-tutor-highlight");
    });
  }

  function applyLessonStateBanner(kind, copyText) {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return null;
    var id = "zn-lesson-status-" + kind;
    var existing = document.getElementById(id);
    if (!copyText) {
      if (existing) existing.hidden = true;
      return existing;
    }
    if (!existing) {
      existing = document.createElement("p");
      existing.id = id;
      existing.className = "zn-status-chip" + (kind === "warn" || kind === "exhausted" ? " zn-status-" + kind : "");
      existing.setAttribute("role", "status");
      existing.setAttribute("aria-live", "polite");
      if (kind === "offline") existing.setAttribute("data-element-id", "EL-LES-01-070");
      if (kind === "warn") existing.setAttribute("data-element-id", "EL-LES-01-071");
      if (kind === "exhausted") existing.setAttribute("data-element-id", "EL-LES-01-072");
      var header = lessonPage.querySelector(".zn-header");
      if (header && header.nextSibling) {
        lessonPage.insertBefore(existing, header.nextSibling);
      } else {
        lessonPage.prepend(existing);
      }
    }
    existing.textContent = copyText;
    existing.hidden = false;
    return existing;
  }

  var ZivonStateMatrix = {
    CANONICAL_STATES: [
      "default", "loading", "empty", "partial", "error",
      "offline", "permission-denied", "reduced-motion",
      "untranslated", "over-credit-budget"
    ],
    buildContextSnapshot: buildContextSnapshot,
    highlightBlocks: highlightBlocks,
    applyState: function (stateName) {
      var s = String(stateName || "default");
      document.documentElement.setAttribute("data-zivon-state", s);
      if (s === "empty" && document.getElementById("zn-courses")) {
        window.ZIVON_COURSES = [];
        renderCourses();
      } else if (s === "offline") {
        var homeChip = document.getElementById("zn-offline-chip");
        if (homeChip) homeChip.hidden = false;
        applyLessonStateBanner("offline", "Offline - lesson content and simulations work without a connection.");
      } else if (s === "over-credit-budget") {
        applyLessonStateBanner("exhausted", "Voice is resting (daily limit). Type your doubt.");
      } else if (s === "untranslated") {
        document.querySelectorAll(".zn-text, .zn-example").forEach(function (blk) {
          if (!blk.querySelector(".zn-untranslated-notice")) {
            var n = document.createElement("p");
            n.className = "zn-untranslated-notice";
            n.setAttribute("data-copy-key", "lesson.untranslated.notice");
            n.textContent = "Not translated yet - showing reviewed English text.";
            blk.prepend(n);
          }
        });
      }
      return s;
    }
  };
  window.ZivonStateMatrix = ZivonStateMatrix;

  /* ------------------------------- boot ----------------------------------
     LessonKit.init covers load, font swap, resize, card open/close and quiz
     feedback changes through its own observers - no manual re-fit listeners.
     On the landing page the paper selector misses, so ruled drawing no-ops
     (§10 scope guard) while the title pen underline still applies. */
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".zn-check").forEach(wireCheck);
    wireLangChips();
    renderCourses();
    wireOfflineChip();
    ensureVoiceDockRegion();
    /* Doctrine §10.7 (v1.4): read each model diagram's viewBox and hand its
       height/width ratio to CSS (--dia-ar) so the diagram box shrinks to the
       drawing's own aspect, rounded up to whole rows on narrow screens.
       CSSOM, never a markup style attribute: the pages' strict CSP
       (style-src 'self') rejects inline style attributes but allows styles
       applied by this shell script. */
    document.querySelectorAll(".zn-diagram-svg").forEach(function (box) {
      var svg = box.querySelector("svg");
      var vb = svg ? svg.getAttribute("viewBox") : null;
      if (!vb) return;
      var p = vb.trim().split(/[\s,]+/);
      var w = parseFloat(p[2]);
      var h = parseFloat(p[3]);
      if (w > 0 && h > 0) box.style.setProperty("--dia-ar", (h / w).toFixed(4));
    });
    window.LessonKit.init({
      paper: ".zn-page:not(.zn-home)",
      pen: "h1.zn-title",
      skip: "script,style,svg,button,sup,sub,.zn-reveal,.zn-sim,.zn-check,[data-ruled-skip]"
    });
  });
})();
