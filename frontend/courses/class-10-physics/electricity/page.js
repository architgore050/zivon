ZivonSim.register("b-12", {
  init: function (ctx) {
    ctx.g = ctx.canvas.getContext('2d');
  },

  draw: function (ctx) {
    var g = ctx.g || ctx.canvas.getContext('2d');
    var W = ctx.width || 480;
    var H = ctx.height || 320;

    /* ---- helpers: axis ranges and ticks are computed, never hand-written ---- */
    function niceCeil(v) {
      var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10));
      var c = [0.8, 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
      for (var i = 0; i < c.length; i++) {
        if (c[i] * p >= v - 1e-9) { return c[i] * p; }
      }
      return 10 * p;
    }
    function niceStep(x) {
      var p = Math.pow(10, Math.floor(Math.log(x) / Math.LN10));
      var c = [1, 2, 5, 10];
      for (var i = 0; i < c.length; i++) {
        if (c[i] * p >= x - 1e-9) { return c[i] * p; }
      }
      return 10 * p;
    }
    function fmtTick(v, step) {
      var r = Math.round(v * 1e6) / 1e6;
      if (Math.abs(r - Math.round(r)) < 1e-9) { return String(Math.round(r)); }
      return step < 0.1 ? r.toFixed(2) : r.toFixed(1);
    }

    /* ---- inputs ---- */
    var cells = Math.round(Number(ctx.values.cells));
    if (!isFinite(cells)) { cells = 1; }
    cells = Math.max(1, Math.min(4, cells));

    var R = Math.round(Number(ctx.values.resistance));
    if (!isFinite(R)) { R = 4; }
    R = Math.max(1, Math.min(10, R));

    /* ---- plot frame ---- */
    var PL = 72, PR = 430, PT = 34, PB = 232;
    var vTop = 8;                              /* 4 cells x 1.5 V = 6 V max, plus headroom */
    var iTop = niceCeil((6 / R) * 1.1);        /* axis depends on R only, so adding cells never rescales it */

    function xOf(I) { return PL + (I / iTop) * (PR - PL); }
    function yOf(V) { return PB - (V / vTop) * (PB - PT); }

    g.clearRect(0, 0, W, H);
    g.lineCap = 'round';
    g.lineJoin = 'round';

    /* ---- axes (frame + arrow-free clean geometry) ---- */
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2.5;
    g.beginPath();
    g.moveTo(PL, PT - 6);
    g.lineTo(PL, PB);
    g.lineTo(PR + 6, PB);
    g.stroke();

    var mono = '"Courier Prime", "Courier New", monospace';

    /* y ticks: computed from yOf, so a tick number always equals the pixel it sits on */
    g.font = '14px ' + mono;
    g.fillStyle = '#5A5748';
    g.textAlign = 'right';
    g.textBaseline = 'middle';
    var vStep = 2;
    for (var i = 0; i * vStep <= vTop + 1e-9; i++) {
      var vv = i * vStep;
      var yy = yOf(vv);
      g.strokeStyle = '#5A5748';
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(PL - 5, yy);
      g.lineTo(PL, yy);
      g.stroke();
      g.fillText(String(vv), PL - 9, yy);
    }

    /* x ticks: computed from xOf with a step derived from the current range */
    var xStep = niceStep(iTop / 5);
    var nT = Math.floor(iTop / xStep + 1e-9);
    g.textAlign = 'center';
    g.textBaseline = 'top';
    for (var j = 0; j <= nT; j++) {
      var iv = j * xStep;
      var xx = xOf(iv);
      g.strokeStyle = '#5A5748';
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(xx, PB);
      g.lineTo(xx, PB + 5);
      g.stroke();
      g.fillText(fmtTick(iv, xStep), xx, PB + 8);
    }

    /* axis titles */
    g.fillStyle = '#1C1B18';
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillText('V (V)', PL, PT - 14);
    g.textAlign = 'right';
    g.textBaseline = 'top';
    g.fillText('I (A)', 474, PB + 8);

    /* ---- the Ohm's-law line V = I*R through the origin, evaluated point by point ---- */
    var ImaxLine = Math.min(iTop, vTop / R);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 3;
    g.beginPath();
    for (var s = 0; s <= 64; s++) {
      var II = ImaxLine * s / 64;
      var VVl = II * R;
      var lx = xOf(II);
      var ly = yOf(VVl);
      if (s === 0) { g.moveTo(lx, ly); } else { g.lineTo(lx, ly); }
    }
    g.stroke();

    /* ---- measured point for the current number of cells ---- */
    var Vn = cells * 1.5;
    var In = Vn / R;
    var pxn = xOf(In);
    var pyn = yOf(Vn);

    /* graphite guides from the live point to both axes */
    g.save();
    g.setLineDash([4, 4]);
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(PL, pyn);
    g.lineTo(pxn, pyn);
    g.lineTo(pxn, PB);
    g.stroke();
    g.restore();

    /* every measurement point (1.5 V per cell) sits on that line */
    for (var k = 1; k <= cells; k++) {
      var Vk = k * 1.5;
      var Ik = Vk / R;
      var xk = xOf(Ik);
      var yk = yOf(Vk);
      var rr = (k === cells) ? 6 : 4.5;
      g.beginPath();
      g.arc(xk, yk, rr, 0, Math.PI * 2);
      g.fillStyle = '#1F3A9E';
      g.fill();
      g.lineWidth = 2;
      g.strokeStyle = '#F6F0CF';
      g.stroke();
    }

    /* ---- readout ---- */
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillStyle = '#1C1B18';
    g.font = 'bold 15px ' + mono;
    var iTxt = In >= 1 ? In.toFixed(2) : In.toFixed(3);
    g.fillText('V = ' + Vn.toFixed(2) + ' V   I = ' + iTxt + ' A   V/I = ' + (Vn / In).toFixed(2) + ' \u03A9', 12, 278);

    g.font = '14px ' + mono;
    g.fillStyle = '#5A5748';
    g.fillText(cells + ' cell' + (cells > 1 ? 's' : '') + ' \u00D7 1.5 V = ' + Vn.toFixed(1) +
               ' V  \u00B7  V/I = R = ' + R + ' \u03A9', 12, 302);
  }
});
