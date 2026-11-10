(function () {
  "use strict";

  var PAL = {
    paper: "#EFE6B8",
    light: "#F6F0CF",
    ink: "#1C1B18",
    graphite: "#5A5748",
    pen: "#1F3A9E",
    red: "#B3261E",
    green: "#2F6B2F"
  };

  var F_NUM = '700 14px "Courier Prime", "Courier New", monospace';
  var F_VAL = '700 15px "Courier Prime", "Courier New", monospace';
  var F_LAB = '500 14px "Bricolage Grotesque", Arial, sans-serif';
  var G_ACC = 9.8;

  function num(x, d) {
    return (typeof x === "number" && isFinite(x)) ? x : d;
  }

  function clamp(x, lo, hi) {
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
  }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y);
    g.quadraticCurveTo(x + w, y, x + w, y + r);
    g.lineTo(x + w, y + h - r);
    g.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    g.lineTo(x + r, y + h);
    g.quadraticCurveTo(x, y + h, x, y + h - r);
    g.lineTo(x, y + r);
    g.quadraticCurveTo(x, y, x + r, y);
    g.closePath();
  }

  /* axis range recomputed from the live values every frame (frame law) */
  function niceAxis(maxVal) {
    var steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000];
    var raw = maxVal / 4;
    var step = steps[steps.length - 1];
    var i;
    for (i = 0; i < steps.length; i++) {
      if (steps[i] >= raw) { step = steps[i]; break; }
    }
    var top = Math.ceil(maxVal / step) * step;
    if (!(top > 0)) top = step;
    return { top: top, step: step };
  }

  /* banked road cross-section: road surface at angle th above the horizontal */
  function drawBank(g, th) {
    var PX = 36, PY = 268, L = 168;
    var cs = Math.cos(th), sn = Math.sin(th);
    var tx = PX + L * cs, ty = PY - L * sn;
    var i, f, bx, by;

    g.setLineDash([]);
    g.strokeStyle = PAL.ink;
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(18, PY);
    g.lineTo(252, PY);
    g.stroke();

    g.strokeStyle = PAL.graphite;
    g.lineWidth = 1.5;
    for (i = 1; i <= 8; i++) {
      f = i / 9;
      bx = PX + L * f * cs;
      by = PY - L * f * sn;
      g.beginPath();
      g.moveTo(bx, by);
      g.lineTo(bx + sn * 9, by + cs * 9);
      g.stroke();
    }

    g.strokeStyle = PAL.ink;
    g.lineWidth = 4;
    g.beginPath();
    g.moveTo(PX, PY);
    g.lineTo(tx, ty);
    g.stroke();

    if (th > 0.002) {
      g.strokeStyle = PAL.graphite;
      g.lineWidth = 2;
      g.beginPath();
      g.arc(PX, PY, 46, -th, 0, false);
      g.stroke();
    }

    var la = -th / 2;
    var lx = PX + 56 * Math.cos(la);
    var ly = PY + 56 * Math.sin(la);
    if (ly > PY - 20) ly = PY - 20;
    g.font = F_LAB;
    g.fillStyle = PAL.ink;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText("\u03B8", lx, ly);

    /* car sits 0.66 of the way up the bank, on the outward normal */
    var f2 = 0.66;
    var cx = PX + L * f2 * cs;
    var cy = PY - L * f2 * sn;
    var ox = cx - sn * 11;
    var oy = cy - cs * 11;

    g.save();
    g.translate(ox, oy);
    g.rotate(-th);
    g.strokeStyle = PAL.ink;
    g.lineWidth = 2.4;
    g.beginPath(); g.arc(-10.5, 7, 3.4, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.arc(10.5, 7, 3.4, 0, Math.PI * 2); g.stroke();
    roundRect(g, -19, -8, 38, 13, 2.5);
    g.stroke();
    roundRect(g, -8, -16, 16, 8, 2);
    g.stroke();
    g.restore();
  }

  /* bars: v_o, v_max, flat-road limit — heights computed from the cited equations */
  function drawChart(g, vo, vmax, vf) {
    var axL = 306, top = 96, bot = 268;
    var finiteMax = Math.max(vo, vf);
    if (isFinite(vmax)) {
      finiteMax = Math.max(finiteMax, vmax);
    } else {
      finiteMax = Math.max(vo, vf, 1) * 1.6;
    }
    if (finiteMax <= 0) finiteMax = 10;

    var ax = niceAxis(finiteMax);
    var sc = (bot - top) / ax.top;

    function yOf(v) {
      var q = v > ax.top ? ax.top : v;
      return bot - q * sc;
    }

    g.setLineDash([]);
    g.strokeStyle = PAL.ink;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(axL, top - 2);
    g.lineTo(axL, bot);
    g.stroke();

    g.font = F_NUM;
    g.fillStyle = PAL.graphite;
    g.textAlign = "right";
    g.textBaseline = "middle";
    var nT = Math.round(ax.top / ax.step);
    var i, tv, ty;
    for (i = 0; i <= nT; i++) {
      tv = i * ax.step;
      ty = yOf(tv);
      g.strokeStyle = PAL.graphite;
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(axL - 8, ty);
      g.lineTo(axL, ty);
      g.stroke();
      g.fillText(String(Math.round(tv)), axL - 12, ty);
    }

    g.font = F_LAB;
    g.fillStyle = PAL.graphite;
    g.textAlign = "right";
    g.textBaseline = "alphabetic";
    g.fillText("v (m/s)", axL, 66);

    var bars = [
      { v: vo, lab: "v_o", col: PAL.pen, cx: 340, dash: false },
      { v: vmax, lab: "v_max", col: PAL.ink, cx: 390, dash: false },
      { v: vf, lab: "flat", col: PAL.graphite, cx: 440, dash: true }
    ];
    var bw = 26;

    for (i = 0; i < bars.length; i++) {
      var bar = bars[i];
      var inf = !isFinite(bar.v);
      var yt = inf ? top : yOf(bar.v);
      var h = bot - yt;
      var x0 = bar.cx - bw / 2;

      if (h > 0.8) {
        g.globalAlpha = 0.14;
        g.fillStyle = bar.col;
        g.fillRect(x0, yt, bw, h);
        g.globalAlpha = 1;
      }

      g.strokeStyle = bar.col;
      g.lineWidth = 2.2;
      g.setLineDash(bar.dash ? [6, 4] : []);
      g.strokeRect(x0, Math.min(yt, bot - 1.5), bw, Math.max(h, 1.5));
      g.setLineDash([]);

      g.font = F_VAL;
      g.fillStyle = bar.col;
      g.textAlign = "center";
      g.textBaseline = "alphabetic";
      g.fillText(inf ? "\u221E" : bar.v.toFixed(1), bar.cx, yt - 8);

      g.font = F_LAB;
      g.fillStyle = PAL.ink;
      g.fillText(bar.lab, bar.cx, bot + 20);
    }

    g.font = F_LAB;
    g.fillStyle = PAL.graphite;
    g.textAlign = "center";
    g.textBaseline = "alphabetic";
    g.fillText("v_o needs no friction \u00B7 v_max is the friction limit", 246, 308);
  }

  ZivonSim.register("b-32", {
    init: function (ctx) {
      ctx.g = ctx.canvas.getContext("2d");
    },
    draw: function (ctx) {
      var g = ctx.g || ctx.canvas.getContext("2d");
      var W = ctx.width || 480;
      var H = ctx.height || 320;

      g.clearRect(0, 0, W, H);
      g.lineCap = "round";
      g.lineJoin = "round";
      g.setLineDash([]);
      g.globalAlpha = 1;

      var vals = ctx.values || {};
      var mu = clamp(num(vals.mu_s, 0.2), 0, 1);
      var R = Math.max(1, num(vals.R, 300));
      var thDeg = clamp(num(vals.theta, 15), 0, 45);
      var th = thDeg * Math.PI / 180;
      var tn = Math.tan(th);

      /* eq-11 */
      var vo = Math.sqrt(R * G_ACC * tn);
      /* eq-08, level road with the same mu_s and R */
      var vf = Math.sqrt(mu * R * G_ACC);
      /* eq-10; mu_s tan(theta) >= 1 means friction never sets a limit */
      var den = 1 - mu * tn;
      var vmax = den > 1e-3 ? Math.sqrt(R * G_ACC * (tn + mu) / den) : Infinity;

      drawBank(g, th);
      drawChart(g, vo, vmax, vf);
    }
  });
})();
