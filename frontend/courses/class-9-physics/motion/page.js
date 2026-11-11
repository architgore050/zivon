// b-16 — Graphs when the net force is zero
// Velocity–time is a horizontal line at v; position–time is a straight line of slope v.
// Both curves are evaluated point-by-point from v(t) = v (constant) and x(t) = v*t.

ZivonSim.register("b-16", {
  init: function (ctx) {
    ctx.t = 0;
  },

  draw: function (ctx) {
    var g = ctx.g || ctx.canvas.getContext("2d");
    var W = 480, H = 320;

    // ---- control value (speed, m/s) ----
    var v = Number(ctx.values && ctx.values.speed);
    if (!isFinite(v)) v = 0;
    v = Math.max(0, Math.min(5, v));

    // ---- declared, fixed axes (content provably stays inside) ----
    var T = 5;      // seconds of motion shown          -> t axis  0..5 s
    var VMAX = 6;   // m/s, speed control max is 5      -> v axis  0..6 m/s
    var XMAX = 25;  // m, largest x = 5 m/s * 5 s       -> x axis  0..25 m

    // ---- layout (480 x 320 buffer) ----
    var PL = 62, PR = 440;
    var ATOP = 34, ABOT = 118;   // velocity–time plot box
    var BTOP = 178, BBOT = 262;  // position–time plot box

    // ---- scale mappings: value -> pixel (used by ticks AND curves) ----
    function tx(t) { return PL + (t / T) * (PR - PL); }
    function vy(val) { return ABOT - (val / VMAX) * (ABOT - ATOP); }
    function xy(val) { return BBOT - (val / XMAX) * (BBOT - BTOP); }

    function fmt(n) { return String(Math.round(n * 100) / 100); }

    var MONO = '14px "Courier Prime","Courier New",monospace';
    var MONOB = 'bold 14px "Courier Prime","Courier New",monospace';

    g.clearRect(0, 0, W, H);
    g.lineCap = "round";
    g.lineJoin = "round";
    g.textBaseline = "alphabetic";

    // ---- tick helpers: tick positions come from the same mapping as the curves ----
    function yTicks(mapVal, step, maxVal) {
      g.font = MONO;
      g.textAlign = "right";
      for (var val = 0; val <= maxVal + 1e-9; val += step) {
        var y = mapVal(val);
        g.strokeStyle = "#5A5748";
        g.lineWidth = 1;
        g.beginPath();
        g.moveTo(PL - 5, y);
        g.lineTo(PL, y);
        g.stroke();
        g.fillStyle = "#5A5748";
        g.fillText(fmt(val), PL - 8, y + 4);
      }
    }
    function xTicks(bot) {
      g.font = MONO;
      g.textAlign = "center";
      for (var t = 0; t <= T + 1e-9; t += 1) {
        var x = tx(t);
        g.strokeStyle = "#5A5748";
        g.lineWidth = 1;
        g.beginPath();
        g.moveTo(x, bot);
        g.lineTo(x, bot + 4);
        g.stroke();
        g.fillStyle = "#5A5748";
        g.fillText(fmt(t), x, bot + 16);
      }
    }
    function frameBox(top, bot, ylabel) {
      g.strokeStyle = "#1C1B18";
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(PL, top);
      g.lineTo(PL, bot);
      g.lineTo(PR, bot);
      g.stroke();
      g.font = MONOB;
      g.fillStyle = "#1C1B18";
      g.textAlign = "left";
      g.fillText(ylabel, PL, top - 16);
      g.textAlign = "right";
      g.fillText("t (s)", PR, top - 16);
    }

    // ---------- 1. axes, ticks, axis labels ----------
    frameBox(ATOP, ABOT, "v (m/s)");
    yTicks(vy, 2, VMAX);
    xTicks(ABOT);

    frameBox(BTOP, BBOT, "x (m)");
    yTicks(xy, 5, XMAX);
    xTicks(BBOT);

    // ---------- 2. the two computed curves ----------
    // velocity–time: v(t) = v, constant, so a horizontal line at height v
    var t, s;
    g.strokeStyle = "#1F3A9E";
    g.lineWidth = 3;
    g.beginPath();
    s = true;
    for (t = 0; t <= T + 1e-9; t += 0.05) {
      var ax = tx(t), ay = vy(v);
      if (s) { g.moveTo(ax, ay); s = false; } else { g.lineTo(ax, ay); }
    }
    g.stroke();

    // position–time: x(t) = v * t, a straight line of constant slope v
    g.beginPath();
    s = true;
    for (t = 0; t <= T + 1e-9; t += 0.05) {
      var bx = tx(t), by = xy(v * t);
      if (s) { g.moveTo(bx, by); s = false; } else { g.lineTo(bx, by); }
    }
    g.stroke();

    // ---------- 3. travelling time marker ----------
    var period = 5.6;
    var time = ctx.t || 0;
    var tNow = Math.min(time % period, T);

    g.save();
    g.setLineDash([3, 4]);
    g.lineWidth = 1;
    g.strokeStyle = "#5A5748";
    g.globalAlpha = 0.65;

    // velocity panel: the velocity is the height of the point above the axis
    g.beginPath();
    g.moveTo(tx(tNow), ABOT);
    g.lineTo(tx(tNow), vy(v));
    g.stroke();

    // position panel: read the position off the y axis
    var px = tx(tNow), py = xy(v * tNow);
    g.beginPath();
    g.moveTo(px, BBOT);
    g.lineTo(px, py);
    g.stroke();
    if (v > 0) {
      g.beginPath();
      g.moveTo(PL, py);
      g.lineTo(px, py);
      g.stroke();
    }
    g.restore();

    g.fillStyle = "#1F3A9E";
    g.beginPath();
    g.arc(tx(tNow), vy(v), 4.5, 0, Math.PI * 2);
    g.fill();
    g.beginPath();
    g.arc(px, py, 4.5, 0, Math.PI * 2);
    g.fill();

    // ---------- 4. readout ----------
    g.font = MONOB;
    g.fillStyle = "#1C1B18";
    g.textAlign = "left";
    g.fillText("v = " + v + " m/s \u00b7 a = 0 \u00b7 x(5 s) = " + (v * T) + " m", 24, 300);
  }
});
