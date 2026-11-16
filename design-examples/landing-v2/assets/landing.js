/* Zivon landing concepts v2 — one generated pen mark + native disclosure/dialog.
   No network, storage, microphone, analytics, or scroll listeners. */
(function () {
  "use strict";

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function drawPenUnderline(el) {
    var old = $(".uline", el);
    if (old) old.remove();

    var nodes = Array.prototype.slice.call(el.childNodes).filter(function (node) {
      return node.nodeType === 3 && node.textContent.trim();
    });
    if (!nodes.length) return;

    var fontSize = parseFloat(getComputedStyle(el).fontSize);
    var width = 0;
    nodes.forEach(function (node) {
      var range = document.createRange();
      range.selectNodeContents(node);
      width += range.getBoundingClientRect().width;
    });
    if (!width) return;

    var text = nodes
      .map(function (node) {
        return node.textContent;
      })
      .join(" ")
      .trim();

    function seedFrom(value) {
      var hash = 2166136261 >>> 0;
      for (var i = 0; i < value.length; i += 1) {
        hash ^= value.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
      }
      return hash >>> 0;
    }

    function rng(seed) {
      return function () {
        seed |= 0;
        seed = (seed + 0x6d2b79f5) | 0;
        var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }

    var length = width + 0.09 * fontSize + 0.18 * fontSize;
    var startX = -0.09 * fontSize;
    var points = Math.max(4, Math.round(length / (0.45 * fontSize)));
    var amplitude = 0.02 * fontSize;
    var period = 4 * fontSize;
    var phase = 0.7;
    var random = rng(seedFrom(text));
    var top = [];
    var bottom = [];

    for (var i = 0; i <= points; i += 1) {
      var t = i / points;
      var x = startX + length * t;
      var y =
        0.08 * fontSize +
        amplitude * Math.sin((2 * Math.PI * (length * t)) / period + phase) +
        (random() * 2 - 1) * 0.007 * fontSize;
      var halfWidth = ((0.067 + (0.033 - 0.067) * t) * fontSize) / 2;
      top.push([x, y - halfWidth]);
      bottom.push([x, y + halfWidth]);
    }

    var d = top
      .concat(bottom.reverse())
      .map(function (point, index) {
        return (index ? "L" : "M") + point[0].toFixed(2) + " " + point[1].toFixed(2);
      })
      .join(" ")
      .concat(" Z");

    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "uline");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", String(Math.ceil(width)));
    svg.setAttribute("height", String(Math.ceil(fontSize)));
    svg.setAttribute("overflow", "visible");

    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "var(--pen-blue)");
    svg.appendChild(path);
    el.appendChild(svg);
  }

  function initPen() {
    if (!$(".pen")) return;
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () {
        $$(".pen").forEach(drawPenUnderline);
      });
    } else {
      $$(".pen").forEach(drawPenUnderline);
    }
    var timer = 0;
    window.addEventListener("resize", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        $$(".pen").forEach(drawPenUnderline);
      }, 160);
    });
  }

  function initDisclosures() {
    var menus = $$("details.menu");
    menus.forEach(function (menu) {
      menu.addEventListener("toggle", function () {
        if (!menu.open) return;
        menus.forEach(function (other) {
          if (other !== menu) other.open = false;
        });
      });
    });

    document.addEventListener("click", function (event) {
      if (event.target.closest("details.menu")) return;
      menus.forEach(function (menu) {
        menu.open = false;
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      menus.forEach(function (menu) {
        if (menu.open) {
          menu.open = false;
          var summary = $("summary", menu);
          if (summary) summary.focus();
        }
      });
    });
  }

  function initDialogs() {
    $$("[data-open-dialog]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = document.getElementById(button.getAttribute("data-open-dialog"));
        if (dialog && !dialog.open) dialog.showModal();
      });
    });

    $$("[data-close-dialog]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = button.closest("dialog");
        if (dialog) dialog.close();
      });
    });

    $$("dialog").forEach(function (dialog) {
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) dialog.close();
      });
    });
  }

  function boot() {
    initPen();
    initDisclosures();
    initDialogs();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
