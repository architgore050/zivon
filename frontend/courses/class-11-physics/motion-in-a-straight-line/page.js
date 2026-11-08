ZivonSim.register("b-04",{init:function(ctx){},draw:function(ctx){var g=ctx.g,W=480,H=320,L=56,R=16,T=46,B=38,pw=W-L-R,ph=H-T-B,t0=ctx.values.t;if(t0===undefined)t0=4;function px(t){return L+t/6*pw;}function py(x){return T+ph-x/18*ph;}var x0=0.08*t0*t0*t0,v=0.24*t0*t0;g.fillStyle="#F6F0CF";g.fillRect(0,0,W,H);g.strokeStyle="#5A5748";g.lineWidth=1;g.setLineDash([4,5]);for(var gx=0;gx<=18;gx+=6){g.beginPath();g.moveTo(L,py(gx));g.lineTo(L+pw,py(gx));g.stroke();}for(var gt=0;gt<=6;gt+=2){g.beginPath();g.moveTo(px(gt),T);g.lineTo(px(gt),T+ph);g.stroke();}g.setLineDash([]);g.strokeStyle="#1C1B18";g.lineWidth=3;g.beginPath();g.moveTo(L,T+ph);g.lineTo(L+pw,T+ph);g.stroke();g.beginPath();g.moveTo(L,T);g.lineTo(L,T+ph);g.stroke();g.fillStyle="#1C1B18";g.font='14px "Courier Prime","Courier New",monospace';g.textAlign="center";for(var tx=0;tx<=6;tx+=2){g.fillText(String(tx),px(tx),T+ph+20);}g.textAlign="right";for(var xx=0;xx<=18;xx+=6){g.fillText(String(xx),L-8,py(xx)+5);}g.textAlign="left";g.fillText("t (s)",L+pw-36,T+ph+20);g.fillText("x (m)",L+4,T-8);g.font='700 15px "Courier Prime","Courier New",monospace';g.fillText("x = 0.08 t^3",L+10,T+18);g.strokeStyle="#1C1B18";g.lineWidth=3;g.beginPath();for(var t=0;t<=6.001;t+=0.05){var x=0.08*t*t*t,X=px(t),Y=py(x);if(t===0)g.moveTo(X,Y);else g.lineTo(X,Y);}g.stroke();g.save();g.beginPath();g.rect(L,T,pw,ph);g.clip();g.strokeStyle="#1F3A9E";g.lineWidth=3;g.beginPath();g.moveTo(px(t0-3),py(x0+v*((t0-3)-t0)));g.lineTo(px(t0+3),py(x0+v*((t0+3)-t0)));g.stroke();g.restore();g.strokeStyle="#5A5748";g.lineWidth=2;g.setLineDash([5,5]);g.beginPath();g.moveTo(px(t0),py(x0));g.lineTo(px(t0),T+ph);g.stroke();g.beginPath();g.moveTo(px(t0),py(x0));g.lineTo(L,py(x0));g.stroke();g.setLineDash([]);var run=t0<=5?1:-1;if(v>0){g.beginPath();g.moveTo(px(t0),py(x0));g.lineTo(px(t0+run),py(x0));g.lineTo(px(t0+run),py(x0+v*run));g.stroke();}g.fillStyle="#1F3A9E";g.beginPath();g.arc(px(t0),py(x0),6,0,6.283);g.fill();g.strokeStyle="#F6F0CF";g.lineWidth=2;g.stroke();g.font='700 15px "Courier Prime","Courier New",monospace';g.fillText("tangent: slope = v",Math.min(px(t0)+10,L+pw-150),Math.max(T+34,py(x0)-12));g.fillStyle="#1C1B18";g.fillText("t = "+t0.toFixed(1)+" s   x = "+x0.toFixed(2)+" m   v = "+v.toFixed(2)+" m/s",L+10,H-8);}});

