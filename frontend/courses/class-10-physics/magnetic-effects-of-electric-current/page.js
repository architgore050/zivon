// b-12 — Field of a straight wire: change the current, change the distance
// Facts obeyed: claim-13 (concentric circles), claim-14 (deflection grows with current),
// claim-15 (field weaker farther out, circles larger), claim-16 (reversing current reverses
// the field). The chapter fixes only the direction of the change, not its size, so the turn of
// the needle is reported in words (small / medium / large).
ZivonSim.register("b-12", {
  init: function (ctx) {
    var v = ctx.values || {};
    var I = typeof v.current === 'number' ? v.current : 2;
    var d = typeof v.distance === 'number' ? v.distance : 2;
    var dir = (typeof v.direction === 'number' ? v.direction : 1) >= 0 ? 1 : -1;
    var raw = I / d;                       // one scalar that rises with I, falls with d
    var deg = 88 * raw / (raw + 1.4);      // deflection magnitude, 0..~70 degrees
    ctx.state = { ang: -dir * deg * Math.PI / 180 };
    var g = ctx.g;
    if (g) { g.lineCap = 'round'; g.lineJoin = 'round'; }
  },

  draw: function (ctx) {
    var g = ctx.g;
    if (!g) return;

    var PAPER_LIGHT = '#F6F0CF';
    var INK = '#1C1B18';
    var GRAPH = '#5A5748';
    var BLUE = '#1F3A9E';

    var v = ctx.values || {};
    var I = typeof v.current === 'number' ? v.current : 2;
    var d = typeof v.distance === 'number' ? v.distance : 2;
    var dir = (typeof v.direction === 'number' ? v.direction : 1) >= 0 ? 1 : -1;

    // ---- physics: the turn of the needle grows with I, shrinks with d, flips with dir
    var raw = I / d;
    var deg = 88 * raw / (raw + 1.4);
    var target = -dir * deg * Math.PI / 180;   // angle from the radial rest line, canvas sign

    if (!ctx.state || typeof ctx.state.ang !== 'number') ctx.state = { ang: target };
    ctx.state.ang += (target - ctx.state.ang) * 0.25;
    if (Math.abs(target - ctx.state.ang) < 0.0008) ctx.state.ang = target;
    var ang = ctx.state.ang;

    // ---- fixed apparatus geometry (canvas buffer 480 x 320)
    var cx = 160, cy = 150;     // wire, seen end on
    var STEP = 30;              // one distance step in pixels
    var RC = 18;                // compass radius
    var cpx = cx + d * STEP;    // compass centre = wire + d steps  (default d=2 -> x=220)

    g.clearRect(0, 0, 480, 320);

    function head(x, y, tx, ty, size, col) {
      var b = Math.atan2(ty, tx);
      g.beginPath();
      g.moveTo(x, y);
      g.lineTo(x - size * Math.cos(b - 0.45), y - size * Math.sin(b - 0.45));
      g.lineTo(x - size * Math.cos(b + 0.45), y - size * Math.sin(b + 0.45));
      g.closePath();
      g.fillStyle = col;
      g.fill();
    }

    // ---- claim-13 / claim-15: concentric circles, growing with distance from the wire
    //      claim-16: the arrowheads follow the sense of the current
    g.strokeStyle = GRAPH;
    g.lineWidth = 1.8;
    for (var k = 0; k < 6; k++) {
      var r = 20 + k * 20;
      g.beginPath();
      g.arc(cx, cy, r, 0, Math.PI * 2);
      g.stroke();
      for (var j = 0; j < 3; j++) {
        var a = -Math.PI / 2 + j * (Math.PI * 2 / 3) + k * 0.35;
        var px = cx + r * Math.cos(a);
        var py = cy + r * Math.sin(a);
        // dir = +1 (current out of page) -> anticlockwise on screen
        var tx = dir === 1 ? Math.sin(a) : -Math.sin(a);
        var ty = dir === 1 ? -Math.cos(a) : Math.cos(a);
        head(px, py, tx, ty, 7, GRAPH);
      }
    }

    // ---- the measured distance, one tick per step
    g.setLineDash([4, 5]);
    g.lineWidth = 1.5;
    g.strokeStyle = GRAPH;
    g.beginPath();
    g.moveTo(cx, cy);
    g.lineTo(cpx, cy);
    g.stroke();
    g.setLineDash([]);
    for (var s = 1; s <= d; s++) {
      var sx = cx + s * STEP;
      g.beginPath();
      g.moveTo(sx, cy - 5);
      g.lineTo(sx, cy + 5);
      g.stroke();
    }

    // ---- the wire end on: dot = out of the page, cross = into the page
    g.beginPath();
    g.arc(cx, cy, 8, 0, Math.PI * 2);
    g.fillStyle = PAPER_LIGHT;
    g.fill();
    g.strokeStyle = INK;
    g.lineWidth = 2.5;
    g.stroke();
    if (dir === 1) {
      g.beginPath();
      g.arc(cx, cy, 3, 0, Math.PI * 2);
      g.fillStyle = INK;
      g.fill();
    } else {
      g.beginPath();
      g.moveTo(cx - 3.6, cy - 3.6); g.lineTo(cx + 3.6, cy + 3.6);
      g.moveTo(cx + 3.6, cy - 3.6); g.lineTo(cx - 3.6, cy + 3.6);
      g.strokeStyle = INK;
      g.lineWidth = 2.2;
      g.stroke();
    }

    // ---- the turn itself, as a pen-blue arc from the rest direction
    if (Math.abs(ang) > 0.02) {
      g.beginPath();
      g.arc(cpx, cy, 25, 0, ang, ang < 0);
      g.strokeStyle = BLUE;
      g.lineWidth = 2;
      g.stroke();
    }

    // ---- compass body
    g.beginPath();
    g.arc(cpx, cy, RC, 0, Math.PI * 2);
    g.fillStyle = PAPER_LIGHT;
    g.fill();
    g.strokeStyle = INK;
    g.lineWidth = 2;
    g.stroke();

    // ---- needle: rests along the radial line, turns towards the field direction
    var ux = Math.cos(ang), uy = Math.sin(ang);
    var qx = -uy, qy = ux;
    var L = 14, wv = 3.4;
    g.beginPath();
    g.moveTo(cpx - ux * L, cy - uy * L);
    g.lineTo(cpx + qx * wv, cy + qy * wv);
    g.lineTo(cpx + ux * L, cy + uy * L);
    g.lineTo(cpx - qx * wv, cy - qy * wv);
    g.closePath();
    g.fillStyle = INK;
    g.fill();

    g.beginPath();
    g.moveTo(cpx, cy);
    g.lineTo(cpx + qx * wv, cy + qy * wv);
    g.lineTo(cpx + ux * L, cy + uy * L);
    g.lineTo(cpx - qx * wv, cy - qy * wv);
    g.closePath();
    g.fillStyle = BLUE;
    g.fill();

    g.beginPath();
    g.arc(cpx, cy, 2, 0, Math.PI * 2);
    g.fillStyle = PAPER_LIGHT;
    g.fill();

    // ---- labels (paper backing keeps every string legible over the circles)
    g.font = '15px "Courier Prime", "Courier New", monospace';
    g.textBaseline = 'alphabetic';
    g.textAlign = 'left';

    function label(text, x, y, rightAlign, col) {
      var w = g.measureText(text).width;
      var lx = rightAlign ? x - w : x;
      g.fillStyle = PAPER_LIGHT;
      g.fillRect(lx - 4, y - 14, w + 8, 19);
      g.fillStyle = col;
      g.fillText(text, lx, y);
    }

    var word = deg < 25 ? 'small' : (deg < 50 ? 'medium' : 'large');
    label(dir === 1 ? 'anticlockwise' : 'clockwise', 16, 22, false, GRAPH);
    label('turn: ' + word, 464, 22, true, INK);
    label(dir === 1 ? 'current out of page' : 'current into page', 16, 302, false, INK);
  }
});
