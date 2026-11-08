ZivonSim.register("b-29", {
  init: function (ctx) {
    ctx.state = {};
  },
  draw: function (ctx) {
    var g = ctx.g;
    var W = ctx.width || 480;
    var H = ctx.height || 320;
    var v0 = ctx.values.v0;
    var a = ctx.values.a;
    var t = ctx.values.t;
    var v = v0 + a * t;
    var x = v0 * t + 0.5 * a * t * t;
    var readoutText = "t = " + t.toFixed(1) + " s, x = " + x.toFixed(1) + " m, v = " + v.toFixed(1) + " m/s";
    try {
      if (typeof ctx.setReadout === "function") ctx.setReadout(readoutText);
      var readEl = ctx.readout || ctx.readEl || null;
      if (!readEl && ctx.el && ctx.el.querySelector) readEl = ctx.el.querySelector(".zn-sim-read");
      if (!readEl && ctx.root && ctx.root.querySelector) readEl = ctx.root.querySelector(".zn-sim-read");
      if (!readEl && typeof document !== "undefined") {
        readEl = document.querySelector('[data-sim="b-29"] .zn-sim-read') || document.querySelector(".zn-sim-b-29 .zn-sim-read") || document.querySelector(".zn-sim-read");
      }
      if (readEl) readEl.textContent = readoutText;
    } catch (e) {}
    var PAPER = "#F6F0CF";
    var INK = "#1C1B18";
    var GRAPHITE = "#5A5748";
    var BLUE = "#1F3A9E";
    g.fillStyle = PAPER;
    g.fillRect(0, 0, W, H);
    g.lineCap = "round";
    g.lineJoin = "round";
    g.fillStyle = INK;
    g.font = "700 16px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = "left";
    g.textBaseline = "top";
    g.fillText("t = " + t.toFixed(1) + " s   x = " + x.toFixed(1) + " m   v = " + v.toFixed(1) + " m/s", 20, 10);
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.fillStyle = GRAPHITE;
    g.fillText("v = v0 + a t", 20, 32);
    g.fillText("x = v0 t + (1/2) a t^2", 130, 32);
    var trackY = 78;
    var trackL = 30;
    var trackR = 450;
    var originX = 240;
    var maxAbsTrack = Math.max(20, Math.abs(x) * 1.25, Math.abs(v0 * t) * 1.1);
    var scaleTrack = 200 / maxAbsTrack;
    g.strokeStyle = INK;
    g.lineWidth = 3;
    g.beginPath(); g.moveTo(trackL, trackY); g.lineTo(trackR, trackY); g.stroke();
    g.strokeStyle = GRAPHITE;
    g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(originX, trackY - 8); g.lineTo(originX, trackY + 8); g.stroke();
    g.fillStyle = GRAPHITE;
    g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
    g.textAlign = "center";
    g.fillText("0", originX, trackY + 12);
    g.textAlign = "left";
    g.fillText("x (m)", trackR - 42, trackY + 12);
    var objX = originX + x * scaleTrack;
    objX = Math.max(trackL + 12, Math.min(trackR - 12, objX));
    var arrowLen = Math.max(-60, Math.min(60, v * 5));
    if (Math.abs(v) > 0.05) {
      g.strokeStyle = BLUE;
      g.lineWidth = 3;
      g.beginPath(); g.moveTo(objX, trackY - 22); g.lineTo(objX + arrowLen, trackY - 22); g.stroke();
      var dir = arrowLen > 0 ? 1 : -1;
      g.beginPath();
      g.moveTo(objX + arrowLen, trackY - 22);
      g.lineTo(objX + arrowLen - dir * 9, trackY - 27);
      g.lineTo(objX + arrowLen - dir * 9, trackY - 17);
      g.closePath(); g.fillStyle = BLUE; g.fill();
      g.fillStyle = BLUE;
      g.textAlign = "center";
      g.fillText("v", objX + arrowLen / 2, trackY - 42);
    }
    g.fillStyle = BLUE;
    g.beginPath(); g.arc(objX, trackY, 11, 0, Math.PI * 2); g.fill();
    g.strokeStyle = INK; g.lineWidth = 2;
    g.beginPath(); g.arc(objX, trackY, 11, 0, Math.PI * 2); g.stroke();
    function drawGraph(left, top, width, height, title, yLabel, isX) {
      var right = left + width;
      var bottom = top + height;
      var midY = top + height / 2;
      var maxAbs = 1;
      var i, tau, val;
      for (i = 0; i <= 50; i++) {
        tau = t * i / 50;
        val = isX ? (v0 * tau + 0.5 * a * tau * tau) : (v0 + a * tau);
        if (Math.abs(val) > maxAbs) maxAbs = Math.abs(val);
      }
      if (t === 0) maxAbs = Math.max(5, Math.abs(v0));
      maxAbs = Math.max(maxAbs * 1.2, 2);
      var scaleY = (height / 2 - 14) / maxAbs;
      var scaleT = (width - 24) / 10;
      g.strokeStyle = INK; g.lineWidth = 2;
      g.beginPath(); g.moveTo(left, midY); g.lineTo(right, midY); g.stroke();
      g.beginPath(); g.moveTo(left + 12, top); g.lineTo(left + 12, bottom); g.stroke();
      g.strokeStyle = GRAPHITE; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(left + 12, top); g.lineTo(left + 12, bottom); g.stroke();
      g.strokeStyle = BLUE; g.lineWidth = 2.5;
      g.beginPath();
      for (i = 0; i <= 60; i++) {
        tau = t * i / 60;
        val = isX ? (v0 * tau + 0.5 * a * tau * tau) : (v0 + a * tau);
        var px = left + 12 + tau * scaleT;
        var py = midY - val * scaleY;
        if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
      }
      g.stroke();
      var curVal = isX ? x : v;
      var cx = left + 12 + t * scaleT;
      var cy = midY - curVal * scaleY;
      g.fillStyle = BLUE;
      g.beginPath(); g.arc(cx, cy, 5, 0, Math.PI * 2); g.fill();
      g.strokeStyle = INK; g.lineWidth = 1.5;
      g.beginPath(); g.arc(cx, cy, 5, 0, Math.PI * 2); g.stroke();
      g.fillStyle = INK;
      g.font = "700 14px 'Courier Prime', 'Courier New', monospace";
      g.textAlign = "left";
      g.fillText(title, left, top - 2);
      g.fillStyle = GRAPHITE;
      g.font = "400 14px 'Courier Prime', 'Courier New', monospace";
      g.fillText(yLabel, left + 16, top + 2);
      g.textAlign = "right";
      g.fillText("t (s)", right, bottom + 4);
      g.textAlign = "left";
      g.fillText("0", left + 8, midY + 4);
    }
    drawGraph(20, 130, 210, 140, "x-t", "x (m)", true);
    drawGraph(250, 130, 210, 140, "v-t", "v (m/s)", false);
  }
});
(function fixDiagrams() {
  function ensureTitle(svg, text) {
    if (!svg.querySelector("title")) {
      var title = svg.ownerDocument.createElementNS(svg.namespaceURI, "title");
      title.textContent = text;
      svg.insertBefore(title, svg.firstChild);
    }
  }
  function run() {
    var svgs = document.querySelectorAll("svg");
    for (var i = 0; i < svgs.length; i++) {
      var svg = svgs[i];
      var txt = svg.textContent || "";
      if (txt.indexOf("P tangent") !== -1) {
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", "Position-time curve with tangent at point P; horizontal axis labelled t, vertical axis labelled x; tangent line labelled P tangent; annotation slope = velocity");
        ensureTitle(svg, "Position-time curve with tangent at point P; slope of tangent is instantaneous velocity");
      } else if (txt.indexOf("area = displacement") !== -1) {
        var rect = svg.querySelector("rect");
        if (rect) {
          var poly = svg.ownerDocument.createElementNS(svg.namespaceURI, "polygon");
          poly.setAttribute("points", "60,190 360,190 360,60 60,160");
          poly.setAttribute("fill", "none");
          poly.setAttribute("stroke", "#1F3A9E");
          poly.setAttribute("stroke-width", "2");
          rect.parentNode.replaceChild(poly, rect);
        }
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", "Velocity-time straight line for constant acceleration; horizontal axis labelled t, vertical axis labelled v; slope = acceleration; trapezoid area under curve to the t-axis = displacement");
        ensureTitle(svg, "Velocity-time straight line; slope is acceleration, area under curve (trapezoid to t-axis) is displacement");
      }
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  run();
})();
