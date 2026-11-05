/* ==========================================================================
   lesson-kit.js  -  shared tools for every lesson page.
   load this file with a script tag (src="lesson-kit.js"), then call LessonKit.init({...})

   THE ONE IDEA: never calculate where a ruled line should be. READ where the
   browser actually put the text, and draw the rule there.

     rule position  =  measured baseline of a real text line      (anchors)
     gaps           =  the distance between two neighbouring anchors cut into
                       equal steps (a whole number of rows)
     above / below  =  continue at one row pitch from the first / last anchor

   Because every rule is derived from the text itself on every layout pass,
   nothing can drift: no rule depends on how many pixels came before it.
   Fonts, zoom, fallback glyphs, wrapping, device-pixel ratio - all irrelevant.

   Page contract (CSS):  --row = the nominal line pitch (e.g. 2.25rem),
   --rule = rule colour.  The paper element is full width; opaque cards on top
   of it hide the rules (their text is skipped as anchors).
   ========================================================================== */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const qa = (s, r = document) => [...r.querySelectorAll(s)];
  const raf = (() => { let q = new Set(), t = 0;
    return fn => { q.add(fn); t ||= requestAnimationFrame(() => { t = 0; const f = [...q]; q.clear(); f.forEach(g => g()); }); }; })();

  /* ---------- measuring primitives (the browser does the maths) ---------- */

  /* Distance from the top of a text run's client rect to its baseline, for one font.
     Measured with a throw-away element laid out by the same engine, cached per font. */
  const ascents = new Map();
  function ascentOf(cs) {
    const key = [cs.fontStyle, cs.fontWeight, cs.fontSize, cs.fontFamily, cs.fontStretch].join('|');
    if (ascents.has(key)) return ascents.get(key);
    const s = document.createElement('span'), m = document.createElement('span');
    s.style.cssText = 'position:absolute;left:0;top:0;visibility:hidden;white-space:nowrap;line-height:normal';
    Object.assign(s.style, { fontStyle: cs.fontStyle, fontWeight: cs.fontWeight, fontSize: cs.fontSize, fontFamily: cs.fontFamily, fontStretch: cs.fontStretch });
    m.style.cssText = 'display:inline-block;width:0;height:0';
    s.textContent = 'Hx'; s.append(m); document.body.append(s);
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
      const cs = getComputedStyle(el); if (cs.visibility === 'hidden') continue;
      const up = ascentOf(cs); r.selectNodeContents(n);
      for (const rc of r.getClientRects()) if (rc.width > 0) out.push(rc.top + up);
    }
    return out.sort((a, b) => a - b);
  }
  /* merge baselines that belong to the same visual line (mixed fonts/inline boxes) */
  function mergeLines(ys, row) {
    const out = [];
    for (const y of ys) { const l = out[out.length - 1]; if (l && y - l.sum / l.n < row * .4) { l.sum += y; l.n++; } else out.push({ sum: y, n: 1 }); }
    return out.map(l => l.sum / l.n);
  }
  /* a CSS length (var / rem / calc) -> px, resolved by the browser */
  function px(host, css) {
    const p = document.createElement('div'); p.style.cssText = `position:absolute;visibility:hidden;height:${css}`;
    host.append(p); const h = p.getBoundingClientRect().height; p.remove(); return h;
  }

  /* ---------- baseline normalising: every font's baseline -> the same place inside its line ---------- */
  /* Exact distance from the TOP of a line box to its baseline, read from two zero-size probes placed
     in that very line: one aligned to the baseline, one aligned to the line-box top. */
  function lineOffset(textNode) {
    const b = document.createElement('span'), t = document.createElement('span');
    b.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
    t.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:top';
    textNode.before(t, b);
    const d = b.getBoundingClientRect().bottom - t.getBoundingClientRect().top;
    t.remove(); b.remove(); return d;
  }
  const shifts = new WeakMap();
  const fold = (d, row) => { d = ((d % row) + row) % row; return d > row / 2 ? d - row : d; };
  const BLOCKISH = /^(block|list-item|inline-block|flow-root|table-cell)$/;
  /* Different fonts put their baseline at different heights inside the same 36px line.
     Measure that per block and nudge it (position:relative; top) so ALL baselines match the reference text. */
  function normalize(paper, ref, skip, row) {
    const refNode = textNodeOf(paper.querySelector(ref)); if (!refNode) return;
    const REF = lineOffset(refNode), seen = new Set(), w = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) {                      /* document order: ancestors before descendants */
      const el = n.parentElement;
      if (!n.nodeValue.trim() || seen.has(el) || el.closest(skip)) continue;
      seen.add(el);
      const cs = getComputedStyle(el); if (!BLOCKISH.test(cs.display) || cs.position === 'absolute') continue;
      let anc = 0; for (let p = el.parentElement; p && p !== paper; p = p.parentElement) anc += shifts.get(p) || 0;
      const own = -fold(lineOffset(n) - REF, row), want = own - anc;     /* ancestors already moved us by `anc` */
      shifts.set(el, own);
      if (cs.position === 'static') el.style.position = 'relative';
      el.style.top = Math.abs(want) < .01 ? '' : want.toFixed(2) + 'px';
    }
  }
  const textNodeOf = el => { if (!el) return null; for (const c of el.childNodes) if (c.nodeType === 3 && c.nodeValue.trim()) return c; return null; };

  /* ---------- tool 1: ruled paper ---------- */
  function ruledPaper(o) {
    const paper = document.querySelector(o.paper); if (!paper) return { refresh() {} };
    Object.assign(paper.style, { position: 'relative', isolation: 'isolate' });   /* rules sit behind content, above the paper colour */
    const svg = document.createElementNS(NS, 'svg'), path = document.createElementNS(NS, 'path');
    svg.setAttribute('aria-hidden', 'true'); svg.classList.add('rules');
    svg.style.cssText = 'position:absolute;left:0;top:0;width:100%;z-index:-1;pointer-events:none;overflow:visible';
    path.style.fill = 'var(--rule)'; svg.append(path); paper.prepend(svg);
    const skip = o.skip || 'script,style,svg,button,sup,sub,.card,[data-ruled-skip]';   /* no rules behind opaque cards */
    const skipShift = 'script,style,svg,button,sup,sub,[data-ruled-skip]';

    function draw() {
      o.beforeDraw && o.beforeDraw();
      const row = px(paper, 'var(--row)');
      normalize(paper, o.ref || 'p', skipShift, row);
      const pr = paper.getBoundingClientRect(), W = pr.width, H = paper.scrollHeight;
      const dpr = devicePixelRatio || 1, snap = y => Math.round(y * dpr) / dpr, th = o.thickness || 2;
      const a = mergeLines(textBaselines(paper, skip), row).map(y => y - pr.top);
      const ys = [];
      if (a.length) {
        for (let y = a[0]; y >= 0; y -= row) ys.push(y);                          /* above the first line  */
        for (let i = 0; i < a.length - 1; i++) {                                  /* between two real lines */
          const n = Math.max(1, Math.round((a[i + 1] - a[i]) / row)), step = (a[i + 1] - a[i]) / n;
          for (let k = 1; k <= n; k++) ys.push(a[i] + k * step);                  /* ends exactly on the next line */
        }
        for (let y = a[a.length - 1] + row; y < H; y += row) ys.push(y);          /* below the last line   */
      }
      svg.setAttribute('height', H); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      path.setAttribute('d', ys.map(y => { y = snap(y); return `M0 ${y}H${W}V${y + th}H0Z`; }).join(''));
      mo.takeRecords();                                                           /* ignore our own DOM writes */
    }
    const refresh = () => raf(draw);
    const mo = new MutationObserver(refresh);
    mo.observe(paper, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['open', 'hidden', 'class', 'aria-checked'] });
    new ResizeObserver(refresh).observe(paper);
    document.addEventListener('toggle', refresh, true);                           /* <details> open/close */
    document.fonts && (document.fonts.ready.then(refresh), document.fonts.addEventListener('loadingdone', refresh));
    refresh(); return { refresh, row: () => px(paper, 'var(--row)') };
  }

  /* ---------- tool 2: pen underline for key statements ---------- */
  const seedFrom = s => { let h = 2166136261 >>> 0; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
  const rng = a => () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  function pen(el) {
    qa('.uline', el).forEach(n => n.remove());
    const rg = document.createRange(), fs = parseFloat(getComputedStyle(el).fontSize);
    rg.selectNodeContents(el);
    const last = [...rg.getClientRects()].pop(); if (!last) return;
    const m = document.createElement('span'); m.style.cssText = 'display:inline-block;width:0;height:0'; el.append(m);
    const baseline = m.getBoundingClientRect().bottom; m.remove();
    const box = el.getBoundingClientRect(), yo = baseline + .3 * fs - box.bottom;     /* .3em under the LAST line */
    const len = last.width + .27 * fs, x0 = -.09 * fs, n = Math.max(4, Math.round(len / (.45 * fs))), R = rng(seedFrom(el.textContent.trim())), top = [], bot = [];
    for (let i = 0; i <= n; i++) { const t = i / n, y = yo + .02 * fs * Math.sin(2 * Math.PI * (len * t) / (4 * fs) + .7) + (R() * 2 - 1) * .007 * fs, h = (.067 - .034 * t) * fs / 2;
      top.push([x0 + len * t, y - h]); bot.push([x0 + len * t, y + h]); }
    const d = top.concat(bot.reverse()).map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ') + 'Z';
    const s = document.createElementNS(NS, 'svg');
    s.setAttribute('class', 'uline'); s.setAttribute('aria-hidden', 'true'); s.setAttribute('overflow', 'visible');
    s.setAttribute('width', Math.ceil(last.width)); s.setAttribute('height', Math.ceil(fs)); s.style.left = (last.left - box.left) + 'px';
    s.innerHTML = `<path d="${d}" fill="#1F3A9E"/>`; el.append(s);
  }
  function penUnderlines(sel) {
    const ro = new ResizeObserver(es => es.forEach(e => pen(e.target)));            /* re-wrap -> redraw */
    const go = () => qa(sel).forEach(el => { pen(el); ro.observe(el); });
    document.fonts ? document.fonts.ready.then(go) : go();
    document.fonts && document.fonts.addEventListener('loadingdone', () => qa(sel).forEach(pen));
  }

  window.LessonKit = {
    /* init({ paper:'.paper', pen:'.key,h1.t', beforeDraw: fn }) */
    init(o = {}) { const r = ruledPaper({ paper: '.paper', ...o }); o.pen !== false && penUnderlines(o.pen || '.key,h1.t'); return r; },
    ruledPaper, pen, px, textBaselines
  };
})();
