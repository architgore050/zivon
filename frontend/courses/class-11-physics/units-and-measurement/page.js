ZivonSim.register("b-23", {
  init: function (ctx) {
    ctx.state = { amp: 0.35 };
  },
  draw: function (ctx) {
    var g = ctx.g;
    var W = ctx.width || 480;
    var H = ctx.height || 320;
    var l = 1;
    if (ctx.values && typeof ctx.values.length === 'number') { l = ctx.values.length; }
    if (l < 0.1) { l = 0.1; }
    if (l > 2) { l = 2; }
    var grav = 9.8;
    var T = 2 * Math.PI * Math.sqrt(l / grav);
    var t = (typeof ctx.t === 'number') ? ctx.t : 0;
    var amp = 0.35;
    if (ctx.state && typeof ctx.state.amp === 'number') { amp = ctx.state.amp; }
    var theta = amp * Math.cos(2 * Math.PI * t / T);
    g.fillStyle = '#F6F0CF';
    g.fillRect(0, 0, W, H);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 1;
    g.strokeRect(0.5, 0.5, W - 1, H - 1);
    g.fillStyle = '#1C1B18';
    g.font = "700 16px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = 'left';
    g.textBaseline = 'alphabetic';
    g.fillText('Pendulum period vs length', 16, 28);
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.fillStyle = '#5A5748';
    g.fillText('T = 2π sqrt(l / g)', 16, 48);
    var pivotX = 115;
    var pivotY = 72;
    var Lpix = 30 + l * 65;
    var bobX = pivotX + Lpix * Math.sin(theta);
    var bobY = pivotY + Lpix * Math.cos(theta);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(35, pivotY);
    g.lineTo(195, pivotY);
    g.stroke();
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.setLineDash([4, 5]);
    g.beginPath();
    g.moveTo(pivotX, pivotY);
    g.lineTo(pivotX, pivotY + Lpix + 18);
    g.stroke();
    g.beginPath();
    for (var a = -amp; a <= amp + 0.001; a += 0.02) {
      var ax = pivotX + Lpix * Math.sin(a);
      var ay = pivotY + Lpix * Math.cos(a);
      if (a <= -amp + 0.001) { g.moveTo(ax, ay); } else { g.lineTo(ax, ay); }
    }
    g.stroke();
    g.setLineDash([]);
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(pivotX, pivotY);
    g.lineTo(bobX, bobY);
    g.stroke();
    g.fillStyle = '#1C1B18';
    g.beginPath();
    g.arc(pivotX, pivotY, 4, 0, 2 * Math.PI);
    g.fill();
    g.fillStyle = '#1F3A9E';
    g.beginPath();
    g.arc(bobX, bobY, 14, 0, 2 * Math.PI);
    g.fill();
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2;
    g.beginPath();
    g.arc(bobX, bobY, 14, 0, 2 * Math.PI);
    g.stroke();
    var midX = (pivotX + bobX) / 2;
    var midY = (pivotY + bobY) / 2;
    g.fillStyle = '#1C1B18';
    g.font = "700 14px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = 'left';
    g.fillText('l = ' + l.toFixed(1) + ' m', midX + 10, midY);
    var gx0 = 275;
    var gx1 = 460;
    var gy0 = 72;
    var gy1 = 232;
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(gx0, gy0);
    g.lineTo(gx0, gy1);
    g.lineTo(gx1, gy1);
    g.stroke();
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = 'center';
    for (var lv = 0.5; lv <= 2.001; lv += 0.5) {
      var tx = gx0 + (lv - 0.1) / 1.9 * (gx1 - gx0);
      g.strokeStyle = '#1C1B18';
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(tx, gy1);
      g.lineTo(tx, gy1 + 5);
      g.stroke();
      g.fillStyle = '#5A5748';
      g.fillText(lv.toFixed(1), tx, gy1 + 20);
    }
    g.textAlign = 'right';
    for (var tv = 0; tv <= 3.001; tv += 1) {
      var ty = gy1 - (tv / 3) * (gy1 - gy0);
      g.strokeStyle = '#1C1B18';
      g.lineWidth = 1.5;
      g.beginPath();
      g.moveTo(gx0 - 5, ty);
      g.lineTo(gx0, ty);
      g.stroke();
      g.fillStyle = '#5A5748';
      g.fillText(String(tv), gx0 - 8, ty + 5);
    }
    g.fillStyle = '#1C1B18';
    g.textAlign = 'center';
    g.fillText('l (m)', (gx0 + gx1) / 2, gy1 + 38);
    g.textAlign = 'left';
    g.fillText('T (s)', gx0 + 6, gy0 - 8);
    g.strokeStyle = '#1F3A9E';
    g.lineWidth = 3;
    g.beginPath();
    for (var ll = 0.1; ll <= 2.001; ll += 0.01) {
      var TT = 2 * Math.PI * Math.sqrt(ll / grav);
      var px = gx0 + (ll - 0.1) / 1.9 * (gx1 - gx0);
      var py = gy1 - (TT / 3) * (gy1 - gy0);
      if (ll <= 0.101) { g.moveTo(px, py); } else { g.lineTo(px, py); }
    }
    g.stroke();
    var mx = gx0 + (l - 0.1) / 1.9 * (gx1 - gx0);
    var my = gy1 - (T / 3) * (gy1 - gy0);
    g.strokeStyle = '#5A5748';
    g.lineWidth = 1.5;
    g.setLineDash([4, 4]);
    g.beginPath();
    g.moveTo(mx, my);
    g.lineTo(mx, gy1);
    g.stroke();
    g.beginPath();
    g.moveTo(mx, my);
    g.lineTo(gx0, my);
    g.stroke();
    g.setLineDash([]);
    g.fillStyle = '#1F3A9E';
    g.beginPath();
    g.arc(mx, my, 6, 0, 2 * Math.PI);
    g.fill();
    g.strokeStyle = '#1C1B18';
    g.lineWidth = 2;
    g.beginPath();
    g.arc(mx, my, 6, 0, 2 * Math.PI);
    g.stroke();
    g.fillStyle = '#1C1B18';
    g.font = "700 16px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = 'left';
    g.fillText('l = ' + l.toFixed(1) + ' m    T = ' + T.toFixed(2) + ' s', 16, 282);
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.fillStyle = '#5A5748';
    g.fillText('g = 9.8 m s-2  -  mass does not appear in T', 16, 304);
    try {
      var readTxt = 'l = ' + l.toFixed(1) + ' m, T = ' + T.toFixed(2) + ' s';
      var readEl = null;
      if (ctx.state && ctx.state._readEl) { readEl = ctx.state._readEl; }
      if (!readEl) {
        if (ctx.read && typeof ctx.read === 'object') { readEl = ctx.read; }
        else if (ctx.readout && typeof ctx.readout === 'object') { readEl = ctx.readout; }
        else if (ctx.output && typeof ctx.output === 'object') { readEl = ctx.output; }
        else { readEl = document.querySelector('.zn-sim-b-23 .zn-sim-read') || document.querySelector('[data-sim="b-23"] .zn-sim-read') || document.querySelector('.zn-sim-read'); }
        if (readEl && ctx.state) { ctx.state._readEl = readEl; }
      }
      if (readEl && readEl.textContent !== readTxt) { readEl.textContent = readTxt; }
    } catch (e) {}
  }
});
(function () {
  function fixB28() {
    var oldQ = 'Which statement is meaningful without specifying a standard for comparison?';
    var newQ = 'Which statement is meaningful because it specifies a standard for comparison?';
    var scoped = document.querySelector('#b-28, [data-block="b-28"], [data-id="b-28"]');
    if (scoped) {
      var els = scoped.querySelectorAll('legend, p, h1, h2, h3, h4, span');
      for (var s = 0; s < els.length; s++) {
        if (els[s].textContent && els[s].textContent.trim() === oldQ) { els[s].textContent = newQ; }
      }
    }
    var all = document.querySelectorAll('legend, p, h1, h2, h3, h4, span, div, label');
    for (var i = 0; i < all.length; i++) {
      if (all[i].textContent && all[i].textContent.trim() === oldQ) { all[i].textContent = newQ; }
    }
    var legends = document.querySelectorAll('legend');
    for (var j = 0; j < legends.length; j++) {
      if (legends[j].textContent && legends[j].textContent.indexOf(oldQ) !== -1) { legends[j].textContent = newQ; }
    }
  }
  function fixDiagrams() {
    var svgs = document.querySelectorAll('svg');
    for (var i = 0; i < svgs.length; i++) {
      var svg = svgs[i];
      var vb = svg.getAttribute('viewBox') || '';
      if (vb === '0 0 420 130') {
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', 'Seven SI base quantities and units: Length m, Mass kg, Time s, Current A, Temp. K, Amount mol, Light cd');
        svg.setAttribute('viewBox', '0 0 420 260');
        svg.innerHTML = "<rect x='5' y='20' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='110' y='20' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='215' y='20' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='320' y='20' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='57' y='120' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='162' y='120' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><rect x='267' y='120' width='95' height='80' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><text x='52' y='58' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Length</text><text x='52' y='88' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>m</text><text x='157' y='58' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Mass</text><text x='157' y='88' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>kg</text><text x='262' y='58' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Time</text><text x='262' y='88' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>s</text><text x='367' y='58' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Current</text><text x='367' y='88' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>A</text><text x='104' y='158' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Temp.</text><text x='104' y='188' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>K</text><text x='209' y='158' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Amount</text><text x='209' y='188' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>mol</text><text x='314' y='158' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Light</text><text x='314' y='188' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>cd</text><text x='210' y='235' fill='#5A5748' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='20' text-anchor='middle'>Seven SI base quantities and units</text>";
      } else if (vb === '0 0 400 150') {
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', 'Volume = L × L × L, [L3]; Force = M × L / T2, [M L T-2]; Dimensions from base quantities [L], [M], [T]');
        svg.setAttribute('viewBox', '0 0 420 260');
        svg.innerHTML = "<rect x='20' y='20' width='380' height='90' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><text x='210' y='58' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Volume = L × L × L</text><text x='210' y='88' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>[L3]</text><rect x='20' y='130' width='380' height='90' fill='#F6F0CF' stroke='#1C1B18' stroke-width='2'/><text x='210' y='168' fill='#1C1B18' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='22' text-anchor='middle'>Force = M × L / T2</text><text x='210' y='198' fill='#1F3A9E' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='24' text-anchor='middle'>[M L T-2]</text><text x='210' y='245' fill='#5A5748' font-family='Caveat, Segoe Print, Bradley Hand, cursive' font-weight='700' font-size='20' text-anchor='middle'>Dimensions from base quantities [L], [M], [T]</text>";
      } else {
        if (svg.getAttribute('role') !== 'img') { svg.setAttribute('role', 'img'); }
        if (!svg.getAttribute('aria-label')) {
          var txt = (svg.textContent || '').split('  ').join(' ').trim();
          if (txt) { svg.setAttribute('aria-label', txt); }
        }
        var texts = svg.querySelectorAll('text');
        for (var j = 0; j < texts.length; j++) {
          var t = texts[j];
          var fs = parseFloat(t.getAttribute('font-size') || '0');
          if (!fs || fs < 20) { t.setAttribute('font-size', '20'); }
          if (!t.getAttribute('font-family')) { t.setAttribute('font-family', 'Caveat, Segoe Print, Bradley Hand, cursive'); }
          t.setAttribute('font-weight', '700');
        }
      }
    }
  }
  function applyFixes() { fixDiagrams(); fixB28(); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', applyFixes); } else { applyFixes(); }
  if (window.MutationObserver && document.body) {
    var mo = new MutationObserver(function () { applyFixes(); });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }
})();