ZivonSim.register('b-08', {
  init: function (ctx) { ctx.tc = 0; },
  draw: function (ctx) {
    var g = ctx.g; if (!g) return;
    var a = (ctx.values && typeof ctx.values.a === 'number') ? ctx.values.a : 2;
    var v0 = (ctx.values && typeof ctx.values.v0 === 'number') ? ctx.values.v0 : 5;
    var T = 4, vMin = -20, vMax = 32;
    var L = 55, R = 465, Top = 38, Bot = 262;
    function X(t) { return L + (t / T) * (R - L); }
    function Y(v) { return Bot - ((v - vMin) / (vMax - vMin)) * (Bot - Top); }
    function vel(t) { return v0 + a * t; }
    g.clearRect(0, 0, 480, 320);
    g.fillStyle = '#F6F0CF'; g.fillRect(0, 0, 480, 320);
    g.font = '400 14px Courier Prime, monospace'; g.textAlign = 'right'; g.textBaseline = 'middle';
    var gv = [-20, -10, 10, 20, 30];
    g.strokeStyle = '#5A5748'; g.lineWidth = 1; g.setLineDash([4, 5]);
    for (var i = 0; i < gv.length; i++) { var y = Y(gv[i]); g.beginPath(); g.moveTo(L, y); g.lineTo(R, y); g.stroke(); g.fillStyle = '#5A5748'; g.fillText(String(gv[i]), L - 6, y); }
    for (var tt = 1; tt <= 4; tt++) { var x = X(tt); g.beginPath(); g.moveTo(x, Top); g.lineTo(x, Bot); g.stroke(); g.textAlign = 'center'; g.fillText(String(tt), x, Bot + 14); }
    g.setLineDash([]);
    g.strokeStyle = '#1C1B18'; g.lineWidth = 2;
    g.beginPath(); g.moveTo(L, Y(0)); g.lineTo(R, Y(0)); g.stroke();
    g.beginPath(); g.moveTo(X(0), Top); g.lineTo(X(0), Bot); g.stroke();
    g.fillStyle = '#1C1B18'; g.textAlign = 'left'; g.font = '700 14px Courier Prime, monospace';
    g.fillText('v (m/s)', 8, Top - 12); g.textAlign = 'right'; g.fillText('t (s)', R, Bot + 14); g.textAlign = 'left'; g.fillText('0', L - 14, Y(0) + 14);
    var period = 5; var raw = (typeof ctx.t === 'number') ? (ctx.t % period) : 2; var tc = Math.min(raw, T);
    var pts = [];
    for (var t = 0; t < tc; t += 0.05) { pts.push([t, vel(t)]); }
    pts.push([tc, vel(tc)]);
    var segs = [], cur = [];
    for (var k = 0; k < pts.length; k++) {
      if (k > 0) {
        var p0 = pts[k - 1], p1 = pts[k];
        if ((p0[1] >= 0 && p1[1] < 0) || (p0[1] <= 0 && p1[1] > 0)) {
          var tx = p0[0] + (0 - p0[1]) * (p1[0] - p0[0]) / (p1[1] - p0[1]);
          cur.push([tx, 0]); segs.push(cur); cur = [[tx, 0]];
        }
      }
      cur.push(pts[k]);
    }
    if (cur.length > 1) segs.push(cur);
    for (var s = 0; s < segs.length; s++) {
      var seg = segs[s]; if (seg.length < 2) continue;
      var pos = false; for (var q = 0; q < seg.length; q++) { if (seg[q][1] > 0) pos = true; }
      g.beginPath(); g.moveTo(X(seg[0][0]), Y(0));
      for (var q2 = 0; q2 < seg.length; q2++) { g.lineTo(X(seg[q2][0]), Y(seg[q2][1])); }
      g.lineTo(X(seg[seg.length - 1][0]), Y(0)); g.closePath();
      g.globalAlpha = pos ? 0.28 : 0.35; g.fillStyle = pos ? '#1F3A9E' : '#5A5748'; g.fill(); g.globalAlpha = 1;
    }
    g.strokeStyle = '#1F3A9E'; g.lineWidth = 3; g.beginPath();
    for (var t2 = 0; t2 <= T; t2 += 0.05) { var px = X(t2), py = Y(vel(t2)); if (t2 === 0) g.moveTo(px, py); else g.lineTo(px, py); }
    g.stroke();
    var vc = vel(tc), mx = X(tc), my = Y(vc);
    g.strokeStyle = '#1F3A9E'; g.lineWidth = 1.5; g.setLineDash([4, 4]);
    g.beginPath(); g.moveTo(mx, my); g.lineTo(mx, Y(0)); g.stroke();
    g.beginPath(); g.moveTo(mx, my); g.lineTo(X(0), my); g.stroke(); g.setLineDash([]);
    g.fillStyle = '#1F3A9E'; g.beginPath(); g.arc(mx, my, 5, 0, 6.2832); g.fill();
    g.strokeStyle = '#F6F0CF'; g.lineWidth = 2; g.stroke();
    var disp = v0 * tc + 0.5 * a * tc * tc;
    g.fillStyle = '#1C1B18'; g.textAlign = 'left'; g.font = '700 16px Courier Prime, monospace';
    g.fillText('Area under v-t line = displacement', L, 20);
    g.font = '700 15px Courier Prime, monospace';
    g.fillText('t = ' + tc.toFixed(1) + ' s   v = ' + vc.toFixed(1) + ' m/s   displacement = ' + disp.toFixed(1) + ' m', L, 288);
    g.font = '400 14px Courier Prime, monospace'; g.fillStyle = '#5A5748';
    g.fillText('v = v0 + a t   displacement = v0 t + 0.5 a t^2', L, 308);
  }
});
