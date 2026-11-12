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
    if (norm.indexOf("/courses/") === 0) {
      var base = norm.replace(/\/(hi|hi-Latn)\/?$/, "/");
      return base.replace(/\/?$/, "/") + loc + "/";
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
        return !el || !el.closest(".zn-sim-read, .zn-voice-dock-region, .zn-consent-sheet, .zn-report-wrap, .zn-read-aloud-wrap, .zn-read-aloud-progress, .zn-footer-links, .zn-status-chip");
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
    if (!saved) {
      /* A direct visit to /<topic>/<locale>/ must start in that locale. */
      var docLang = (document.documentElement && document.documentElement.lang) || "";
      return AUTONYM_TO_CODE[docLang.toLowerCase()] || docLang || "en";
    }
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

  function isLocaleBundleAvailable(loc) {
    var code = String(loc || "en");
    if (code === "en") return true;
    var i18n = window.ZIVON_I18N;
    if (i18n && typeof i18n === "object" && Object.prototype.hasOwnProperty.call(i18n, code)) {
      return true;
    }
    var mf = window.__ZIVON_MANIFEST__;
    if (mf && Array.isArray(mf.locales_available) && mf.locales_available.indexOf(code) !== -1) {
      return true;
    }
    if (document.querySelector('link[rel="alternate"][hreflang="' + code + '"]')) {
      return true;
    }
    return false;
  }

  function syncLangBarBundleAvailability(row) {
    var bar = document.querySelector(".zn-lang-bar");
    if (bar && !bar.getAttribute("data-element-id")) {
      bar.setAttribute("data-element-id", "EL-LES-01-006");
    }
    if (!row) return;
    var chips = Array.prototype.slice.call(row.querySelectorAll(".zn-chip"));
    chips.forEach(function (c) {
      var code = chipLocaleCode(c);
      if (!c.getAttribute("data-lang")) c.setAttribute("data-lang", code);
      if (!c.getAttribute("data-locale")) c.setAttribute("data-locale", code);
      if (!c.getAttribute("data-element-id")) {
        if (code === "en") c.setAttribute("data-element-id", "EL-LES-01-007");
        else if (code === "hi") c.setAttribute("data-element-id", "EL-LES-01-008");
        else if (code === "hi-Latn") c.setAttribute("data-element-id", "EL-LES-01-009");
      }
      var route = ZivonRouter.currentRoute();
      if (!c.getAttribute("data-href") && route.canonical_path) {
        c.setAttribute("data-href", ZivonRouter.buildLocalizedHref(route.canonical_path, code));
      }
      var hasBundle = isLocaleBundleAvailable(code);
      if (!hasBundle && code !== "en") {
        c.setAttribute("aria-disabled", "true");
        c.setAttribute("title", "Translation bundle not generated yet for " + (c.textContent || code).trim() + " — showing reviewed English.");
      } else {
        c.removeAttribute("aria-disabled");
        c.removeAttribute("title");
      }
    });
  }

  function applyClientBundleSwap(locale) {
    var root = window.ZIVON_I18N;
    if (!root || typeof root !== "object") return false;
    var locData = root[locale];
    if (!locData || typeof locData !== "object") return false;
    document.documentElement.lang = locale;
    var strings = locData.strings || {};
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (key && Object.prototype.hasOwnProperty.call(strings, key)) {
        el.textContent = String(strings[key]);
      }
    });
    return true;
  }

  function announceLangStatus(msg) {
    var host = document.querySelector(".zn-lang-in") || document.querySelector(".zn-lang-bar");
    if (!host) return;
    var status = host.querySelector(".zn-lang-status");
    if (!status) {
      status = document.createElement("span");
      status.className = "zn-lang-status zn-sr-only";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      host.appendChild(status);
    }
    status.textContent = msg || "";
    return status;
  }

  function selectLangChip(row, targetChip, persistAndEmit) {
    if (!row || !targetChip) return;
    /* A chip with aria-disabled has no translation bundle: selecting it would
       persist a locale with no strings, run the untranslated-notice path and
       wrongly suppress read-aloud. Say so honestly and change nothing. */
    if (targetChip.getAttribute("aria-disabled") === "true") {
      var msg =
        "इस भाषा में अभी अनुवाद नहीं है / not translated yet — showing reviewed English.";
      announceLangStatus(msg);
      var statusEl = row.querySelector(".zn-lang-status");
      if (statusEl) {
        statusEl.textContent = msg;
        statusEl.classList.remove("zn-sr-only");
      }
      return;
    }
    var chips = Array.prototype.slice.call(row.querySelectorAll(".zn-chip"));
    var prevChip = row.querySelector('.zn-chip[aria-checked="true"]');
    var fromCode = prevChip ? chipLocaleCode(prevChip) : "en";
    var toCode = chipLocaleCode(targetChip);
    if (toCode !== "en") {
      announceLangStatus("Language: " + (targetChip.textContent || toCode).trim());
    } else {
      announceLangStatus("Language: English");
    }

    chips.forEach(function (c) {
      var isTarget = c === targetChip;
      c.setAttribute("aria-checked", String(isTarget));
      c.setAttribute("tabindex", isTarget ? "0" : "-1");
    });

    if (isLocaleBundleAvailable(toCode) && toCode !== "en") {
      applyClientBundleSwap(toCode);
    }

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
      /* A locale with a generated page lives at <topic>/<locale>/ (the
         renderer writes it next to its bundle). English is the bare topic
         path. Only navigate when the target differs from where we are. */
      if (/\/courses\//.test(window.location.pathname)) {
        var basePath = window.location.pathname.replace(/\/(hi|hi-Latn)\/?$/, "/");
        var targetPath =
          toCode === "en" ? basePath : basePath.replace(/\/$/, "/") + toCode + "/";
        if (targetPath !== window.location.pathname) {
          window.location.assign(targetPath);
          return;
        }
      }
    }
    /* §10.13: read-aloud buttons follow the active locale; a locale with no
       narration shows no buttons. Rebuild them on every switch. */
    refreshReadAloudForLocale();
  }

  function wireLangChips() {
    var row = document.querySelector(".zn-lang-row");
    if (!row) return;
    var chips = Array.prototype.slice.call(row.querySelectorAll(".zn-chip"));
    if (!chips.length) return;
    syncLangBarBundleAvailability(row);

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
        /* Skip chips with no bundle when moving the roving selection: focus
           may land on them, but the selected language must stay honest. */
        if (nextChip.getAttribute("aria-disabled") === "true") {
          nextChip.focus();
          return;
        }
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

  /* One network seam for every same-origin call. A file:// document has no
     server to answer and Chromium logs a hard console error for every
     attempted fetch, so offline previews get ONE typed failure: every caller
     (report, consent sync, data wipe, telemetry flush, manifest load) handles
     NoTransportError explicitly — no caller mistakes a synthetic "ok:false"
     response for a real server answer, and no call is silently swallowed. */
  function NoTransportError(message) {
    this.name = "NoTransportError";
    this.message = message || "No network transport in this document (file:// preview).";
  }
  NoTransportError.prototype = Object.create(Error.prototype);
  NoTransportError.prototype.constructor = NoTransportError;

  function hasNetworkTransport() {
    return typeof location === "undefined" || location.protocol !== "file:";
  }

  function sameOriginRequest(url, options) {
    if (!hasNetworkTransport()) {
      return Promise.reject(new NoTransportError());
    }
    if (typeof fetch !== "function") {
      return Promise.reject(new Error("http_unavailable"));
    }
    return fetch(url, options || {});
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

  function refreshReadAloudForLocale() {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return;
    stopReadAloud();
    lessonPage.querySelectorAll(".zn-read-aloud-wrap, .zn-read-aloud-progress").forEach(function (el) {
      el.remove();
    });
    lessonPage.removeAttribute("data-zn-readaloud-mounted");
    injectReadAloudControls(window.__ZIVON_MANIFEST__ || null);
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

    /* Offline gating (EL-LES-01-012 `disabled-offline`): narration is a
       network fetch, so an offline page disables the control and says why
       instead of offering a button that can only fail. */
    function syncReadAloudOffline() {
      var off = typeof navigator !== "undefined" && navigator.onLine === false;
      lessonPage.querySelectorAll(".zn-read-aloud-btn").forEach(function (b) {
        b.disabled = off;
        if (off) {
          b.title = "Offline — narration needs a connection.";
          b.setAttribute("data-state", "disabled-offline");
        } else if (b.getAttribute("data-state") === "disabled-offline") {
          b.removeAttribute("title");
          b.setAttribute("data-state", "default");
        }
      });
      if (off) stopReadAloud();
    }
    if (lessonPage.getAttribute("data-zn-readaloud-netwired") !== "true") {
      lessonPage.setAttribute("data-zn-readaloud-netwired", "true");
      window.addEventListener("online", syncReadAloudOffline);
      window.addEventListener("offline", syncReadAloudOffline);
    }

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
      btn.setAttribute("data-state", "default");
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

      function failNarration(message) {
        /* Honest, recoverable failure: reset the control, announce once.
           A 404/CSP/decode failure must never leave a dead "playing" pill.
           Stale failures (the student already started another block) are
           ignored so they cannot stop the live track. */
        if (activeNarrationBtn !== btn && btn.getAttribute("aria-pressed") !== "true") return;
        stopReadAloud();
        btn.setAttribute("data-state", "error");
        span.textContent = "▶ सुनो / Listen";
        statusSr.textContent = message || "Audio could not be played.";
      }

      btn.addEventListener("click", function () {
        if (typeof navigator !== "undefined" && navigator.onLine === false) {
          statusSr.textContent = "You are offline — narration needs a connection.";
          return;
        }
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
        btn.setAttribute("data-state", "loading");
        btn.setAttribute("aria-pressed", "true");
        span.textContent = "■ रोकें / Stop";
        statusSr.textContent = "playing narration";
        var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (!reduceMotion) {
          prog.style.transform = "scaleX(0.15)";
        }
        try {
          var playPromise = audio.play();
          if (playPromise && typeof playPromise.then === "function") {
            playPromise.then(function () {
              btn.setAttribute("data-state", "playing");
            }, function (err) {
              /* CSP block, 404, autoplay refusal: handle, never swallow. */
              failNarration(err && err.name === "NotAllowedError"
                ? "Playback was blocked by the browser — press Listen again."
                : "Narration could not be played. Check your connection and try again.");
            });
          }
        } catch (err) {
          failNarration("Narration could not be played. Check your connection and try again.");
        }
      });

      audio.addEventListener("error", function () {
        failNarration("Narration audio is unavailable right now — try again later.");
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

    syncReadAloudOffline();
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

  /* ---------------- §2.5 Provenance Report (F-COR-PROV-01) ------------------
     Injects report button (EL-LES-01-040) + form panel (EL-LES-01-041) into
     the lesson footer (.zn-footer). Submits to POST /v1/reports with
     course_id, block_id, category, optional text (<= 500 chars), and zero PII.
     Honest success/error states; keeps draft on failure; never blocks reading. */
  function injectReportSurface() {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return { mounted: false };
    var footer = lessonPage.querySelector(".zn-footer");
    if (!footer) return { mounted: false };
    var existingBtn = footer.querySelector('[data-element-id="EL-LES-01-040"]');
    var existingPanel = footer.querySelector('[data-element-id="EL-LES-01-041"]');
    if (existingBtn && existingPanel) {
      return { mounted: true, button: existingBtn, panel: existingPanel };
    }

    var wrap = document.createElement("div");
    wrap.className = "zn-report-wrap";
    wrap.setAttribute("data-zn-mounted", "true");
    wrap.setAttribute("data-ruled-skip", "true");

    var reportBtn = document.createElement("button");
    reportBtn.type = "button";
    reportBtn.className = "zn-report-btn";
    reportBtn.setAttribute("data-element-id", "EL-LES-01-040");
    reportBtn.setAttribute("aria-expanded", "false");
    reportBtn.textContent = "Report a problem";

    var panel = document.createElement("form");
    panel.className = "zn-report-panel";
    panel.setAttribute("data-element-id", "EL-LES-01-041");
    panel.setAttribute("data-report-state", "default");
    panel.hidden = true;

    var catLabel = document.createElement("label");
    catLabel.className = "zn-report-field";
    var catSpan = document.createElement("span");
    catSpan.textContent = "What needs fixing?";
    var catSelect = document.createElement("select");
    catSelect.className = "zn-report-category";
    catSelect.name = "category";
    [
      { value: "wrong_physics", label: "Wrong physics / calculation" },
      { value: "bad_translation", label: "Bad translation" },
      { value: "broken_sim", label: "Broken simulation or diagram" },
      { value: "other", label: "Other issue" }
    ].forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      catSelect.appendChild(o);
    });
    catLabel.appendChild(catSpan);
    catLabel.appendChild(catSelect);

    var txtLabel = document.createElement("label");
    txtLabel.className = "zn-report-field";
    var txtSpan = document.createElement("span");
    txtSpan.textContent = "Short note (optional, do not include your name or contact info):";
    var txtArea = document.createElement("textarea");
    txtArea.className = "zn-report-text";
    txtArea.name = "text";
    txtArea.rows = 2;
    txtArea.maxLength = 500;
    txtArea.placeholder = "Describe the issue briefly…";
    txtLabel.appendChild(txtSpan);
    txtLabel.appendChild(txtArea);

    var btnRow = document.createElement("div");
    btnRow.className = "zn-report-actions";
    var submitBtn = document.createElement("button");
    submitBtn.type = "submit";
    submitBtn.className = "zn-report-submit";
    submitBtn.textContent = "Send report";
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "zn-report-cancel";
    cancelBtn.textContent = "Cancel";
    btnRow.appendChild(submitBtn);
    btnRow.appendChild(cancelBtn);

    var statusMsg = document.createElement("p");
    statusMsg.className = "zn-report-status";
    statusMsg.setAttribute("role", "status");
    statusMsg.setAttribute("aria-live", "polite");
    statusMsg.hidden = true;

    [catLabel, txtLabel, btnRow, statusMsg].forEach(function (el) { panel.appendChild(el); });
    wrap.appendChild(reportBtn);
    wrap.appendChild(panel);
    footer.appendChild(wrap);

    function syncReportOffline() {
      var isOff = typeof navigator !== "undefined" && navigator.onLine === false;
      reportBtn.disabled = isOff;
      if (isOff) {
        reportBtn.title = "Offline - reports require a connection.";
        panel.setAttribute("data-report-state", "error-offline");
      } else {
        reportBtn.removeAttribute("title");
      }
    }
    window.addEventListener("online", syncReportOffline);
    window.addEventListener("offline", syncReportOffline);
    syncReportOffline();

    reportBtn.addEventListener("click", function () {
      var open = panel.hidden;
      panel.hidden = !open;
      reportBtn.setAttribute("aria-expanded", String(open));
      if (open) {
        panel.setAttribute("data-report-state", "open");
        try { catSelect.focus(); } catch (e) {}
      }
    });

    cancelBtn.addEventListener("click", function () {
      panel.hidden = true;
      reportBtn.setAttribute("aria-expanded", "false");
      try { reportBtn.focus(); } catch (e) {}
    });

    panel.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        panel.setAttribute("data-report-state", "error-offline");
        statusMsg.hidden = false;
        statusMsg.textContent = "Could not send while offline — your note is kept.";
        return;
      }
      var snap = buildContextSnapshot();
      var catVal = catSelect.value || "other";
      var noteVal = (txtArea.value || "").trim().slice(0, 500);
      panel.setAttribute("data-report-state", "sending");
      submitBtn.disabled = true;
      statusMsg.hidden = false;
      statusMsg.textContent = "Sending…";
      try {
        var payload = {
          course_id: snap.course_id || "physics",
          class_level: snap.class || 9,
          block_id: snap.block_id || "b-01",
          category: catVal,
          device_pseudo_id: getDevicePseudoId()
        };
        if (noteVal) payload.text = noteVal;
        var res = await sameOriginRequest("/v1/reports", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res && res.ok) {
          panel.setAttribute("data-report-state", "sent");
          reportBtn.setAttribute("data-report-state", "sent");
          statusMsg.textContent = "Sent — thank you.";
          txtArea.value = "";
          if (window.ZivonEvents && typeof window.ZivonEvents.emit === "function") {
            window.ZivonEvents.emit("EVT-report_submitted", {
              page_id: payload.course_id,
              block_id: payload.block_id,
              category: payload.category
            });
          }
        } else {
          panel.setAttribute("data-report-state", "error-offline");
          statusMsg.textContent = "Could not send — try again.";
        }
      } catch (err) {
        panel.setAttribute("data-report-state", "error-offline");
        statusMsg.textContent = "Could not send — try again.";
      } finally {
        submitBtn.disabled = false;
      }
    });

    return { mounted: true, button: reportBtn, panel: panel };
  }

  var ZivonReport = {
    mount: injectReportSurface
  };
  window.ZivonReport = ZivonReport;

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
    /* §10.14: a one-time CONSENT SHEET. As an in-flow card at the bottom of a
       long lesson it was never seen, so voice was undiscoverable on first
       visit. It is a bottom sheet (fixed), modal while open, with focus
       containment; declining still never re-nags. */
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("data-consent-presentation", "sheet");
    card.setAttribute("aria-labelledby", "zn-consent-title");
    var sheetTitle = document.createElement("h2");
    sheetTitle.className = "zn-consent-title";
    sheetTitle.id = "zn-consent-title";
    sheetTitle.textContent = "Voice tutor: before we start";

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

    card.appendChild(sheetTitle);
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
        return;
      }
      if (ev.key !== "Tab") return;
      /* Focus stays inside the modal sheet. */
      var focusables = Array.prototype.slice.call(
        card.querySelectorAll("button:not([disabled]), input, a[href]")
      );
      if (!focusables.length) return;
      var first = focusables[0];
      var last = focusables[focusables.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    });

    /* If already granted or declined on this device, keep hidden (no re-nag) */
    card.hidden = cState === "granted" || cState === "declined";
    lessonPage.appendChild(card);
    if (!card.hidden) {
      /* First visit: move focus into the sheet so keyboard/screen-reader
         users meet the gate instead of the page scrolling past it. */
      try { guardianBox.focus(); } catch (e) {}
    }
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

  /* ---------------- SCR-PRIV-01 Privacy page & clear data -------------------
     Device wipe order is binding (doctrine §10.14 "clearing data removes it"
     + this wave's review finding): the server delete is attempted FIRST; the
     device pseudonym is deleted LAST, and only after the server confirms.
     If the server wipe fails, NOTHING local is deleted — the consent gate and
     pseudonym stay, so the student can retry, and the UI says so honestly. */
  var WIPE_LOCAL_KEYS = [
    "zivon.dock",
    "zivon.consent",
    "zivon.consent_record",
    "zivon_locale",
    "zivon.lang",
    "zivon.captions",
    "zivon.identity_seen",
    "zivon.evtdebug"
  ];

  async function clearAllDeviceData() {
    var devId = getDevicePseudoId();
    if (!hasNetworkTransport() || (typeof navigator !== "undefined" && navigator.onLine === false)) {
      return {
        local_cleared: false,
        server_wiped: false,
        device_pseudo_id: devId,
        reason: "offline"
      };
    }

    /* challenge -> DELETE /v1/data (supports both POST and GET on /v1/data/challenge) */
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
    } catch (e) {
      /* NoTransportError / network failure: server_wiped stays false and the
         honest branch below keeps every local key (retry when online). */
      serverWiped = false;
    }

    if (!serverWiped) {
      return {
        local_cleared: false,
        server_wiped: false,
        device_pseudo_id: devId,
        reason: "server_unreachable"
      };
    }

    /* No EVT-data_cleared here: the server just erased this pseudonym, and
       emitting (or flushing) telemetry under it would re-create records the
       student asked us to delete. Local prefs go first, the pseudonym LAST. */
    WIPE_LOCAL_KEYS.forEach(safeStorageRemove);
    cachedDeviceId = null;
    safeStorageRemove(DEVICE_STORAGE_KEY);
    return { local_cleared: true, server_wiped: true, device_pseudo_id: devId };
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

    /* Offline state is honest: a wipe that cannot reach the server is not
       offered as if it worked (EL-PRV-003 `disabled-offline`). */
    function syncWipeOffline() {
      if (!clearBtn) return;
      var isOff = typeof navigator !== "undefined" && navigator.onLine === false;
      clearBtn.disabled = isOff;
      if (isOff) {
        clearBtn.title = "Offline - clearing data needs the server so it can erase your records too.";
        if (statusEl) {
          statusEl.hidden = false;
          statusEl.textContent = "You are offline. Clear my data needs a connection so the server records are erased too.";
        }
      } else {
        clearBtn.removeAttribute("title");
      }
    }
    window.addEventListener("online", syncWipeOffline);
    window.addEventListener("offline", syncWipeOffline);
    syncWipeOffline();

    function cancelDialog() {
      if (!dialogEl) return;
      dialogEl.hidden = true;
      if (clearBtn) {
        try { clearBtn.focus(); } catch (e) {}
      }
    }

    if (clearBtn && dialogEl) {
      clearBtn.addEventListener("click", function () {
        if (clearBtn.disabled) return;
        dialogEl.hidden = false;
        if (statusEl) {
          statusEl.hidden = true;
          statusEl.textContent = "";
        }
        if (confirmBtn) {
          try { confirmBtn.focus(); } catch (e) {}
        }
      });
    }
    if (cancelBtn && dialogEl) {
      cancelBtn.addEventListener("click", cancelDialog);
    }
    if (dialogEl) {
      /* Esc closes; Tab stays inside the modal dialog (aria-modal="true"). */
      dialogEl.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          ev.preventDefault();
          cancelDialog();
          return;
        }
        if (ev.key !== "Tab") return;
        var focusables = Array.prototype.slice.call(
          dialogEl.querySelectorAll("button:not([disabled]), a[href], input, select, textarea")
        );
        if (!focusables.length) return;
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        if (ev.shiftKey && document.activeElement === first) {
          ev.preventDefault();
          last.focus();
        } else if (!ev.shiftKey && document.activeElement === last) {
          ev.preventDefault();
          first.focus();
        }
      });
    }
    if (confirmBtn && dialogEl) {
      confirmBtn.addEventListener("click", async function () {
        confirmBtn.disabled = true;
        var res = await clearAllDeviceData();
        confirmBtn.disabled = false;
        if (!res || !res.server_wiped) {
          /* Honest failure: nothing was deleted, the pseudonym is kept and
             the dialog stays open so "Confirm erase" is a real retry. */
          if (statusEl) {
            statusEl.hidden = false;
            statusEl.textContent = "Could not reach the server — your data was NOT deleted; retry when online.";
          }
          try { confirmBtn.focus(); } catch (e) {}
          return;
        }
        dialogEl.hidden = true;
        if (stampEl) {
          stampEl.textContent = "Consent status: no consent record on this device.";
        }
        if (statusEl) {
          statusEl.hidden = false;
          statusEl.textContent = "All local and server data for this device has been erased.";
        }
        if (clearBtn) {
          try { clearBtn.focus(); } catch (e) {}
        }
      });
    }
    return { mounted: true };
  }

  function injectFooterPrivacyLink() {
    /* Never link the privacy page to itself. */
    if (document.querySelector('[data-screen-id="SCR-PRIV-01"]') ||
        /^\/privacy(\/|$)/.test((typeof location !== "undefined" && location.pathname) || "")) {
      return { mounted: false, reason: "already_on_privacy_page" };
    }
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

  /* ---------------- §10.12 Voice dock (ledger sheet) ----------------------
     Direction B — Ledger (founder review, 2026-11-11). The sheet is a page
     from the notebook: a handwritten role + time margin, an answer body in
     Courier Prime, one small tape on the top edge.
     Binding rules implemented here:
     - two-column ledger, no bubbles; the transcript takes the sheet's
       remaining height and sticks to the bottom while the student is there;
     - append-only rendering: a state change never rebuilds the transcript,
       so scroll position and screen-reader position survive every tick;
     - at most ONE conditional status line, and only where it changes what
       the student can do next;
     - no anchor chip, no block ids, no block-type words, no copy button, no
       captions toggle, no global retry, no memory/clear, no silence-close,
       no separate Stop (the mic is the stop/interrupt target);
     - one icon-only panel open/close control, one language dropdown;
     - a single tape at the sheet's top edge, clipped to that edge.
     ----------------------------------------------------------------------- */
  var DOCK_STORAGE_KEY = "zivon.dock";
  var IDENTITY_SEEN_KEY = "zivon.identity_seen";
  var DOCK_MAX_MESSAGES = 24;
  var DOCK_RETRY_LABEL = "Phir se koshish karo — retry the last answer";

  var DOCK_LANG_OPTIONS = [
    { code: "en", label: "English" },
    { code: "hi", label: "हिन्दी" },
    { code: "hi-Latn", label: "Hinglish" }
  ];

  var DOCK_STATE_COPY = {
    "idle": "",
    "requesting-permission": "",
    "connecting": "",
    "ready": "",
    "listening": "Sun rahe hain — band karne ke liye mic dabao.",
    "endpointing": "",
    "thinking": "Soch rahe hain…",
    "speaking": "",
    "speaking_text": "",
    "interrupted": "",
    "reconnecting": "Phir se jud rahe hain — jo type karoge woh queue mein rahega.",
    "offline": "Connection gaya — type karo, message queue ho jayega. Lesson padhta rahega.",
    "error:mic-denied": "Lesson chalta rahega — type karke poochho.",
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

  function normalizeDockLocale(value) {
    var raw = String(value == null ? "" : value).trim();
    if (!raw) return null;
    var lower = raw.toLowerCase();
    if (lower === "hi-latn" || lower === "hinglish") return "hi-Latn";
    if (lower === "hi" || lower === "hindi" || raw === "हिन्दी") return "hi";
    if (lower === "en" || lower === "english") return "en";
    return AUTONYM_TO_CODE[lower] || null;
  }

  /* Exactly one conditional line. Empty string => no line at all. */
  function dockStatusFor(st, detail) {
    if (st === "error:mic-denied") {
      return { stamp: "MIC OFF", text: DOCK_STATE_COPY["error:mic-denied"] };
    }
    if (st.indexOf("error:") === 0) {
      var msg = DOCK_STATE_COPY[st] || (detail && detail.message ? String(detail.message) : "");
      return msg ? { text: msg } : null;
    }
    var copy = DOCK_STATE_COPY[st];
    return copy ? { text: copy } : null;
  }

  function dockRetryStateFor(st) {
    return (
      st === "reconnecting" ||
      st === "offline" ||
      st === "error:mic-in-use" ||
      st === "error:mic-constraint" ||
      st === "error:no-input" ||
      st === "error:no-match" ||
      st === "error:system-error" ||
      st === "error:timeout"
    );
  }

  function dockClockNow() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function getInitialContainment() {
    var saved = safeStorageGet(DOCK_STORAGE_KEY);
    if (saved === "hidden") return "hidden";
    /* A stored "expanded" starts collapsed on a new page load (never auto-expand, §10.12) */
    return "collapsed";
  }

  /* Inline mic glyph (§10.12: never a literal "[mic]" string). Decorative
     only — the accessible name lives on the button. */
  function makeMicIcon() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "20");
    svg.setAttribute("height", "20");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var body = document.createElementNS(ns, "rect");
    body.setAttribute("x", "9");
    body.setAttribute("y", "3");
    body.setAttribute("width", "6");
    body.setAttribute("height", "11");
    body.setAttribute("rx", "3");
    body.setAttribute("fill", "none");
    body.setAttribute("stroke", "currentColor");
    body.setAttribute("stroke-width", "2");
    var arc = document.createElementNS(ns, "path");
    arc.setAttribute("d", "M5 11a7 7 0 0 0 14 0M12 18v3");
    arc.setAttribute("fill", "none");
    arc.setAttribute("stroke", "currentColor");
    arc.setAttribute("stroke-width", "2");
    arc.setAttribute("stroke-linecap", "round");
    svg.appendChild(body);
    svg.appendChild(arc);
    return svg;
  }

  function makeChevronIcon(direction) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "22");
    svg.setAttribute("height", "22");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", direction === "up" ? "M6 15l6-6 6 6" : "M6 9l6 6 6-6");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.appendChild(path);
    return svg;
  }

  function makeRetryIcon() {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var arc = document.createElementNS(ns, "path");
    arc.setAttribute("d", "M20 11a8 8 0 1 0-2.3 5.7");
    arc.setAttribute("fill", "none");
    arc.setAttribute("stroke", "currentColor");
    arc.setAttribute("stroke-width", "1.8");
    arc.setAttribute("stroke-linecap", "round");
    var head = document.createElementNS(ns, "path");
    head.setAttribute("d", "M20 5v6h-6");
    head.setAttribute("fill", "none");
    head.setAttribute("stroke", "currentColor");
    head.setAttribute("stroke-width", "1.8");
    head.setAttribute("stroke-linecap", "round");
    head.setAttribute("stroke-linejoin", "round");
    svg.appendChild(arc);
    svg.appendChild(head);
    return svg;
  }

  function makeDockBars() {
    var wrap = document.createElement("span");
    wrap.className = "zn-dock-bars";
    wrap.setAttribute("aria-hidden", "true");
    for (var i = 0; i < 5; i++) {
      var bar = document.createElement("span");
      bar.className = "zn-dock-bar";
      wrap.appendChild(bar);
    }
    return wrap;
  }

  var dockEarconCtx = null;
  function playDockEarconOnce(kind) {
    /* Created lazily inside a user gesture (dock open / mic press). */
    try {
      if (!dockEarconCtx) {
        var Ctor = window.AudioContext || window.webkitAudioContext;
        if (!Ctor) return;
        dockEarconCtx = new Ctor();
      }
      if (dockEarconCtx.state === "suspended" && typeof dockEarconCtx.resume === "function") {
        dockEarconCtx.resume();
      }
      playDockEarcon(kind, dockEarconCtx);
    } catch (e) {}
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
    _view: null,
    _locale: null,
    getRegion: ensureVoiceDockRegion,
    setContainment: function (nextContainment, persist) {
      var region = ensureVoiceDockRegion();
      if (!region) return "collapsed";
      var c = nextContainment === "hidden" || nextContainment === "expanded" ? nextContainment : "collapsed";
      var prev = region.getAttribute("data-containment") || getInitialContainment();
      var activeEl = document.activeElement;
      var activeInRegion = Boolean(activeEl && region.contains(activeEl));
      region.setAttribute("data-containment", c);
      var tabBtn = region.querySelector(".zn-dock-tab");
      var stripEl = region.querySelector(".zn-dock-strip");
      var sheetEl = region.querySelector(".zn-dock-sheet");
      if (tabBtn) tabBtn.hidden = c !== "hidden";
      if (stripEl) stripEl.hidden = c !== "collapsed";
      if (sheetEl) sheetEl.hidden = c !== "expanded";
      region.querySelectorAll(".zn-dock-panel-toggle").forEach(function (btn) {
        btn.setAttribute("aria-expanded", c === "expanded" ? "true" : "false");
      });
      if (persist !== false) {
        safeStorageSet(DOCK_STORAGE_KEY, c);
      }
      if (typeof document !== "undefined" && document.body) {
        document.body.classList.toggle("zn-dock-present", c !== "hidden");
        document.body.setAttribute("data-dock-containment", c);
      }
      /* EL-LES-01-051 identity disclosure is "seen" once the student has
         actually expanded the sheet and could read it. */
      var identity = region.querySelector(".zn-dock-disclosure");
      if (identity && c === "expanded" && !identity.hidden) {
        safeStorageSet(IDENTITY_SEEN_KEY, "true");
      }
      if (prev !== c && activeInRegion) {
        /* The control the student was on just disappeared (hidden subtree):
           hand focus to the control that is now visible, never to a
           display:none node. offsetParent is null once an ancestor hides. */
        var focusTarget = null;
        if (c === "expanded") focusTarget = region.querySelector(".zn-dock-panel-toggle-sheet");
        else if (c === "collapsed") focusTarget = region.querySelector(".zn-dock-panel-toggle-strip");
        else focusTarget = region.querySelector(".zn-dock-tab");
        if (focusTarget && (!activeEl || activeEl.offsetParent === null)) {
          try { focusTarget.focus({ preventScroll: true }); } catch (e) { try { focusTarget.focus(); } catch (e2) {} }
        }
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
    getLocale: function () {
      return ZivonVoiceDock._locale || getSavedLang();
    },
    /* A `language.detected` server event reflects what the student actually
       spoke. It updates the dropdown label, <html lang> and (when a bundle
       exists) the client strings. It never navigates: the turn in flight and
       the lesson position survive. Tolerates the event being absent. */
    applyDetectedLocale: function (locale) {
      var norm = normalizeDockLocale(locale);
      if (!norm) return false;
      if (norm === ZivonVoiceDock.getLocale()) return false;
      ZivonVoiceDock._locale = norm;
      safeStorageSet(LANG_STORAGE_KEY, norm);
      if (document && document.documentElement) document.documentElement.lang = norm;
      if (norm === "en") {
        document.querySelectorAll(".zn-untranslated-notice").forEach(function (n) { n.remove(); });
      } else if (isLocaleBundleAvailable(norm)) {
        applyClientBundleSwap(norm);
        renderUntranslatedNotices(norm);
        if (typeof refreshReadAloudForLocale === "function") refreshReadAloudForLocale();
      }
      ZivonVoiceDock.updateLanguageLabel();
      return true;
    },
    updateLanguageLabel: function () {
      var view = ZivonVoiceDock._view;
      if (!view || !view.langLabel) return;
      var code = ZivonVoiceDock.getLocale();
      var label = code;
      DOCK_LANG_OPTIONS.forEach(function (o) { if (o.code === code) label = o.label; });
      view.langLabel.textContent = label;
      view.langLabel.setAttribute(
        "lang",
        code === "hi" ? "hi" : (code === "hi-Latn" ? "hi-Latn" : "en")
      );
      view.langBtn.setAttribute("aria-label", "Language: " + label + " — change language");
      view.langOptions.forEach(function (o) {
        o.btn.setAttribute("aria-selected", o.code === code ? "true" : "false");
      });
    },
    syncTranscript: function () {
      if (!ZivonVoiceDock._activeClient) return;
      var region = ensureVoiceDockRegion();
      if (!region || region.getAttribute("data-zn-dock-mounted") !== "true") return;
      ZivonVoiceDock.syncMessages();
    },
    syncMessages: function () {
      var view = ZivonVoiceDock._view;
      if (!view) return;
      var client = ZivonVoiceDock._activeClient;
      var list = client && typeof client.getTranscripts === "function" ? client.getTranscripts() : [];
      var msgs = ZivonVoiceDock._buildMessages(list);
      var host = view.transcript;
      var prev = view.messages;
      var stick = view.stick;
      var next = [];

      for (var i = 0; i < msgs.length; i++) {
        var m = msgs[i];
        var old = prev[i];
        if (old && old.key === m.key) {
          if (old.text !== m.text) {
            old.textEl.textContent = m.text;
            old.text = m.text;
          }
          var isDraft = Boolean(m.draft);
          if (old.draft !== isDraft) {
            old.el.classList.toggle("is-draft", isDraft);
            old.draft = isDraft;
          }
          var isCut = Boolean(m.interrupted);
          if (old.interrupted !== isCut) {
            ZivonVoiceDock._setCutOff(old, isCut);
            old.interrupted = isCut;
          }
          next.push(old);
          continue;
        }
        if (old && old.el.parentNode) old.el.parentNode.removeChild(old.el);
        var row = ZivonVoiceDock._buildRow(m);
        var anchor = prev[i + 1] && prev[i + 1].el && prev[i + 1].el.parentNode === host
          ? prev[i + 1].el
          : null;
        host.insertBefore(row.el, anchor);
        next.push(row);
      }
      for (var j = msgs.length; j < prev.length; j++) {
        if (prev[j].el.parentNode) prev[j].el.parentNode.removeChild(prev[j].el);
      }
      /* A ledger page is finite; keep the newest turns and drop the oldest
         from the top (never a rebuild, never a scroll jump at the bottom). */
      while (next.length > DOCK_MAX_MESSAGES) {
        var dead = next.shift();
        if (dead.el.parentNode) dead.el.parentNode.removeChild(dead.el);
      }
      view.messages = next;

      var hasMessages = next.length > 0;
      if (view.empty) view.empty.hidden = hasMessages;

      /* The retry control belongs to the newest ANSWER. Moving the same node
         is not a rebuild: listeners and focus survive. */
      var newest = null;
      for (var k = next.length - 1; k >= 0; k--) {
        if (next[k].role === "tutor") { newest = next[k]; break; }
      }
      if (newest) {
        newest.bodyEl.appendChild(view.retryBtn);
      } else if (view.retryBtn.parentNode !== view.statusHost) {
        view.statusHost.appendChild(view.retryBtn);
      }

      if (view.stripLine) {
        var strip = ZivonVoiceDock._stripFor(view.region.getAttribute("data-agent-state") || "idle", next);
        view.stripLine.textContent = strip.text;
        if (view.stripWho) view.stripWho.textContent = strip.who;
        if (view.stripLineBtn) {
          /* WCAG 2.5.3: the accessible name contains the visible label. */
          view.stripLineBtn.setAttribute(
            "aria-label",
            "Open the tutor panel: " + strip.who + " " + strip.text
          );
        }
      }
      if (stick && hasMessages) {
        host.scrollTop = host.scrollHeight;
        view.stick = true;
      }
      ZivonVoiceDock._placeRetry();
    },
    _stripFor: function (st, messages) {
      if (st === "listening") return { who: "You", text: "Sun rahe hain…" };
      if (st === "thinking") return { who: "Tutor", text: "Soch rahe hain…" };
      if (st === "offline") return { who: "Tutor", text: "Offline — type karo, queue ho jayega" };
      if (st === "reconnecting") return { who: "Tutor", text: "Phir se jud rahe hain…" };
      var last = messages.length ? messages[messages.length - 1] : null;
      if (!last) return { who: "Tutor", text: "Poochho kuch bhi is page se" };
      return { who: last.role === "you" ? "You" : "Tutor", text: last.text || "…" };
    },
    _buildMessages: function (list) {
      var out = [];
      var last = null;
      for (var i = 0; i < list.length; i++) {
        var item = list[i] || {};
        var kind = item.kind;
        if (kind === "partial") {
          /* A live partial is only a draft while it is the newest line; once
             stt.final lands it is superseded, so it is never duplicated. */
          if (i === list.length - 1 && String(item.text || "")) {
            out.push({ key: "partial", role: "you", text: String(item.text), draft: true });
          }
          continue;
        }
        if (kind !== "student" && kind !== "tutor") continue;
        var role = kind === "tutor" ? "tutor" : "you";
        var key = role === "tutor" ? "t" + (item.turn_id || ("x" + i)) : "s" + i;
        if (role === "tutor" && last && last.role === "tutor" && last.key === key) {
          /* Streamed tutor deltas are one answer, not one line per chunk.
             Segments arrive without surrounding whitespace: join with one
             space unless punctuation already separates them. */
          var add = String(item.text || "");
          if (add) {
            var prev = String(last.text || "");
            var needsSpace = prev && !/[\s]$/.test(prev) && !/^[\s.,;:!?…]/.test(add);
            last.text = prev + (needsSpace ? " " : "") + add;
          }
          last.interrupted = last.interrupted || Boolean(item.interrupted);
          continue;
        }
        last = {
          key: key,
          role: role,
          text: String(item.text || ""),
          draft: false,
          interrupted: Boolean(item.interrupted)
        };
        out.push(last);
      }
      return out;
    },
    _buildRow: function (m) {
      var row = document.createElement("div");
      row.className = "zn-dock-row zn-dock-row-" + m.role + (m.draft ? " is-draft" : "");
      row.setAttribute("data-row-key", m.key);

      var margin = document.createElement("div");
      margin.className = "zn-dock-row-margin";
      var who = document.createElement("span");
      who.className = "zn-dock-who";
      who.textContent = m.role === "tutor" ? "Tutor" : "You";
      var time = document.createElement("time");
      time.className = "zn-dock-time";
      time.textContent = dockClockNow();
      margin.appendChild(who);
      margin.appendChild(time);

      var body = document.createElement("p");
      body.className = "zn-dock-said";
      var textEl = document.createElement("span");
      textEl.className = "zn-dock-said-text";
      textEl.textContent = m.text;
      body.appendChild(textEl);

      row.appendChild(margin);
      row.appendChild(body);

      var built = {
        key: m.key,
        role: m.role,
        text: m.text,
        draft: Boolean(m.draft),
        interrupted: false,
        el: row,
        bodyEl: body,
        textEl: textEl
      };
      if (m.interrupted) ZivonVoiceDock._setCutOff(built, true);
      return built;
    },
    _setCutOff: function (row, on) {
      var mark = row.bodyEl.querySelector(".zn-dock-cut");
      if (on && !mark) {
        mark = document.createElement("span");
        mark.className = "zn-dock-cut";
        mark.setAttribute("data-cut-off", "true");
        mark.textContent = "▍cut off";
        row.bodyEl.appendChild(mark);
        row.interrupted = true;
      } else if (!on && mark) {
        mark.remove();
        row.interrupted = false;
      }
    },
    _placeRetry: function () {
      var view = ZivonVoiceDock._view;
      if (!view) return;
      view.retryBtn.hidden = ZivonVoiceDock._retryVisible !== true;
    },
    renderAgentState: function (agentState, detail) {
      var region = ensureVoiceDockRegion();
      if (!region || region.getAttribute("data-zn-dock-mounted") !== "true") return;
      var view = ZivonVoiceDock._view;
      if (!view) return;
      var st = String(agentState || "idle");
      if (st === "error:quota-exhausted") st = "text_only";
      region.setAttribute("data-agent-state", st);

      var d = detail || {};
      var isListening = st === "listening";
      var isTextOnly = st === "text_only";
      var isMicDenied = st === "error:mic-denied";
      var micBlocked = isTextOnly || isMicDenied || st === "offline" || st === "reconnecting";

      view.mics.forEach(function (mb) {
        mb.setAttribute("aria-pressed", isListening ? "true" : "false");
        mb.setAttribute("aria-label", isListening ? "Stop listening" : "Start listening");
        mb.disabled = micBlocked;
      });
      /* The pressed mic shows the level bars instead of the glyph (CSS). */

      /* At most one conditional line. Never for idle/ready/connecting/
         endpointing/speaking: those change nothing the student can do, and
         the mic itself is the stop/interrupt target. */
      var status = dockStatusFor(st, d);
      view.status.hidden = !status;
      view.statusStamp.hidden = !status || !status.stamp;
      view.statusStamp.textContent = status && status.stamp ? status.stamp : "MIC OFF";
      view.statusText.textContent = status ? status.text : "";
      view.status.setAttribute("aria-live", st.indexOf("error:") === 0 ? "assertive" : "polite");

      ZivonVoiceDock._retryVisible = dockRetryStateFor(st);
      ZivonVoiceDock.syncMessages();

      if (isMicDenied) {
        ZivonVoiceDock.setContainment("expanded", false);
        try { view.typedInput.focus(); } catch (e) {}
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

      var view = {
        region: region,
        messages: [],
        stick: true,
        mics: [],
        langOptions: [],
        retryVisible: false
      };
      ZivonVoiceDock._view = view;

      /* 1. Hidden state: 44 px paper tab (mic glyph + the word "Ask"; a bare
         icon is never the only affordance for a student who cannot hear). */
      var tabBtn = document.createElement("button");
      tabBtn.type = "button";
      tabBtn.className = "zn-dock-tab";
      tabBtn.setAttribute("data-element-id", "EL-LES-01-042");
      tabBtn.setAttribute("aria-label", "Ask the tutor");
      tabBtn.appendChild(makeMicIcon());
      var tabWord = document.createElement("span");
      tabWord.textContent = "Ask";
      tabBtn.appendChild(tabWord);

      /* 2. Collapsed state: one-line strip, panel-open control, mic toggle. */
      var stripEl = document.createElement("div");
      stripEl.className = "zn-dock-strip";
      var stripLineBtn = document.createElement("button");
      stripLineBtn.type = "button";
      stripLineBtn.className = "zn-dock-strip-line-btn";
      stripLineBtn.setAttribute("aria-label", "Open the tutor panel");
      var stripWho = document.createElement("span");
      stripWho.className = "zn-dock-strip-who";
      stripWho.textContent = "Tutor";
      stripWho.setAttribute("lang", "en");
      var stripLine = document.createElement("span");
      stripLine.className = "zn-dock-strip-line";
      stripLine.setAttribute("lang", "hi-Latn");
      stripLine.textContent = "Poochho kuch bhi is page se";
      stripLineBtn.appendChild(stripWho);
      stripLineBtn.appendChild(stripLine);

      var stripToggle = document.createElement("button");
      stripToggle.type = "button";
      stripToggle.className = "zn-dock-panel-toggle zn-dock-panel-toggle-strip";
      stripToggle.setAttribute("aria-label", "Open the tutor panel");
      stripToggle.setAttribute("aria-expanded", "false");
      stripToggle.appendChild(makeChevronIcon("up"));

      var stripMicBtn = document.createElement("button");
      stripMicBtn.type = "button";
      stripMicBtn.className = "zn-dock-mic zn-dock-mic-strip";
      stripMicBtn.setAttribute("data-element-id", "EL-LES-01-043");
      stripMicBtn.setAttribute("aria-pressed", "false");
      stripMicBtn.setAttribute("aria-label", "Start listening");
      stripMicBtn.appendChild(makeMicIcon());
      var stripMicBars = makeDockBars();
      stripMicBtn.appendChild(stripMicBars);

      [stripLineBtn, stripToggle, stripMicBtn].forEach(function (el) {
        stripEl.appendChild(el);
      });

      /* 3. Expanded state: the ledger sheet. */
      var sheetEl = document.createElement("section");
      sheetEl.className = "zn-dock-sheet";

      /* ONE tape at the sheet's top edge (doctrine §10.12 / B-AUDIT §1.3):
         92×27, -3°, the kit's torn-end clip, clipped by an 18 px band so
         nothing floats over the lesson and the ink rule is never painted
         over. There is no tape in the hidden/tab state (no sheet edge). */
      var tapeClip = document.createElement("span");
      tapeClip.className = "zn-dock-tape-clip";
      tapeClip.setAttribute("aria-hidden", "true");
      var tape = document.createElement("span");
      tape.className = "zn-dock-tape";
      tapeClip.appendChild(tape);

      /* Sheet grip rule: a paper-slip cue inside the sheet only. The panel
         toggle above is the real control; this is not a button. */
      var grip = document.createElement("span");
      grip.className = "zn-dock-grip";
      grip.setAttribute("aria-hidden", "true");

      var head = document.createElement("header");
      head.className = "zn-dock-head";

      /* Contract: the box shows the current language + a chevron inside it;
         the whole box opens the menu. Tapping the label never switches the
         language — only choosing an option does. */
      var langWrap = document.createElement("div");
      langWrap.className = "zn-dock-lang";
      var langBtn = document.createElement("button");
      langBtn.type = "button";
      langBtn.className = "zn-dock-lang-btn";
      langBtn.setAttribute("aria-haspopup", "listbox");
      langBtn.setAttribute("aria-expanded", "false");
      var langLabel = document.createElement("span");
      langLabel.className = "zn-dock-lang-label";
      langLabel.textContent = "English";
      var langChevron = makeChevronIcon("down");
      langChevron.setAttribute("class", "zn-dock-lang-chevron");
      langBtn.appendChild(langLabel);
      langBtn.appendChild(langChevron);

      var langMenu = document.createElement("ul");
      langMenu.className = "zn-dock-lang-menu";
      langMenu.setAttribute("role", "listbox");
      langMenu.setAttribute("aria-label", "Lesson language");
      langMenu.hidden = true;
      DOCK_LANG_OPTIONS.forEach(function (opt) {
        var li = document.createElement("li");
        li.setAttribute("role", "none");
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "zn-dock-lang-option";
        btn.setAttribute("role", "option");
        btn.setAttribute("data-locale", opt.code);
        btn.setAttribute("aria-selected", "false");
        var txt = document.createElement("span");
        txt.className = "zn-dock-lang-option-label";
        if (opt.code === "hi") txt.setAttribute("lang", "hi");
        else if (opt.code === "hi-Latn") txt.setAttribute("lang", "hi-Latn");
        else txt.setAttribute("lang", "en");
        txt.textContent = opt.label;
        var note = document.createElement("span");
        note.className = "zn-dock-lang-option-note";
        note.textContent = "not ready";
        note.hidden = true;
        btn.appendChild(txt);
        btn.appendChild(note);
        li.appendChild(btn);
        langMenu.appendChild(li);
        view.langOptions.push({ code: opt.code, btn: btn, note: note });
      });
      langWrap.appendChild(langBtn);
      langWrap.appendChild(langMenu);

      var sheetToggle = document.createElement("button");
      sheetToggle.type = "button";
      sheetToggle.className = "zn-dock-panel-toggle zn-dock-panel-toggle-sheet";
      sheetToggle.setAttribute("aria-label", "Close the tutor panel");
      sheetToggle.setAttribute("aria-expanded", "true");
      sheetToggle.appendChild(makeChevronIcon("down"));

      head.appendChild(langWrap);
      head.appendChild(sheetToggle);

      var transcriptPanel = document.createElement("div");
      transcriptPanel.className = "zn-dock-transcript";
      transcriptPanel.setAttribute("data-element-id", "EL-LES-01-047");
      transcriptPanel.setAttribute("role", "log");
      transcriptPanel.setAttribute("aria-live", "polite");
      transcriptPanel.setAttribute("aria-relevant", "additions text");

      var emptyEl = document.createElement("div");
      emptyEl.className = "zn-dock-empty";
      var emptyLine = document.createElement("p");
      emptyLine.className = "zn-dock-empty-line";
      emptyLine.setAttribute("lang", "hi-Latn");
      emptyLine.textContent = "Poochho kuch bhi is page se — mic dabao ya type karo.";
      var disclosure = document.createElement("p");
      disclosure.className = "zn-dock-disclosure";
      disclosure.setAttribute("data-element-id", "EL-LES-01-051");
      disclosure.setAttribute("lang", "en");
      disclosure.textContent = "AI tutor — it sees this lesson page, not your room. Voice is transcribed; audio is not kept.";
      if (safeStorageGet(IDENTITY_SEEN_KEY) === "true") disclosure.hidden = true;
      var hints = document.createElement("div");
      hints.className = "zn-dock-hints";
      hints.setAttribute("role", "list");
      ["Yeh formula kab lagta hai?", "Step by step samjhao"].forEach(function (phrase) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "zn-dock-hint";
        chip.setAttribute("role", "listitem");
        chip.setAttribute("lang", "hi-Latn");
        chip.textContent = phrase;
        hints.appendChild(chip);
      });
      emptyEl.appendChild(emptyLine);
      emptyEl.appendChild(disclosure);
      emptyEl.appendChild(hints);
      transcriptPanel.appendChild(emptyEl);

      var statusHost = document.createElement("div");
      statusHost.className = "zn-dock-status-host";
      var statusEl = document.createElement("p");
      statusEl.className = "zn-dock-status";
      statusEl.setAttribute("role", "status");
      statusEl.setAttribute("aria-live", "polite");
      statusEl.hidden = true;
      var statusStamp = document.createElement("span");
      statusStamp.className = "zn-dock-stamp";
      statusStamp.hidden = true;
      statusStamp.textContent = "MIC OFF";
      var statusText = document.createElement("span");
      statusText.className = "zn-dock-status-text";
      statusText.setAttribute("lang", "hi-Latn");
      statusEl.appendChild(statusStamp);
      statusEl.appendChild(statusText);

      var retryBtn = document.createElement("button");
      retryBtn.type = "button";
      retryBtn.className = "zn-dock-retry";
      retryBtn.setAttribute("aria-label", DOCK_RETRY_LABEL);
      retryBtn.title = DOCK_RETRY_LABEL;
      retryBtn.hidden = true;
      retryBtn.appendChild(makeRetryIcon());

      statusHost.appendChild(statusEl);

      var composer = document.createElement("form");
      composer.className = "zn-dock-composer";
      composer.setAttribute("autocomplete", "off");

      var sheetMicBtn = document.createElement("button");
      sheetMicBtn.type = "button";
      sheetMicBtn.className = "zn-dock-mic zn-dock-mic-sheet";
      sheetMicBtn.setAttribute("data-element-id", "EL-LES-01-043");
      sheetMicBtn.setAttribute("aria-pressed", "false");
      sheetMicBtn.setAttribute("aria-label", "Start listening");
      sheetMicBtn.appendChild(makeMicIcon());
      var sheetMicBars = makeDockBars();
      sheetMicBtn.appendChild(sheetMicBars);

      var typedInput = document.createElement("input");
      typedInput.type = "text";
      typedInput.className = "zn-dock-typed-input";
      typedInput.setAttribute("data-element-id", "EL-LES-01-052");
      typedInput.setAttribute("aria-label", "Type your physics doubt");
      typedInput.placeholder = "Apna doubt yahan type karein…";
      typedInput.setAttribute("lang", "hi-Latn");
      typedInput.autocomplete = "off";

      var typedSend = document.createElement("button");
      typedSend.type = "submit";
      typedSend.className = "zn-dock-typed-send";
      typedSend.setAttribute("lang", "en");
      typedSend.textContent = "Send";

      composer.appendChild(sheetMicBtn);
      composer.appendChild(typedInput);
      composer.appendChild(typedSend);

      [tapeClip, grip, head, transcriptPanel, statusHost, composer].forEach(function (el) {
        sheetEl.appendChild(el);
      });

      region.appendChild(tabBtn);
      region.appendChild(stripEl);
      region.appendChild(sheetEl);

      view.transcript = transcriptPanel;
      view.empty = emptyEl;
      view.hints = hints;
      view.disclosure = disclosure;
      view.status = statusEl;
      view.statusStamp = statusStamp;
      view.statusText = statusText;
      view.statusHost = statusHost;
      view.stripLine = stripLine;
      view.stripLineBtn = stripLineBtn;
      view.stripWho = stripWho;
      view.retryBtn = retryBtn;
      view.typedInput = typedInput;
      view.langWrap = langWrap;
      view.langBtn = langBtn;
      view.langLabel = langLabel;
      view.langMenu = langMenu;
      view.mics = [stripMicBtn, sheetMicBtn];
      view.micBars = [stripMicBars, sheetMicBars];
      ZivonVoiceDock._locale = getSavedLang();

      function refreshLangAvailability() {
        var current = ZivonVoiceDock.getLocale();
        view.langOptions.forEach(function (o) {
          var available = o.code === "en" || isLocaleBundleAvailable(o.code);
          o.available = available;
          o.btn.setAttribute("aria-disabled", available ? "false" : "true");
          o.note.hidden = available;
          if (available) {
            o.btn.removeAttribute("title");
          } else {
            o.btn.setAttribute("title", "Translation bundle not generated yet — showing reviewed English.");
          }
          o.btn.setAttribute("aria-selected", o.code === current ? "true" : "false");
        });
        ZivonVoiceDock.updateLanguageLabel();
      }

      function closeLangMenu(focusBack) {
        if (view.langMenu.hidden) return;
        view.langMenu.hidden = true;
        view.langBtn.setAttribute("aria-expanded", "false");
        if (focusBack) { try { view.langBtn.focus(); } catch (e) {} }
      }

      function openLangMenu() {
        refreshLangAvailability();
        view.langMenu.hidden = false;
        view.langBtn.setAttribute("aria-expanded", "true");
      }

      /* The one place a language is actually switched from the dock: the
         existing routing/persistence path, so the page bar, storage, route
         and bundle swap cannot drift apart. */
      function selectDockLocale(code) {
        var norm = normalizeDockLocale(code);
        if (!norm) return false;
        if (norm !== "en" && !isLocaleBundleAvailable(norm)) return false;
        var from = ZivonVoiceDock.getLocale();
        if (norm === from) { closeLangMenu(true); return true; }
        ZivonVoiceDock._locale = norm;
        if (document && document.documentElement) document.documentElement.lang = norm;
        safeStorageSet(LANG_STORAGE_KEY, norm);
        if (window.ZivonEvents && typeof window.ZivonEvents.recordLangSwitch === "function") {
          window.ZivonEvents.recordLangSwitch(from, norm);
        }
        var row = document.querySelector(".zn-lang-row");
        var chip = null;
        if (row) {
          /* The bundle set can arrive after first mount (localized page,
             late manifest). Re-sync honesty before delegating. */
          syncLangBarBundleAvailability(row);
          Array.prototype.slice.call(row.querySelectorAll(".zn-chip")).forEach(function (c) {
            if (!chip && chipLocaleCode(c) === norm) chip = c;
          });
        }
        if (chip) {
          selectLangChip(row, chip, true);
        } else {
          if (norm === "en") {
            document.querySelectorAll(".zn-untranslated-notice").forEach(function (n) { n.remove(); });
          } else {
            applyClientBundleSwap(norm);
            renderUntranslatedNotices(norm);
          }
          /* §10.13: read-aloud buttons follow the active locale. */
          if (typeof refreshReadAloudForLocale === "function") refreshReadAloudForLocale();
        }
        ZivonVoiceDock.updateLanguageLabel();
        closeLangMenu(true);
        return true;
      }

      view.langBtn.addEventListener("click", function () {
        if (view.langMenu.hidden) openLangMenu();
        else closeLangMenu(false);
      });
      view.langBtn.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ") {
          if (!view.langMenu.hidden) return;
          ev.preventDefault();
          openLangMenu();
          var first = view.langOptions[0];
          if (first) { try { first.btn.focus(); } catch (e) {} }
        }
      });
      view.langOptions.forEach(function (o) {
        o.btn.addEventListener("click", function (ev) {
          ev.stopPropagation();
          if (!selectDockLocale(o.code)) return;
        });
        o.btn.addEventListener("keydown", function (ev) {
          var idx = view.langOptions.indexOf(o);
          if (ev.key === "ArrowDown") {
            ev.preventDefault();
            view.langOptions[(idx + 1) % view.langOptions.length].btn.focus();
          } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            view.langOptions[(idx - 1 + view.langOptions.length) % view.langOptions.length].btn.focus();
          } else if (ev.key === "Escape") {
            ev.preventDefault();
            closeLangMenu(true);
          }
        });
      });
      function onDocumentClick(ev) {
        if (!view.langMenu.hidden && !langWrap.contains(ev.target)) closeLangMenu(false);
      }
      document.addEventListener("click", onDocumentClick);

      /* Containment interactions: one icon control opens (strip) and one
         closes (sheet); the strip line itself is also a target. */
      tabBtn.addEventListener("click", function () {
        playDockEarconOnce("start");
        ZivonVoiceDock.setContainment("collapsed", true);
      });
      stripLineBtn.addEventListener("click", function () {
        playDockEarconOnce("start");
        ZivonVoiceDock.setContainment("expanded", true);
      });
      stripToggle.addEventListener("click", function () {
        playDockEarconOnce("start");
        ZivonVoiceDock.setContainment("expanded", true);
      });
      sheetToggle.addEventListener("click", function () {
        ZivonVoiceDock.setContainment("collapsed", true);
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
          playDockEarconOnce("stop");
          client.bargeIn("ptt_press");
          return;
        }
        if (cur === "listening") {
          playDockEarconOnce("stop");
          client.endAudio();
          return;
        }
        playDockEarconOnce("start");
        /* Permission FIRST (user gesture), then connect, then queue the turn
           behind session.ready (M2). Denied or unsupported browsers land in
           an honest error state with the typed field open — never a fake
           "listening". Tap once to start, tap again to stop: no hold timing
           to lose while the permission prompt is open. */
        if (!client.hasMicrophone() && typeof client.requestMicPermission === "function") {
          client.requestMicPermission().then(function (res) {
            if (!res || !res.ok) return; /* state machine shows the reason */
            if (client.getState() === "idle" || client.getState() === "offline" || client.getState() === "reconnecting") {
              client.connect();
            }
            client.startListening("doubt");
          });
          return;
        }
        if (client.getState() === "idle" || client.getState() === "offline" || client.getState() === "reconnecting") {
          client.connect();
        }
        client.startListening("doubt");
      }

      view.mics.forEach(function (btn) {
        btn.addEventListener("click", function () { handleMicTrigger(); });
      });

      retryBtn.addEventListener("click", function () {
        var client = ensureClientWired();
        client.reconnect();
        try { sheetMicBtn.focus(); } catch (e) {}
      });

      hints.querySelectorAll(".zn-dock-hint").forEach(function (chip) {
        chip.addEventListener("click", function () {
          typedInput.value = chip.textContent.trim();
          try { typedInput.focus(); } catch (e) {}
        });
      });

      composer.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var txt = (typedInput.value || "").trim();
        if (!txt) return;
        stopReadAloud();
        var client = ensureClientWired();
        client.sendTypedDoubt(txt);
        typedInput.value = "";
        ZivonVoiceDock.renderAgentState(client.getState(), {});
      });

      /* Space is a page-wide talk key ONLY when focus is not on a control:
         hijacking Space inside buttons/inputs/links would make those controls
         unusable (§10.12 keyboard rule + normal browser behaviour). */
      function isInteractiveTarget(target) {
        if (!target || typeof target.closest !== "function") return false;
        return Boolean(
          target.closest(
            "button, input, select, textarea, a, summary, [contenteditable], [role='textbox'], [role='button']"
          )
        );
      }

      /* Keyboard (§10.12): Space toggles listening, Esc stops/interrupts then
         collapses, Enter sends the typed doubt (the form handles it). */
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
          }
        } else if (ev.key === " " && !ev.repeat && !isInteractiveTarget(ev.target)) {
          var client2 = ensureClientWired();
          ev.preventDefault();
          stopReadAloud();
          ZivonVoiceDock.setContainment("expanded", true);
          if (client2.getState() === "listening") client2.endAudio();
          else handleMicTrigger();
        }
      });

      /* Stick-to-bottom: follow new text only while the student is at the
         bottom; scrolling up to re-read stops the page from yanking away. */
      transcriptPanel.addEventListener("scroll", function () {
        var gap = transcriptPanel.scrollHeight - transcriptPanel.scrollTop - transcriptPanel.clientHeight;
        view.stick = gap < 32;
      }, { passive: true });

      refreshLangAvailability();
      ZivonVoiceDock.setContainment(getInitialContainment(), false);
      ZivonVoiceDock.renderAgentState("idle", {});
      return { mounted: true, region: region };
    }
  };
  window.ZivonVoiceDock = ZivonVoiceDock;

  /* A block's human label for the tutor prompt and the visible_blocks list.
     Never the DOM id, never the internal type word: the model receives a
     page description, not protocol. */
  var BLOCK_TYPE_HUMAN = {
    text: "Lesson text",
    simulation: "Simulation",
    check: "Check question",
    diagram: "Diagram",
    worked_example: "Worked example",
    reveal: "Reveal"
  };

  function blockTextExcerpt(el) {
    if (!el) return "";
    var raw = typeof el.innerText === "string" && el.innerText
      ? el.innerText
      : (el.textContent || "");
    return String(raw).replace(/\s+/g, " ").trim().slice(0, 400);
  }

  function humanBlockTitle(el, headingEl, bType) {
    var heading = headingEl ? String(headingEl.textContent || "").replace(/\s+/g, " ").trim() : "";
    if (heading) return heading.slice(0, 80);
    var excerpt = blockTextExcerpt(el);
    if (excerpt) return excerpt.slice(0, 60);
    return BLOCK_TYPE_HUMAN[bType] || "Lesson content";
  }

  function buildContextSnapshot(explicitBlockId) {
    var route = ZivonRouter.currentRoute();
    var kicker = document.querySelector(".zn-kicker");
    var titleEl = document.querySelector("h1.zn-title");
    var checkedChip = document.querySelector('.zn-lang-row .zn-chip[aria-checked="true"]');
    var langPref = checkedChip ? (checkedChip.getAttribute("data-lang") || checkedChip.textContent.trim()) : (document.documentElement.lang || "en");
    var visibleBlocks = [];
    var blockTypes = {};
    var blockTitles = {};
    var blockTexts = {};
    var viewportCentre = (typeof window !== "undefined" && window.innerHeight ? window.innerHeight : 800) / 2;
    var bestBlockId = null;
    var bestBlockType = "text";
    var bestDistance = Infinity;
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
      blockTypes[el.id] = bType;
      var blockTitle = humanBlockTitle(el, h, bType);
      blockTitles[el.id] = blockTitle;
      blockTexts[el.id] = blockTextExcerpt(el);
      visibleBlocks.push({
        id: el.id,
        type: bType,
        /* `title` is the human label the tutor prompt may quote; it is never
           the DOM id or the internal block type. */
        title: blockTitle
      });
      /* Anchor = the block nearest the viewport centre (§10.12 "the block
         being discussed"), not simply the first block on the page. */
      if (typeof el.getBoundingClientRect === "function") {
        var rect = el.getBoundingClientRect();
        var centre = rect.top + rect.height / 2;
        var dist = Math.abs(centre - viewportCentre);
        if (dist < bestDistance) {
          bestDistance = dist;
          bestBlockId = el.id;
          bestBlockType = bType;
        }
      }
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
    var activeBlock = explicitBlockId || bestBlockId || (visibleBlocks[0] ? visibleBlocks[0].id : "page");
    var activeBlockType = blockTypes[activeBlock] || bestBlockType || "text";
    var firstSim = simStates[0] || null;
    var activeSim = simStates.filter(function (s) { return s.block_id === activeBlock; })[0] || firstSim;

    var snap = {
      topic_id: route.topic_slug || (titleEl ? titleEl.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-") : "topic"),
      course_id: route.course_id || (kicker ? kicker.textContent.trim() : "physics"),
      class: parseInt(String(route.course_id || "9").replace(/\D+/g, ""), 10) || 9,
      chapter: titleEl ? titleEl.textContent.trim().slice(0, 120) : "",
      topic_title: titleEl ? titleEl.textContent.trim().slice(0, 120) : "",
      block_id: activeBlock,
      block_type: activeBlockType,
      /* Human-readable anchor for the tutor prompt: what the student is
         looking at + a concise excerpt of it. Ids stay internal. */
      block_title: blockTitles[activeBlock] || BLOCK_TYPE_HUMAN[activeBlockType] || "Lesson content",
      block_text: blockTexts[activeBlock] || "",
      sim_id: activeSim ? activeSim.block_id : null,
      sim_vars: activeSim ? activeSim.controls : {},
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
      snap.block_text = String(snap.block_text || "").slice(0, 200);
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
       close. A transient drop is the `reconnecting` state, never `offline`:
       the dock only says offline for a genuine `navigator.onLine === false`
       or after the retry budget is exhausted. A pong timeout (only when a
       ping on a live socket goes unanswered) closes the socket first.
       Connect/session-ready/keepalive budgets are generous by default and
       overridable via `createVoiceClient` options (weak 2G/3G links).
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
    var sessionBootstrapPending = false;

    /* API-001: the browser never mints its own token. Bootstrap a
       pseudonymous session from the core backend and use the issued
       HMAC token for the WS. Without this the server correctly rejects the
       dev placeholder with auth.invalid (found 2026-11-10). */
    function bootstrapSessionToken() {
      var snap = buildContextSnapshot();
      var locale = snap.lang_pref || "en";
      var lang = locale === "hi" ? "hi-IN" : (locale === "hi-Latn" ? "hi-en" : "en-IN");
      var ctrl = typeof AbortController === "function" ? new AbortController() : null;
      var abortTimer = ctrl ? setTimeout(function () {
        try { ctrl.abort(); } catch (e) {}
      }, bootstrapTimeoutMs) : null;
      function clearAbort() {
        if (abortTimer) { clearTimeout(abortTimer); abortTimer = null; }
      }
      return sameOriginRequest("/v1/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: ctrl ? ctrl.signal : undefined,
        body: JSON.stringify({
          device_pseudo_id: deviceId,
          lang: lang,
          mode: "guide",
          page: { course_id: snap.course_id, class: snap.class }
        })
      })
        .then(function (res) { return res && res.ok ? res.json() : null; })
        .then(function (data) {
          clearAbort();
          return data && data.session_token ? data.session_token : null;
        })
        .catch(function () { clearAbort(); return null; });
    }
    var jitterBufferedMs = 0;
    var jitterTargetMs = opts.jitter_target_ms || 180;
    var minLeadTimeS = (opts.min_lead_ms !== undefined ? opts.min_lead_ms : 60) / 1000.0;
    var ttsSampleRate = opts.tts_sample_rate || (typeof window !== "undefined" && window.ZIVON_VOICE_TTS_SAMPLE_RATE) || 16000;
    var nextPlayTimeS = 0;
    var activeSources = [];
    var scheduledChunksCount = 0;
    var minFramesBeforeSpeaking = opts.min_frames_before_speaking || opts.min_buffer_frames || 3;
    var audioCtx = opts.audioContext || null;
    var micGainNode = null;
    var agentGainNode = null;
    var agentGainConnected = false;
    var mediaStream = null;
    /* Capture path: MediaStreamSource -> ScriptProcessorNode -> muted gain ->
       destination. Never enabled unless a real MediaStream exists. */
    var captureProcessor = null;
    var captureSource = null;
    var captureSink = null;
    var captureResidual = [];
    var captureFramesSent = 0;
    /* A mic press during `connecting` must start once session.ready lands
       (first-visit race: connect() then startListening() used to hit offline). */
    var pendingStartHint = null;
    var creditState = "ok";
    var pingTimer = null;
    var reconnectTimer = null;
    var reconnectAttempts = 0;
    /* Weak-network policy (2G/3G): retry for minutes, never call a transient
       drop "offline". 8 attempts with a 1 s base and a 30 s cap is ~2.5 min of
       patience before the dock offers typed-only mode; the retry button is
       always one tap away. All values are overridable from the dock. */
    var maxReconnectAttempts = opts.max_reconnect_attempts !== undefined ? opts.max_reconnect_attempts : 8;
    var reconnectBaseMs = opts.reconnect_base_ms !== undefined ? opts.reconnect_base_ms : 1000;
    var reconnectMaxMs = opts.reconnect_max_ms !== undefined ? opts.reconnect_max_ms : 30000;
    /* The browser exposes no handshake timeout: on a stalled 2G dial the WS
       can sit in CONNECTING forever. This closes it and retries. */
    var connectTimeoutMs = opts.connect_timeout_ms !== undefined ? opts.connect_timeout_ms : 30000;
    /* A slow link can open the socket but take a long time to deliver
       session.ready; treat that as a retry, not as a dead tutor. */
    var sessionReadyTimeoutMs = opts.session_ready_timeout_ms !== undefined ? opts.session_ready_timeout_ms : 30000;
    /* The pseudonymous-session bootstrap is a plain fetch before the WS even
       dials; on a stalled link it needs its own ceiling or the dock waits on
       an abandoned request. */
    var bootstrapTimeoutMs = opts.bootstrap_timeout_ms !== undefined ? opts.bootstrap_timeout_ms : 30000;
    /* Keepalive: ping every 15 s, but only judge the link dead when a ping
       sent on a live socket goes unanswered for this long (mobile browsers
       throttle timers, so the old absolute 30 s "last pong" clock could
       declare offline after a long listening turn). */
    var pingIntervalMs = opts.ping_interval_ms !== undefined ? opts.ping_interval_ms : 15000;
    var pongTimeoutMs = opts.pong_timeout_ms !== undefined ? opts.pong_timeout_ms : 60000;
    var connectTimer = null;
    var sessionReadyTimer = null;
    var lastPongTs = 0;
    var lastPingSentTs = 0;
    var consecutiveVadTriggers = 0;
    var lastVadTriggerTs = 0;
    var queuedTypedDoubts = [];
    var transcripts = [];
    var turnTimings = {};
    var lastCompletedTurnMetrics = null;

    /* Genuine connectivity events are the only signals allowed to say
       "offline" without waiting for retries. Reconnecting on `online` makes
       the retry budget last through a tunnel/radio drop instead of burning
       attempts against a dead interface. */
    function onBrowserOffline() {
      if (state !== "idle") setState("offline", { reason: "navigator_offline" });
    }
    function onBrowserOnline() {
      if (state === "offline" || state === "reconnecting") {
        reconnectAttempts = 0;
        connect(true);
      }
    }
    if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
      window.addEventListener("offline", onBrowserOffline);
      window.addEventListener("online", onBrowserOnline);
    }

    function setState(nextState, detail) {
      var prev = state;
      state = nextState;
      /* Terminal / non-speaking states restore the bookkeeping gains: a turn
         that ends in error, interrupt or a dropped link must not leave the
         mic path ducked at 0.2 forever. */
      if (nextState === "offline" || nextState === "reconnecting" ||
          nextState === "interrupted" ||
          nextState === "error" || String(nextState).indexOf("error:") === 0) {
        if (nextState === "offline" || nextState === "reconnecting" || nextState === "interrupted") {
          stopPlaybackImmediately();
        }
        /* Any terminal state stops capture: never leave a live processor
           running while the dock shows an error or a dropped link.
           `interrupted` keeps the stream because barge-in transitions straight
           back to listening; `reconnecting` keeps the stream too (no second
           permission prompt) but stops the processor; everything else also
           stops the track. */
        stopCapture(nextState !== "interrupted" && nextState !== "reconnecting");
        setDucking("normal");
      }
      if (nextState === "reconnecting") {
        /* A transient drop is NOT "offline": the lesson stays usable and the
           tutor is still trying. The offline wording is reserved for a real
           browser-offline event or exhausted retries. */
        applyLessonStateBanner("reconnecting", "Reconnecting - voice tutor is retrying; lesson and simulations stay active.");
      } else if (nextState === "offline") {
        applyLessonStateBanner("offline", "Offline - voice tutor paused; lesson and simulations stay active.");
      } else if (nextState === "ready" || nextState === "listening" ||
                 nextState === "thinking" || nextState === "speaking" ||
                 nextState === "speaking_text" || nextState === "text_only") {
        applyLessonStateBanner("reconnecting", "");
        applyLessonStateBanner("offline", "");
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
        noteTransportLoss("ws_not_open");
        return false;
      }
      ws.send(JSON.stringify(payload));
      return true;
    }

    function isBrowserOffline() {
      return typeof navigator !== "undefined" && navigator.onLine === false;
    }

    /* One place decides what a lost socket means. A transient drop (mobile
       network handover, slow 2G, NAT reaping) becomes `reconnecting` and is
       retried with backoff; only a genuine browser-offline signal or an
       exhausted retry budget degrades to `offline`. */
    function noteTransportLoss(reason) {
      if (state === "idle") return;
      if (state !== "reconnecting" && state !== "offline") {
        if (isBrowserOffline()) {
          setState("offline", { reason: reason || "navigator_offline" });
          return;
        }
        setState("reconnecting", { reason: reason || "transport_lost", attempt: reconnectAttempts + 1 });
      }
      scheduleReconnect();
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
      if (!forceFlush && nextPlayTimeS === 0 && jitterBufferedMs < jitterTargetMs && pcmJitterQueue.length < minFramesBeforeSpeaking) {
        return;
      }
      var nowS = typeof audioCtx.currentTime === "number" ? audioCtx.currentTime : 0;
      if (nextPlayTimeS < nowS + minLeadTimeS) {
        /* Never hard-schedule < 150 ms ahead on initial/underrun start (ws-contract.md §2/§3) */
        nextPlayTimeS = nowS + minLeadTimeS;
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

    /* --- Uplink capture -------------------------------------------------
       Server contract (voice/audio_io.py, ws-contract.md §3): C→S audio is
       8-byte header + little-endian PCM16 MONO at 16 kHz, nominally 100 ms
       frames; the server accepts 2–200 ms (64–6400 payload bytes). We capture
       at the AudioContext rate (typically 48 kHz), resample to 16 kHz and send
       20 ms frames (320 samples = 640 bytes), well inside those bounds.
       The client never sends Opus: it does not encode it and the server does
       not expect it on this path. */
    var CAPTURE_SAMPLE_RATE = 16000;
    var CAPTURE_FRAME_SAMPLES = 320; /* 20 ms at 16 kHz */

    function resampleTo16k(input, srcRate) {
      var target = CAPTURE_SAMPLE_RATE;
      if (!input || !input.length) return new Float32Array(0);
      if (!srcRate || srcRate === target) return input;
      var ratio = srcRate / target;
      var outLen = Math.floor(input.length / ratio);
      var out = new Float32Array(outLen);
      for (var i = 0; i < outLen; i++) {
        var pos = i * ratio;
        var i0 = Math.floor(pos);
        var frac = pos - i0;
        var a = input[i0] !== undefined ? input[i0] : 0;
        var b = input[i0 + 1] !== undefined ? input[i0 + 1] : a;
        out[i] = a + (b - a) * frac;
      }
      return out;
    }

    function float32ToPcm16Le(samples) {
      var out = new Uint8Array(samples.length * 2);
      var dv = new DataView(out.buffer);
      for (var i = 0; i < samples.length; i++) {
        var s = samples[i];
        if (s > 1) s = 1;
        else if (s < -1) s = -1;
        dv.setInt16(i * 2, s < 0 ? Math.round(s * 32768) : Math.round(s * 32767), true);
      }
      return out;
    }

    function stopCapture(stopTracks) {
      if (captureProcessor) {
        try { captureProcessor.onaudioprocess = null; } catch (e) {}
        try { if (typeof captureProcessor.disconnect === "function") captureProcessor.disconnect(); } catch (e) {}
        captureProcessor = null;
      }
      if (captureSource) {
        try { if (typeof captureSource.disconnect === "function") captureSource.disconnect(); } catch (e) {}
        captureSource = null;
      }
      if (captureSink) {
        try { if (typeof captureSink.disconnect === "function") captureSink.disconnect(); } catch (e) {}
        captureSink = null;
      }
      captureResidual = [];
      if (stopTracks) {
        if (mediaStream) {
          try {
            var tracks = typeof mediaStream.getTracks === "function" ? mediaStream.getTracks() : [];
            tracks.forEach(function (t) { try { t.stop(); } catch (e) {} });
          } catch (e) {}
        }
        mediaStream = null;
      }
    }

    /* Returns "ok" | "no-stream" | "unsupported". "unsupported" means this
       browser cannot capture at all — the dock must then show an honest
       downgrade instead of a fake listening state. */
    function startCapture() {
      if (!mediaStream) return "no-stream";
      if (captureProcessor) return "ok";
      ensureAudioGraph();
      if (!audioCtx ||
          typeof audioCtx.createMediaStreamSource !== "function" ||
          typeof audioCtx.createScriptProcessor !== "function") {
        return "unsupported";
      }
      try {
        var srcRate = audioCtx.sampleRate || 48000;
        captureSource = audioCtx.createMediaStreamSource(mediaStream);
        /* 2048 frames ≈ 43 ms at 48 kHz: a standard, widely supported block. */
        captureProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
        captureProcessor.onaudioprocess = function (ev) {
          if (state !== "listening" || !captureProcessor) return;
          var channel = ev && ev.inputBuffer && typeof ev.inputBuffer.getChannelData === "function"
            ? ev.inputBuffer.getChannelData(0)
            : null;
          if (!channel || !channel.length) return;
          var down = resampleTo16k(channel, srcRate);
          for (var i = 0; i < down.length; i++) captureResidual.push(down[i]);
          while (captureResidual.length >= CAPTURE_FRAME_SAMPLES && state === "listening") {
            var frame = captureResidual.splice(0, CAPTURE_FRAME_SAMPLES);
            var pcm = float32ToPcm16Le(frame);
            if (sendAudioChunk(pcm, false)) captureFramesSent += 1;
          }
        };
        captureSink = audioCtx.createGain();
        captureSink.gain.value = 0; /* processing only - never monitor the mic */
        captureSource.connect(captureProcessor);
        captureProcessor.connect(captureSink);
        if (audioCtx.destination && typeof captureSink.connect === "function") {
          captureSink.connect(audioCtx.destination);
        }
      } catch (err) {
        /* A test fake / exotic stream can fail here; a real MediaStream does
           not. Never claim capture we do not have: the caller logs and the
           honest state machine still applies (no frames are fabricated). */
        if (window.console && console.warn) {
          console.warn("zivon.audio: capture graph unavailable:", err && err.message ? err.message : err);
        }
        stopCapture(false);
        return "error";
      }
      return "ok";
    }

    function handleBinaryFrame(data) {
      var parsed = decodeAudioFrame(data);
      if (!parsed.valid) {
        setState("error:system-error", { reason: parsed.reason });
        return;
      }
      var seg = parsed.segment_id;
      /* Track the next expected sequence per segment so a gap/duplicate stays
         observable alongside the PCM16 decode + AudioBufferSource scheduling
         that follows below (ws-contract.md §3). */
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
      if (pendingFrames.length >= minFramesBeforeSpeaking || jitterBufferedMs >= jitterTargetMs || parsed.is_final) {
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
        clearSessionReadyTimer();
        reconnectAttempts = 0;
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
        /* A mic press made while connecting starts now (M2). */
        if (pendingStartHint) {
          var queuedHint = pendingStartHint;
          pendingStartHint = null;
          if (state === "ready") beginListening(queuedHint);
        }
        /* A typed doubt submitted before the socket opened is sent now.
           The student line was already echoed locally; only the turn frames
           are replayed here (never a duplicate transcript row). */
        if (queuedTypedDoubts.length) {
          var queuedTurns = queuedTypedDoubts.slice();
          queuedTypedDoubts = [];
          queuedTurns.forEach(function (text) {
            sendJson(Object.assign({ type: "context.snapshot" }, buildContextSnapshot()));
            sendJson({ type: "typed.doubt", text: text });
          });
          setState("thinking", { typed: true, text: queuedTurns[queuedTurns.length - 1] });
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
      if (t === "language.detected") {
        /* The server tells us which language the student actually spoke.
           Reflect it (label, <html lang>, client strings when a bundle
           exists) without navigating away from the turn. The event is
           optional: an older server simply never sends it. */
        if (window.ZivonVoiceDock && typeof window.ZivonVoiceDock.applyDetectedLocale === "function") {
          window.ZivonVoiceDock.applyDetectedLocale(
            payload.locale || payload.lang || payload.language
          );
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
        /* A segment that is only Timbre tags (e.g. a standalone <pauses>) is
           a delivery cue, not a sentence: never render it as tutor text. */
        var tagOnly = /^\s*(?:<[^>]+>\s*)+$/.test(String(txt));
        var subkind = payload.kind || "speech";
        if (!tagOnly && subkind !== "summary" && subkind !== "filler") {
          transcripts.push({ kind: "tutor", subkind: subkind, text: String(txt), turn_id: payload.turn_id || lastTurnId });
          /* Streaming text must reach the DOM now, not only on the next state
             change: the dock rebuilds its transcript from getTranscripts(). */
          if (window.ZivonVoiceDock && typeof window.ZivonVoiceDock.syncTranscript === "function") {
            window.ZivonVoiceDock.syncTranscript();
          }
        }
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
        lastPingSentTs = 0;
        return;
      }
      if (t === "ping") {
        /* A server ping is also proof the link is alive. */
        lastPongTs = Date.now();
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

    function clearConnectTimer() {
      if (connectTimer) { clearTimeout(connectTimer); connectTimer = null; }
    }

    function clearSessionReadyTimer() {
      if (sessionReadyTimer) { clearTimeout(sessionReadyTimer); sessionReadyTimer = null; }
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
      if (reconnectTimer) return true;
      if (reconnectAttempts >= maxReconnectAttempts) {
        if (state !== "offline") {
          setState("offline", { reason: "reconnect_attempts_exhausted", attempts: reconnectAttempts });
        }
        return false;
      }
      var capped = Math.min(reconnectMaxMs, reconnectBaseMs * Math.pow(2, reconnectAttempts));
      var delay = Math.max(1, Math.round(capped * (0.5 + Math.random() * 0.5))); /* jitter */
      reconnectAttempts += 1;
      reconnectTimer = setTimeout(function () {
        reconnectTimer = null;
        if (isBrowserOffline()) {
          /* Stay honest while the radio is down; the `online` listener below
             resumes the retry loop instead of burning attempts. */
          setState("offline", { reason: "navigator_offline" });
          return;
        }
        if (state === "offline" || state === "reconnecting") connect(true);
      }, delay);
      return true;
    }

    function teardownMediaAndAudio() {
      stopCapture(false);
      pendingStartHint = null;
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
      clearConnectTimer();
      clearSessionReadyTimer();
      queuedTypedDoubts = [];
      pendingFrames = [];
      if (typeof window !== "undefined" && typeof window.removeEventListener === "function") {
        window.removeEventListener("offline", onBrowserOffline);
        window.removeEventListener("online", onBrowserOnline);
      }
      teardownMediaAndAudio();
    }
    voiceClientCleanups.push(cleanup);

    function connect(resumeFlag) {
      clearReconnectTimer();
      clearPingTimer();
      clearConnectTimer();
      clearSessionReadyTimer();
      detachSocket();
      /* A retry keeps the "reconnecting" chrome: flipping back to "connecting"
         on every attempt would look like a fresh dial and hide the retry. */
      if (state !== "reconnecting") setState("connecting");
      var mockTransport = typeof opts.createWebSocket === "function";
      if (!mockTransport && (!sessionToken || sessionToken === "dev-session-token") && !sessionBootstrapPending) {
        sessionBootstrapPending = true;
        bootstrapSessionToken().then(function (tok) {
          sessionBootstrapPending = false;
          if (tok) {
            sessionToken = tok;
            connect(resumeFlag);
          } else {
            noteTransportLoss("session_bootstrap_failed");
          }
        });
        return false;
      }
      var url = opts.url || ((window.location && window.location.protocol === "https:" ? "wss://" : "ws://") +
        ((window.location && window.location.host) || "localhost:8080") + "/voice/ws");
      var factory = opts.createWebSocket || function (u) { return new WebSocket(u); };
      try {
        ws = factory(url);
      } catch (err) {
        noteTransportLoss("connect_failed: " + String(err));
        return false;
      }
      ws.binaryType = "arraybuffer";
      var connectAttemptSocket = ws;
      connectTimer = setTimeout(function () {
        connectTimer = null;
        /* Only this attempt's socket may be failed by this timer. */
        if (ws === connectAttemptSocket && ws && ws.readyState !== 1) {
          detachSocket();
          noteTransportLoss("connect_timeout");
        }
      }, connectTimeoutMs);
      ws.onopen = function () {
        clearConnectTimer();
        /* Do NOT reset the retry budget here: the handshake is not proof of a
           usable session. session.ready (below) is. A server that accepts and
           instantly closes must still exhaust the budget instead of looping
           forever at the base delay. */
        lastPongTs = Date.now();
        lastPingSentTs = 0;
        clearPingTimer();
        pingTimer = setInterval(function () {
          if (state === "ready" || state === "thinking" || state === "idle" ||
              state === "listening" || state === "endpointing" ||
              state === "speaking" || state === "speaking_text") {
            checkKeepalive(Date.now());
          }
        }, pingIntervalMs);
        /* A slow 2G link can open the socket and then stall before
           session.ready; retry instead of leaving the dock in `connecting`. */
        clearSessionReadyTimer();
        sessionReadyTimer = setTimeout(function () {
          sessionReadyTimer = null;
          if (state === "connecting" || state === "reconnecting") {
            detachSocket();
            noteTransportLoss("session_ready_timeout");
          }
        }, sessionReadyTimeoutMs);
        var snap = buildContextSnapshot();
        sendJson({
          type: "session.start",
          session_token: sessionToken,
          device: deviceId,
          locale: snap.lang_pref || "en",
          /* This client captures PCM16 mono 16 kHz and decodes PCM16 downlink;
             it does not encode or decode Opus, so it must not advertise it. */
          capabilities: { ptt: true, opus: false, uplink_codec: "pcm16-16000", webrtc_vad: true },
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
        clearConnectTimer();
        clearSessionReadyTimer();
        if (ev && ev.code === 4401) {
          setState("error:auth.invalid", { code: 4401 });
        } else if (ev && ev.code === 4409) {
          setState("error:version.mismatch", { code: 4409 });
        } else if (state !== "idle") {
          noteTransportLoss("ws_closed:" + (ev ? ev.code : 1006));
        }
      };
      return true;
    }

    function beginListening(turnHint) {
      /* Only capture when a real stream exists (the dock requests permission
         BEFORE calling this). A browser with no capture API gets an honest
         error state — and NO audio.start — never a fake "listening". */
      if (mediaStream) {
        var cap = startCapture();
        if (cap === "unsupported") {
          setState("error:unsupported-browser", { fallback: "text" });
          return false;
        }
      }
      micSeq = 0;
      captureFramesSent = 0;
      captureResidual = [];
      turnTimings = { t_start: performance.now() };
      if (window.ZivonEvents && typeof window.ZivonEvents.recordMicPress === "function") {
        window.ZivonEvents.recordMicPress(sessionId);
      }
      sendJson(Object.assign({ type: "context.snapshot" }, buildContextSnapshot()));
      sendJson({ type: "audio.start", turn_hint: turnHint || null });
      setState("listening");
      return true;
    }

    function startListening(turnHint) {
      if (state === "speaking" || state === "thinking" || state === "speaking_text") {
        /* P0 PTT press during speaking/thinking IS barge-in interrupt (SP1 §5) */
        bargeIn("ptt_press");
      }
      if (!ws || ws.readyState !== 1 || state === "connecting" || state === "reconnecting") {
        /* First press after connect(): the socket is still CONNECTING. Queue
           the turn behind session.ready instead of reporting offline — the
           old path always landed the very first mic press in `offline`. */
        pendingStartHint = turnHint || "doubt";
        if (!ws || ws.readyState > 1) {
          connect();
        }
        return true;
      }
      return beginListening(turnHint);
    }

    function sendAudioChunk(pcmBytes, isFinal) {
      if (state !== "listening") return false;
      if (!ws || ws.readyState !== 1) {
        noteTransportLoss("audio_send_ws_closed");
        return false;
      }
      var frame = encodeAudioFrame(pcmBytes, 1, micSeq++, Boolean(isFinal));
      ws.send(frame);
      return true;
    }

    function endAudio() {
      if (state !== "listening" && state !== "endpointing") return false;
      turnTimings.t_endpoint = performance.now();
      /* Release the microphone the moment the turn ends: disconnect the
         processor AND stop the track (privacy + no dead-mic). */
      stopCapture(true);
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
      if (mediaStream) startCapture();
      return true;
    }

    function sendTypedDoubt(text) {
      var clean = String(text || "").trim();
      if (!clean) return false;
      turnTimings = { t_endpoint: performance.now() };
      transcripts.push({ kind: "student", text: clean, typed: true });
      if (!ws || ws.readyState !== 1) {
        queuedTypedDoubts.push(clean);
        /* A typed doubt must not depend on a prior mic press to open the
           socket (found 2026-11-10: the text path queued forever and the
           tutor never replied). Open it now; session.ready flushes the
           queue. */
        if (state === "idle" || state === "offline") {
          connect();
        } else if (state !== "connecting" && state !== "reconnecting") {
          noteTransportLoss("typed_send_ws_closed");
        }
        return true;
      }
      sendJson(Object.assign({ type: "context.snapshot" }, buildContextSnapshot()));
      /* If the link dies between the two frames, keep the student's text —
         it is flushed on the next session.ready, never silently dropped. */
      if (!sendJson({ type: "typed.doubt", text: clean })) {
        queuedTypedDoubts.push(clean);
        return true;
      }
      setState("thinking", { typed: true, text: clean });
      return true;
    }

    function reconnect() {
      reconnectAttempts = 0;
      clearReconnectTimer();
      return connect(true);
    }

    function checkKeepalive(nowMs) {
      var now = nowMs || Date.now();
      /* Only an unanswered ping proves a dead link. A long listening turn, a
         throttled background tab, or a slow radio used to age `lastPongTs`
         past a 30 s absolute window and declare offline while the socket was
         perfectly alive. */
      if (lastPingSentTs && now - lastPingSentTs > pongTimeoutMs && lastPongTs < lastPingSentTs) {
        clearPingTimer();
        detachSocket();
        noteTransportLoss("pong_timeout");
        return false;
      }
      if (!ws || ws.readyState !== 1) return false;
      lastPingSentTs = now;
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
      hasMicrophone: function () { return Boolean(mediaStream); },
      getCaptureStats: function () {
        return { active: Boolean(captureProcessor), frames_sent: captureFramesSent };
      },
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
    "EVT-heartbeat":           { evt_id: "EVT-F12", event: "frontend.heartbeat",        privacy_class: "L2" },
    "EVT-read_aloud_played":   { evt_id: "EVT-012", event: "frontend.page_view",        privacy_class: "L2" },
    "EVT-consent_recorded":    { evt_id: "EVT-013", event: "frontend.page_view",        privacy_class: "L2" },
    "EVT-report_submitted":    { evt_id: "EVT-014", event: "frontend.page_view",        privacy_class: "L2" },
    "EVT-data_cleared":        { evt_id: "EVT-018", event: "frontend.page_view",        privacy_class: "L2" }
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
    /* C-025/T5: no interaction telemetry before voice consent. Nothing is
       queued, nothing is flushed, nothing leaves the device. Consent itself
       is recorded through PUT /v1/consent, not this queue. */
    if (getConsentState() !== "granted") return null;
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
    /* Queue pressure: keep the in-memory buffer bounded by flushing a batch
       instead of silently dropping the oldest interaction signal. */
    if (eventQueue.length >= EVENT_BATCH_SIZE && !flushInFlight) {
      try { flushEvents(); } catch (e) {}
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

  var EVENT_BATCH_SIZE = 20;
  var flushInFlight = false;

  async function flushEvents(endpointUrl, options) {
    var opts = options || {};
    if (flushInFlight || !eventQueue.length) {
      return { flushed: 0, remaining: eventQueue.length };
    }
    /* C-025/T5: telemetry only after consent; a pre-consent page never
       contacts the events endpoint, even if something queued by mistake. */
    if (getConsentState() !== "granted") {
      return { flushed: 0, remaining: eventQueue.length, gated: true };
    }
    var meta = currentTopicMeta();
    var url = endpointUrl || "/api/v1/events";
    var batch = eventQueue.slice(0, EVENT_BATCH_SIZE).map(function (ev) {
      return {
        evt_id: ev.evt_id,
        event: ev.event,
        client_session_id: ev.client_session_id,
        device_pseudo_id: getDevicePseudoId(),
        /* course_id was wrongly filled from props.topic; the route's course
           id (e.g. class-9-physics) is the field the backend ingests. */
        course_id: ev.props && ev.props.course_id
          ? String(ev.props.course_id)
          : String(meta.course_id || "physics"),
        block_id: ev.props && ev.props.block_id ? String(ev.props.block_id) : undefined,
        props: ev.props || {},
        ts: ev.ts
      };
    });
    flushInFlight = true;
    var sentOk = false;
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        var res = await sameOriginRequest(url, Object.assign({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ events: batch })
        }, opts.keepalive ? { keepalive: true } : {}));
        if (res && res.ok) {
          sentOk = true;
          break;
        }
      } catch (e) {
        /* Offline/no-transport: queue retained in memory, never thrown. */
      }
    }
    flushInFlight = false;
    if (sentOk) {
      eventQueue.splice(0, batch.length);
      return { flushed: batch.length, remaining: eventQueue.length, ok: true };
    }
    /* No-op fallback: retain capped queue in memory without throwing */
    return { flushed: 0, remaining: eventQueue.length, ok: false };
  }

  /* Docs README claimed flush() shipped with no caller. Wire it for real on
     pagehide (keepalive so the batch survives navigation) — gated on consent
     inside flushEvents, so an un-consented page sends nothing. */
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("pagehide", function () {
      try { flushEvents(undefined, { keepalive: true }); } catch (e) {}
    });
  }

  window.ZivonEvents = {
    EVENT_QUEUE_MAX: EVENT_QUEUE_MAX,
    EVENT_BATCH_SIZE: EVENT_BATCH_SIZE,
    EVENT_CATALOG: EVENT_CATALOG,
    emit: emitEvent,
    flush: flushEvents,
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
    ZivonShell.mount();
  });

  /* --------------- 9. Shell Injection (shell-injection.md §3) --------------
     Injects product chrome on content-only lesson pages in exact order:
       1. Global notices (offline, voice-limited warn, typed-only exhausted)
       2. Read-aloud controls (§10.13, from manifest.json -> narration.blocks)
       3. Report-a-problem button/panel (F-COR-PROV-01, POST /v1/reports)
       4. Consent gate (§10.14, localStorage["zivon.consent"])
       5. Voice dock (§10.12, ZivonVoiceDock.lazyMount)
       6. Privacy link + locale controls
     Idempotent per root (data-zn-mounted); every step is isolated in try/catch
     so any failure leaves lesson content and simulations 100% readable. */
  var globalNoticeNetWired = false;
  function ensureGlobalLessonNotices() {
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return { mounted: false };
    var isOff = typeof navigator !== "undefined" && navigator.onLine === false;
    applyLessonStateBanner(
      "offline",
      isOff ? "Offline - lesson content and simulations work without a connection." : ""
    );
    /* Mount is idempotent: re-entry must not stack duplicate listeners. */
    if (!globalNoticeNetWired) {
      globalNoticeNetWired = true;
      window.addEventListener("offline", function () {
        applyLessonStateBanner("offline", "Offline - lesson content and simulations work without a connection.");
      });
      window.addEventListener("online", function () {
        applyLessonStateBanner("offline", "");
      });
    }
    return { mounted: true };
  }

  var manifestFetchStarted = false;
  function loadTopicManifestAndMountReadAloud(explicitManifest) {
    if (explicitManifest && typeof explicitManifest === "object") {
      window.__ZIVON_MANIFEST__ = explicitManifest;
      injectReadAloudControls(explicitManifest);
      var row = document.querySelector(".zn-lang-row");
      if (row) syncLangBarBundleAvailability(row);
      return Promise.resolve(explicitManifest);
    }
    if (window.__ZIVON_MANIFEST__ && typeof window.__ZIVON_MANIFEST__ === "object") {
      injectReadAloudControls(window.__ZIVON_MANIFEST__);
      var row2 = document.querySelector(".zn-lang-row");
      if (row2) syncLangBarBundleAvailability(row2);
      return Promise.resolve(window.__ZIVON_MANIFEST__);
    }
    var lessonPage = document.querySelector(".zn-page:not(.zn-home)");
    if (!lessonPage) return Promise.resolve(null);
    /* A file:// document cannot fetch (Chromium blocks the scheme and logs a
       console error), and production is HTTP(S) only. Local previews and the
       browser tests that open a page straight off disk therefore run with no
       narration rather than a spurious console error; an explicit manifest
       (window.ZivonShell.mount({manifest}) or window.__ZIVON_MANIFEST__) is
       still honoured above. */
    if (!hasNetworkTransport()) {
      return Promise.resolve(null);
    }
    if (manifestFetchStarted) {
      /* Mount is idempotent: never fetch the manifest twice. */
      return Promise.resolve(window.__ZIVON_MANIFEST__ || null);
    }
    manifestFetchStarted = true;
    var manifestPath = (window.location && window.location.pathname
      ? window.location.pathname.replace(/\/(hi|hi-Latn)\/?$/, "/")
      : "./") + "manifest.json";
    return sameOriginRequest(manifestPath, { method: "GET" })
      .then(function (res) {
        if (!res || !res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data || typeof data !== "object") return data;
        var locMatch = (window.location.pathname || "").match(/\/(hi|hi-Latn)\/?$/);
        if (!locMatch) {
          window.__ZIVON_MANIFEST__ = data;
          injectReadAloudControls(data);
          var row3 = document.querySelector(".zn-lang-row");
          if (row3) syncLangBarBundleAvailability(row3);
          return data;
        }
        /* A localized page prefers its own narration bundle (pre-generated
           audio in that language); the topic manifest stays the fallback. */
        var locManifestPath = manifestPath.replace(/manifest\.json$/, locMatch[1] + "/manifest.json");
        return sameOriginRequest(locManifestPath, { method: "GET" })
          .then(function (res) { return res && res.ok ? res.json() : null; })
          .catch(function () { return null; })
          .then(function (locData) {
            if (locData && locData.narration) {
              data = Object.assign({}, data, { narration: locData.narration });
            }
            window.__ZIVON_MANIFEST__ = data;
            injectReadAloudControls(data);
            var row4 = document.querySelector(".zn-lang-row");
            if (row4) syncLangBarBundleAvailability(row4);
            return data;
          });
      })
      .catch(function () { return null; });
  }

  var ZivonShell = {
    mount: function (options) {
      var opts = options || {};
      var steps = {};
      var root = document.querySelector(".zn-page");
      var alreadyMounted = root && root.getAttribute("data-zn-mounted") === "true";

      /* Step 1: Global notices */
      try {
        if (opts.throwAtStep === "notices") throw new Error("injected_notices_error");
        steps.notices = ensureGlobalLessonNotices();
      } catch (e) {
        steps.notices = { mounted: false, error: String(e) };
      }

      /* Step 2: Read-aloud controls (§10.13) */
      try {
        if (opts.throwAtStep === "read_aloud") throw new Error("injected_read_aloud_error");
        if (opts.manifest) {
          window.__ZIVON_MANIFEST__ = opts.manifest;
        }
        steps.read_aloud = injectReadAloudControls(opts.manifest || window.__ZIVON_MANIFEST__ || null);
        if (!opts.manifest && !window.__ZIVON_MANIFEST__ && !alreadyMounted) {
          loadTopicManifestAndMountReadAloud(null);
        }
      } catch (e) {
        steps.read_aloud = { mounted: false, error: String(e) };
      }

      /* Step 3: Report-a-problem button/panel (F-COR-PROV-01) */
      try {
        if (opts.throwAtStep === "report") throw new Error("injected_report_error");
        steps.report = injectReportSurface();
      } catch (e) {
        steps.report = { mounted: false, error: String(e) };
      }

      /* Step 4: Consent gate (§10.14) */
      try {
        if (opts.throwAtStep === "consent") throw new Error("injected_consent_error");
        steps.consent = injectConsentGate();
      } catch (e) {
        steps.consent = { mounted: false, error: String(e) };
      }

      /* Step 5: Voice dock (§10.12) */
      try {
        if (opts.throwAtStep === "dock") throw new Error("injected_dock_error");
        steps.dock = ZivonVoiceDock.lazyMount();
      } catch (e) {
        steps.dock = { mounted: false, error: String(e) };
      }

      /* Step 6: Privacy page / footer link + locale controls */
      try {
        if (opts.throwAtStep === "privacy_locale") throw new Error("injected_privacy_locale_error");
        wirePrivacyPage();
        steps.privacy = injectFooterPrivacyLink();
        var langRow = document.querySelector(".zn-lang-row");
        if (langRow) syncLangBarBundleAvailability(langRow);
      } catch (e) {
        steps.privacy = { mounted: false, error: String(e) };
      }

      if (root) {
        root.setAttribute("data-zn-mounted", "true");
      }
      return { idempotent: Boolean(alreadyMounted), steps: steps };
    }
  };
  window.ZivonShell = ZivonShell;
})();
