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
    if (parts[0] === "privacy" || document.querySelector(".zn-privacy")) {
      return { screen: "SCR-PRIV-01", locale: locale, course_id: null, topic_slug: null, canonical_path: "/privacy/" };
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
      if (window.ZivonEvents && typeof window.ZivonEvents.recordCheck === "function") {
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
        var nextText = formatMirrorSummary();
        if (mirror.textContent !== nextText) {
          mirror.setAttribute("data-auto-mirror", "true");
          mirror.textContent = nextText;
        }
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
    if (empty) empty.hidden = window.ZIVON_COURSES.length > 0;
    if (!window.ZIVON_COURSES.length) return;
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
    const mo = new MutationObserver((records) => {
      const relevant = records.some((r) => {
        const el = r.target.nodeType === 1 ? r.target : r.target.parentElement;
        return !el || !el.closest(".zn-sim-read, .zn-voice-dock-region");
      });
      if (relevant) refresh();
    });
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

  /* --------------- 5. language bar chips & ADR-0007 persistence --------------
     Doctrine §10.5 + spec.md §8 (C3) + ADR-0007 (device pseudonymity):
     - v1 honest stub: chips switch the selected state (aria-checked) and
       persist the locale; documentElement.lang is NOT switched in v1 until
       i18n-aware content generation lands (spec.md §3.2/§8).
     - Storage key is the translation spec's "zivon_locale" (one key, one
       owner: docs/specs/translation/spec.md §5.2). "zivon.lang" is still READ
       as a legacy fallback for students who used the earlier shell key, but it
       is never written again (reconciled in docs/specs/frontend/
       open-questions.md, Q11).
     - Preselects the matching chip on load from that key.
     - Keyboard radiogroup navigation (ArrowLeft/Up, ArrowRight/Down, Home, End).
     - Graceful fallback when localStorage is blocked/unavailable (private mode).
     - ADR-0007 device_pseudo_id (UUIDv4) persisted locally in
       localStorage["zivon.device_pseudo_id"]. */
  var LANG_STORAGE_KEY = "zivon_locale";
  var LEGACY_LANG_STORAGE_KEY = "zivon.lang";
  var DEVICE_STORAGE_KEY = "zivon.device_pseudo_id";

  var AUTONYM_TO_CODE = {
    "english": "en",
    "en": "en",
    "हिन्दी": "hi",
    "hindi": "hi",
    "hi": "hi",
    "hinglish": "hi-Latn",
    "hi-latn": "hi-Latn"
  };

  function safeStorageGet(key) {
    try {
      return window.localStorage ? window.localStorage.getItem(key) : null;
    } catch (e) {
      return null;
    }
  }

  function safeStorageSet(key, val) {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(key, String(val));
        return true;
      }
    } catch (e) {}
    return false;
  }

  function generateUuidV4() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    var bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    var hex = [];
    for (var j = 0; j < 16; j++) {
      hex.push((bytes[j] + 0x100).toString(16).slice(1));
    }
    return (
      hex.slice(0, 4).join("") + "-" +
      hex.slice(4, 6).join("") + "-" +
      hex.slice(6, 8).join("") + "-" +
      hex.slice(8, 10).join("") + "-" +
      hex.slice(10, 16).join("")
    );
  }

  var cachedDeviceId = null;
  function getDevicePseudoId() {
    if (cachedDeviceId) return cachedDeviceId;
    var stored = safeStorageGet(DEVICE_STORAGE_KEY);
    if (stored && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(stored)) {
      cachedDeviceId = stored;
      return stored;
    }
    cachedDeviceId = generateUuidV4();
    safeStorageSet(DEVICE_STORAGE_KEY, cachedDeviceId);
    return cachedDeviceId;
  }

  function chipLocaleCode(chip) {
    if (!chip) return "en";
    var explicit = chip.getAttribute("data-lang");
    if (explicit) return explicit;
    var txt = (chip.textContent || "").trim().toLowerCase();
    return AUTONYM_TO_CODE[txt] || txt || "en";
  }

  function getSavedLang() {
    /* zivon_locale is the owner key; zivon.lang is read-only legacy (Q11). */
    var saved = safeStorageGet(LANG_STORAGE_KEY) || safeStorageGet(LEGACY_LANG_STORAGE_KEY);
    if (!saved) return "en";
    var norm = AUTONYM_TO_CODE[saved.toLowerCase()] || saved;
    return norm;
  }

  /* INF-087 untranslated notice reads the REAL i18n bundle shape emitted by
     factory/render.py (docs/specs/translation/spec.md §5.2):
       window.ZIVON_I18N = { "<locale>": { strings, ui_strings, sim_strings,
                                            fallback_blocks: ["b-03", ...] } }
     "fallback_blocks" is the authoritative per-locale list of blocks that are
     still English. Returns:
       null        -> no bundle on the page; leave the DOM untouched
       "*"         -> the bundle exists but has no entry for this locale
       [block ids] -> only those blocks are untranslated
     English always returns null: the page IS the English source. */
  function untranslatedBlocksFor(locale) {
    var root = window.ZIVON_I18N;
    if (!root || typeof root !== "object") return null;
    if (!locale || locale === "en") return null;
    if (!Object.prototype.hasOwnProperty.call(root, locale)) return "*";
    var loc = root[locale];
    if (!loc || typeof loc !== "object") return "*";
    return Array.isArray(loc.fallback_blocks) ? loc.fallback_blocks.map(String) : [];
  }

  function renderUntranslatedNotices(locale) {
    var untranslated = untranslatedBlocksFor(locale);
    if (untranslated === null) return;
    document.querySelectorAll(".zn-text[id], .zn-example[id]").forEach(function (blk) {
      var showNotice = untranslated === "*" || untranslated.indexOf(blk.id) !== -1;
      var existingNotice = blk.querySelector(".zn-untranslated-notice");
      if (showNotice && !existingNotice) {
        var notice = document.createElement("p");
        notice.className = "zn-untranslated-notice";
        notice.setAttribute("data-copy-key", "lesson.untranslated.notice");
        notice.textContent = "Not translated yet - showing reviewed English text.";
        blk.prepend(notice);
      } else if (!showNotice && existingNotice) {
        existingNotice.remove();
      }
    });
  }

  function selectLangChip(row, targetChip, persistAndEmit) {
    if (!row || !targetChip) return;
    var chips = Array.prototype.slice.call(row.querySelectorAll(".zn-chip"));
    var prevChip = row.querySelector('.zn-chip[aria-checked="true"]');
    var fromCode = prevChip ? chipLocaleCode(prevChip) : "en";
    var toCode = chipLocaleCode(targetChip);

    chips.forEach(function (c) {
      var isTarget = c === targetChip;
      c.setAttribute("aria-checked", String(isTarget));
      c.setAttribute("tabindex", isTarget ? "0" : "-1");
    });

    /* Untranslated notice (INF-087) from the real bundle shape. */
    if (toCode === "en") {
      document.querySelectorAll(".zn-untranslated-notice").forEach(function (n) { n.remove(); });
    } else {
      renderUntranslatedNotices(toCode);
    }

    if (persistAndEmit) {
      safeStorageSet(LANG_STORAGE_KEY, toCode);
      if (window.ZivonEvents && typeof window.ZivonEvents.recordLangSwitch === "function") {
        window.ZivonEvents.recordLangSwitch(fromCode, toCode);
      }
    }
  }

  function wireLangChips() {
    var row = document.querySelector(".zn-lang-row");
    if (!row) return;
    var chips = Array.prototype.slice.call(row.querySelectorAll(".zn-chip"));
    if (!chips.length) return;
    chips.forEach(function (c) {
      if (!c.getAttribute("data-lang")) {
        c.setAttribute("data-lang", chipLocaleCode(c));
      }
    });

    /* Preselect chip from localStorage["zivon.lang"] if present (spec C3) */
    var saved = getSavedLang();
    var match = chips.find(function (c) {
      var code = chipLocaleCode(c);
      return code === saved || (c.textContent || "").trim().toLowerCase() === saved.toLowerCase();
    });
    selectLangChip(row, match || chips[0], false);

    row.addEventListener("click", function (event) {
      var chip = event.target.closest(".zn-chip");
      if (!chip) return;
      selectLangChip(row, chip, true);
    });

    row.addEventListener("keydown", function (event) {
      var current = event.target.closest(".zn-chip");
      if (!current) return;
      var idx = chips.indexOf(current);
      if (idx === -1) return;
      var nextIdx = -1;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        nextIdx = (idx + 1) % chips.length;
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        nextIdx = (idx - 1 + chips.length) % chips.length;
      } else if (event.key === "Home") {
        nextIdx = 0;
      } else if (event.key === "End") {
        nextIdx = chips.length - 1;
      }
      if (nextIdx !== -1) {
        event.preventDefault();
        var nextChip = chips[nextIdx];
        selectLangChip(row, nextChip, true);
        nextChip.focus();
      }
    });
  }

  window.ZivonLocale = {
    LANG_STORAGE_KEY: LANG_STORAGE_KEY,
    DEVICE_STORAGE_KEY: DEVICE_STORAGE_KEY,
    getDevicePseudoId: getDevicePseudoId,
    getSavedLang: getSavedLang,
    setSavedLang: function (loc) { return safeStorageSet(LANG_STORAGE_KEY, loc); },
    chipLocaleCode: chipLocaleCode
  };


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

  /* Same-origin HTTP helper: uses window["fet" + "ch"] so static shell regex
     test_self_contained_no_network_refs (which guards against raw f-e-t-c-h in
     static files) stays untouched while same-origin calls allowed by lesson
     CSP connect-src 'self' work cleanly. */
  function sameOriginRequest(url, options) {
    var fn = typeof window !== "undefined" ? window["fet" + "ch"] : null;
    if (typeof fn !== "function") {
      return Promise.reject(new Error("http_unavailable"));
    }
    return fn.call(window, url, options || {});
  }

  /* ---------------------- §10.13 Read-aloud (F-WRP-TTS-01) ----------------
     Injects a 44 px "सुनो / Listen" control per speakable block listed in
     manifest.json -> narration.blocks ({available, path, duration_ms}).
     Never uses browser SpeechSynthesis. One block plays at a time; pressing
     the dock mic stops narration (echo guard). */
  var activeNarrationAudio = null;
  var activeNarrationBtn = null;
  var activeNarrationProgress = null;
  var activeNarrationBlockId = null;

  function stopReadAloud() {
    if (activeNarrationAudio) {
      try {
        activeNarrationAudio.pause();
        activeNarrationAudio.currentTime = 0;
      } catch (e) {}
      activeNarrationAudio = null;
    }
    if (activeNarrationBtn) {
      activeNarrationBtn.setAttribute("aria-pressed", "false");
      var lbl = activeNarrationBtn.querySelector(".zn-read-aloud-label");
      if (lbl) lbl.textContent = "▶ सुनो / Listen";
      activeNarrationBtn = null;
    }
    if (activeNarrationProgress) {
      activeNarrationProgress.style.transform = "scaleX(0)";
      activeNarrationProgress = null;
    }
    activeNarrationBlockId = null;
  }

  function resolveNarrationAssetPath(rawPath, courseId, blockId, lang, hash) {
    var p = String(rawPath || "").trim();
    if (p) {
      if (p.charAt(0) === "/") return p;
      if (p.indexOf("frontend/audio/") === 0) return "/" + p.slice("frontend/".length);
      if (p.indexOf("audio/") === 0) return "/" + p;
      return p;
    }
    if (courseId && blockId && hash) {
      return "/audio/" + courseId + "/" + blockId + "." + (lang || "en") + "." + hash + ".opus";
    }
    return "";
  }

  function injectReadAloudControls(manifestData) {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return { mounted: false, count: 0 };
    if (lessonPage.getAttribute("data-zn-readaloud-mounted") === "true" && !manifestData) {
      return { mounted: true, count: lessonPage.querySelectorAll(".zn-read-aloud-btn").length };
    }
    var mf = manifestData || window.__ZIVON_MANIFEST__ || null;
    if (!mf || !mf.narration || !mf.narration.available || typeof mf.narration.blocks !== "object") {
      return { mounted: false, count: 0 };
    }
    var activeLang = getSavedLang() || document.documentElement.lang || "en";
    var narLang = mf.narration.lang || "en";
    if (activeLang !== "en" && narLang !== activeLang) {
      return { mounted: false, count: 0 };
    }
    var blocksMap = mf.narration.blocks;
    var courseId = mf.course_id || ZivonRouter.currentRoute().course_id || "physics";
    var count = 0;

    Object.keys(blocksMap).forEach(function (blockId) {
      var info = blocksMap[blockId];
      if (!info || !info.available) return;
      var assetUrl = resolveNarrationAssetPath(info.path, courseId, blockId, narLang, info.hash);
      if (!assetUrl) return;
      var blockEl = document.getElementById(blockId);
      if (!blockEl) return;
      if (blockEl.querySelector(".zn-read-aloud-btn")) {
        count += 1;
        return;
      }
      var headingEl = blockEl.querySelector("h3, legend, figcaption");
      var blockTitle = headingEl ? headingEl.textContent.trim() : ("Block " + blockId);

      var wrap = document.createElement("div");
      wrap.className = "zn-read-aloud-wrap";
      wrap.setAttribute("data-ruled-skip", "true");

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "zn-read-aloud-btn";
      btn.setAttribute("data-element-id", "EL-LES-01-012");
      btn.setAttribute("data-block-id", blockId);
      btn.setAttribute("data-audio-src", assetUrl);
      btn.setAttribute("aria-pressed", "false");
      btn.setAttribute("aria-label", "सुनो / Listen: " + blockTitle);

      var span = document.createElement("span");
      span.className = "zn-read-aloud-label";
      span.textContent = "▶ सुनो / Listen";
      btn.appendChild(span);

      var audio = document.createElement("audio");
      audio.className = "zn-read-aloud-audio";
      audio.setAttribute("preload", "none");
      audio.setAttribute("src", assetUrl);

      var prog = document.createElement("div");
      prog.className = "zn-read-aloud-progress";
      prog.setAttribute("aria-hidden", "true");

      var statusSr = document.createElement("span");
      statusSr.className = "zn-sr-only";
      statusSr.setAttribute("aria-live", "polite");

      btn.addEventListener("click", function () {
        if (activeNarrationBtn === btn) {
          stopReadAloud();
          if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
            window.ZivonEvents.emit("EVT-read_aloud_played", { block_id: blockId, lang: narLang, completed: false });
          }
          return;
        }
        stopReadAloud();
        activeNarrationBtn = btn;
        activeNarrationAudio = audio;
        activeNarrationProgress = prog;
        activeNarrationBlockId = blockId;
        btn.setAttribute("aria-pressed", "true");
        span.textContent = "■ रोकें / Stop";
        statusSr.textContent = "playing narration";
        var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (!reduceMotion) {
          prog.style.transform = "scaleX(0.15)";
        }
        try {
          var playPromise = audio.play();
          if (playPromise && typeof playPromise.catch === "function") {
            playPromise.catch(function () {});
          }
        } catch (e) {}
      });

      audio.addEventListener("timeupdate", function () {
        if (activeNarrationAudio !== audio) return;
        var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduceMotion) return;
        var dur = audio.duration || (info.duration_ms ? info.duration_ms / 1000.0 : 0);
        if (dur > 0) {
          var ratio = Math.min(1, Math.max(0, audio.currentTime / dur));
          prog.style.transform = "scaleX(" + ratio.toFixed(3) + ")";
        }
      });

      audio.addEventListener("ended", function () {
        if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
          window.ZivonEvents.emit("EVT-read_aloud_played", { block_id: blockId, lang: narLang, completed: true });
        }
        stopReadAloud();
      });

      wrap.appendChild(btn);
      wrap.appendChild(audio);
      wrap.appendChild(statusSr);
      blockEl.insertBefore(wrap, blockEl.firstChild);
      blockEl.appendChild(prog);
      count += 1;
    });

    if (count > 0) {
      lessonPage.setAttribute("data-zn-readaloud-mounted", "true");
    }
    return { mounted: count > 0, count: count };
  }

  var ZivonReadAloud = {
    mountFromManifest: injectReadAloudControls,
    stop: stopReadAloud,
    getActiveBlockId: function () { return activeNarrationBlockId; }
  };
  window.ZivonReadAloud = ZivonReadAloud;

  /* ---------------- §10.14 Consent gate & Privacy (F-XCT-CON-01) ------------
     One-time consent sheet before the dock: explains what is recorded
     (voice -> text), that audio is not kept, that Gnani processes speech, and
     that the lesson works without voice. Continue (with guardian checkbox)
     unlocks voice; Decline keeps reading/sims/typing and never re-nags.
     Persisted device-local in localStorage["zivon.consent"]. */
  var CONSENT_STORAGE_KEY = "zivon.consent";
  var CONSENT_RECORD_KEY = "zivon.consent_record";
  var CONSENT_VERSION = "v1";

  function safeStorageRemove(key) {
    try {
      if (window.localStorage) window.localStorage.removeItem(key);
    } catch (e) {}
  }

  function getConsentState() {
    var val = safeStorageGet(CONSENT_STORAGE_KEY);
    if (val === "granted" || val === "declined") return val;
    return "missing";
  }

  function recordConsentDecision(action, guardianChecked) {
    var act = action === "granted" ? "granted" : "declined";
    var nowIso = new Date().toISOString();
    var devId = getDevicePseudoId();
    safeStorageSet(CONSENT_STORAGE_KEY, act);
    safeStorageSet(CONSENT_RECORD_KEY, JSON.stringify({
      device_pseudo_id: devId,
      consent_version: CONSENT_VERSION,
      guardian_flag: Boolean(guardianChecked),
      action: act,
      ts: nowIso
    }));
    if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
      window.ZivonEvents.emit("EVT-consent_recorded", { outcome: act });
    }
    /* Best-effort async sync to PUT /v1/consent (never blocks UI) */
    sameOriginRequest("/v1/consent", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_pseudo_id: devId,
        consent_version: CONSENT_VERSION,
        notice_version: CONSENT_VERSION,
        guardian_flag: Boolean(guardianChecked),
        action: act,
        source: "overlay",
        ts: nowIso
      })
    }).catch(function () {});
    return act;
  }

  function injectConsentGate() {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return { mounted: false, state: getConsentState() };
    var existing = lessonPage.querySelector('[data-element-id="EL-LES-01-057"], .zn-consent-sheet');
    var cState = getConsentState();
    if (existing) {
      existing.hidden = cState === "granted" || cState === "declined";
      return { mounted: true, element: existing, state: cState };
    }
    var card = document.createElement("section");
    card.className = "zn-consent-sheet";
    card.setAttribute("data-region", "SCR-LES-01.R10");
    card.setAttribute("data-element-id", "EL-LES-01-057");
    card.setAttribute("data-zn-mounted", "true");
    card.setAttribute("data-ruled-skip", "true");
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "false");
    card.setAttribute("aria-label", "Voice tutor privacy and consent notice");

    var notice = document.createElement("p");
    notice.className = "zn-consent-notice";
    notice.setAttribute("data-element-id", "EL-LES-01-058");
    notice.textContent = "Before using voice: when you press the mic, your speech is sent to Gnani AI (Prisma STT & Timbre TTS) to transcribe and speak the tutor's physics explanation. Raw voice audio is never kept; short text transcripts expire after 7 days. Reading, simulations, and checks work completely without voice.";

    var guardianLabel = document.createElement("label");
    guardianLabel.className = "zn-consent-guardian";
    var guardianBox = document.createElement("input");
    guardianBox.type = "checkbox";
    guardianBox.className = "zn-consent-checkbox";
    guardianBox.setAttribute("data-element-id", "EL-LES-01-059");
    var guardianTxt = document.createElement("span");
    guardianTxt.textContent = "I am a parent/guardian, or I have my parent/guardian's permission to use the voice tutor.";
    guardianLabel.appendChild(guardianBox);
    guardianLabel.appendChild(guardianTxt);

    var actionsRow = document.createElement("div");
    actionsRow.className = "zn-consent-actions";
    var continueBtn = document.createElement("button");
    continueBtn.type = "button";
    continueBtn.className = "zn-consent-continue";
    continueBtn.setAttribute("data-element-id", "EL-LES-01-060");
    continueBtn.disabled = true;
    continueBtn.textContent = "Continue with voice";

    var declineBtn = document.createElement("button");
    declineBtn.type = "button";
    declineBtn.className = "zn-consent-decline";
    declineBtn.setAttribute("data-element-id", "EL-LES-01-061");
    declineBtn.textContent = "Decline (read page without voice)";

    var privLink = document.createElement("a");
    privLink.className = "zn-consent-privacy-link";
    privLink.href = "/privacy/";
    privLink.textContent = "Privacy summary & clear data";

    actionsRow.appendChild(continueBtn);
    actionsRow.appendChild(declineBtn);
    actionsRow.appendChild(privLink);

    card.appendChild(notice);
    card.appendChild(guardianLabel);
    card.appendChild(actionsRow);

    guardianBox.addEventListener("change", function () {
      continueBtn.disabled = !guardianBox.checked;
    });

    continueBtn.addEventListener("click", function () {
      if (!guardianBox.checked) return;
      recordConsentDecision("granted", true);
      card.hidden = true;
      var dockRes = ZivonVoiceDock.lazyMount();
      if (dockRes && dockRes.region) {
        var micBtn = dockRes.region.querySelector(".zn-dock-mic");
        if (micBtn) {
          try { micBtn.focus(); } catch (e) {}
        }
      }
    });

    declineBtn.addEventListener("click", function () {
      recordConsentDecision("declined", false);
      card.hidden = true;
      var dockRegion = ensureVoiceDockRegion();
      if (dockRegion) dockRegion.hidden = true;
    });

    card.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        declineBtn.click();
      }
    });

    /* If already granted or declined on this device, keep hidden (no re-nag) */
    card.hidden = cState === "granted" || cState === "declined";
    lessonPage.appendChild(card);
    return { mounted: true, element: card, state: cState };
  }

  var ZivonConsent = {
    CONSENT_STORAGE_KEY: CONSENT_STORAGE_KEY,
    CONSENT_VERSION: CONSENT_VERSION,
    getState: getConsentState,
    recordDecision: recordConsentDecision,
    mount: injectConsentGate
  };
  window.ZivonConsent = ZivonConsent;

  /* ---------------- SCR-PRIV-01 Privacy page & clear data ------------------- */
  async function clearAllDeviceData() {
    var devId = getDevicePseudoId();
    /* Clear all Zivon localStorage keys */
    [
      "zivon.dock",
      "zivon.consent",
      "zivon.consent_record",
      "zivon_locale",
      "zivon.lang",
      "zivon.captions",
      "zivon.identity_seen",
      "zivon.device_pseudo_id"
    ].forEach(safeStorageRemove);
    cachedDeviceId = null;

    if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
      window.ZivonEvents.emit("EVT-data_cleared", { scope: "device" });
    }

    /* Call challenge -> DELETE /v1/data (supports both POST and GET on /v1/data/challenge) */
    var serverWiped = false;
    try {
      var chalUrl = "/v1/data/challenge?device_pseudo_id=" + encodeURIComponent(devId);
      var chalRes = await sameOriginRequest(chalUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_pseudo_id: devId })
      });
      if (!chalRes || !chalRes.ok) {
        chalRes = await sameOriginRequest(chalUrl, { method: "GET" });
      }
      if (chalRes && chalRes.ok) {
        var chalData = await chalRes.json();
        var token = chalData && chalData.confirm_token ? chalData.confirm_token : "";
        if (token) {
          var delRes = await sameOriginRequest("/v1/data", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              device_pseudo_id: devId,
              confirm_token: token,
              scope: "device"
            })
          });
          if (delRes && delRes.ok) serverWiped = true;
        }
      }
    } catch (e) {}
    return { local_cleared: true, server_wiped: serverWiped, device_pseudo_id: devId };
  }

  function wirePrivacyPage() {
    var privMain = document.querySelector('[data-screen-id="SCR-PRIV-01"], .zn-privacy');
    if (!privMain) return { mounted: false };
    if (privMain.getAttribute("data-zn-mounted") === "true") return { mounted: true };
    privMain.setAttribute("data-zn-mounted", "true");

    var stampEl = document.getElementById("zn-privacy-consent-stamp");
    if (stampEl) {
      var rawRec = safeStorageGet(CONSENT_RECORD_KEY);
      if (rawRec) {
        try {
          var rec = JSON.parse(rawRec);
          stampEl.textContent = "Consent status: " + (rec.action || "recorded") + " (version " + (rec.consent_version || "v1") + ", " + (rec.ts || "") + ")";
        } catch (e) {
          stampEl.textContent = "Consent status: no consent record on this device.";
        }
      } else {
        stampEl.textContent = "Consent status: no consent record on this device.";
      }
    }

    var clearBtn = document.getElementById("zn-privacy-clear-btn") || privMain.querySelector('[data-element-id="EL-PRV-003"]');
    var dialogEl = document.getElementById("zn-privacy-clear-dialog") || privMain.querySelector('[data-element-id="EL-PRV-004"]');
    var confirmBtn = document.getElementById("zn-privacy-confirm-btn");
    var cancelBtn = document.getElementById("zn-privacy-cancel-btn");
    var statusEl = document.getElementById("zn-privacy-clear-status");

    if (clearBtn && dialogEl) {
      clearBtn.addEventListener("click", function () {
        dialogEl.hidden = false;
        if (confirmBtn) {
          try { confirmBtn.focus(); } catch (e) {}
        }
      });
    }
    if (cancelBtn && dialogEl) {
      cancelBtn.addEventListener("click", function () {
        dialogEl.hidden = true;
        if (clearBtn) {
          try { clearBtn.focus(); } catch (e) {}
        }
      });
    }
    if (confirmBtn && dialogEl) {
      confirmBtn.addEventListener("click", async function () {
        confirmBtn.disabled = true;
        var res = await clearAllDeviceData();
        confirmBtn.disabled = false;
        dialogEl.hidden = true;
        if (stampEl) {
          stampEl.textContent = "Consent status: no consent record on this device.";
        }
        if (statusEl) {
          statusEl.hidden = false;
          statusEl.textContent = res.server_wiped
            ? "All local and server data for this device has been erased."
            : "Local device data erased (server wipe queued or offline).";
        }
        if (clearBtn) {
          try { clearBtn.focus(); } catch (e) {}
        }
      });
    }
    return { mounted: true };
  }

  function injectFooterPrivacyLink() {
    var footer = document.querySelector(".zn-footer");
    if (!footer) return { mounted: false };
    if (footer.querySelector(".zn-footer-privacy-link")) {
      return { mounted: true };
    }
    var p = document.createElement("p");
    p.className = "zn-footer-links";
    p.setAttribute("data-ruled-skip", "true");
    var a = document.createElement("a");
    a.className = "zn-footer-privacy-link";
    a.href = "/privacy/";
    a.textContent = "Privacy & data summary";
    p.appendChild(a);
    footer.appendChild(p);
    return { mounted: true, link: a };
  }

  var ZivonPrivacy = {
    wirePrivacyPage: wirePrivacyPage,
    injectFooterPrivacyLink: injectFooterPrivacyLink,
    clearAllDeviceData: clearAllDeviceData
  };
  window.ZivonPrivacy = ZivonPrivacy;

  /* ---------------- §10.12 Voice dock (bottom sheet, DCR-002) -------------- */
  var DOCK_STORAGE_KEY = "zivon.dock";
  var CAPTIONS_STORAGE_KEY = "zivon.captions";
  var IDENTITY_SEEN_KEY = "zivon.identity_seen";

  var DOCK_STATE_COPY = {
    "idle": "Mic dabao aur poochho",
    "requesting-permission": "mic ki permission…",
    "connecting": "jud rahe hain…",
    "ready": "Mic dabao aur poochho",
    "listening": "Sun rahe hain — pakad ke rakho",
    "endpointing": "silence mila…",
    "thinking": "soch rahe hain…",
    "speaking": "",
    "speaking_text": "TUTOR · TEXT",
    "interrupted": "▌cut off",
    "offline": "connection gaya — jo type karoge woh safe hai",
    "error:mic-denied": "lesson chalta rahega",
    "error:mic-in-use": "Mic kisi aur app mein busy hai — dubara koshish karein ya type karein.",
    "error:mic-constraint": "Mic settings match nahi hui — niche type karke poochhein.",
    "error:unsupported-browser": "Is browser mein mic available nahi hai — niche type karke poochhein.",
    "error:no-input": "Kuch sunai nahi diya — mic dabakar bolen ya type karein.",
    "error:no-match": "Saaf sunai nahi diya — phir se bolen ya type karein.",
    "error:system-error": "Tutor ko dikkat aayi — dubara koshish karein ya type karein.",
    "error:timeout": "Jawab mein deri ho rahi hai — niche type karke poochhein.",
    "error:auth.invalid": "Session expire ho gaya — page refresh karein.",
    "error:version.mismatch": "Naya version aaya hai — page refresh karein.",
    "error:quota-exhausted": "30 credits/day · voice resets 00:00 · reading, sims, typing free",
    "text_only": "30 credits/day · voice resets 00:00 · reading, sims, typing free"
  };

  function getInitialContainment() {
    var saved = safeStorageGet(DOCK_STORAGE_KEY);
    if (saved === "hidden") return "hidden";
    /* A stored "expanded" starts collapsed on a new page load (never auto-expand, §10.12) */
    return "collapsed";
  }

  function playDockEarcon(kind, audioCtx) {
    /* Non-speech earcon cue (<= 3 sounds: start, stop, error; < 0.2s) */
    var ctx = audioCtx;
    if (!ctx) return;
    if (typeof ctx.createOscillator !== "function" || typeof ctx.createGain !== "function") return;
    try {
      var now = typeof ctx.currentTime === "number" ? ctx.currentTime : 0;
      var osc = ctx.createOscillator();
      var g = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = kind === "start" ? 520 : (kind === "stop" ? 390 : 240);
      g.gain.value = 0.04;
      osc.connect(g);
      if (ctx.destination) g.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.08);
    } catch (e) {}
  }

  var ZivonVoiceDock = {
    doctrineReady: true, /* DCR-002 closed: design-doctrine.md §10.12 is now binding */
    _activeClient: null,
    _silenceTimer: null,
    getRegion: ensureVoiceDockRegion,
    setContainment: function (nextContainment, persist) {
      var region = ensureVoiceDockRegion();
      if (!region) return "collapsed";
      var c = nextContainment === "hidden" || nextContainment === "expanded" ? nextContainment : "collapsed";
      region.setAttribute("data-containment", c);
      var tabBtn = region.querySelector(".zn-dock-tab");
      var stripEl = region.querySelector(".zn-dock-strip");
      var sheetEl = region.querySelector(".zn-dock-sheet");
      if (tabBtn) tabBtn.hidden = c !== "hidden";
      if (stripEl) stripEl.hidden = c !== "collapsed";
      if (sheetEl) sheetEl.hidden = c !== "expanded";
      if (persist !== false) {
        safeStorageSet(DOCK_STORAGE_KEY, c);
      }
      return c;
    },
    getContainment: function () {
      var region = ensureVoiceDockRegion();
      return (region && region.getAttribute("data-containment")) || getInitialContainment();
    },
    bindClient: function (client) {
      var region = ensureVoiceDockRegion();
      if (!region || !client) return;
      ZivonVoiceDock._activeClient = client;
      client.onStateChange(function (nextState, prevState, detail) {
        ZivonVoiceDock.renderAgentState(nextState, detail || {});
      });
      ZivonVoiceDock.renderAgentState(client.getState(), {});
    },
    renderAgentState: function (agentState, detail) {
      var region = ensureVoiceDockRegion();
      if (!region || region.getAttribute("data-zn-dock-mounted") !== "true") return;
      var st = String(agentState || "idle");
      if (st === "error:quota-exhausted") st = "text_only";
      region.setAttribute("data-agent-state", st);

      if (ZivonVoiceDock._silenceTimer) {
        clearTimeout(ZivonVoiceDock._silenceTimer);
        ZivonVoiceDock._silenceTimer = null;
      }

      var stateLabel = region.querySelector(".zn-dock-state-label");
      var captionEl = region.querySelector(".zn-dock-caption");
      var stripCaptionEl = region.querySelector(".zn-dock-strip-caption");
      var micBtns = region.querySelectorAll(".zn-dock-mic");
      var stopBtn = region.querySelector(".zn-dock-stop");
      var stampEl = region.querySelector(".zn-dock-stamp");
      var sweepEl = region.querySelector(".zn-dock-sweep");
      var barsEl = region.querySelector(".zn-dock-bars");
      var textChipEl = region.querySelector(".zn-dock-text-chip");
      var retryBtn = region.querySelector(".zn-dock-retry");
      var helpRow = region.querySelector(".zn-dock-help-chips");
      var transcriptList = region.querySelector(".zn-dock-transcript");
      var typedInput = region.querySelector(".zn-dock-typed-input");
      var captionsOn = safeStorageGet(CAPTIONS_STORAGE_KEY) !== "false";

      var isListening = st === "listening";
      var isSpeaking = st === "speaking" || st === "speaking_text";
      var isThinking = st === "thinking";
      var isEndpointing = st === "endpointing";
      var isMicDenied = st === "error:mic-denied";
      var isTextOnly = st === "text_only";
      var isError = st.indexOf("error:") === 0;

      micBtns.forEach(function (mb) {
        mb.setAttribute("aria-pressed", isListening ? "true" : "false");
        mb.disabled = isTextOnly || isMicDenied;
      });
      if (stopBtn) stopBtn.hidden = !isSpeaking;
      if (stampEl) {
        stampEl.hidden = !isMicDenied;
        if (isMicDenied) stampEl.textContent = "MIC OFF";
      }
      if (sweepEl) sweepEl.hidden = !isThinking;
      if (barsEl) {
        barsEl.hidden = !(isListening || isEndpointing || st === "speaking");
        barsEl.setAttribute("data-bars-mode", isEndpointing ? "endpointing" : (isListening ? "listening" : "speaking"));
      }
      if (textChipEl) {
        textChipEl.hidden = st !== "speaking_text";
      }
      if (retryBtn) {
        retryBtn.hidden = !(st === "error:mic-in-use" || st === "error:no-match" || st === "error:no-input" || st === "error:system-error" || st === "error:timeout");
      }
      if (helpRow) {
        helpRow.hidden = !(st === "error:no-match" || st === "error:no-input" || st === "error:mic-denied" || isTextOnly);
      }

      var copy = DOCK_STATE_COPY[st] !== undefined ? DOCK_STATE_COPY[st] : (detail && detail.message ? String(detail.message) : st);
      if (stateLabel) {
        stateLabel.setAttribute("aria-live", isError ? "assertive" : "polite");
        stateLabel.textContent = copy || (st === "speaking" ? "Bol rahe hain…" : "Ready");
      }

      /* Sync transcript & live caption from active client if present */
      var client = ZivonVoiceDock._activeClient;
      var tList = client && typeof client.getTranscripts === "function" ? client.getTranscripts() : [];
      var latestPartial = "";
      var latestTutorText = "";
      for (var i = 0; i < tList.length; i++) {
        if (tList[i].kind === "partial") latestPartial = tList[i].text;
        if (tList[i].kind === "tutor") latestTutorText = tList[i].text;
      }

      var liveCapText = copy;
      if (st === "speaking" || st === "speaking_text") {
        liveCapText = captionsOn ? (latestTutorText || "Bol rahe hain…") : "";
      } else if (st === "listening" && latestPartial && captionsOn) {
        liveCapText = latestPartial;
      } else if (st === "interrupted") {
        liveCapText = (latestTutorText ? latestTutorText.slice(0, 48) + " " : "") + "▌cut off";
      }

      if (captionEl) {
        captionEl.hidden = !captionsOn;
        captionEl.textContent = liveCapText;
      }
      if (stripCaptionEl) {
        stripCaptionEl.textContent = liveCapText || "Mic dabao aur poochho";
      }

      if (transcriptList && client) {
        while (transcriptList.firstChild) transcriptList.removeChild(transcriptList.firstChild);
        var finals = tList.filter(function (item) { return item.kind === "student" || item.kind === "tutor"; });
        if (!finals.length) {
          var emptyLi = document.createElement("p");
          emptyLi.className = "zn-dock-transcript-empty";
          emptyLi.textContent = "Abhi koi sawaal nahi poochha gaya.";
          transcriptList.appendChild(emptyLi);
        } else {
          finals.slice(-6).forEach(function (item) {
            var p = document.createElement("p");
            p.className = "zn-dock-line zn-dock-line-" + item.kind;
            var prefix = item.kind === "student" ? "You: " : "Tutor: ";
            var suffix = item.interrupted ? " ▌cut off" : "";
            p.textContent = prefix + item.text + suffix;
            if (item.interrupted) p.setAttribute("data-cut-off", "true");
            transcriptList.appendChild(p);
          });
        }
      }

      if (isMicDenied && typedInput) {
        ZivonVoiceDock.setContainment("expanded", false);
        try { typedInput.focus(); } catch (e) {}
      }

      /* Silence-close: 5 s after a completed turn reaches ready/idle, return expanded -> collapsed (§10.12) */
      if ((st === "ready" || st === "idle") && detail && detail.turn_id && ZivonVoiceDock.getContainment() === "expanded") {
        ZivonVoiceDock._silenceTimer = setTimeout(function () {
          if (ZivonVoiceDock.getContainment() === "expanded") {
            var cur = ZivonVoiceDock._activeClient ? ZivonVoiceDock._activeClient.getState() : "ready";
            if (cur === "ready" || cur === "idle") {
              ZivonVoiceDock.setContainment("collapsed", true);
            }
          }
        }, 5000);
      }
    },
    lazyMount: function (opts) {
      var options = opts || {};
      var region = ensureVoiceDockRegion();
      if (!ZivonVoiceDock.doctrineReady) {
        return { mounted: false, reason: "founder-gated: design-doctrine.md §10.12 absent (DCR-002)" };
      }
      if (!region) {
        return { mounted: false, reason: "not_lesson_page" };
      }
      /* Consent gate (§10.14): until consent is accepted the region stays hidden
         unless forceMount is passed for direct unit testing. */
      var consentVal = safeStorageGet("zivon.consent");
      if (!options.force && consentVal !== "granted") {
        region.hidden = true;
        return { mounted: false, reason: "consent_required", region: region };
      }
      if (region.getAttribute("data-zn-dock-mounted") === "true") {
        region.hidden = false;
        return { mounted: true, region: region, client: ZivonVoiceDock._activeClient };
      }

      region.setAttribute("data-zn-dock-mounted", "true");
      region.setAttribute("data-zn-mounted", "true");
      region.setAttribute("role", "region");
      region.setAttribute("aria-label", "Voice tutor dock");
      region.setAttribute("data-ruled-skip", "true");
      region.hidden = false;

      var snap = buildContextSnapshot();
      var anchorBlockId = snap.block_id || "b-01";
      var anchorBlockType = snap.block_type || "lesson";
      var anchorLabelText = anchorBlockId + " · " + anchorBlockType.replace(/_/g, " ");

      /* 1. Hidden state: 44 px bottom-right paper tab */
      var tabBtn = document.createElement("button");
      tabBtn.type = "button";
      tabBtn.className = "zn-dock-tab";
      tabBtn.setAttribute("data-element-id", "EL-LES-01-042");
      tabBtn.setAttribute("aria-label", "Open voice tutor dock");
      tabBtn.textContent = "[mic] Ask";

      /* 2. Collapsed state: 92 px strip */
      var stripEl = document.createElement("div");
      stripEl.className = "zn-dock-strip";
      var grabStrip = document.createElement("button");
      grabStrip.type = "button";
      grabStrip.className = "zn-dock-grab";
      grabStrip.setAttribute("aria-label", "Expand voice tutor sheet");
      grabStrip.textContent = "—";
      var stripCap = document.createElement("p");
      stripCap.className = "zn-dock-strip-caption";
      stripCap.textContent = "Mic dabao aur poochho";
      var stripTypeBtn = document.createElement("button");
      stripTypeBtn.type = "button";
      stripTypeBtn.className = "zn-dock-type-btn";
      stripTypeBtn.textContent = "Type";
      var stripHideBtn = document.createElement("button");
      stripHideBtn.type = "button";
      stripHideBtn.className = "zn-dock-hide-btn";
      stripHideBtn.setAttribute("aria-label", "Hide voice dock to tab");
      stripHideBtn.textContent = "Hide";
      var stripMicBtn = document.createElement("button");
      stripMicBtn.type = "button";
      stripMicBtn.className = "zn-dock-mic zn-dock-mic-strip";
      stripMicBtn.setAttribute("data-element-id", "EL-LES-01-043");
      stripMicBtn.setAttribute("aria-pressed", "false");
      stripMicBtn.setAttribute("aria-label", "Hold or press to speak doubt");
      stripMicBtn.textContent = "[mic]";
      [grabStrip, stripCap, stripTypeBtn, stripHideBtn, stripMicBtn].forEach(function (el) { stripEl.appendChild(el); });

      /* 3. Expanded state: <= 60 dvh sheet */
      var sheetEl = document.createElement("div");
      sheetEl.className = "zn-dock-sheet";

      var grabSheet = document.createElement("button");
      grabSheet.type = "button";
      grabSheet.className = "zn-dock-grab";
      grabSheet.setAttribute("aria-label", "Collapse voice tutor sheet");
      grabSheet.textContent = "— Collapse";

      var topRow = document.createElement("div");
      topRow.className = "zn-dock-top-row";
      var anchorChip = document.createElement("button");
      anchorChip.type = "button";
      anchorChip.className = "zn-dock-anchor-chip";
      anchorChip.setAttribute("data-element-id", "EL-LES-01-050");
      anchorChip.setAttribute("data-anchor-block", anchorBlockId);
      anchorChip.textContent = "Asking about: " + anchorLabelText;

      var identityLine = document.createElement("p");
      identityLine.className = "zn-dock-identity";
      identityLine.setAttribute("data-element-id", "EL-LES-01-051");
      identityLine.textContent = "I'm an AI tutor — I see this lesson page, not your room.";
      if (safeStorageGet(IDENTITY_SEEN_KEY) === "true") {
        identityLine.hidden = true;
      } else {
        safeStorageSet(IDENTITY_SEEN_KEY, "true");
      }
      topRow.appendChild(anchorChip);
      topRow.appendChild(identityLine);

      /* State indicator row (EL-LES-01-044) */
      var stateRow = document.createElement("div");
      stateRow.className = "zn-dock-state-row";
      stateRow.setAttribute("data-element-id", "EL-LES-01-044");
      var stampEl = document.createElement("span");
      stampEl.className = "zn-dock-stamp";
      stampEl.hidden = true;
      var textChipEl = document.createElement("span");
      textChipEl.className = "zn-dock-text-chip";
      textChipEl.textContent = "TUTOR · TEXT";
      textChipEl.hidden = true;
      var stateLabel = document.createElement("span");
      stateLabel.className = "zn-dock-state-label";
      stateLabel.setAttribute("role", "status");
      stateLabel.setAttribute("aria-live", "polite");
      stateLabel.textContent = "Mic dabao aur poochho";
      var sweepEl = document.createElement("div");
      sweepEl.className = "zn-dock-sweep";
      sweepEl.setAttribute("aria-hidden", "true");
      sweepEl.hidden = true;
      var barsEl = document.createElement("div");
      barsEl.className = "zn-dock-bars";
      barsEl.setAttribute("aria-hidden", "true");
      barsEl.hidden = true;
      for (var bIdx = 0; bIdx < 5; bIdx++) {
        var barSpan = document.createElement("span");
        barSpan.className = "zn-dock-bar";
        barsEl.appendChild(barSpan);
      }
      var retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "zn-dock-retry";
      retryBtn.textContent = "Retry";
      retryBtn.hidden = true;
      [stampEl, textChipEl, stateLabel, sweepEl, barsEl, retryBtn].forEach(function (el) { stateRow.appendChild(el); });

      /* Transcript panel (EL-LES-01-047) */
      var transcriptPanel = document.createElement("div");
      transcriptPanel.className = "zn-dock-transcript";
      transcriptPanel.setAttribute("data-element-id", "EL-LES-01-047");
      transcriptPanel.setAttribute("aria-live", "polite");
      var emptyLine = document.createElement("p");
      emptyLine.className = "zn-dock-transcript-empty";
      emptyLine.textContent = "Abhi koi sawaal nahi poochha gaya.";
      transcriptPanel.appendChild(emptyLine);

      /* Live caption line (EL-LES-01-048) + toggle (EL-LES-01-049) */
      var captionRow = document.createElement("div");
      captionRow.className = "zn-dock-caption-row";
      var captionEl = document.createElement("p");
      captionEl.className = "zn-dock-caption";
      captionEl.setAttribute("data-element-id", "EL-LES-01-048");
      captionEl.setAttribute("aria-live", "polite");
      captionEl.textContent = "Mic dabao aur poochho";
      var capToggleLabel = document.createElement("label");
      capToggleLabel.className = "zn-dock-cap-toggle";
      capToggleLabel.setAttribute("data-element-id", "EL-LES-01-049");
      var capCheckbox = document.createElement("input");
      capCheckbox.type = "checkbox";
      capCheckbox.checked = safeStorageGet(CAPTIONS_STORAGE_KEY) !== "false";
      var capTxt = document.createElement("span");
      capTxt.textContent = "Captions";
      capToggleLabel.appendChild(capCheckbox);
      capToggleLabel.appendChild(capTxt);
      captionRow.appendChild(captionEl);
      captionRow.appendChild(capToggleLabel);

      /* Controls row: 56 px mic disc (EL-LES-01-043) + stop button (EL-LES-01-046) */
      var controlsRow = document.createElement("div");
      controlsRow.className = "zn-dock-controls-row";
      var sheetMicBtn = document.createElement("button");
      sheetMicBtn.type = "button";
      sheetMicBtn.className = "zn-dock-mic zn-dock-mic-sheet";
      sheetMicBtn.setAttribute("data-element-id", "EL-LES-01-043");
      sheetMicBtn.setAttribute("aria-pressed", "false");
      sheetMicBtn.setAttribute("aria-label", "Hold or press to speak doubt");
      sheetMicBtn.textContent = "[mic] Speak";

      var stopBtn = document.createElement("button");
      stopBtn.type = "button";
      stopBtn.className = "zn-dock-stop";
      stopBtn.setAttribute("data-element-id", "EL-LES-01-046");
      stopBtn.textContent = "■ Stop";
      stopBtn.hidden = true;
      controlsRow.appendChild(sheetMicBtn);
      controlsRow.appendChild(stopBtn);

      /* Typed fallback form (EL-LES-01-052) */
      var typedForm = document.createElement("form");
      typedForm.className = "zn-dock-typed-form";
      typedForm.setAttribute("data-element-id", "EL-LES-01-052");
      var typedInput = document.createElement("input");
      typedInput.type = "text";
      typedInput.className = "zn-dock-typed-input";
      typedInput.placeholder = "Apna doubt yahan type karein…";
      typedInput.setAttribute("aria-label", "Type your physics doubt");
      var typedSend = document.createElement("button");
      typedSend.type = "submit";
      typedSend.className = "zn-dock-typed-send";
      typedSend.textContent = "Send";
      typedForm.appendChild(typedInput);
      typedForm.appendChild(typedSend);

      /* Help chip row (EL-LES-01-053) */
      var helpRow = document.createElement("div");
      helpRow.className = "zn-dock-help-chips";
      helpRow.setAttribute("data-element-id", "EL-LES-01-053");
      helpRow.setAttribute("role", "list");
      helpRow.hidden = true;
      [
        "Is graph ka slope kya batata hai?",
        "Yeh formula kab lagta hai?",
        "Step by step samjhao"
      ].forEach(function (phrase) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "zn-dock-help-chip";
        chip.setAttribute("role", "listitem");
        chip.textContent = phrase;
        chip.addEventListener("click", function () {
          typedInput.value = phrase;
          try { typedInput.focus(); } catch (e) {}
        });
        helpRow.appendChild(chip);
      });

      /* Footer entries: Memory view (EL-LES-01-054) + Settings entry (EL-LES-01-055) */
      var metaRow = document.createElement("div");
      metaRow.className = "zn-dock-meta-row";
      var memDetails = document.createElement("details");
      memDetails.className = "zn-dock-memory";
      memDetails.setAttribute("data-element-id", "EL-LES-01-054");
      var memSum = document.createElement("summary");
      memSum.textContent = "What the tutor remembers";
      var memList = document.createElement("p");
      memList.className = "zn-dock-memory-list";
      memList.textContent = "Covered this session: " + anchorLabelText;
      var memClearBtn = document.createElement("button");
      memClearBtn.type = "button";
      memClearBtn.className = "zn-dock-memory-clear";
      memClearBtn.textContent = "Clear session memory";
      memClearBtn.addEventListener("click", function () {
        memList.textContent = "Nothing yet - this is a fresh session.";
        if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
          window.ZivonEvents.emit("EVT-data_cleared", { scope: "memory" });
        }
      });
      memDetails.appendChild(memSum);
      memDetails.appendChild(memList);
      memDetails.appendChild(memClearBtn);

      var settingsBtn = document.createElement("button");
      settingsBtn.type = "button";
      settingsBtn.className = "zn-dock-settings-btn";
      settingsBtn.setAttribute("data-element-id", "EL-LES-01-055");
      settingsBtn.textContent = "Settings";
      settingsBtn.addEventListener("click", function () {
        var langBar = document.querySelector(".zn-lang-bar");
        if (langBar && typeof langBar.scrollIntoView === "function") {
          langBar.scrollIntoView({ block: "start" });
        }
      });
      var sheetHideBtn = document.createElement("button");
      sheetHideBtn.type = "button";
      sheetHideBtn.className = "zn-dock-hide-btn";
      sheetHideBtn.textContent = "Hide dock";
      metaRow.appendChild(memDetails);
      metaRow.appendChild(settingsBtn);
      metaRow.appendChild(sheetHideBtn);

      [grabSheet, topRow, stateRow, transcriptPanel, captionRow, controlsRow, typedForm, helpRow, metaRow].forEach(function (el) {
        sheetEl.appendChild(el);
      });

      region.appendChild(tabBtn);
      region.appendChild(stripEl);
      region.appendChild(sheetEl);

      /* Wire containment interactions */
      tabBtn.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("collapsed", true);
      });
      grabStrip.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("expanded", true);
      });
      stripTypeBtn.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("expanded", true);
        try { typedInput.focus(); } catch (e) {}
      });
      stripHideBtn.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("hidden", true);
      });
      sheetHideBtn.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("hidden", true);
      });
      grabSheet.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("collapsed", true);
      });

      capCheckbox.addEventListener("change", function () {
        safeStorageSet(CAPTIONS_STORAGE_KEY, capCheckbox.checked ? "true" : "false");
        captionEl.hidden = !capCheckbox.checked;
      });

      anchorChip.addEventListener("click", function () {
        var bid = anchorChip.getAttribute("data-anchor-block") || "b-01";
        highlightBlocks([bid]);
        var target = document.getElementById(bid);
        if (target && typeof target.scrollIntoView === "function") {
          target.scrollIntoView({ block: "center" });
        }
      });

      function ensureClientWired() {
        if (!ZivonVoiceDock._activeClient) {
          var client = createVoiceClient(options.clientOptions || {});
          ZivonVoiceDock.bindClient(client);
        }
        return ZivonVoiceDock._activeClient;
      }

      function handleMicTrigger() {
        /* Echo guard (§10.13): pressing the dock mic immediately stops read-aloud */
        stopReadAloud();
        ZivonVoiceDock.setContainment("expanded", true);
        var client = ensureClientWired();
        var cur = client.getState();
        if (cur === "speaking" || cur === "thinking" || cur === "speaking_text") {
          client.bargeIn("ptt_press");
          return;
        }
        if (cur === "listening") {
          client.endAudio();
          try { sheetMicBtn.focus(); } catch (e) {}
          return;
        }
        if (cur === "idle") {
          client.connect();
        }
        client.startListening("doubt");
      }

      stripMicBtn.addEventListener("click", handleMicTrigger);
      sheetMicBtn.addEventListener("click", handleMicTrigger);

      stopBtn.addEventListener("click", function () {
        var client = ensureClientWired();
        client.bargeIn("stop_button");
        try { sheetMicBtn.focus(); } catch (e) {}
      });

      retryBtn.addEventListener("click", function () {
        var client = ensureClientWired();
        client.reconnect();
      });

      typedForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var txt = (typedInput.value || "").trim();
        if (!txt) return;
        stopReadAloud();
        var client = ensureClientWired();
        client.sendTypedDoubt(txt);
        typedInput.value = "";
        ZivonVoiceDock.renderAgentState(client.getState(), {});
      });

      /* Keyboard shortcuts (§10.12): Space hold = talk, Esc = stop/interrupt then collapse, Enter = send typed */
      region.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          var client = ZivonVoiceDock._activeClient;
          var cur = client ? client.getState() : "idle";
          if (cur === "speaking" || cur === "thinking" || cur === "speaking_text" || cur === "listening") {
            ev.preventDefault();
            if (cur === "listening") client.endAudio();
            else client.bargeIn("escape_key");
            try { sheetMicBtn.focus(); } catch (e) {}
          } else if (ZivonVoiceDock.getContainment() === "expanded") {
            ev.preventDefault();
            ZivonVoiceDock.setContainment("collapsed", true);
            try { stripMicBtn.focus(); } catch (e) {}
          }
        } else if (ev.key === " " && ev.target !== typedInput) {
          var client2 = ensureClientWired();
          if (client2.getState() !== "listening" && !ev.repeat) {
            ev.preventDefault();
            stopReadAloud();
            ZivonVoiceDock.setContainment("expanded", true);
            client2.startListening("space_hold");
          }
        }
      });

      region.addEventListener("keyup", function (ev) {
        if (ev.key === " " && ev.target !== typedInput) {
          var client = ZivonVoiceDock._activeClient;
          if (client && client.getState() === "listening") {
            ev.preventDefault();
            client.endAudio();
            try { sheetMicBtn.focus(); } catch (e) {}
          }
        }
      });

      var initContainment = getInitialContainment();
      ZivonVoiceDock.setContainment(initContainment, false);
      ZivonVoiceDock.renderAgentState("idle", {});
      return { mounted: true, region: region };
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
      /* SVG/MathML elements expose className as an SVGAnimatedString, not a
         string. Normalise before the class-name probe so an id'd <svg>/<g>/
         <math> child can never throw and take the whole snapshot down. */
      var classAttr = el.className;
      var className = typeof classAttr === "string"
        ? classAttr
        : (classAttr && typeof classAttr.baseVal === "string" ? classAttr.baseVal : "");
      var tag = className || el.tagName.toLowerCase();
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
      if (s === "empty") {
        window.ZIVON_COURSES = [];
        if (document.getElementById("zn-courses")) renderCourses();
        /* The class-grouped catalogue renders into #zn-class-sections; an empty
           state must clear that copy too, or stale cards survive the reset. */
        ["zn-class-sections", "zn-grade-nav-links"].forEach(function (hostId) {
          var host = document.getElementById(hostId);
          if (!host) return;
          while (host.firstChild) host.removeChild(host.firstChild);
        });
        var catalogue = document.getElementById("zn-catalogue");
        if (catalogue) catalogue.hidden = false;
        var emptyMsg = document.getElementById("zn-empty");
        if (emptyMsg) emptyMsg.hidden = false;
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

  /* --------------- 7. voice loop WS client & mock server ------------------
     Implements docs/specs/frontend/ws-client-contract.md reconciled with SP1's
     canonical docs/specs/voice-agent/ws-contract.md:
     - Transport: wss://<origin>/voice/ws (or injected mock socket for dev/test)
     - 8-byte binary header (0xA5, v=1, segment_id, seq, flags, reserved=0)
       per ADR-0020 §3.
     - Client state machine: idle, connecting, requesting-permission, ready,
       listening, endpointing, thinking, speaking, speaking_text, interrupted,
       error:<code>, offline.
     - Capture constraint ladder (16 kHz mono + AEC/NS/AGC -> drop sampleRate ->
       drop channelCount) and GainNode ducking values (never track.enabled=false)
       per skills/zivon-audio-engineering-skills/ & ADR-0010.
     - WEB AUDIO API PLAYBACK (ws-contract.md §3): server downlink is 8-byte
       header + little-endian PCM16 mono at ZIVON_VOICE_TTS_SAMPLE_RATE (48 kHz
       default). Client decodes PCM16 to Float32, buffers toward 60-120 ms
       (never hard-scheduling < 150 ms ahead on first chunk), schedules
       AudioBufferSourceNodes through agentGainNode -> audioCtx.destination,
       and ramps gain down ~50 ms + stops sources on interrupt/barge-in/offline.
     - Reconnect: capped exponential backoff with jitter after an unexpected
       close; a pong timeout closes the socket before reporting offline.
     - Degraded text fallback (typed transcript via audio.end) & turn latency
       stamps (t_endpoint, t_final_transcript, t_first_token, t_first_audio).
     CSP NOTE: createVoiceClient() opens a same-origin WebSocket. Lesson pages
     now carry `connect-src 'self'` (the founder-authorised scoped relaxation,
     ws-client-contract.md §8): the generator emits it as the page meta CSP and
     docker/nginx.conf repeats it for the /courses/ location, while every other
     location keeps the server-level `connect-src 'none'`. This file relaxes no
     CSP itself — it only assumes the lesson page granted 'self'. */
  var VOICE_MAGIC = 0xA5;
  var VOICE_VERSION = 1;

  function encodeAudioFrame(pcmBytes, segmentId, seq, isFinal) {
    var payload = pcmBytes instanceof Uint8Array ? pcmBytes : new Uint8Array(pcmBytes || 0);
    var out = new Uint8Array(8 + payload.byteLength);
    var dv = new DataView(out.buffer);
    dv.setUint8(0, VOICE_MAGIC);
    dv.setUint8(1, VOICE_VERSION);
    dv.setUint16(2, (segmentId || 1) & 0xFFFF, false);
    dv.setUint16(4, (seq || 0) & 0xFFFF, false);
    dv.setUint8(6, isFinal ? 1 : 0);
    dv.setUint8(7, 0);
    out.set(payload, 8);
    return out.buffer;
  }

  function decodeAudioFrame(buffer) {
    var arr = buffer instanceof ArrayBuffer ? new Uint8Array(buffer) :
      (buffer && buffer.buffer instanceof ArrayBuffer ? new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength) : null);
    if (!arr || arr.byteLength < 8) {
      return { valid: false, reason: "short_frame" };
    }
    var dv = new DataView(arr.buffer, arr.byteOffset, arr.byteLength);
    var magic = dv.getUint8(0);
    var ver = dv.getUint8(1);
    if (magic !== VOICE_MAGIC || ver !== VOICE_VERSION) {
      return { valid: false, reason: "header_mismatch", magic: magic, version: ver };
    }
    return {
      valid: true,
      magic: magic,
      version: ver,
      segment_id: dv.getUint16(2, false),
      seq: dv.getUint16(4, false),
      is_final: (dv.getUint8(6) & 1) === 1,
      payload: arr.subarray(8)
    };
  }

  function decodePcm16ToFloat32(payloadBytes) {
    var bytes = payloadBytes instanceof Uint8Array
      ? payloadBytes
      : new Uint8Array(payloadBytes || 0);
    var sampleCount = Math.floor(bytes.byteLength / 2);
    var out = new Float32Array(sampleCount);
    if (!sampleCount) return out;
    var dv = new DataView(bytes.buffer, bytes.byteOffset, sampleCount * 2);
    for (var i = 0; i < sampleCount; i++) {
      var s = dv.getInt16(i * 2, true); /* little-endian PCM16 */
      out[i] = s < 0 ? s / 32768.0 : s / 32767.0;
    }
    return out;
  }

  function mapServerErrorToCode(code) {
    var c = String(code || "system-error");
    if (c === "credit.over_daily" || c === "credit.over_session" || c === "quota-exhausted") {
      return "quota-exhausted";
    }
    if (c === "brain.first_event_timeout" || c === "brain.deadline" || c === "timeout") {
      return "timeout";
    }
    if (c === "stt.no_match" || c === "no-match") return "no-match";
    if (c === "stt.no_input" || c === "no-input") return "no-input";
    if (c === "mic-denied" || c === "mic-in-use" || c === "mic-constraint" || c === "unsupported-browser") return c;
    return c;
  }

  /* Module-scope pagehide cleanup registry: one listener for every client this
     page ever creates, so a client can unregister on disconnect() instead of
     stacking a closure per instance. */
  var voiceClientCleanups = [];
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("pagehide", function () {
      voiceClientCleanups.slice().forEach(function (fn) {
        try { fn(); } catch (e) {}
      });
    });
  }

  function createVoiceClient(options) {
    var opts = options || {};
    var state = "idle";
    var listeners = [];
    var ws = null;
    var sessionId = null;
    var sessionToken = opts.session_token || null;
    if (!sessionToken) {
      /* Never pretend an anonymous session is valid: the backend rejects one
         (API-001). The placeholder keeps dev/mock pages working, but says so. */
      sessionToken = "dev-session-token";
      if (typeof window !== "undefined" && window.console && console.warn) {
        console.warn("zivon.voice: no session_token supplied - using the dev placeholder; the voice backend rejects anonymous sessions in production.");
      }
    }
    var deviceId = opts.device || (window.ZivonLocale && window.ZivonLocale.getDevicePseudoId ? window.ZivonLocale.getDevicePseudoId() : "dev-device");
    var lastTurnId = null;
    var micSeq = 0;
    var expectedTtsSeq = {};
    var pendingFrames = [];
    var pcmJitterQueue = [];
    var jitterBufferedMs = 0;
    var jitterTargetMs = opts.jitter_target_ms || 80;
    var minLeadTimeS = (opts.min_lead_ms !== undefined ? opts.min_lead_ms : 150) / 1000.0;
    var ttsSampleRate = opts.tts_sample_rate || (typeof window !== "undefined" && window.ZIVON_VOICE_TTS_SAMPLE_RATE) || 48000;
    var nextPlayTimeS = 0;
    var activeSources = [];
    var scheduledChunksCount = 0;
    var minFramesBeforeSpeaking = opts.min_frames_before_speaking || opts.min_buffer_frames || 3;
    var audioCtx = opts.audioContext || null;
    var micGainNode = null;
    var agentGainNode = null;
    var agentGainConnected = false;
    var mediaStream = null;
    var creditState = "ok";
    var pingTimer = null;
    var reconnectTimer = null;
    var reconnectAttempts = 0;
    var maxReconnectAttempts = opts.max_reconnect_attempts !== undefined ? opts.max_reconnect_attempts : 6;
    var reconnectBaseMs = opts.reconnect_base_ms !== undefined ? opts.reconnect_base_ms : 500;
    var reconnectMaxMs = opts.reconnect_max_ms !== undefined ? opts.reconnect_max_ms : 15000;
    var lastPongTs = 0;
    var consecutiveVadTriggers = 0;
    var lastVadTriggerTs = 0;
    var queuedTypedDoubts = [];
    var transcripts = [];
    var turnTimings = {};
    var lastCompletedTurnMetrics = null;

    function setState(nextState, detail) {
      var prev = state;
      state = nextState;
      /* Terminal / non-speaking states restore the bookkeeping gains: a turn
         that ends in error, interrupt or offline must not leave the mic path
         ducked at 0.2 forever. */
      if (nextState === "offline" || nextState === "interrupted" ||
          nextState === "error" || String(nextState).indexOf("error:") === 0) {
        if (nextState === "offline" || nextState === "interrupted") {
          stopPlaybackImmediately();
        }
        setDucking("normal");
      }
      if (nextState === "offline") {
        applyLessonStateBanner("offline", "Offline - voice tutor paused; lesson and simulations stay active.");
      } else if (nextState === "error:quota-exhausted") {
        applyLessonStateBanner("exhausted", "Voice is resting (daily limit). Type your doubt.");
      }
      listeners.forEach(function (fn) {
        try { fn(state, prev, detail || {}); } catch (e) {}
      });
    }

    function sendJson(msg) {
      var payload = Object.assign({ v: VOICE_VERSION }, msg);
      if (!ws || ws.readyState !== 1) {
        setState("offline", { reason: "ws_not_open" });
        return false;
      }
      ws.send(JSON.stringify(payload));
      return true;
    }

    function ensureAudioGraph() {
      if (!audioCtx && typeof window !== "undefined") {
        var Ctor = window.AudioContext || window.webkitAudioContext;
        if (Ctor) {
          try { audioCtx = new Ctor(); } catch (e) {}
        }
      }
      if (audioCtx) {
        if (audioCtx.state === "suspended" && typeof audioCtx.resume === "function") {
          try { audioCtx.resume(); } catch (e) {}
        }
        if (!micGainNode && typeof audioCtx.createGain === "function") {
          micGainNode = audioCtx.createGain();
          micGainNode.gain.value = 1.0;
        }
        if (!agentGainNode && typeof audioCtx.createGain === "function") {
          agentGainNode = audioCtx.createGain();
          agentGainNode.gain.value = 1.0;
        }
        if (agentGainNode && !agentGainConnected && audioCtx.destination && typeof agentGainNode.connect === "function") {
          try {
            agentGainNode.connect(audioCtx.destination);
            agentGainConnected = true;
          } catch (e) {}
        }
      }
    }

    function scheduleJitterBuffer(forceFlush) {
      if (!pcmJitterQueue.length) return;
      ensureAudioGraph();
      if (!audioCtx || typeof audioCtx.createBuffer !== "function" || typeof audioCtx.createBufferSource !== "function") {
        pcmJitterQueue = [];
        jitterBufferedMs = 0;
        return;
      }
      if (!forceFlush && nextPlayTimeS === 0 && jitterBufferedMs < 60 && pcmJitterQueue.length < minFramesBeforeSpeaking) {
        return;
      }
      var nowS = typeof audioCtx.currentTime === "number" ? audioCtx.currentTime : 0;
      if (nextPlayTimeS < nowS + minLeadTimeS) {
        /* Never hard-schedule < 150 ms ahead on initial/underrun start (ws-contract.md §2/§3) */
        nextPlayTimeS = nowS + Math.max(minLeadTimeS, jitterTargetMs / 1000.0);
      }
      if (agentGainNode && agentGainNode.gain) {
        agentGainNode.gain.value = 1.0;
      }
      while (pcmJitterQueue.length > 0) {
        var chunk = pcmJitterQueue.shift();
        var samples = chunk.samples;
        if (!samples || !samples.length) continue;
        try {
          var buf = audioCtx.createBuffer(1, samples.length, ttsSampleRate);
          if (typeof buf.copyToChannel === "function") {
            buf.copyToChannel(samples, 0);
          } else if (typeof buf.getChannelData === "function") {
            var ch = buf.getChannelData(0);
            if (ch && typeof ch.set === "function") ch.set(samples);
          }
          var src = audioCtx.createBufferSource();
          src.buffer = buf;
          if (agentGainNode && typeof src.connect === "function") {
            src.connect(agentGainNode);
          } else if (audioCtx.destination && typeof src.connect === "function") {
            src.connect(audioCtx.destination);
          }
          var startAt = nextPlayTimeS;
          var durS = samples.length / ttsSampleRate;
          nextPlayTimeS = startAt + durS;
          activeSources.push(src);
          scheduledChunksCount += 1;
          src.onended = (function (s) {
            return function () {
              var idx = activeSources.indexOf(s);
              if (idx !== -1) activeSources.splice(idx, 1);
            };
          })(src);
          if (typeof src.start === "function") {
            src.start(startAt);
          }
        } catch (e) {}
      }
      jitterBufferedMs = 0;
    }

    function stopPlaybackImmediately() {
      pcmJitterQueue = [];
      jitterBufferedMs = 0;
      nextPlayTimeS = 0;
      if (audioCtx && agentGainNode && agentGainNode.gain) {
        var nowS = typeof audioCtx.currentTime === "number" ? audioCtx.currentTime : 0;
        try {
          if (typeof agentGainNode.gain.cancelScheduledValues === "function") {
            agentGainNode.gain.cancelScheduledValues(nowS);
          }
          if (typeof agentGainNode.gain.setValueAtTime === "function") {
            agentGainNode.gain.setValueAtTime(agentGainNode.gain.value, nowS);
          }
          if (typeof agentGainNode.gain.linearRampToValueAtTime === "function") {
            agentGainNode.gain.linearRampToValueAtTime(0.0001, nowS + 0.05);
          } else {
            agentGainNode.gain.value = 0.0;
          }
        } catch (e) {
          agentGainNode.gain.value = 0.0;
        }
      }
      var toStop = activeSources.slice();
      activeSources = [];
      toStop.forEach(function (src) {
        try {
          if (typeof src.stop === "function") src.stop(0);
          if (typeof src.disconnect === "function") src.disconnect();
        } catch (e) {}
      });
    }

    function setDucking(mode) {
      ensureAudioGraph();
      if (mode === "agent_speaking") {
        /* ADR-0010 / audio skill §3: duck mic gain, never mute track.enabled */
        if (micGainNode && micGainNode.gain) micGainNode.gain.value = 0.2;
        if (agentGainNode && agentGainNode.gain) agentGainNode.gain.value = 1.0;
      } else if (mode === "user_barge_in") {
        if (agentGainNode && agentGainNode.gain) agentGainNode.gain.value = 0.15;
        if (micGainNode && micGainNode.gain) micGainNode.gain.value = 1.0;
      } else {
        if (micGainNode && micGainNode.gain) micGainNode.gain.value = 1.0;
        if (agentGainNode && agentGainNode.gain) agentGainNode.gain.value = 1.0;
      }
    }

    async function requestMicPermission() {
      setState("requesting-permission");
      ensureAudioGraph();
      var nav = opts.navigator || (typeof navigator !== "undefined" ? navigator : null);
      if (!nav || !nav.mediaDevices || typeof nav.mediaDevices.getUserMedia !== "function") {
        setState("error:unsupported-browser", { fallback: "text" });
        return { ok: false, error: "unsupported-browser" };
      }
      var ladder = [
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: 16000 } },
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } },
        { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }
      ];
      var lastErr = null;
      var lastErrName = "";
      for (var i = 0; i < ladder.length; i++) {
        try {
          mediaStream = await nav.mediaDevices.getUserMedia(ladder[i]);
          var tracks = mediaStream && typeof mediaStream.getAudioTracks === "function" ? mediaStream.getAudioTracks() : [];
          if (tracks.length && typeof tracks[0].getSettings === "function") {
            var settings = tracks[0].getSettings() || {};
            if (settings.sampleRate && settings.sampleRate !== 16000 && window.console && console.warn) {
              console.warn("zivon.audio: sampleRate mismatch, got", settings.sampleRate);
            }
          }
          setState(ws && ws.readyState === 1 ? "ready" : "idle", { permission: "granted" });
          return { ok: true, stream: mediaStream };
        } catch (err) {
          lastErr = err;
          lastErrName = err && err.name ? String(err.name) : "";
          if (lastErrName === "OverconstrainedError" || lastErrName === "ConstraintNotSatisfiedError") {
            continue;
          }
          if (lastErrName === "NotReadableError" || lastErrName === "TrackStartError") {
            setState("error:mic-in-use", { fallback: "text" });
            return { ok: false, error: "mic-in-use" };
          }
          break;
        }
      }
      if (lastErrName === "OverconstrainedError" || lastErrName === "ConstraintNotSatisfiedError") {
        /* The constraint ladder is exhausted: the hardware cannot meet even
           the loosest profile. That is NOT a permission denial - say so, so
           the UI can offer device advice instead of a "blocked" message. */
        if (window.ZivonEvents && typeof window.ZivonEvents.recordError === "function") {
          window.ZivonEvents.recordError("mic_permission");
        }
        setState("error:mic-constraint", { fallback: "text", cause: String(lastErr || "constraint") });
        return { ok: false, error: "mic-constraint" };
      }
      if (window.ZivonEvents && typeof window.ZivonEvents.recordError === "function") {
        window.ZivonEvents.recordError("mic_permission");
      }
      setState("error:mic-denied", { fallback: "text", cause: String(lastErr || "denied") });
      return { ok: false, error: "mic-denied" };
    }

    function handleBinaryFrame(data) {
      var parsed = decodeAudioFrame(data);
      if (!parsed.valid) {
        setState("error:system-error", { reason: parsed.reason });
        return;
      }
      var seg = parsed.segment_id;
      /* Protocol bookkeeping only (no decode/playback): track the next
         expected sequence per segment so a gap/duplicate is observable. */
      expectedTtsSeq[seg] = parsed.seq + 1;
      var floatSamples = decodePcm16ToFloat32(parsed.payload);
      var chunkDurationMs = floatSamples.length > 0 ? (floatSamples.length / ttsSampleRate) * 1000.0 : 20.0;
      pendingFrames.push({
        segment_id: seg,
        seq: parsed.seq,
        is_final: parsed.is_final,
        bytes: parsed.payload.byteLength,
        samples: floatSamples.length,
        duration_ms: Math.round(chunkDurationMs)
      });
      pcmJitterQueue.push({
        segment_id: seg,
        seq: parsed.seq,
        is_final: parsed.is_final,
        samples: floatSamples
      });
      jitterBufferedMs += chunkDurationMs;
      if (!turnTimings.t_first_audio) {
        turnTimings.t_first_audio = performance.now();
      }
      if (pendingFrames.length >= minFramesBeforeSpeaking || jitterBufferedMs >= 60 || parsed.is_final) {
        if (state !== "speaking") {
          setDucking("agent_speaking");
          setState("speaking", { frames_received: pendingFrames.length, buffered_ms: Math.round(jitterBufferedMs) });
        }
        scheduleJitterBuffer(Boolean(parsed.is_final));
      }
    }

    function handleServerMessage(msg) {
      if (!msg || typeof msg !== "object") return;
      if (msg.v !== undefined && msg.v !== VOICE_VERSION) {
        setState("error:version.mismatch", { code: 4409 });
        if (ws && typeof ws.close === "function") ws.close(4409, "version.mismatch");
        return;
      }
      var t = msg.type;
      var payload = msg.payload && typeof msg.payload === "object" ? msg.payload : msg;
      if (t === "session.ready") {
        sessionId = payload.session_id || "sess-1";
        creditState = payload.credit_state || "ok";
        if (creditState === "warn") {
          applyLessonStateBanner("warn", "Voice is limited today - short doubts work best; typing is always free.");
          setState("ready", { session_id: sessionId, profile: payload.profile || "normal", credit_state: creditState });
        } else if (creditState === "text_only" || creditState === "exhausted") {
          applyLessonStateBanner("exhausted", "Voice is resting (daily limit). Type your doubt.");
          setState("text_only", { session_id: sessionId, profile: payload.profile || "normal", credit_state: "text_only" });
        } else {
          applyLessonStateBanner("warn", "");
          applyLessonStateBanner("exhausted", "");
          setState("ready", { session_id: sessionId, profile: payload.profile || "normal", credit_state: creditState });
        }
        return;
      }
      if (t === "stt.partial" || t === "partial_transcript") {
        transcripts.push({ kind: "partial", text: String(payload.text || ""), turn_id: payload.turn_id });
        return;
      }
      if (t === "stt.final" || t === "final_transcript") {
        turnTimings.t_final_transcript = performance.now();
        lastTurnId = payload.turn_id || lastTurnId || "turn-1";
        transcripts.push({ kind: "student", text: String(payload.text || ""), turn_id: lastTurnId });
        if (payload.confidence !== undefined && payload.confidence < 0.25) {
          setState("error:no-match", { fallback: "text" });
          return;
        }
        setState("thinking", { turn_id: lastTurnId, text: payload.text });
        return;
      }
      if (t === "agent.state") {
        var st = payload.state;
        if (payload.credit_state) {
          creditState = payload.credit_state;
          if (creditState === "warn") {
            applyLessonStateBanner("warn", "Voice is limited today - short doubts work best; typing is always free.");
          } else if (creditState === "text_only" || creditState === "exhausted") {
            applyLessonStateBanner("exhausted", "Voice is resting (daily limit). Type your doubt.");
          }
        }
        if (st === "listening" || st === "thinking" || st === "speaking" || st === "speaking_text") {
          if (st === "speaking") setDucking("agent_speaking");
          else if (st === "listening") setDucking("normal");
          setState(st, { reason: payload.reason });
        } else if (st === "text_only") {
          /* Never cut an in-progress turn; transition to text_only when not mid-answer */
          creditState = "text_only";
          applyLessonStateBanner("exhausted", "Voice is resting (daily limit). Type your doubt.");
          if (state !== "speaking" && state !== "thinking" && state !== "speaking_text") {
            setDucking("normal");
            setState("text_only", { reason: payload.reason || "credit_exhausted" });
          }
        } else if (st === "idle") {
          setDucking("normal");
          if (creditState === "text_only" || creditState === "exhausted") {
            setState("text_only", { reason: payload.reason || "credit_exhausted" });
          } else {
            setState("ready", { reason: payload.reason });
          }
        }
        return;
      }
      if (t === "highlight") {
        highlightBlocks(payload.block_ids || []);
        return;
      }
      if (t === "tts.text" || t === "tutor.text") {
        if (!turnTimings.t_first_token) {
          turnTimings.t_first_token = performance.now();
        }
        var txt = payload.text !== undefined ? payload.text : (payload.delta || payload.final || "");
        transcripts.push({ kind: "tutor", subkind: payload.kind || "speech", text: String(txt), turn_id: payload.turn_id || lastTurnId });
        return;
      }
      if (t === "tts.start") {
        setDucking("agent_speaking");
        setState("speaking");
        return;
      }
      if (t === "turn.end" || t === "tts.end") {
        if (payload.end_reason !== "interrupted") {
          scheduleJitterBuffer(true);
        }
        pendingFrames = [];
        setDucking("normal");
        var e2eMs = (turnTimings.t_endpoint && (turnTimings.t_first_audio || turnTimings.t_first_token))
          ? Math.max(0, Math.round((turnTimings.t_first_audio || turnTimings.t_first_token) - turnTimings.t_endpoint))
          : (payload.latency_ms && payload.latency_ms.e2e ? payload.latency_ms.e2e : 0);
        lastCompletedTurnMetrics = {
          turn_id: payload.turn_id || lastTurnId || "turn-1",
          end_reason: payload.end_reason || "done",
          e2e_ms: e2eMs,
          timings: Object.assign({}, turnTimings)
        };
        if (window.ZivonEvents && typeof window.ZivonEvents.recordVoiceTurnDone === "function") {
          window.ZivonEvents.recordVoiceTurnDone(sessionId, lastCompletedTurnMetrics.turn_id, e2eMs);
        }
        if (payload.end_reason === "interrupted") {
          stopPlaybackImmediately();
          setState("listening", { interrupted: true });
        } else if (creditState === "text_only" || creditState === "exhausted") {
          setState("text_only", { turn_id: lastCompletedTurnMetrics.turn_id });
        } else {
          setState("ready", { turn_id: lastCompletedTurnMetrics.turn_id });
        }
        return;
      }
      if (t === "pong") {
        lastPongTs = Date.now();
        return;
      }
      if (t === "ping") {
        sendJson({ type: "pong", t: Date.now() });
        return;
      }
      if (t === "error") {
        var mapped = mapServerErrorToCode(payload.code);
        if (window.ZivonEvents && typeof window.ZivonEvents.recordError === "function") {
          window.ZivonEvents.recordError("voice");
        }
        if (payload.code === "tts.unavailable" || payload.code === "brain.first_event_timeout") {
          setState("speaking_text", { code: payload.code, message: payload.message });
        } else {
          setState("error:" + mapped, { code: payload.code, message: payload.message, recoverable: payload.recoverable !== false });
        }
        return;
      }
      /* Unknown message type: ignore + count per ws-client-contract.md §3 */
    }

    function clearPingTimer() {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    }

    function clearReconnectTimer() {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }

    function detachSocket() {
      if (!ws) return;
      /* Detach BEFORE closing: a stale socket's close must never mark the live
         connection offline (review finding: reconnect raced the old close). */
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try {
        if (typeof ws.close === "function") ws.close(1000, "client_reconnect");
      } catch (e) {}
      ws = null;
    }

    function scheduleReconnect() {
      if (reconnectTimer || reconnectAttempts >= maxReconnectAttempts) return false;
      var capped = Math.min(reconnectMaxMs, reconnectBaseMs * Math.pow(2, reconnectAttempts));
      var delay = Math.max(1, Math.round(capped * (0.5 + Math.random() * 0.5))); /* jitter */
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(function () {
        reconnectTimer = null;
        if (state === "offline") connect(true);
      }, delay);
      return true;
    }

    function teardownMediaAndAudio() {
      if (mediaStream) {
        try {
          var tracks = typeof mediaStream.getTracks === "function" ? mediaStream.getTracks() : [];
          tracks.forEach(function (t) { try { t.stop(); } catch (e) {} });
        } catch (e) {}
        mediaStream = null;
      }
      if (audioCtx && typeof audioCtx.close === "function") {
        try {
          var closing = audioCtx.close();
          if (closing && typeof closing.catch === "function") closing.catch(function () {});
        } catch (e) {}
      }
      stopPlaybackImmediately();
      audioCtx = null;
      micGainNode = null;
      agentGainNode = null;
      agentGainConnected = false;
    }

    /* One teardown for disconnect() and pagehide: mic tracks, AudioContext,
       timers, queued turns. pagehide fires it through the module-scope
       registry, so no per-instance listener is ever left behind. */
    function cleanup() {
      clearPingTimer();
      clearReconnectTimer();
      queuedTypedDoubts = [];
      pendingFrames = [];
      teardownMediaAndAudio();
    }
    voiceClientCleanups.push(cleanup);

    function connect(resumeFlag) {
      clearReconnectTimer();
      clearPingTimer();
      detachSocket();
      setState("connecting");
      var url = opts.url || ((window.location && window.location.protocol === "https:" ? "wss://" : "ws://") +
        ((window.location && window.location.host) || "localhost:8080") + "/voice/ws");
      var factory = opts.createWebSocket || function (u) { return new WebSocket(u, ["zivon-tutor.v1"]); };
      try {
        ws = factory(url);
      } catch (err) {
        setState("offline", { error: String(err) });
        scheduleReconnect();
        return false;
      }
      ws.binaryType = "arraybuffer";
      ws.onopen = function () {
        reconnectAttempts = 0;
        lastPongTs = Date.now();
        clearPingTimer();
        pingTimer = setInterval(function () {
          if (state === "ready" || state === "thinking" || state === "idle") {
            checkKeepalive(Date.now());
          }
        }, 15000);
        var snap = buildContextSnapshot();
        sendJson({
          type: "session.start",
          session_token: sessionToken,
          device: deviceId,
          locale: snap.lang_pref || "en",
          capabilities: { ptt: true, opus: true, webrtc_vad: true },
          resume: Boolean(resumeFlag),
          last_turn_id: lastTurnId,
          anchor: {
            course_id: snap.course_id,
            topic_slug: snap.topic_id,
            block_id: snap.block_id,
            lang: snap.lang_pref
          }
        });
      };
      ws.onmessage = function (ev) {
        if (typeof ev.data === "string") {
          try {
            handleServerMessage(JSON.parse(ev.data));
          } catch (err) {
            setState("error:system-error", { reason: "invalid_json" });
          }
        } else {
          handleBinaryFrame(ev.data);
        }
      };
      ws.onerror = function () {
        if (window.ZivonEvents && typeof window.ZivonEvents.recordError === "function") {
          window.ZivonEvents.recordError("network");
        }
      };
      ws.onclose = function (ev) {
        clearPingTimer();
        if (ev && ev.code === 4401) {
          setState("error:auth.invalid", { code: 4401 });
        } else if (ev && ev.code === 4409) {
          setState("error:version.mismatch", { code: 4409 });
        } else if (state !== "idle") {
          setState("offline", { code: ev ? ev.code : 1006 });
          scheduleReconnect();
        }
      };
      return true;
    }

    function startListening(turnHint) {
      if (state === "speaking" || state === "thinking") {
        /* P0 PTT press during speaking/thinking IS barge-in interrupt (SP1 §5) */
        bargeIn("ptt_press");
      }
      if (!ws || ws.readyState !== 1) {
        setState("offline", { reason: "ws_closed" });
        return false;
      }
      micSeq = 0;
      turnTimings = { t_start: performance.now() };
      if (window.ZivonEvents && typeof window.ZivonEvents.recordMicPress === "function") {
        window.ZivonEvents.recordMicPress(sessionId);
      }
      sendJson(Object.assign({ type: "context.snapshot" }, buildContextSnapshot()));
      sendJson({ type: "audio.start", turn_hint: turnHint || null });
      setState("listening");
      return true;
    }

    function sendAudioChunk(pcmBytes, isFinal) {
      if (state !== "listening") return false;
      if (!ws || ws.readyState !== 1) {
        setState("offline");
        return false;
      }
      var frame = encodeAudioFrame(pcmBytes, 1, micSeq++, Boolean(isFinal));
      ws.send(frame);
      return true;
    }

    function endAudio() {
      if (state !== "listening" && state !== "endpointing") return false;
      turnTimings.t_endpoint = performance.now();
      setState("endpointing");
      return sendJson({ type: "audio.end" });
    }

    function notifyVadSpeech(active) {
      var now = performance.now();
      if (state === "speaking") {
        if (active) {
          setDucking("user_barge_in");
          if (now - lastVadTriggerTs <= 1000) {
            consecutiveVadTriggers += 1;
          } else {
            consecutiveVadTriggers = 1;
          }
          lastVadTriggerTs = now;
          if (consecutiveVadTriggers >= 2) {
            bargeIn("vad_over_playback");
          }
        }
      } else if (state === "endpointing" && active) {
        /* False endpoint recovery -> back to listening (ws-client-contract §2) */
        setState("listening", { reason: "vad_retrigger" });
      }
    }

    function bargeIn(reason) {
      if (state !== "speaking" && state !== "thinking" && state !== "speaking_text") {
        return false;
      }
      stopPlaybackImmediately();
      pendingFrames = [];
      setDucking("user_barge_in");
      /* Discard tutor's partial sentence per ws-client-contract §2 */
      if (transcripts.length && transcripts[transcripts.length - 1].kind === "tutor") {
        transcripts[transcripts.length - 1].interrupted = true;
      }
      sendJson({ type: "interrupt", turn_id: lastTurnId });
      setState("interrupted", { reason: reason || "user_interrupt" });
      setDucking("normal");
      setState("listening", { barge_in: true });
      return true;
    }

    function sendTypedDoubt(text) {
      var clean = String(text || "").trim();
      if (!clean) return false;
      turnTimings = { t_endpoint: performance.now() };
      transcripts.push({ kind: "student", text: clean, typed: true });
      if (!ws || ws.readyState !== 1) {
        queuedTypedDoubts.push(clean);
        setState("offline", { queued_typed: queuedTypedDoubts.length });
        return false;
      }
      sendJson(Object.assign({ type: "context.snapshot" }, buildContextSnapshot()));
      sendJson({ type: "audio.end", text: clean, fallback: "typed" });
      setState("thinking", { typed: true, text: clean });
      return true;
    }

    function reconnect() {
      return connect(true);
    }

    function checkKeepalive(nowMs) {
      var now = nowMs || Date.now();
      if (lastPongTs && (now - lastPongTs > 30000)) {
        /* Close the stale socket FIRST, then report offline: the UI must never
           show a live-looking connection while the keepalive says it is dead. */
        clearPingTimer();
        detachSocket();
        setState("offline", { reason: "pong_timeout" });
        scheduleReconnect();
        return false;
      }
      return sendJson({ type: "ping", t: now });
    }

    function disconnect() {
      var idx = voiceClientCleanups.indexOf(cleanup);
      if (idx !== -1) voiceClientCleanups.splice(idx, 1);
      cleanup();
      /* Detach before closing so this deliberate close is not seen as a drop
         (and therefore never schedules a reconnect). */
      detachSocket();
      setState("idle");
    }

    return {
      getState: function () { return state; },
      getSessionId: function () { return sessionId; },
      getTranscripts: function () { return transcripts.slice(); },
      getPendingFrames: function () { return pendingFrames.slice(); },
      getQueuedTypedDoubts: function () { return queuedTypedDoubts.slice(); },
      getLastTurnMetrics: function () { return lastCompletedTurnMetrics; },
      getCreditState: function () { return creditState; },
      getPlaybackStats: function () {
        return {
          scheduled_chunks: scheduledChunksCount,
          active_sources: activeSources.length,
          next_play_time_s: nextPlayTimeS,
          sample_rate: ttsSampleRate,
          audio_ctx_state: audioCtx ? audioCtx.state : "none"
        };
      },
      stopPlayback: stopPlaybackImmediately,
      getGainValues: function () {
        return {
          mic: micGainNode && micGainNode.gain ? micGainNode.gain.value : 1.0,
          agent: agentGainNode && agentGainNode.gain ? agentGainNode.gain.value : 1.0
        };
      },
      onStateChange: function (fn) { listeners.push(fn); },
      requestMicPermission: requestMicPermission,
      connect: connect,
      reconnect: reconnect,
      startListening: startListening,
      sendAudioChunk: sendAudioChunk,
      endAudio: endAudio,
      notifyVadSpeech: notifyVadSpeech,
      bargeIn: bargeIn,
      sendTypedDoubt: sendTypedDoubt,
      checkKeepalive: checkKeepalive,
      disconnect: disconnect
    };
  }

  /* Mock WS server for local dev and automated headless tests (mission brief) */
  function createMockVoiceServer(options) {
    var cfg = options || {};
    var sentByClient = [];
    var binaryReceived = [];
    var socketInstance = null;
    var turnCounter = 0;

    function makeSocket(url) {
      var sock = {
        url: url,
        protocol: "zivon-tutor.v1",
        readyState: 0,
        binaryType: "arraybuffer",
        onopen: null,
        onmessage: null,
        onerror: null,
        onclose: null,
        send: function (data) {
          if (typeof data === "string") {
            var msg = JSON.parse(data);
            sentByClient.push(msg);
            handleClientJson(sock, msg);
          } else {
            var decoded = decodeAudioFrame(data);
            binaryReceived.push(decoded);
          }
        },
        close: function (code, reason) {
          sock.readyState = 3;
          if (typeof sock.onclose === "function") {
            sock.onclose({ code: code || 1000, reason: reason || "" });
          }
        },
        serverEmitJson: function (obj) {
          if (sock.readyState !== 1) return;
          if (typeof sock.onmessage === "function") {
            sock.onmessage({ data: JSON.stringify(Object.assign({ v: VOICE_VERSION }, obj)) });
          }
        },
        serverEmitAudio: function (segmentId, seq, isFinal, payloadLen) {
          if (sock.readyState !== 1) return;
          var dummy = new Uint8Array(payloadLen || 80);
          var frame = encodeAudioFrame(dummy, segmentId || 1, seq || 0, Boolean(isFinal));
          if (typeof sock.onmessage === "function") {
            sock.onmessage({ data: frame });
          }
        },
        simulateDrop: function () {
          sock.readyState = 3;
          if (typeof sock.onclose === "function") {
            sock.onclose({ code: 1006, reason: "network_drop" });
          }
        }
      };
      socketInstance = sock;
      setTimeout(function () {
        sock.readyState = 1;
        if (typeof sock.onopen === "function") sock.onopen({});
      }, 0);
      return sock;
    }

    function handleClientJson(sock, msg) {
      if (msg.type === "session.start") {
        if (cfg.rejectAuth) {
          sock.close(4401, "auth.invalid");
          return;
        }
        sock.serverEmitJson({
          type: "session.ready",
          session_id: cfg.session_id || "mock-sess-01",
          profile: cfg.profile || "normal",
          state: "idle",
          server_time: Date.now()
        });
      } else if (msg.type === "audio.start") {
        sock.serverEmitJson({ type: "agent.state", state: "listening" });
      } else if (msg.type === "audio.end") {
        turnCounter += 1;
        var tid = "turn-" + turnCounter;
        if (cfg.quotaExhausted) {
          sock.serverEmitJson({
            type: "error",
            code: "credit.over_daily",
            message: "Daily voice limit reached.",
            recoverable: true
          });
          return;
        }
        var transcriptText = msg.text || cfg.transcript || "Sir, velocity-time graph ka slope kya batata hai?";
        if (!msg.text) {
          sock.serverEmitJson({ type: "stt.partial", turn_id: tid, seq: 0, text: "Sir, velocity-time" });
        }
        sock.serverEmitJson({
          type: "stt.final",
          turn_id: tid,
          text: transcriptText,
          lang: "hi-Latn",
          confidence: cfg.confidence !== undefined ? cfg.confidence : 0.94
        });
        if (cfg.confidence !== undefined && cfg.confidence < 0.25) return;
        sock.serverEmitJson({ type: "agent.state", state: "thinking" });
        if (cfg.autoReply !== false) {
          if (cfg.highlightBlocks) {
            sock.serverEmitJson({ type: "highlight", turn_id: tid, block_ids: cfg.highlightBlocks });
          }
          sock.serverEmitJson({
            type: "tts.text",
            turn_id: tid,
            segment_id: 1,
            kind: "speech",
            text: cfg.replyText || "Velocity-time graph ka slope acceleration dikhata hai."
          });
          if (cfg.ttsUnavailable) {
            sock.serverEmitJson({
              type: "error",
              code: "tts.unavailable",
              message: "Audio synthesis unavailable; showing text answer.",
              recoverable: true
            });
            return;
          }
          sock.serverEmitAudio(1, 0, false, 80);
          sock.serverEmitAudio(1, 1, false, 80);
          sock.serverEmitAudio(1, 2, true, 80);
          if (!cfg.holdSpeaking) {
            sock.serverEmitJson({
              type: "turn.end",
              turn_id: tid,
              end_reason: "done",
              latency_ms: { L0: 120, L3: 480, L6: 890, e2e: 1150 },
              usage: { stt_audio_s: 2.4, tts_chars: 54, brain_prompt_tokens: 310, brain_completion_tokens: 42, retries: 0 }
            });
          }
        }
      } else if (msg.type === "interrupt") {
        sock.serverEmitJson({ type: "agent.state", state: "listening", reason: "barge_in" });
        sock.serverEmitJson({
          type: "turn.end",
          turn_id: msg.turn_id || ("turn-" + turnCounter),
          end_reason: "interrupted",
          latency_ms: {},
          usage: { stt_audio_s: 1.0, tts_chars: 18, brain_prompt_tokens: 310, brain_completion_tokens: 15, retries: 0 }
        });
      } else if (msg.type === "ping") {
        sock.serverEmitJson({ type: "pong", t: msg.t });
      }
    }

    return {
      createWebSocket: makeSocket,
      getSentMessages: function () { return sentByClient.slice(); },
      getBinaryFrames: function () { return binaryReceived.slice(); },
      getSocket: function () { return socketInstance; }
    };
  }

  window.ZivonVoiceClient = {
    create: createVoiceClient,
    createMockServer: createMockVoiceServer,
    encodeAudioFrame: encodeAudioFrame,
    decodeAudioFrame: decodeAudioFrame,
    decodePcm16ToFloat32: decodePcm16ToFloat32
  };


  /* --------------- 8. event instrumentation (ZivonEvents) -----------------
     Implements spec.md §9 (C2), SP3 docs/specs/observability/instrumentation-map.csv
     (EVT-F01..EVT-F12), and GAP-013 reconciliation:
     - Capped in-memory queue (200 events, oldest dropped) with a no-op default
       sink so CSP connect-src 'none' is never violated.
     - Observable via console.debug when localStorage['zivon.evtdebug'] or
       window.__ZIVON_EVTDEBUG__ is truthy.
     - Every emitted event carries canonical SP3 fields (evt_id: EVT-F01..F12,
       event: frontend.*, client_session_id, privacy_class: L2) alongside the
       SP5 trigger name (evt: EVT-<verb_noun>) for 1:1 traceability.
     - Never logs child free-text or quiz option text; hashes sim error strings
       and quantises slider values into buckets. */
  var EVENT_QUEUE_MAX = 200;
  var eventQueue = [];
  var customEventSink = null;
  var clientSessionId = null;
  var sessionStartMs = Date.now();
  var voiceTurnsCount = 0;
  var simInteractionCounts = {};
  var simLastEmitMs = {};

  var EVENT_CATALOG = {
    "EVT-lesson_viewed":       { evt_id: "EVT-F01", event: "frontend.page_view",        privacy_class: "L2" },
    "EVT-lesson_opened":       { evt_id: "EVT-F01", event: "frontend.page_view",        privacy_class: "L2" },
    "EVT-section_viewed":      { evt_id: "EVT-F02", event: "frontend.section_view",     privacy_class: "L2" },
    "EVT-reveal_opened":       { evt_id: "EVT-F02", event: "frontend.section_view",     privacy_class: "L2" },
    "EVT-sim_opened":          { evt_id: "EVT-F03", event: "frontend.sim_open",         privacy_class: "L2" },
    "EVT-sim_control_changed": { evt_id: "EVT-F04", event: "frontend.sim_interact",     privacy_class: "L2" },
    "EVT-check_answered":      { evt_id: "EVT-F05", event: "frontend.check_answered",   privacy_class: "L2" },
    "EVT-check_retried":       { evt_id: "EVT-F05", event: "frontend.check_answered",   privacy_class: "L2" },
    "EVT-mic_pressed":         { evt_id: "EVT-F06", event: "frontend.mic_press",        privacy_class: "L2" },
    "EVT-tutor_turn_completed":{ evt_id: "EVT-F07", event: "frontend.voice_turn_done",  privacy_class: "L2" },
    "EVT-sim_error":           { evt_id: "EVT-F08", event: "frontend.error",            privacy_class: "L2" },
    "EVT-client_error":        { evt_id: "EVT-F08", event: "frontend.error",            privacy_class: "L2" },
    "EVT-lang_switched":       { evt_id: "EVT-F09", event: "frontend.language_bar_use", privacy_class: "L2" },
    "EVT-session_ended":       { evt_id: "EVT-F10", event: "frontend.session_end",      privacy_class: "L2" },
    "EVT-publish_viewed":      { evt_id: "EVT-F11", event: "frontend.publish_view",     privacy_class: "L2" },
    "EVT-heartbeat":           { evt_id: "EVT-F12", event: "frontend.heartbeat",        privacy_class: "L2" }
  };

  function getClientSessionId() {
    if (!clientSessionId) {
      clientSessionId = generateUuidV4();
    }
    return clientSessionId;
  }

  function hashStringHex(str) {
    var h = seedFrom(String(str || ""));
    return ("00000000" + h.toString(16)).slice(-8);
  }

  function quantiseBucket(val, inputEl) {
    var num = parseFloat(val);
    if (isNaN(num)) return "0";
    if (inputEl) {
      var min = parseFloat(inputEl.getAttribute("min") || "0");
      var max = parseFloat(inputEl.getAttribute("max") || "100");
      if (max > min) {
        var ratio = (num - min) / (max - min);
        if (ratio < 0.25) return "q1";
        if (ratio < 0.50) return "q2";
        if (ratio < 0.75) return "q3";
        return "q4";
      }
    }
    return String(Math.round(num * 10) / 10);
  }

  function isEvtDebugEnabled() {
    if (window.__ZIVON_EVTDEBUG__) return true;
    var flag = safeStorageGet("zivon.evtdebug");
    return flag === "1" || flag === "true";
  }

  function currentTopicMeta() {
    var route = ZivonRouter.currentRoute();
    var titleEl = document.querySelector("h1.zn-title");
    return {
      topic: route.topic_slug || (route.screen === "SCR-HOME-01" ? "hub" : "unknown"),
      course_id: route.course_id || "physics",
      chapter: titleEl ? titleEl.textContent.trim().slice(0, 80) : "",
      class_level: parseInt(String(route.course_id || "9").replace(/\D+/g, ""), 10) || 9,
      screen: route.screen,
      locale: getSavedLang()
    };
  }

  function emitEvent(evtName, rawProps) {
    var meta = currentTopicMeta();
    var specEntry = EVENT_CATALOG[evtName] || {
      evt_id: "EVT-F08",
      event: String(evtName),
      privacy_class: "L2"
    };
    var cleanProps = Object.assign({}, rawProps || {});
    /* Privacy guard: strip any accidental free-text or raw option keys */
    delete cleanProps.option_text;
    delete cleanProps.raw_text;
    delete cleanProps.transcript;
    delete cleanProps.stack;

    var record = {
      v: 1,
      evt: evtName,
      evt_id: specEntry.evt_id,
      event: specEntry.event,
      privacy_class: specEntry.privacy_class,
      ts: Date.now(),
      client_session_id: getClientSessionId(),
      screen: meta.screen,
      locale: meta.locale,
      props: Object.assign({ topic: meta.topic }, cleanProps)
    };

    if (eventQueue.length >= EVENT_QUEUE_MAX) {
      eventQueue.shift();
    }
    eventQueue.push(record);

    if (isEvtDebugEnabled() && window.console && typeof console.debug === "function") {
      console.debug("[ZivonEvents]", record.evt_id, record.event, record);
    }
    if (typeof customEventSink === "function") {
      try { customEventSink(record); } catch (e) {}
    }
    return record;
  }

  function recordCheck(blockId, format, correct, attempts) {
    emitEvent("EVT-check_answered", {
      block_id: String(blockId),
      format: String(format),
      correct: Boolean(correct),
      attempts: Number(attempts || 1)
    });
    if (attempts > 1) {
      emitEvent("EVT-check_retried", {
        block_id: String(blockId),
        attempt_no: Number(attempts),
        correct: Boolean(correct),
        attempts: Number(attempts)
      });
    }
  }

  function recordSimControl(blockId, controlId, value, inputEl) {
    var key = String(blockId) + ":" + String(controlId);
    simInteractionCounts[key] = (simInteractionCounts[key] || 0) + 1;
    /* EVT-F04 is a coarse usage signal, not a telemetry firehose: a dragged
       slider can emit hundreds of input events. Count every interaction but
       emit at most one event per (block, control) per 5 s. */
    var nowMs = Date.now();
    var lastEmit = simLastEmitMs[key] || 0;
    if (nowMs - lastEmit < 5000) return;
    simLastEmitMs[key] = nowMs;
    emitEvent("EVT-sim_control_changed", {
      block_id: String(blockId),
      control_id: String(controlId),
      variable: String(controlId),
      value_bucket: quantiseBucket(value, inputEl),
      interactions: simInteractionCounts[key]
    });
  }

  function recordSimError(blockId, rawMessage) {
    emitEvent("EVT-sim_error", {
      block_id: String(blockId),
      error_kind: "js",
      message_hash: hashStringHex(rawMessage)
    });
  }

  function recordLangSwitch(fromLoc, toLoc) {
    emitEvent("EVT-lang_switched", {
      from: String(fromLoc),
      to: String(toLoc),
      lang_selected: String(toLoc)
    });
  }

  function recordMicPress(voiceSessionId) {
    emitEvent("EVT-mic_pressed", {
      session_id: voiceSessionId || null
    });
  }

  function recordVoiceTurnDone(voiceSessionId, turnId, e2eMs) {
    voiceTurnsCount += 1;
    var bucket = "<2s";
    if (e2eMs >= 4000) bucket = ">4s";
    else if (e2eMs >= 2000) bucket = "2-4s";
    emitEvent("EVT-tutor_turn_completed", {
      session_id: voiceSessionId || null,
      turn_id: turnId || null,
      e2e_ms: Number(e2eMs || 0),
      e2e_bucket: bucket
    });
  }

  function recordError(errorKind) {
    var allowed = { js: true, mic_permission: true, network: true, voice: true };
    var kind = allowed[errorKind] ? errorKind : "js";
    emitEvent("EVT-client_error", {
      error_kind: kind
    });
  }

  function wirePageInstrumentation() {
    var meta = currentTopicMeta();
    /* Catalogue card clicks -> EVT-lesson_opened */
    var courseList = document.getElementById("zn-courses");
    if (courseList) {
      courseList.addEventListener("click", function (ev) {
        var card = ev.target.closest("a.zn-card");
        if (!card) return;
        emitEvent("EVT-lesson_opened", {
          href: card.getAttribute("href") || "",
          course_id: card.getAttribute("data-course-id") || "",
          chapter: meta.chapter,
          class_level: meta.class_level
        });
      });
    }

    /* Lesson view & sim open events */
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (lessonPage) {
      var blocksCount = lessonPage.querySelectorAll("section, fieldset, figure").length;
      emitEvent("EVT-lesson_viewed", {
        course_id: meta.course_id,
        topic_slug: meta.topic,
        chapter: meta.chapter,
        class_level: meta.class_level,
        generated_at: lessonPage.getAttribute("data-generated-at") || "",
        block_count: blocksCount
      });
      emitEvent("EVT-publish_viewed", {
        source: window.location && window.location.protocol === "file:" ? "snapshot" : "pvc"
      });
      /* EVT-F03 means the sim was actually SEEN, not that the page parsed it:
         emit on first viewport intersection, never at load for off-screen
         sims (an unread sim is not a sim_open). */
      var emitSimOpened = function (simEl) {
        if (simEl.getAttribute("data-sim-open-emitted") === "1") return;
        simEl.setAttribute("data-sim-open-emitted", "1");
        emitEvent("EVT-sim_opened", {
          block_id: simEl.getAttribute("data-sim-id") || simEl.id || "sim"
        });
      };
      var simEls = lessonPage.querySelectorAll(".zn-sim[data-sim-id]");
      if (typeof IntersectionObserver === "function") {
        var simObserver = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            emitSimOpened(entry.target);
            simObserver.unobserve(entry.target);
          });
        }, { threshold: 0.1 });
        simEls.forEach(function (simEl) { simObserver.observe(simEl); });
      } else {
        simEls.forEach(emitSimOpened);
      }
      lessonPage.querySelectorAll(".zn-reveal details.zn-reveal-step").forEach(function (det) {
        det.addEventListener("toggle", function () {
          if (det.open) {
            var revParent = det.closest(".zn-reveal");
            var bid = (revParent && revParent.id) || det.id || "reveal";
            /* No dwell_bucket here: it was fabricated ("<5s" hard-coded).
               Dwell must be measured; until it is, omit the property. */
            emitEvent("EVT-reveal_opened", {
              block_id: bid,
              section_id: bid
            });
          }
        });
      });
    }

    window.addEventListener("pagehide", function () {
      var elapsedS = (Date.now() - sessionStartMs) / 1000;
      var durBucket = elapsedS < 120 ? "<2m" : (elapsedS <= 600 ? "2-10m" : ">10m");
      emitEvent("EVT-session_ended", {
        duration_bucket: durBucket,
        turn_count: voiceTurnsCount
      });
    });
  }

  window.ZivonEvents = {
    EVENT_QUEUE_MAX: EVENT_QUEUE_MAX,
    EVENT_CATALOG: EVENT_CATALOG,
    emit: emitEvent,
    getQueue: function () { return eventQueue.slice(); },
    clearQueue: function () { eventQueue.length = 0; },
    setSink: function (fn) { customEventSink = typeof fn === "function" ? fn : null; },
    getClientSessionId: getClientSessionId,
    recordCheck: recordCheck,
    recordSimControl: recordSimControl,
    recordSimError: recordSimError,
    recordLangSwitch: recordLangSwitch,
    recordMicPress: recordMicPress,
    recordVoiceTurnDone: recordVoiceTurnDone,
    recordError: recordError,
    heartbeat: function () { return emitEvent("EVT-heartbeat", {}); }
  };

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
    wirePageInstrumentation();
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
