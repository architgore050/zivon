ZivonSim.register('b-19', {
  init: function (ctx) {
    ctx.ready = true;
  },
  draw: function (ctx) {
    var g = ctx.g;
    if (!g) { return; }
    var W = 480;
    var H = 320;
    var v = 20;
    if (ctx.values && typeof ctx.values.velocity === 'number') { v = ctx.values.velocity; }
    if (v < 0) { v = 0; }
    if (v > 30) { v = 30; }
    var T = 6;
    var Smax = 180;
    var x0 = 62;
    var y0 = 268;
    var x1 = 438;
    var y1 = 96;
    function X(t) { return x0 + (t / T) * (x1 - x0); }
    function Y(s) { return y0 - (s / Smax) * (y0 - y1); }
    var send = v * T;
    g.fillStyle = '#F6F0CF';
    g.fillRect(0, 0, W, H);
    g.font = '14px Courier Prime, monospace';
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillStyle = '#1C1B18';
    g.fillText('s = v x t  -  position = velocity x time', 16, 22);
    g.fillStyle = '#1F3A9E';
    g.fillText('v = ' + v + ' m/s', 16, 42);
    g.fillStyle = '#1C1B18';
    g.fillText('slope = (s2 - s1)/(t2 - t1) = ' + Math.round(send) + '/6 = ' + v + ' m/s', 16, 62);
    g.fillStyle = '#5A5748';
    g.fillText('straight line means constant velocity', 16, 82);
    var i;
    var t;
    var s;
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1;
    g.setLineDash([4, 5]);
    for (i = 0; i <= 3; i++) {
      t = i * 2;
      g.beginPath();
      g.moveTo(X(t), y1);
      g.lineTo(X(t), y0);
      g.stroke();
      s = i * 60;
      g.beginPath();
      g.moveTo(x0, Y(s));
      g.lineTo(x1, Y(s));
      g.stroke();
    }
    g.setLineDash([]);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2.5;
    g.beginPath();
    g.moveTo(x0, y0);
    g.lineTo(x1, y0);
    g.stroke();
    g.beginPath();
    g.moveTo(x0, y0);
    g.lineTo(x0, y1);
    g.stroke();
    g.beginPath();
    g.moveTo(x1, y0);
    g.lineTo(x1 - 8, y0 - 4);
    g.moveTo(x1, y0);
    g.lineTo(x1 - 8, y0 + 4);
    g.stroke();
    g.beginPath();
    g.moveTo(x0, y1);
    g.lineTo(x0 - 4, y1 + 8);
    g.moveTo(x0, y1);
    g.lineTo(x0 + 4, y1 + 8);
    g.stroke();
    g.fillStyle = '#1C1B18';
    g.textAlign = 'center';
    for (i = 0; i <= 3; i++) {
      t = i * 2;
      g.fillText(String(t), X(t), y0 + 20);
    }
    g.textAlign = 'right';
    for (i = 0; i <= 3; i++) {
      s = i * 60;
      g.fillText(String(s), x0 - 8, Y(s) + 5);
    }
    g.textAlign = 'left';
    g.fillText('time t (s)', x1 - 70, y0 + 40);
    g.save();
    g.translate(16, (y0 + y1) / 2);
    g.rotate(-Math.PI / 2);
    g.textAlign = 'center';
    g.fillText('position s (m)', 0, 0);
    g.restore();
    if (send > 0) {
      g.strokeStyle = '#5A5748';
      g.lineWidth = 2;
      g.setLineDash([5, 5]);
      g.beginPath();
      g.moveTo(X(T), Y(send));
      g.lineTo(X(T), y0);
      g.stroke();
      g.beginPath();
      g.moveTo(x0, Y(send));
      g.lineTo(X(T), Y(send));
      g.stroke();
      g.setLineDash([]);
    }
    g.strokeStyle = '#1F3A9E';
    g.lineWidth = 3;
    g.beginPath();
    for (t = 0; t <= T + 0.001; t += 0.05) {
      s = v * t;
      if (t === 0) { g.moveTo(X(t), Y(s)); } else { g.lineTo(X(t), Y(s)); }
    }
    g.stroke();
    g.fillStyle = '#1F3A9E';
    g.beginPath();
    g.arc(X(T), Y(send), 5, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 1.5;
    g.stroke();
    var tc = 0;
    if (typeof ctx.t === 'number') { tc = ctx.t % T; }
    var sc = v * tc;
    g.fillStyle = '#1C1B18';
    g.beginPath();
    g.arc(X(tc), Y(sc), 6, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = '#F6F0CF';
    g.lineWidth = 2;
    g.stroke();
    g.fillStyle = '#5A5748';
    g.textAlign = 'center';
    g.fillText('6 s', X(3), y0 - 10);
    if (send >= 20) {
      g.textAlign = 'right';
      g.fillText(Math.round(send) + ' m', X(T) - 6, Y(send / 2) + 5);
    }
    g.textAlign = 'right';
    g.fillStyle = '#1F3A9E';
    g.fillText(Math.round(send) + ' m at 6 s', X(T) - 8, Y(send) + 20);
  }
});

ZivonSim.register("b-25", {
  init: function (ctx) {
  },
  draw: function (ctx) {
    var g = ctx.g;
    var W = ctx.width || 480;
    var H = ctx.height || 320;
    var u = 0;
    var a = 0.5;
    if (ctx.values) {
      if (typeof ctx.values.initial_velocity === "number") u = ctx.values.initial_velocity;
      if (typeof ctx.values.acceleration === "number") a = ctx.values.acceleration;
    }
    var T = 30;
    var vFinal = u + a * T;
    var s = u * T + 0.5 * a * T * T;
    var v10 = u + a * 10;
    var v20 = u + a * 20;
    function fmt(n) {
      var r = Math.round(n);
      if (Math.abs(n - r) < 0.001) return String(r);
      return n.toFixed(1);
    }
    var left = 58;
    var right = 28;
    var top = 70;
    var bottom = 44;
    var plotW = W - left - right;
    var plotH = H - top - bottom;
    var vMin = Math.min(0, u, vFinal);
    var vMax = Math.max(0, u, vFinal);
    var range = vMax - vMin;
    if (range < 1) range = 1;
    var pad = range * 0.18 + 1;
    vMin = vMin - pad;
    vMax = vMax + pad;
    function xForT(t) { return left + (t / T) * plotW; }
    function yForV(v) { return top + plotH - ((v - vMin) / (vMax - vMin)) * plotH; }
    g.fillStyle = "#F6F0CF";
    g.fillRect(0, 0, W, H);
    g.textAlign = "left";
    g.textBaseline = "alphabetic";
    g.fillStyle = "#1C1B18";
    g.font = "700 14px 'Courier Prime', 'Courier New', monospace";
    g.fillText("u = " + fmt(u) + " m/s    a = " + fmt(a) + " m/s²", left, 20);
    g.fillText("v(30 s) = " + fmt(vFinal) + " m/s    s = " + fmt(s) + " m", left, 38);
    g.fillStyle = "#5A5748";
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.fillText("10-20 s: Δv = " + fmt(v20 - v10) + " m/s, a = Δv/10 = " + fmt(a) + " m/s²", left, 56);
    g.strokeStyle = "#5A5748";
    g.lineWidth = 1;
    g.setLineDash([4, 5]);
    g.globalAlpha = 0.45;
    var i;
    var ts = [0, 10, 20, 30];
    for (i = 0; i < ts.length; i++) {
      var gx = xForT(ts[i]);
      g.beginPath();
      g.moveTo(gx, top);
      g.lineTo(gx, top + plotH);
      g.stroke();
    }
    g.globalAlpha = 1;
    g.setLineDash([]);
    var x0 = xForT(0);
    var xT = xForT(T);
    var y0 = yForV(0);
    var yU = yForV(u);
    var yV = yForV(vFinal);
    g.strokeStyle = "#1C1B18";
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(left, y0);
    g.lineTo(left + plotW, y0);
    g.stroke();
    g.beginPath();
    g.moveTo(x0, top);
    g.lineTo(x0, top + plotH);
    g.stroke();
    g.fillStyle = "#5A5748";
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = "center";
    for (i = 0; i < ts.length; i++) {
      g.fillText(String(ts[i]), xForT(ts[i]), top + plotH + 18);
    }
    g.textAlign = "right";
    g.fillText("t (s)", left + plotW, top + plotH + 36);
    g.fillText("0", left - 8, y0 + 5);
    if (Math.abs(u) > 0.001) {
      g.fillText(fmt(u), left - 8, yU + 5);
    }
    if (Math.abs(vFinal) > 0.001 && Math.abs(vFinal - u) > 0.001) {
      g.fillText(fmt(vFinal), left - 8, yV + 5);
    }
    g.textAlign = "left";
    g.fillText("v (m/s)", x0 + 6, top + 14);
    g.fillStyle = "#1F3A9E";
    g.globalAlpha = 0.16;
    var step = 0.5;
    var t;
    for (t = 0; t < T; t += step) {
      var v1 = u + a * t;
      var v2 = u + a * (t + step);
      var xa = xForT(t);
      var xb = xForT(t + step);
      var ya = yForV(v1);
      var yb = yForV(v2);
      g.beginPath();
      g.moveTo(xa, ya);
      g.lineTo(xb, yb);
      g.lineTo(xb, y0);
      g.lineTo(xa, y0);
      g.closePath();
      g.fill();
    }
    g.globalAlpha = 1;
    g.strokeStyle = "#5A5748";
    g.lineWidth = 1.5;
    g.setLineDash([5, 4]);
    g.beginPath();
    g.moveTo(x0, yU);
    g.lineTo(xT, yU);
    g.stroke();
    g.beginPath();
    g.moveTo(xT, yU);
    g.lineTo(xT, yV);
    g.stroke();
    g.setLineDash([]);
    g.strokeStyle = "#1F3A9E";
    g.lineWidth = 3;
    g.lineCap = "round";
    g.lineJoin = "round";
    g.beginPath();
    for (t = 0; t <= T; t += 0.5) {
      var vv = u + a * t;
      var xx = xForT(t);
      var yy = yForV(vv);
      if (t === 0) g.moveTo(xx, yy);
      else g.lineTo(xx, yy);
    }
    g.stroke();
    g.fillStyle = "#1F3A9E";
    g.strokeStyle = "#1C1B18";
    g.lineWidth = 1.5;
    g.beginPath();
    g.arc(x0, yU, 5, 0, Math.PI * 2);
    g.fill();
    g.stroke();
    g.beginPath();
    g.arc(xT, yV, 5, 0, Math.PI * 2);
    g.fill();
    g.stroke();
    g.fillStyle = "#1F3A9E";
    g.font = "700 20px Caveat, cursive";
    g.textAlign = "center";
    var vMid = u + a * 15;
    var xMid = xForT(15);
    var yMid = yForV(vMid);
    var ySlope = yMid - 12;
    if (ySlope < top + 18) ySlope = top + 18;
    g.fillText("slope = a", xMid, ySlope);
    var yArea = yForV(vMid / 2);
    if (yArea < top + 18) yArea = top + 18;
    if (yArea > top + plotH - 6) yArea = top + plotH - 6;
    g.fillText("area = s", xMid, yArea);
    g.fillStyle = "#5A5748";
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    var yTrap = yArea + 18;
    if (yTrap > top + plotH - 4) yTrap = yArea - 22;
    g.fillText("(u+v)/2 × t", xMid, yTrap);
    g.fillText("Δt = 30 s", (x0 + xT) / 2, yU - 8);
    g.fillText("Δv", xT - 22, (yU + yV) / 2 + 5);
  }
});

ZivonSim.register('b-33', {
  init: function (ctx) {
    ctx.ready = true;
  },
  draw: function (ctx) {
    var g = ctx.g;
    if (!g) { return; }
    var W = ctx.width || 480;
    var H = ctx.height || 320;
    var R = (ctx.values && typeof ctx.values.radius === 'number') ? ctx.values.radius : 5;
    var T = (ctx.values && typeof ctx.values.period === 'number') ? ctx.values.period : 10;
    var t = (typeof ctx.t === 'number') ? ctx.t : 0;
    var v = 2 * Math.PI * R / T;
    var omega = 2 * Math.PI / T;
    var theta = omega * t;
    var cx = W / 2;
    var cy = H / 2 + 12;
    var scale = 11;
    var rPx = R * scale;
    var x = cx + rPx * Math.cos(theta);
    var y = cy + rPx * Math.sin(theta);
    var tx = -Math.sin(theta);
    var ty = Math.cos(theta);
    var arrowLen = v * 14;
    if (arrowLen < 18) { arrowLen = 18; }
    if (arrowLen > 80) { arrowLen = 80; }
    g.fillStyle = '#F6F0CF';
    g.fillRect(0, 0, W, H);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2.5;
    g.beginPath();
    g.arc(cx, cy, rPx, 0, 2 * Math.PI);
    g.stroke();
    g.fillStyle = '#5A5748';
    for (var i = 20; i >= 1; i--) {
      var ta = theta - i * 0.07;
      var xa = cx + rPx * Math.cos(ta);
      var ya = cy + rPx * Math.sin(ta);
      g.globalAlpha = 0.12 + 0.5 * (1 - i / 20);
      g.beginPath();
      g.arc(xa, ya, 3, 0, 2 * Math.PI);
      g.fill();
    }
    g.globalAlpha = 1;
    g.strokeStyle = '#5A5748';
    g.lineWidth = 2;
    g.setLineDash([4, 4]);
    for (var k = 1; k <= 2; k++) {
      var tg = theta - k * Math.PI / 2;
      var xg = cx + rPx * Math.cos(tg);
      var yg = cy + rPx * Math.sin(tg);
      var tgx = -Math.sin(tg);
      var tgy = Math.cos(tg);
      g.beginPath();
      g.moveTo(xg, yg);
      g.lineTo(xg + tgx * arrowLen, yg + tgy * arrowLen);
      g.stroke();
    }
    g.setLineDash([]);
    g.strokeStyle = '#5A5748';
    g.lineWidth = 2;
    g.setLineDash([5, 5]);
    g.beginPath();
    g.moveTo(cx, cy);
    g.lineTo(x, y);
    g.stroke();
    g.setLineDash([]);
    g.fillStyle = '#1C1B18';
    g.beginPath();
    g.arc(cx, cy, 4, 0, 2 * Math.PI);
    g.fill();
    var x2 = x + tx * arrowLen;
    var y2 = y + ty * arrowLen;
    g.strokeStyle = '#1F3A9E';
    g.fillStyle = '#1F3A9E';
    g.lineWidth = 3;
    g.lineCap = 'round';
    g.beginPath();
    g.moveTo(x, y);
    g.lineTo(x2, y2);
    g.stroke();
    var h = 10;
    var hx1 = x2 - tx * h - ty * h * 0.55;
    var hy1 = y2 - ty * h + tx * h * 0.55;
    var hx2 = x2 - tx * h + ty * h * 0.55;
    var hy2 = y2 - ty * h - tx * h * 0.55;
    g.beginPath();
    g.moveTo(hx1, hy1);
    g.lineTo(x2, y2);
    g.lineTo(hx2, hy2);
    g.closePath();
    g.fill();
    g.beginPath();
    g.arc(x, y, 7, 0, 2 * Math.PI);
    g.fill();
    g.fillStyle = '#1C1B18';
    g.font = '700 14px Courier Prime, Courier New, monospace';
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillText('speed v = 2 pi R / T = ' + v.toFixed(2) + ' m/s', 16, 24);
    g.fillStyle = '#1F3A9E';
    g.fillText('speed constant, direction changes', 16, 44);
    g.fillStyle = '#1C1B18';
    g.fillText('R = ' + R.toFixed(0) + ' m', cx + (x - cx) * 0.5 + 6, cy + (y - cy) * 0.5 - 6);
    g.fillStyle = '#1F3A9E';
    var lx = x2 + tx * 8;
    var ly = y2 + ty * 8;
    if (lx > W - 30) { lx = W - 30; }
    if (lx < 4) { lx = 4; }
    if (ly > H - 6) { ly = H - 6; }
    if (ly < 58) { ly = 58; }
    g.fillText('v', lx, ly);
    g.fillStyle = '#5A5748';
    g.fillText('centre', cx + 8, cy + 18);
  }
});