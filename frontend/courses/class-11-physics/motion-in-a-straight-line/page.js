ZivonSim.register('b-05', {
  init: function (ctx) {
    if (ctx.values.t === undefined || ctx.values.t === null) { ctx.values.t = 4; }
  },
  draw: function (ctx) {
    var g = ctx.g;
    var W = ctx.width || 480;
    var H = ctx.height || 320;
    var t0 = (ctx.values.t !== undefined && ctx.values.t !== null) ? ctx.values.t : 4;
    var plotL = 58, plotR = W - 16, plotT = 20, plotB = H - 64;
    var tMax = 6, xMax = 18;
    function X(t) { return plotL + (t / tMax) * (plotR - plotL); }
    function Y(x) { return plotB - (x / xMax) * (plotB - plotT); }
    function pos(t) { return 0.08 * t * t * t; }
    function vel(t) { return 0.24 * t * t; }
    var x0 = pos(t0);
    var v0 = vel(t0);
    var gt, gx, t, tt, px, py, xt, tx, ty;
    g.fillStyle = '#F6F0CF';
    g.fillRect(0, 0, W, H);
    g.strokeStyle = '#5A5748';
    g.globalAlpha = 0.18;
    g.lineWidth = 1;
    g.setLineDash([]);
    for (gt = 0; gt <= 6; gt++) { g.beginPath(); g.moveTo(X(gt), plotT); g.lineTo(X(gt), plotB); g.stroke(); }
    for (gx = 0; gx <= 18; gx += 6) { g.beginPath(); g.moveTo(plotL, Y(gx)); g.lineTo(plotR, Y(gx)); g.stroke(); }
    g.globalAlpha = 1;
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2.5;
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(plotL, plotT);
    g.lineTo(plotL, plotB);
    g.lineTo(plotR, plotB);
    g.stroke();
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 3;
    g.lineJoin = 'round';
    g.beginPath();
    for (t = 0; t <= 6.0001; t += 0.05) { px = X(t); py = Y(pos(t)); if (t === 0) { g.moveTo(px, py); } else { g.lineTo(px, py); } }
    g.stroke();
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.setLineDash([5, 5]);
    g.beginPath();
    g.moveTo(X(t0), Y(x0));
    g.lineTo(X(t0), plotB);
    g.moveTo(X(t0), Y(x0));
    g.lineTo(plotL, Y(x0));
    g.stroke();
    g.setLineDash([]);
    var dtri = t0 <= 5 ? 1 : -1;
    var qx = X(t0 + dtri), qy = Y(x0), rx = qx, ry = Y(x0 + v0 * dtri);
    g.setLineDash([4, 4]);
    g.beginPath();
    g.moveTo(X(t0), qy);
    g.lineTo(qx, qy);
    g.lineTo(rx, ry);
    g.stroke();
    g.setLineDash([]);
    g.strokeStyle = '#1F3A9E';
    g.lineWidth = 3;
    g.beginPath();
    var inSeg = false;
    for (tt = 0; tt <= 6.0001; tt += 0.05) {
      xt = x0 + v0 * (tt - t0);
      if (xt >= 0 && xt <= xMax) {
        tx = X(tt); ty = Y(xt);
        if (!inSeg) { g.moveTo(tx, ty); inSeg = true; } else { g.lineTo(tx, ty); }
      } else { inSeg = false; }
    }
    g.stroke();
    g.fillStyle = '#1F3A9E';
    g.beginPath();
    g.arc(X(t0), Y(x0), 6, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = '#F6F0CF';
    g.lineWidth = 2;
    g.stroke();
    g.fillStyle = '#5A5748';
    g.font = '14px Courier Prime, monospace';
    g.textAlign = 'center';
    g.textBaseline = 'top';
    for (gt = 0; gt <= 6; gt++) { g.fillText(String(gt), X(gt), plotB + 6); }
    g.textAlign = 'right';
    g.textBaseline = 'middle';
    for (gx = 0; gx <= 18; gx += 6) { g.fillText(String(gx), plotL - 8, Y(gx)); }
    g.fillStyle = '#1C1B18';
    g.font = 'bold 14px Courier Prime, monospace';
    g.textAlign = 'left';
    g.textBaseline = 'top';
    g.fillText('x (m)', plotL + 6, plotT + 4);
    g.textAlign = 'right';
    g.textBaseline = 'bottom';
    g.fillText('t (s)', plotR - 4, plotB - 4);
    g.fillStyle = '#5A5748';
    g.font = '14px Courier Prime, monospace';
    g.textAlign = 'center';
    g.textBaseline = 'top';
    g.fillText('1 s', (X(t0) + qx) / 2, qy + 4);
    if (v0 > 0.05) {
      g.textBaseline = 'middle';
      if (dtri > 0) { g.textAlign = 'left'; g.fillText('Δx', qx + 4, (qy + ry) / 2); }
      else { g.textAlign = 'right'; g.fillText('Δx', qx - 4, (qy + ry) / 2); }
    }
    var leftSide = X(t0) >= W - 190;
    var ax = leftSide ? X(t0) - 180 : X(t0) + 14;
    var ay = Y(x0) - 30;
    if (ay < plotT + 4) { ay = plotT + 4; }
    g.fillStyle = '#1F3A9E';
    g.font = '700 20px Caveat, cursive';
    g.textAlign = 'left';
    g.textBaseline = 'top';
    g.fillText('slope = v', ax, ay);
    var sx = leftSide ? ax + 150 : ax;
    var sy = ay + 10;
    var ang = Math.atan2(Y(x0) - sy, X(t0) - sx);
    g.strokeStyle = '#1F3A9E';
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(sx, sy);
    g.lineTo(X(t0), Y(x0));
    g.moveTo(X(t0), Y(x0));
    g.lineTo(X(t0) - 10 * Math.cos(ang - 0.4), Y(x0) - 10 * Math.sin(ang - 0.4));
    g.moveTo(X(t0), Y(x0));
    g.lineTo(X(t0) - 10 * Math.cos(ang + 0.4), Y(x0) - 10 * Math.sin(ang + 0.4));
    g.stroke();
    g.fillStyle = '#1C1B18';
    g.font = '15px Courier Prime, monospace';
    g.textAlign = 'left';
    g.textBaseline = 'top';
    g.fillText('t = ' + t0.toFixed(1) + ' s    x = 0.08 t³ = ' + x0.toFixed(2) + ' m', plotL, plotB + 24);
    g.fillStyle = '#1F3A9E';
    g.font = 'bold 16px Courier Prime, monospace';
    g.fillText('v = dx/dt = 0.24 t² = ' + v0.toFixed(2) + ' m s⁻¹', plotL, plotB + 44);
  }
});


ZivonSim.register('b-09', { init: function (ctx) {}, draw: function (ctx) { var g = ctx.g || ctx.canvas.getContext('2d'); var W = ctx.canvas.width || 480; var H = ctx.canvas.height || 320; var v0 = (ctx.values && typeof ctx.values.v0 === 'number') ? ctx.values.v0 : 5; var a = (ctx.values && typeof ctx.values.a === 'number') ? ctx.values.a : 2; var T = 4; var vT = v0 + a * T; var disp = v0 * T + 0.5 * a * T * T; var lo = Math.min(0, v0, vT); var hi = Math.max(0, v0, vT); var pad = Math.max(2, (hi - lo) * 0.18); lo -= pad; hi += pad; var L = 50, R = 470, Tp = 40, Bt = 250; function xOf(t) { return L + (t / T) * (R - L); } function yOf(v) { return Tp + (hi - v) / (hi - lo) * (Bt - Tp); } function fmt(n) { return String(Math.round(n * 10) / 10); } g.fillStyle = '#EFE6B8'; g.fillRect(0, 0, W, H); g.beginPath(); g.moveTo(xOf(0), yOf(0)); g.lineTo(xOf(0), yOf(v0)); for (var t = 0; t <= T + 0.0001; t += 0.1) { var v = v0 + a * t; g.lineTo(xOf(t), yOf(v)); } g.lineTo(xOf(T), yOf(0)); g.closePath(); g.fillStyle = 'rgba(31,58,158,0.22)'; g.fill(); g.strokeStyle = '#1F3A9E'; g.lineWidth = 1.5; g.setLineDash([5, 4]); g.stroke(); g.setLineDash([]); if (a !== 0) { g.beginPath(); g.moveTo(xOf(0), yOf(v0)); g.lineTo(xOf(1), yOf(v0)); g.lineTo(xOf(1), yOf(v0 + a)); g.strokeStyle = '#5A5748'; g.lineWidth = 1.5; g.setLineDash([4, 4]); g.stroke(); g.setLineDash([]); } g.strokeStyle = '#1C1B18'; g.lineWidth = 2.5; g.beginPath(); g.moveTo(L, yOf(0)); g.lineTo(R, yOf(0)); g.moveTo(xOf(0), Tp); g.lineTo(xOf(0), Bt); g.stroke(); g.beginPath(); g.moveTo(R, yOf(0)); g.lineTo(R - 10, yOf(0) - 5); g.lineTo(R - 10, yOf(0) + 5); g.closePath(); g.fillStyle = '#1C1B18'; g.fill(); g.beginPath(); g.moveTo(xOf(0), Tp); g.lineTo(xOf(0) - 5, Tp + 10); g.lineTo(xOf(0) + 5, Tp + 10); g.closePath(); g.fill(); g.beginPath(); for (var t2 = 0; t2 <= T + 0.0001; t2 += 0.1) { var v2 = v0 + a * t2; var px = xOf(t2); var py = yOf(v2); if (t2 === 0) { g.moveTo(px, py); } else { g.lineTo(px, py); } } g.strokeStyle = '#1F3A9E'; g.lineWidth = 3; g.stroke(); g.beginPath(); g.arc(xOf(0), yOf(v0), 5, 0, Math.PI * 2); g.fillStyle = '#F6F0CF'; g.fill(); g.strokeStyle = '#1C1B18'; g.lineWidth = 2; g.stroke(); g.beginPath(); g.arc(xOf(T), yOf(vT), 5, 0, Math.PI * 2); g.fill(); g.stroke(); var now = (typeof ctx.t === 'number') ? ctx.t : 0; var tt = now % T; var vv = v0 + a * tt; g.beginPath(); g.moveTo(xOf(tt), yOf(vv)); g.lineTo(xOf(tt), yOf(0)); g.strokeStyle = '#5A5748'; g.lineWidth = 1.5; g.setLineDash([4, 4]); g.stroke(); g.setLineDash([]); g.beginPath(); g.arc(xOf(tt), yOf(vv), 5, 0, Math.PI * 2); g.fillStyle = '#1F3A9E'; g.fill(); g.strokeStyle = '#1C1B18'; g.lineWidth = 2; g.stroke(); g.fillStyle = '#1C1B18'; g.font = '700 15px monospace'; g.textAlign = 'left'; g.textBaseline = 'alphabetic'; g.fillText('Velocity-time graph', L, 24); g.save(); g.translate(18, (Tp + Bt) / 2); g.rotate(-Math.PI / 2); g.textAlign = 'center'; g.font = '700 14px monospace'; g.fillText('v (m/s)', 0, 0); g.restore(); g.textAlign = 'right'; g.font = '700 14px monospace'; g.fillText('t (s)', R, yOf(0) - 8); g.textAlign = 'left'; g.fillText(fmt(v0), xOf(0) + 8, yOf(v0) - 8); g.textAlign = 'right'; g.fillText(fmt(vT), xOf(T) - 8, yOf(vT) - 8); g.textAlign = 'center'; g.font = '700 16px cursive'; g.fillStyle = '#1F3A9E'; g.fillText('area', xOf(T / 2), yOf((v0 + vT) / 4) + 5); if (a !== 0) { g.textAlign = 'left'; g.font = '700 14px monospace'; g.fillStyle = '#5A5748'; g.fillText('slope = a', xOf(1) + 6, yOf(v0 + a / 2) + 5); } g.fillStyle = '#F6F0CF'; g.fillRect(L, 262, R - L, 50); g.strokeStyle = '#1C1B18'; g.lineWidth = 1; g.strokeRect(L, 262, R - L, 50); g.fillStyle = '#1C1B18'; g.font = '700 14px monospace'; g.textAlign = 'left'; g.fillText('v0 = ' + fmt(v0) + ' m/s   a = ' + fmt(a) + ' m/s²   v(4 s) = ' + fmt(vT) + ' m/s', L + 10, 283); g.fillText('area = ((' + fmt(v0) + '+' + fmt(vT) + ')/2) x 4 = ' + fmt(disp) + ' m = displacement', L + 10, 303); } });