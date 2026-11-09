ZivonSim.register('b-24', {
  init: function (ctx) {},
  draw: function (ctx) {
    var g = ctx.g;
    var W = 480;
    var H = 320;
    var v0 = ctx.values.v0;
    var thetaDeg = ctx.values.theta;
    if (v0 === undefined) v0 = 20;
    if (thetaDeg === undefined) thetaDeg = 45;
    var grav = 9.8;
    var th = thetaDeg * Math.PI / 180;
    var vox = v0 * Math.cos(th);
    var voy = v0 * Math.sin(th);
    var tm = v0 * Math.sin(th) / grav;
    var Tf = 2 * v0 * Math.sin(th) / grav;
    var hm = v0 * v0 * Math.sin(th) * Math.sin(th) / (2 * grav);
    var R = v0 * v0 * Math.sin(2 * th) / grav;
    if (R < 0) R = 0;
    if (hm < 0) hm = 0;
    if (Tf < 0) Tf = 0;
    g.fillStyle = '#F6F0CF';
    g.fillRect(0, 0, W, H);
    g.fillStyle = '#1C1B18';
    g.font = '700 14px Courier Prime, Courier New, monospace';
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    var line1 = 'v0 = ' + v0.toFixed(0) + ' m/s   theta0 = ' + thetaDeg.toFixed(0) + ' deg';
    var line2 = 'hm = ' + hm.toFixed(1) + ' m   R = ' + R.toFixed(1) + ' m   Tf = ' + Tf.toFixed(2) + ' s';
    g.fillText(line1, 16, 22);
    g.fillText(line2, 16, 42);
    var ox = 48;
    var oy = 268;
    var plotW = 400;
    var plotH = 190;
    var scale = 10;
    if (R > 0.01 && hm > 0.01) {
      scale = Math.min(plotW / R, plotH / hm);
    } else if (R > 0.01) {
      scale = plotW / R;
    } else if (hm > 0.01) {
      scale = plotH / hm;
    }
    if (scale > 80) scale = 80;
    if (scale < 1) scale = 1;
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(ox - 12, oy);
    g.lineTo(ox + plotW + 12, oy);
    g.stroke();
    g.lineWidth = 2;
    g.strokeStyle = '#5A5748';
    g.beginPath();
    g.moveTo(ox, oy);
    g.lineTo(ox, oy - plotH);
    g.stroke();
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.beginPath();
    for (var hx = ox - 8; hx < ox + plotW + 8; hx += 24) {
      g.moveTo(hx, oy + 10);
      g.lineTo(hx - 8, oy);
    }
    g.stroke();
    if (hm > 0.01 && R > 0.01) {
      var topX = ox + (R / 2) * scale;
      var topY = oy - hm * scale;
      g.strokeStyle = '#5A5748';
      g.lineWidth = 1.5;
      g.setLineDash([5, 5]);
      g.beginPath();
      g.moveTo(topX, oy);
      g.lineTo(topX, topY);
      g.moveTo(ox, topY);
      g.lineTo(topX, topY);
      g.stroke();
      g.setLineDash([]);
    } else if (hm > 0.01) {
      var topY2 = oy - hm * scale;
      g.strokeStyle = '#5A5748';
      g.lineWidth = 1.5;
      g.setLineDash([5, 5]);
      g.beginPath();
      g.moveTo(ox, topY2);
      g.lineTo(ox + 30, topY2);
      g.stroke();
      g.setLineDash([]);
    }
    if (Tf > 0.01) {
      g.strokeStyle = '#1F3A9E';
      g.lineWidth = 3;
      g.beginPath();
      var steps = 200;
      for (var i = 0; i <= steps; i++) {
        var t = Tf * i / steps;
        var x = v0 * Math.cos(th) * t;
        var y = v0 * Math.sin(th) * t - 0.5 * grav * t * t;
        var px = ox + x * scale;
        var py = oy - y * scale;
        if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
      }
      g.stroke();
    }
    var arrowLen = 56;
    var ax = ox + Math.cos(th) * arrowLen;
    var ay = oy - Math.sin(th) * arrowLen;
    g.strokeStyle = '#1C1B18';
    g.fillStyle = '#1C1B18';
    g.lineWidth = 2.5;
    g.beginPath();
    g.moveTo(ox, oy);
    g.lineTo(ax, ay);
    g.stroke();
    var dirx = Math.cos(th);
    var diry = -Math.sin(th);
    var hx1 = ax - dirx * 10 - diry * 4;
    var hy1 = ay - diry * 10 + dirx * 4;
    var hx2 = ax - dirx * 10 + diry * 4;
    var hy2 = ay - diry * 10 - dirx * 4;
    g.beginPath();
    g.moveTo(ax, ay);
    g.lineTo(hx1, hy1);
    g.lineTo(hx2, hy2);
    g.closePath();
    g.fill();
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.beginPath();
    g.arc(ox, oy, 28, -th, 0);
    g.stroke();
    if (R > 0.01) {
      var rx = ox + R * scale;
      g.strokeStyle = '#1F3A9E';
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(ox, oy + 14);
      g.lineTo(rx, oy + 14);
      g.stroke();
      g.beginPath();
      g.moveTo(ox, oy + 10);
      g.lineTo(ox, oy + 18);
      g.moveTo(rx, oy + 10);
      g.lineTo(rx, oy + 18);
      g.stroke();
      g.fillStyle = '#1F3A9E';
      g.font = '700 14px Courier Prime, Courier New, monospace';
      g.textAlign = 'center';
      g.fillText('R = ' + R.toFixed(1) + ' m', (ox + rx) / 2, oy + 34);
    }
    if (hm > 0.01) {
      var topX3 = ox + (R / 2) * scale;
      var topY3 = oy - hm * scale;
      g.fillStyle = '#1F3A9E';
      g.font = '700 14px Courier Prime, Courier New, monospace';
      g.textAlign = 'left';
      var label = 'hm = ' + hm.toFixed(1) + ' m';
      var lx = topX3 + 6;
      if (lx > 360) lx = topX3 - 110;
      g.fillText(label, lx, topY3 - 6);
    }
    g.fillStyle = '#5A5748';
    g.font = '14px Courier Prime, Courier New, monospace';
    g.textAlign = 'left';
    g.fillText('y (m)', ox + 6, oy - plotH + 14);
    g.textAlign = 'right';
    g.fillText('x (m)', ox + plotW + 10, oy + 34);
    g.textAlign = 'left';
    g.fillText('theta0', ox + 32, oy - 8);
    var dotX = ox;
    var dotY = oy;
    if (Tf > 0.01) {
      var cycle = Tf + 1.2;
      var tt = (ctx.t || 0) % cycle;
      if (tt > Tf) tt = Tf;
      var dx = v0 * Math.cos(th) * tt;
      var dy = v0 * Math.sin(th) * tt - 0.5 * grav * tt * tt;
      dotX = ox + dx * scale;
      dotY = oy - dy * scale;
    }
    g.fillStyle = '#1F3A9E';
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2;
    g.beginPath();
    g.arc(dotX, dotY, 6, 0, Math.PI * 2);
    g.fill();
    g.stroke();
    g.fillStyle = '#1C1B18';
    g.beginPath();
    g.arc(ox, oy, 3, 0, Math.PI * 2);
    g.fill();
  }
});