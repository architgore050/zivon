/* Zivon public site behaviour (F1).
   Owns: mobile menu disclosures, the one generated pen underline, the
   catalogue/class-page renderer, and the landing coverage list.

   Constraints (docs/specs/frontend/spec.md G1/G2):
   - vanilla JS, no framework, no build step;
   - no network, no storage, no microphone, no analytics;
   - the page argument must survive with this file absent; every renderer
     has a static fallback or an honest no-JS note in the HTML. */
(function () {
  "use strict";

  var CLASSES = [9, 10, 11, 12];

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function text(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function normalise(value) {
    return text(value).toLowerCase().replace(/\s+/g, " ").trim();
  }

  /* ---- mobile menu (native details; close on outside click / Escape) ---- */
  function initMenus() {
    var menus = $$("details.menu");
    if (!menus.length) return;

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
        if (!menu.open) return;
        menu.open = false;
        var summary = $("summary", menu);
        if (summary) summary.focus();
      });
    });
  }

  /* ---- the one pen annotation (doctrine §4.1) ---- */
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

    var label = nodes
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
    var random = rng(seedFrom(label));
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

  /* ---- catalogue data (courses.js is the generated site manifest) ---- */
  function readCourses() {
    var raw = window.ZIVON_COURSES;
    if (!Array.isArray(raw)) return null;
    var entries = [];
    var dropped = 0;
    raw.forEach(function (item) {
      if (!item || typeof item !== "object") {
        dropped += 1;
        return;
      }
      if (!item.href || !item.title) {
        dropped += 1;
        return;
      }
      var klass = Number(item.class);
      if (CLASSES.indexOf(klass) === -1) {
        dropped += 1;
        return;
      }
      entries.push({
        href: text(item.href),
        title: text(item.title),
        lessonTitle: text(item.lesson_title || item.title),
        class: klass,
        chapterNumber: Number(item.chapter_number || (item.chapter && item.chapter.number) || 0),
        chapterTitle: text(item.chapter && item.chapter.title),
        languages: item.languages && Array.isArray(item.languages.available)
          ? item.languages.available.slice()
          : ["en"],
        counts: item.counts && typeof item.counts === "object" ? item.counts : {},
        concepts: Array.isArray(item.concepts)
          ? item.concepts.map(function (concept) {
              return text(concept && concept.title);
            }).filter(Boolean)
          : [],
        generatedAt: text(item.generated_at),
        status: text(item.status || "lesson_only")
      });
    });
    return { entries: entries, dropped: dropped };
  }

  function lessonHref(entry) {
    return "/" + entry.href.replace(/^\/+/, "");
  }

  function languageLabel(code) {
    if (code === "en") return "English";
    if (code === "hi") return "हिन्दी";
    if (code === "hi-Latn") return "Hinglish";
    return code;
  }

  function languageNode(code) {
    var li = document.createElement("li");
    li.className = "lang";
    li.setAttribute("lang", code === "hi-Latn" ? "hi-Latn" : code);
    li.textContent = languageLabel(code);
    return li;
  }

  function statusNode(kind, label) {
    var span = document.createElement("span");
    span.className = "status status--" + kind;
    span.textContent = label;
    return span;
  }

  function countLine(counts) {
    var parts = [];
    if (Number(counts.checks) > 0) parts.push(Number(counts.checks) + " checks");
    if (Number(counts.simulations) > 0) parts.push(Number(counts.simulations) + " simulations");
    if (Number(counts.diagrams) > 0) parts.push(Number(counts.diagrams) + " diagrams");
    return parts.join(" · ");
  }

  function setText(selector, value, root) {
    var el = $(selector, root || document);
    if (el) el.textContent = value;
  }

  function show(el, visible) {
    if (el) el.hidden = !visible;
  }

  function buildCard(entry) {
    var li = document.createElement("li");
    li.className = "chapter-card";

    var num = document.createElement("p");
    num.className = "chapter-num";
    num.textContent = entry.chapterNumber ? "Chapter " + entry.chapterNumber : "Chapter";
    li.appendChild(num);

    var body = document.createElement("div");
    var title = document.createElement("h3");
    title.className = "chapter-title";
    var link = document.createElement("a");
    link.href = lessonHref(entry);
    link.textContent = entry.title;
    title.appendChild(link);
    body.appendChild(title);

    if (entry.chapterTitle && normalise(entry.chapterTitle) !== normalise(entry.title)) {
      var chapterLine = document.createElement("p");
      chapterLine.className = "meta mt-1";
      chapterLine.textContent = "From: " + entry.chapterTitle;
      body.appendChild(chapterLine);
    }

    var meta = document.createElement("p");
    meta.className = "chapter-meta";
    meta.appendChild(statusNode("live", "Lesson live"));

    var languages = document.createElement("ul");
    languages.className = "lang-list";
    languages.setAttribute("aria-label", "Languages available");
    entry.languages.forEach(function (code) {
      languages.appendChild(languageNode(code));
    });
    meta.appendChild(languages);

    var counts = countLine(entry.counts);
    if (counts) {
      var countSpan = document.createElement("span");
      countSpan.textContent = counts;
      meta.appendChild(countSpan);
    }
    body.appendChild(meta);

    var availability = document.createElement("p");
    availability.className = "chapter-meta";
    availability.appendChild(statusNode("none", "Practice not yet"));
    availability.appendChild(statusNode("none", "Chapter test not yet"));
    body.appendChild(availability);

    li.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "chapter-actions";
    var open = document.createElement("a");
    open.className = "text-link";
    open.href = lessonHref(entry);
    open.textContent = "Open lesson →";
    actions.appendChild(open);
    li.appendChild(actions);

    return li;
  }

  function matches(entry, query) {
    if (!query) return true;
    var haystack = normalise(
      [
        entry.title,
        entry.lessonTitle,
        entry.chapterTitle,
        "class " + entry.class,
        entry.concepts.join(" ")
      ].join(" ")
    );
    return query.split(" ").every(function (word) {
      return haystack.indexOf(word) !== -1;
    });
  }

  function formatDate(value) {
    if (!value) return "";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "";
    try {
      return date.toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC"
      });
    } catch (error) {
      return value.slice(0, 10);
    }
  }

  function replaceQuery(params) {
    try {
      var search = params.toString();
      var next = window.location.pathname + (search ? "?" + search : "") + window.location.hash;
      window.history.replaceState(null, "", next);
    } catch (error) {
      /* file:// or a locked-down browser: filtering still works in-page. */
    }
  }

  function initCatalogue() {
    var root = $("[data-catalogue]");
    if (!root) return;

    var list = $("#catalogue-list", root);
    var empty = $("#catalogue-empty", root);
    var error = $("#catalogue-error", root);
    var partial = $("#catalogue-partial", root);
    var count = $("#catalogue-count", root);
    var search = $("#catalogue-search", root);
    var tabs = $$("[data-class-filter]", root);
    var clear = $("#catalogue-clear", root);
    if (!list) return;

    var data = readCourses();
    if (!data) {
      show(error, true);
      show(empty, false);
      show(partial, false);
      if (count) count.textContent = "The catalogue did not load.";
      if (search) search.disabled = true;
      return;
    }
    show(error, false);
    if (data.dropped > 0) {
      show(partial, true);
      setText("[data-catalogue-dropped]", String(data.dropped), partial || root);
    }

    var params = new URLSearchParams(window.location.search);
    var requested = params.get("class");
    var state = {
      klass: requested && CLASSES.indexOf(Number(requested)) !== -1 ? Number(requested) : 0,
      query: normalise(params.get("q") || "")
    };
    if (search) {
      search.value = params.get("q") || "";
      search.disabled = false;
    }

    function applyTabs() {
      tabs.forEach(function (tab) {
        var value = Number(tab.getAttribute("data-class-filter")) || 0;
        tab.setAttribute("aria-pressed", value === state.klass ? "true" : "false");
      });
    }

    function render() {
      var visible = data.entries.filter(function (entry) {
        if (state.klass && entry.class !== state.klass) return false;
        return matches(entry, state.query);
      });
      visible.sort(function (a, b) {
        if (a.class !== b.class) return a.class - b.class;
        return a.chapterNumber - b.chapterNumber;
      });

      list.textContent = "";
      var lastClass = 0;
      visible.forEach(function (entry) {
        if (entry.class !== lastClass) {
          lastClass = entry.class;
          var heading = document.createElement("li");
          heading.className = "class-group-heading";
          var headingText = document.createElement("h3");
          headingText.textContent = "Class " + entry.class;
          heading.appendChild(headingText);
          list.appendChild(heading);
        }
        list.appendChild(buildCard(entry));
      });

      var total = data.entries.length;
      if (count) {
        if (visible.length === total) {
          count.textContent = total + (total === 1 ? " chapter live" : " chapters live");
        } else {
          count.textContent = visible.length + " of " + total + " chapters shown";
        }
      }
      show(empty, visible.length === 0);

      var emptyTitle = $("#catalogue-empty-title", root);
      if (empty && emptyTitle) {
        if (state.query) {
          emptyTitle.textContent = "No chapter matches “" + state.query + "”.";
        } else if (state.klass) {
          emptyTitle.textContent = "Class " + state.klass + " has no published chapter yet.";
        } else {
          emptyTitle.textContent = "No published chapter yet.";
        }
      }
      applyTabs();

      var coverage = $("#catalogue-coverage", root);
      if (coverage) {
        var missing = CLASSES.filter(function (klass) {
          return !data.entries.some(function (entry) {
            return entry.class === klass;
          });
        });
        if (missing.length && !state.klass && !state.query) {
          coverage.textContent =
            "No published chapter yet: " + missing.map(function (k) { return "Class " + k; }).join(", ") + ".";
          show(coverage, true);
        } else {
          show(coverage, false);
        }
      }
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        state.klass = Number(tab.getAttribute("data-class-filter")) || 0;
        var next = new URLSearchParams(window.location.search);
        if (state.klass) next.set("class", String(state.klass));
        else next.delete("class");
        if (state.query) next.set("q", search ? search.value : state.query);
        replaceQuery(next);
        render();
      });
    });

    if (search) {
      var timer = 0;
      search.addEventListener("input", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          state.query = normalise(search.value);
          var next = new URLSearchParams(window.location.search);
          if (state.query) next.set("q", search.value.trim());
          else next.delete("q");
          if (state.klass) next.set("class", String(state.klass));
          replaceQuery(next);
          render();
        }, 120);
      });
    }

    if (clear) {
      clear.addEventListener("click", function () {
        state.query = "";
        if (search) search.value = "";
        var next = new URLSearchParams(window.location.search);
        next.delete("q");
        replaceQuery(next);
        render();
        if (search) search.focus();
      });
    }

    render();
  }

  /* ---- class/course pages ---- */
  function initClassPage() {
    var root = $("[data-class-page]");
    if (!root) return;
    var klass = Number(root.getAttribute("data-class"));
    var list = $("#class-chapter-list", root);
    var empty = $("#class-empty", root);
    var error = $("#class-error", root);
    var count = $("#class-count", root);
    var latest = $("#class-latest", root);
    if (!list) return;

    var data = readCourses();
    if (!data) {
      show(error, true);
      show(empty, false);
      if (count) count.textContent = "The chapter list did not load.";
      return;
    }
    show(error, false);

    var entries = data.entries.filter(function (entry) {
      return entry.class === klass;
    });
    entries.sort(function (a, b) {
      return a.chapterNumber - b.chapterNumber;
    });

    list.textContent = "";
    entries.forEach(function (entry) {
      list.appendChild(buildCard(entry));
    });
    show(empty, entries.length === 0);

    if (count) {
      count.textContent = entries.length
        ? entries.length + (entries.length === 1 ? " chapter live" : " chapters live")
        : "No published chapter yet";
    }
    if (latest && entries.length) {
      var newest = entries
        .map(function (entry) {
          return formatDate(entry.generatedAt);
        })
        .filter(Boolean)
        .pop();
      if (newest) latest.textContent = "Latest chapter published " + newest + ".";
    }
  }

  /* ---- landing coverage (progressive enhancement; static copy remains) ---- */
  function initCoverage() {
    var root = $("[data-coverage]");
    if (!root) return;
    var data = readCourses();
    if (!data || !data.entries.length) {
      show(root, false);
      return;
    }
    var body = $("[data-coverage-body]", root);
    if (!body) return;
    body.textContent = "";
    CLASSES.forEach(function (klass) {
      var entries = data.entries.filter(function (entry) {
        return entry.class === klass;
      });
      var row = document.createElement("tr");
      var name = document.createElement("td");
      var strong = document.createElement("strong");
      strong.textContent = "Class " + klass;
      name.appendChild(strong);
      row.appendChild(name);
      var live = document.createElement("td");
      if (entries.length) {
        live.textContent = entries.length + (entries.length === 1 ? " chapter live" : " chapters live");
      } else {
        live.textContent = "No published chapter yet";
      }
      row.appendChild(live);
      var languages = document.createElement("td");
      if (entries.length) {
        var langs = [];
        entries.forEach(function (entry) {
          entry.languages.forEach(function (code) {
            if (langs.indexOf(code) === -1) langs.push(code);
          });
        });
        languages.textContent = langs.map(languageLabel).join(" · ");
      } else {
        languages.textContent = "—";
      }
      row.appendChild(languages);
      body.appendChild(row);
    });
    show(root, true);
  }

  function boot() {
    initMenus();
    initPen();
    initCatalogue();
    initClassPage();
    initCoverage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
