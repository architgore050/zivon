ZivonSim.register("b-36", {
  init: function (ctx) {
    // Fixed pixel layout inside the 480x320 buffer (never read from layout).
    ctx.G = 10;        // g = 10 m s-2 (stated in the brief)
    ctx.RMAX = 120;    // x-axis domain: R from 0 to 120 m (control range is 5..120)
    ctx.VTOP = 35;     // y-axis top: sqrt(0.9*120*10) = 32.86 < 35 for every allowed control
    ctx.L = 64;        // plot left  (R = 0)
    ctx.RX = 452;      // plot right (R = 120)
    ctx.T = 72;        // plot top   (v = 35)
    ctx.B = 258;       // plot bottom(v = 0)
  },

  draw: function (ctx) {
    var g = ctx.g;
    var cw = (ctx.canvas && ctx.canvas.width) || 480;
    var ch = (ctx.canvas && ctx.canvas.height) || 320;

    var G = 10, RMAX = 120, VTOP = 35;
    var L = 64, RX = 452, T = 72, B = 258;
    var PW = RX - L, PH = B - T;

    var mus = (ctx.values && typeof ctx.values.mus === 'number') ? ctx.values.mus : 0.5;
    var R   = (ctx.values && typeof ctx.values.radius === 'number') ? ctx.values.radius : 30;

    var PAPER = '#F6F0CF', INK = '#1C1B18', GRAPH = '#5A5748', PEN = '#1F3A9E';

    function fnt(sz, bold) {
      return (bold ? '700 ' : '400 ') + sz + 'px "Courier Prime","Courier New",monospace';
    }

    /* ---------- paper ---------- */
    g.setLineDash([]);
    g.fillStyle = PAPER;
    g.fillRect(0, 0, cw, ch);

    /* ---------- axes ---------- */
    g.strokeStyle = INK;
    g.lineWidth = 2.5;
    g.lineCap = 'round';
    g.lineJoin = 'round';
    g.beginPath();
    g.moveTo(L, B); g.lineTo(L, T - 6);
    g.moveTo(L, B); g.lineTo(RX + 6, B);
    g.stroke();

    g.fillStyle = INK;
    g.beginPath();
    g.moveTo(L, T - 16); g.lineTo(L - 4.5, T - 5); g.lineTo(L + 4.5, T - 5);
    g.closePath(); g.fill();
    g.beginPath();
    g.moveTo(RX + 16, B); g.lineTo(RX + 5, B - 4.5); g.lineTo(RX + 5, B + 4.5);
    g.closePath(); g.fill();

    /* ---------- x ticks: R = 0,20,...,120 m (positions from the scale mapping) ---------- */
    var i, rv, vv, px, py;
    g.font = fnt(14, false);
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    for (i = 0; i <= 6; i++) {
      rv = i * 20;
      px = L + (rv / RMAX) * PW;
      g.strokeStyle = INK; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(px, B); g.lineTo(px, B + 5); g.stroke();
      g.fillStyle = GRAPH;
      g.fillText(String(rv), px, B + 16);
    }

    /* ---------- y ticks: v = 0,5,...,35 m/s (positions from the scale mapping) ---------- */
    g.textAlign = 'right';
    for (i = 0; i <= 7; i++) {
      vv = i * 5;
      py = B - (vv / VTOP) * PH;
      g.strokeStyle = INK; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(L - 5, py); g.lineTo(L, py); g.stroke();
      g.fillStyle = GRAPH;
      g.fillText(String(vv), L - 9, py);
    }

    /* ---------- axis titles ---------- */
    g.fillStyle = GRAPH;
    g.font = fnt(14, false);
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText('R (m)', (L + RX) / 2, B + 30);

    g.save();
    g.translate(20, (T + B) / 2);
    g.rotate(-Math.PI / 2);
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillStyle = GRAPH;
    g.font = fnt(14, false);
    g.fillText('v_max (m/s)', 0, 0);
    g.restore();

    /* ---------- the curve: v_max = sqrt(mu_s * R * g), evaluated point by point ---------- */
    g.beginPath();
    var STEPS = 240;
    for (i = 0; i <= STEPS; i++) {
      rv = (i / STEPS) * RMAX;
      var vCurve = Math.sqrt(mus * rv * G);              // eq-12
      if (vCurve > VTOP) vCurve = VTOP;                  // provably never needed, kept as a guard
      px = L + (rv / RMAX) * PW;
      py = B - (vCurve / VTOP) * PH;
      if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
    }
    g.strokeStyle = PEN;
    g.lineWidth = 3;
    g.lineJoin = 'round';
    g.lineCap = 'round';
    g.stroke();

    /* ---------- the chosen radius: its maximum safe speed and its guides ---------- */
    var vSel = Math.sqrt(mus * R * G);                     // eq-12 at the chosen R
    var mx = L + (R / RMAX) * PW;
    var my = B - (vSel / VTOP) * PH;

    g.save();
    g.setLineDash([5, 5]);
    g.lineWidth = 1.5;
    g.strokeStyle = GRAPH;
    g.beginPath();
    g.moveTo(mx, B);
    g.lineTo(mx, my);
    g.lineTo(L, my);
    g.stroke();
    g.restore();

    g.beginPath();
    g.arc(mx, my, 5.5, 0, Math.PI * 2);
    g.fillStyle = PEN;
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = PAPER;
    g.stroke();

    /* ---------- readout strip above the plot (kept clear of curve, axes and guides) ---------- */
    g.textBaseline = 'middle';
    g.font = fnt(14, false);
    g.fillStyle = INK;
    g.textAlign = 'left';
    g.fillText('\u00B5 = ' + mus.toFixed(2), 20, 20);
    g.textAlign = 'right';
    g.fillText('R = ' + Math.round(R) + ' m', 460, 20);

    g.textAlign = 'left';
    g.font = fnt(16, true);
    g.fillStyle = PEN;
    g.fillText('v_max = ' + vSel.toFixed(1) + ' m/s', 20, 42);
  }
});
