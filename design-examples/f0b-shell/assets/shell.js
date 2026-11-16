/* ==========================================================================
   F0B shell exploration — behaviour
   --------------------------------------------------------------------------
   Vanilla JS, no build step, no framework, no network. This is the example's
   behaviour layer only: the product implementation lands in frontend/assets/
   app-shell.js + design-system.js after the founder's verdict.

   Everything is progressive enhancement:
   - links and forms work without JS;
   - dialogs are native <dialog>;
   - the review strip is example chrome, not a product surface;
   - no microphone, camera, localStorage, or network request is used.
   ========================================================================== */
(function () {
  "use strict";

  var STATE_LABELS = {
    default: "Default",
    loading: "Loading",
    empty: "Empty",
    error: "Panel error",
    offline: "Offline",
    auth: "Auth required",
    quota: "Quota exhausted",
    idle: "Idle",
    recording: "Recording",
    transcribing: "Transcribing",
    result: "Result",
    permission: "Mic denied",
    untranslated: "Untranslated",
    "autosave-fail": "Autosave failed",
    "time-expired": "Time expired",
    submit: "Submit dialog"
  };

  var toastEl = null;
  var toastTimer = 0;
  var currentState = "default";
  var consentGranted = false;
  var consentDeclined = false;
  var pendingConsentNext = "dock";

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function showToast(message) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "zn-toast";
      toastEl.id = "zn-demo-toast";
      toastEl.setAttribute("role", "status");
      toastEl.setAttribute("aria-live", "polite");
      toastEl.hidden = true;
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.hidden = false;
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastEl.hidden = true;
    }, 4400);
  }

  /* ---- details menus ---------------------------------------------------- */

  function initMenus() {
    var menus = $$("details.zn-menu");

    menus.forEach(function (menu) {
      menu.addEventListener("toggle", function () {
        if (!menu.open) return;
        menus.forEach(function (other) {
          if (other !== menu) other.open = false;
        });
      });

      menu.addEventListener("keydown", function (event) {
        if (!menu.open) return;
        var items = $$(".zn-menu-item", menu);
        var index = items.indexOf(document.activeElement);
        if (index === -1) return;
        var next = null;
        if (event.key === "ArrowDown") next = items[(index + 1) % items.length];
        if (event.key === "ArrowUp") next = items[(index - 1 + items.length) % items.length];
        if (event.key === "Home") next = items[0];
        if (event.key === "End") next = items[items.length - 1];
        if (!next) return;
        event.preventDefault();
        next.focus();
      });
    });

    document.addEventListener("click", function (event) {
      if (event.target.closest("details.zn-menu")) return;
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

  /* ---- dialogs and drawers --------------------------------------------- */

  function openDialog(id) {
    var dialog = typeof id === "string" ? document.getElementById(id) : id;
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (!dialog.open) dialog.showModal();

    var focusTarget = $("[autofocus]", dialog) || $(".zn-dialog-actions .zn-btn", dialog);
    if (focusTarget) focusTarget.focus();
  }

  function initDialogs() {
    document.addEventListener("click", function (event) {
      var opener = event.target.closest("[data-open-dialog]");
      if (opener) {
        event.preventDefault();
        openDialog(opener.getAttribute("data-open-dialog"));
        return;
      }
      var closer = event.target.closest("[data-close-dialog]");
      if (closer) {
        event.preventDefault();
        var dialog = closer.closest("dialog");
        if (dialog) dialog.close();
      }
    });

    $$("dialog.zn-dialog, dialog.zn-sheet, dialog.zn-drawer").forEach(function (dialog) {
      dialog.addEventListener("click", function (event) {
        if (event.target === dialog) dialog.close();
      });
    });
  }

  /* ---- tabs, catalogue filters, search --------------------------------- */

  function initTabs() {
    $$("[role='tablist']").forEach(function (tablist) {
      var tabs = $$("[role='tab']", tablist);

      function select(tab, focus) {
        tabs.forEach(function (other) {
          var selected = other === tab;
          other.setAttribute("aria-selected", selected ? "true" : "false");
          other.tabIndex = selected ? 0 : -1;
        });
        if (focus) tab.focus();
        if (tablist.hasAttribute("data-tab-filter")) filterCatalogue();
        if (tablist.hasAttribute("data-demo-tabs")) {
          $$("[role='tabpanel']", tablist.parentElement).forEach(function (panel) {
            panel.hidden = panel.id !== tab.getAttribute("aria-controls");
          });
        }
      }

      tabs.forEach(function (tab, index) {
        tab.addEventListener("click", function () {
          select(tab, false);
        });
        tab.addEventListener("keydown", function (event) {
          var next = null;
          if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
          if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
          if (event.key === "Home") next = tabs[0];
          if (event.key === "End") next = tabs[tabs.length - 1];
          if (!next) return;
          event.preventDefault();
          select(next, true);
        });
      });

      var initial = tabs.filter(function (tab) {
        return tab.getAttribute("aria-selected") === "true";
      })[0] || tabs[0];

      var requestedClass = new URLSearchParams(window.location.search).get("class");
      if (tablist.hasAttribute("data-tab-filter") && requestedClass) {
        var requested = tabs.filter(function (tab) {
          return tab.getAttribute("data-class") === requestedClass;
        })[0];
        if (requested) initial = requested;
      }

      if (initial) select(initial, false);
    });
  }

  function filterCatalogue() {
    var list = $("#chapter-list");
    if (!list) return;

    var tablist = $("[data-tab-filter='class']");
    var activeTab = tablist ? $("[role='tab'][aria-selected='true']", tablist) : null;
    var activeClass = activeTab ? activeTab.getAttribute("data-class") : "all";
    var queryInput = $("#catalogue-search");
    var query = queryInput ? queryInput.value.trim().toLowerCase() : "";
    var liveOnly = $("#filter-live") && $("#filter-live").getAttribute("aria-pressed") === "true";
    var practiceOnly =
      $("#filter-practice") && $("#filter-practice").getAttribute("aria-pressed") === "true";
    var testsOnly = $("#filter-tests") && $("#filter-tests").getAttribute("aria-pressed") === "true";

    var rows = $$(".chapter-row", list);
    var visible = 0;
    var live = 0;

    rows.forEach(function (row) {
      var rowClass = row.getAttribute("data-class") || "";
      var status = row.getAttribute("data-status") || "";
      var text = row.textContent.toLowerCase();
      var matches =
        (!activeClass || activeClass === "all" || activeClass === rowClass) &&
        (!query || text.indexOf(query) !== -1) &&
        (!liveOnly || status === "live") &&
        (!practiceOnly || row.getAttribute("data-has-practice") === "true") &&
        (!testsOnly || row.getAttribute("data-has-tests") === "true");

      row.hidden = !matches;
      if (matches) {
        visible += 1;
        if (status === "live") live += 1;
      }
    });

    var count = $("#catalogue-count");
    if (count) count.textContent = visible + " chapters · " + live + " live";

    var empty = $("#catalogue-empty");
    if (empty) empty.hidden = visible !== 0;
  }

  function initCatalogue() {
    var search = $("#catalogue-search");
    if (search) search.addEventListener("input", filterCatalogue);

    ["#filter-live", "#filter-practice", "#filter-tests"].forEach(function (id) {
      var button = $(id);
      if (!button) return;
      button.addEventListener("click", function () {
        var on = button.getAttribute("aria-pressed") === "true";
        button.setAttribute("aria-pressed", on ? "false" : "true");
        filterCatalogue();
      });
    });

    if ($("#chapter-list")) filterCatalogue();
  }

  function clearCatalogueFilters() {
    var search = $("#catalogue-search");
    if (search) search.value = "";
    ["#filter-live", "#filter-practice", "#filter-tests"].forEach(function (id) {
      var button = $(id);
      if (button) button.setAttribute("aria-pressed", "false");
    });
    filterCatalogue();
  }

  /* ---- switches, saves, toasts ----------------------------------------- */

  function initSwitches() {
    $$("[data-switch]").forEach(function (button) {
      button.addEventListener("click", function () {
        var on = button.getAttribute("aria-checked") === "true";
        button.setAttribute("aria-checked", on ? "false" : "true");
      });
    });
  }

  function initSaves() {
    $$("[data-save]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.disabled || button.getAttribute("aria-busy") === "true") return;
        var label = button.getAttribute("data-save") || "Settings";
        var original = button.textContent;
        button.setAttribute("aria-busy", "true");
        button.textContent = "Saving…";

        var actions = button.closest(".settings-actions");
        var status = actions ? $(".save-status", actions) : null;
        if (status) status.textContent = "Saving…";

        window.setTimeout(function () {
          button.removeAttribute("aria-busy");
          button.textContent = original;
          if (status) {
            status.textContent = "Saved · " + timeNow();
          }
          showToast("Saved: " + label);
        }, 450);
      });
    });
  }

  function timeNow() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function initDemoToasts() {
    $$("[data-toast]").forEach(function (button) {
      button.addEventListener("click", function () {
        showToast(button.getAttribute("data-toast"));
      });
    });
  }

  /* ---- pen underline (doctrine §4.1) ----------------------------------- */

  function drawPenUnderlines() {
    $$(".zn-pen").forEach(function (el) {
      var old = $(".uline", el);
      if (old) old.remove();

      var textNodes = Array.prototype.slice.call(el.childNodes).filter(function (node) {
        return node.nodeType === 3 && node.textContent.trim();
      });
      if (!textNodes.length) return;

      var fontSize = parseFloat(getComputedStyle(el).fontSize);
      var width = 0;
      textNodes.forEach(function (node) {
        var range = document.createRange();
        range.selectNodeContents(node);
        width += range.getBoundingClientRect().width;
      });
      if (!width) return;

      var text = textNodes
        .map(function (node) {
          return node.textContent;
        })
        .join(" ")
        .trim();

      function seedFrom(s) {
        var h = 2166136261 >>> 0;
        for (var i = 0; i < s.length; i += 1) {
          h ^= s.charCodeAt(i);
          h = Math.imul(h, 16777619);
        }
        return h >>> 0;
      }

      function rng(a) {
        return function () {
          a |= 0;
          a = (a + 0x6d2b79f5) | 0;
          var t = Math.imul(a ^ (a >>> 15), 1 | a);
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
    });
  }

  function initPen() {
    if (!$(".zn-pen")) return;
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(drawPenUnderlines);
    } else {
      drawPenUnderlines();
    }
    var resizeTimer = 0;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(drawPenUnderlines, 150);
    });
  }

  /* ---- lesson checks ---------------------------------------------------- */

  function initChecks() {
    $$("[data-check]").forEach(function (button) {
      button.addEventListener("click", function () {
        var root = button.closest("[data-check-root]");
        if (!root) return;
        var inputs = $$("input[type='radio']", root);
        var checked = inputs.filter(function (input) {
          return input.checked;
        })[0];
        var feedback = $(".lesson-feedback", root) || $(".feedback-panel", root);
        if (!feedback) return;

        if (!checked) {
          feedback.hidden = false;
          feedback.textContent = "Choose one option first.";
          return;
        }

        var answer = String(root.getAttribute("data-answer"));
        var correct = checked.value === answer;
        feedback.hidden = false;

        if (feedback.classList.contains("feedback-panel")) {
          var title = $(".feedback-title", feedback);
          var copy = $(".feedback-copy", feedback);
          if (title) {
            title.setAttribute("data-outcome", correct ? "correct" : "wrong");
            title.innerHTML =
              '<span class="feedback-mark" aria-hidden="true">' +
              (correct ? "✓" : "✗") +
              "</span><span>" +
              (correct ? "Correct" : "Not quite") +
              "</span>";
          }
          if (copy) {
            copy.textContent = correct
              ? "That is the right idea. Open “Why?” for the full reasoning."
              : "Not yet. Open “Why?” and check the sign convention, then try again.";
          }
        } else {
          feedback.textContent = correct
            ? "✓ Correct. Open “Why?” for the reasoning."
            : "✗ Not quite. Open “Why?” for the reasoning.";
        }
      });
    });
  }

  function initHints() {
    $$("[data-show-hint]").forEach(function (button) {
      button.addEventListener("click", function () {
        var hint = $("#practice-hint");
        if (!hint) return;
        hint.hidden = false;
        button.setAttribute("aria-expanded", "true");
        button.textContent = "Hint shown";
        button.disabled = true;
        var used = $("#hint-used");
        if (used) used.textContent = "1 hint used";
      });
    });
  }

  /* ---- lesson: bookmark, read-aloud, language, progress, dock, consent -- */

  function initLessonChrome() {
    var bookmark = $("[data-bookmark]");
    if (bookmark) {
      bookmark.addEventListener("click", function () {
        var on = bookmark.getAttribute("aria-pressed") === "true";
        bookmark.setAttribute("aria-pressed", on ? "false" : "true");
        bookmark.textContent = on ? "Bookmark" : "Bookmarked";
        showToast(on ? "Bookmark removed (design example)." : "Bookmarked (design example).");
      });
    }

    $$("[data-audio-demo]").forEach(function (button) {
      var readBar = button.parentElement
        ? button.parentElement.querySelector(".lesson-read-progress")
        : null;

      function stopAudioDemo() {
        button.setAttribute("aria-pressed", "false");
        var label = button.querySelector("[data-audio-label]");
        if (label) label.textContent = "Listen";
        var wrap = button.closest(".zn-audio");
        if (wrap) wrap.setAttribute("data-playing", "false");
        if (readBar) readBar.style.transform = "scaleX(0)";
      }

      button.addEventListener("click", function () {
        var playing = button.getAttribute("aria-pressed") === "true";
        button.setAttribute("aria-pressed", playing ? "false" : "true");
        button.querySelector("[data-audio-label]").textContent = playing ? "Listen" : "Stop";
        var wrap = button.closest(".zn-audio");
        if (wrap) wrap.setAttribute("data-playing", playing ? "false" : "true");
        if (readBar) readBar.style.transform = playing ? "scaleX(0)" : "scaleX(1)";
        showToast("Design example: no audio file is bundled.");
        if (!playing) {
          window.setTimeout(stopAudioDemo, 6000);
        }
      });
    });

    $$(".lesson-chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var group = chip.closest("[role='radiogroup']");
        if (!group) return;
        $$(".lesson-chip", group).forEach(function (other) {
          other.setAttribute("aria-checked", other === chip ? "true" : "false");
        });
        showToast("Language is page-level. String switching lands with i18n.");
      });
    });

    var progress = $("#lesson-progress-fill");
    if (progress) {
      var update = function () {
        var paper = $(".lesson-paper");
        if (!paper) return;
        var rect = paper.getBoundingClientRect();
        var total = rect.height - window.innerHeight;
        var done = total > 0 ? (-rect.top / total) : 0;
        var value = Math.max(0, Math.min(1, done));
        progress.style.transform = "scaleX(" + value.toFixed(3) + ")";
      };
      window.addEventListener("scroll", update, { passive: true });
      window.addEventListener("resize", update);
      update();
    }

    var dockMic = $("[data-dock-mic]");
    var dockCaption = $("[data-dock-caption]");
    if (dockMic) {
      dockMic.addEventListener("click", function () {
        var on = dockMic.getAttribute("aria-pressed") === "true";
        dockMic.setAttribute("aria-pressed", on ? "false" : "true");
        if (dockCaption) {
          dockCaption.textContent = on
            ? "Mic dabao aur poochho"
            : "Sun rahe hain — pakad ke rakho";
        }
        showToast("Design example: the dock is visual only; no microphone is opened.");
      });
    }

    var dockType = $("[data-dock-type]");
    if (dockType) {
      dockType.addEventListener("click", function () {
        showToast("Typed fallback is part of the §10.12 dock; shown in F4.");
      });
    }

    var reportForm = $("#report-form");
    if (reportForm) {
      reportForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var dialog = reportForm.closest("dialog");
        if (dialog) dialog.close();
        showToast("Report noted (design example). No data is sent.");
      });
    }
  }

  function requestConsent(next) {
    pendingConsentNext = next || "dock";
    openDialog("consent-dialog");
  }

  function acceptConsent() {
    consentGranted = true;
    var dialog = document.getElementById("consent-dialog");
    if (dialog) dialog.close();

    if (pendingConsentNext === "speak") {
      setSpeakState("recording");
      return;
    }

    var tab = $("[data-dock-tab]");
    var dock = $("[data-dock-region]");
    if (tab) tab.hidden = true;
    if (dock) {
      dock.hidden = false;
      var mic = $("[data-dock-mic]", dock);
      if (mic) mic.focus();
    }
  }

  function declineConsent() {
    consentDeclined = true;
    var dialog = document.getElementById("consent-dialog");
    if (dialog) dialog.close();
    var tab = $("[data-dock-tab]");
    if (tab) tab.hidden = true;
    showToast("Voice is off on this device. Reading, simulations, and typing still work.");
  }

  function initConsent() {
    $$("[data-consent-accept]").forEach(function (button) {
      var dialog = button.closest("dialog");
      var guardian = dialog ? $("input[type='checkbox']", dialog) : null;
      if (guardian) {
        button.disabled = true;
        button.setAttribute("aria-describedby", "consent-guardian-help");
        guardian.addEventListener("change", function () {
          button.disabled = !guardian.checked;
        });
      }
      button.addEventListener("click", acceptConsent);
    });
    $$("[data-consent-decline]").forEach(function (button) {
      button.addEventListener("click", declineConsent);
    });

    var tab = $("[data-dock-tab]");
    if (tab) {
      tab.addEventListener("click", function () {
        requestConsent("dock");
      });
    }

    var start = $("[data-start-speaking]");
    if (start) {
      start.addEventListener("click", function () {
        if (!consentGranted) {
          requestConsent("speak");
          return;
        }
        if (speakState === "recording") {
          stopRecording();
        } else {
          setSpeakState("recording");
        }
      });
    }

    var mic = $("[data-speak-mic]");
    if (mic) {
      mic.addEventListener("click", function () {
        if (!consentGranted) {
          requestConsent("speak");
          return;
        }
        if (speakState === "recording") {
          stopRecording();
        } else {
          setSpeakState("recording");
        }
      });
    }
  }

  /* ---- speaking recorder ------------------------------------------------ */

  var speakTimer = 0;
  var transcribeTimer = 0;
  var speakStartedAt = 0;
  var speakState = "idle";
  var speakDuration = 0;

  function formatClock(seconds) {
    var safe = Math.max(0, Math.min(45, seconds));
    return "00:" + String(safe).padStart(2, "0");
  }

  function setSpeakState(state) {
    var root = $("[data-speaking]");
    if (!root) return;
    var mapped = state === "default" ? "idle" : state;
    speakState = mapped;
    root.setAttribute("data-speaking-state", mapped);

    var select = $("#review-state");
    if (select) {
      var selectValue = mapped === "idle" ? "default" : mapped;
      Array.prototype.slice.call(select.options).forEach(function (option) {
        if (option.value === selectValue) select.value = selectValue;
      });
    }
    currentState = mapped;

    $$("[data-speak]", root).forEach(function (block) {
      var states = (block.getAttribute("data-speak") || "").split(/\s+/);
      var show = states.indexOf(mapped) !== -1 || states.indexOf("always") !== -1;
      block.hidden = !show;
    });

    var clock = $("#recorder-clock");
    var status = $("#recorder-status");
    var mic = $("[data-speak-mic]");

    if (mapped === "recording") {
      if (!speakStartedAt) speakStartedAt = Date.now();
      window.clearInterval(speakTimer);
      speakTimer = window.setInterval(function () {
        var elapsed = Math.floor((Date.now() - speakStartedAt) / 1000);
        if (clock) clock.textContent = formatClock(elapsed) + " / 00:45";
        if (elapsed >= 45) stopRecording();
      }, 500);
      if (clock) clock.textContent = "00:00 / 00:45";
      if (status) status.textContent = "Recording — speak in your own words.";
      if (mic) {
        mic.setAttribute("aria-pressed", "true");
        mic.setAttribute("aria-label", "Stop recording");
        var label = $("[data-speak-label]", root);
        if (label) label.textContent = "Stop recording";
      }
      var wave = $("[data-speak-wave]");
      if (wave) wave.setAttribute("data-active", "true");
    } else {
      window.clearInterval(speakTimer);
      speakTimer = 0;
      if (mic) {
        mic.setAttribute("aria-pressed", "false");
        mic.setAttribute("aria-label", "Start recording");
        var micLabel = $("[data-speak-label]", root);
        if (micLabel) micLabel.textContent = "Start recording";
      }
      var activeWave = $("[data-speak-wave]");
      if (activeWave) activeWave.setAttribute("data-active", "false");
      if (mapped !== "recording") speakStartedAt = 0;
    }

    if (mapped === "transcribing") {
      if (status) status.textContent = "Turning your answer into text…";
      window.clearTimeout(transcribeTimer);
      transcribeTimer = window.setTimeout(function () {
        var speakingRoot = $("[data-speaking]");
        if (speakingRoot && speakingRoot.getAttribute("data-speaking-state") === "transcribing") {
          setSpeakState("result");
        }
      }, 1400);
    }

    if (mapped === "result") {
      if (status) status.textContent = "Feedback ready. This is AI feedback, not a mark.";
      if (clock) clock.textContent = formatClock(speakDuration || 41) + " / 00:45";
    }

    if (mapped === "permission" && status) {
      status.textContent = "Microphone is off. You can still read the prompt and model answer.";
    }
    if (mapped === "quota" && status) {
      status.textContent = "Voice is used up for today. The rest of the page still works.";
    }
    if (mapped === "offline" && status) {
      status.textContent = "Recording needs a connection. Your prompt is still readable.";
    }
    if (mapped === "idle" && status) {
      status.textContent = "Tap the mic when you are ready. You can re-record.";
    }
  }

  function stopRecording() {
    if (speakState !== "recording") {
      setSpeakState("transcribing");
      return;
    }
    speakDuration = Math.floor((Date.now() - speakStartedAt) / 1000);
    setSpeakState("transcribing");
  }

  function initSpeaking() {
    var root = $("[data-speaking]");
    if (!root) return;

    var reRecord = $("[data-re-record]");
    if (reRecord) {
      reRecord.addEventListener("click", function () {
        setSpeakState("idle");
      });
    }

    var save = $("[data-save-attempt]");
    if (save) {
      save.addEventListener("click", function () {
        showToast("Saved to progress (design example).");
      });
    }

    var del = $("[data-delete-attempt]");
    if (del) {
      del.addEventListener("click", function () {
        setSpeakState("idle");
        showToast("Attempt deleted (design example).");
      });
    }

    setSpeakState("idle");
  }

  /* ---- test player ------------------------------------------------------ */

  var autosaveTimer = 0;

  function setTestState(state) {
    var autosave = $("#autosave");
    var banner = $("#time-expired-banner");
    var submit = $("#submit-test");
    var answer = $("#test-answer");

    if (!autosave) return;

    if (state === "autosave-fail") {
      autosave.setAttribute("data-state", "error");
      autosave.textContent = "Could not save — retrying";
      var retry = $("#autosave-retry");
      if (retry) retry.hidden = false;
    } else if (state === "offline") {
      autosave.setAttribute("data-state", "saved");
      autosave.textContent = "Saved on this device · syncs when online";
    } else if (state === "time-expired") {
      autosave.setAttribute("data-state", "saved");
      autosave.textContent = "Answers kept on this device";
      if (banner) banner.hidden = false;
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Submitting…";
      }
      if (answer) answer.disabled = true;
      var timer = $("#exam-timer");
      if (timer) timer.textContent = "00:00 remaining";
    } else {
      autosave.setAttribute("data-state", "saved");
      autosave.textContent = "Saved just now";
      var retry2 = $("#autosave-retry");
      if (retry2) retry2.hidden = true;
      if (banner) banner.hidden = true;
      if (submit) {
        submit.disabled = false;
        submit.textContent = "Submit test";
      }
      if (answer) answer.disabled = false;
      var timer2 = $("#exam-timer");
      if (timer2) timer2.textContent = "38:12 remaining";
    }

    if (state === "submit") {
      window.setTimeout(function () {
        updateSubmitCopy();
        openDialog("submit-dialog");
      }, 0);
    }
  }

  function updateSubmitCopy() {
    var cells = $$("[data-palette-cell]");
    var unanswered = cells.filter(function (cell) {
      return cell.getAttribute("data-palette") === "unanswered";
    }).length;
    var copy = $("#submit-unanswered");
    if (!copy) return;
    if (!cells.length) return;
    copy.textContent =
      unanswered === 0
        ? "All " + cells.length + " questions are answered."
        : unanswered + (unanswered === 1 ? " question is" : " questions are") + " unanswered.";
  }

  function initTest() {
    var root = $("[data-test]");
    if (!root) return;

    var retry = $("#autosave-retry");
    if (retry) {
      retry.addEventListener("click", function () {
        showToast("Retry started (design example).");
        setTestState("default");
      });
    }

    var answer = $("#test-answer");
    if (answer) {
      answer.addEventListener("input", function () {
        var autosave = $("#autosave");
        if (!autosave) return;
        if (currentState === "autosave-fail" || currentState === "offline") return;
        if (autosave.getAttribute("data-state") === "saving") return;
        autosave.setAttribute("data-state", "saving");
        autosave.textContent = "Saving…";
        window.clearTimeout(autosaveTimer);
        autosaveTimer = window.setTimeout(function () {
          autosave.setAttribute("data-state", "saved");
          autosave.textContent = "Saved just now";
        }, 700);
      });
    }

    $$("[data-palette-cell]").forEach(function (cell) {
      cell.addEventListener("click", function () {
        showToast("Palette selection is visual in this single-question example.");
      });
    });

    var submit = $("#submit-test");
    if (submit) {
      submit.addEventListener("click", function (event) {
        event.preventDefault();
        updateSubmitCopy();
        openDialog("submit-dialog");
      });
    }

    updateSubmitCopy();
  }

  /* ---- state handling --------------------------------------------------- */

  function stateList() {
    return (document.body.getAttribute("data-states") || "default")
      .split(",")
      .map(function (value) {
        return value.trim();
      })
      .filter(Boolean);
  }

  function buildStateSelect() {
    var select = $("#review-state");
    var wrap = $(".review-strip-state");
    if (!select) return;
    var list = stateList();

    if (list.length <= 1) {
      if (wrap) wrap.hidden = true;
      return;
    }

    select.innerHTML = "";
    list.forEach(function (state) {
      var option = document.createElement("option");
      option.value = state;
      option.textContent =
        state === "default"
          ? document.body.getAttribute("data-default-label") || "Default"
          : STATE_LABELS[state] || state;
      select.appendChild(option);
    });

    select.addEventListener("change", function () {
      applyReviewState(select.value);
    });
  }

  function setDisabledGroup(selector, on) {
    $$(selector).forEach(function (element) {
      if (on) {
        if (!element.hasAttribute("data-was-disabled")) {
          element.setAttribute("data-was-disabled", element.disabled ? "1" : "0");
        }
        if ("disabled" in element) element.disabled = true;
        element.setAttribute("aria-disabled", "true");
        element.classList.add("is-disabled");
      } else {
        if (element.getAttribute("data-was-disabled") === "0") element.disabled = false;
        element.removeAttribute("aria-disabled");
        element.removeAttribute("data-was-disabled");
        element.classList.remove("is-disabled");
      }
    });
  }

  function updateBanners(state) {
    $$("[data-banner]").forEach(function (banner) {
      var states = (banner.getAttribute("data-banner") || "").split(/\s+/);
      banner.hidden = states.indexOf(state) === -1;
    });
  }

  function updateCredits(state) {
    $$("[data-credits]").forEach(function (chip) {
      if (!chip.hasAttribute("data-original")) {
        chip.setAttribute("data-original", chip.innerHTML);
      }
      if (state === "quota") {
        chip.innerHTML = '<span class="zn-credits-label">Voice</span> 0 / 30';
        chip.setAttribute("data-empty", "true");
      } else {
        chip.innerHTML = chip.getAttribute("data-original");
        chip.removeAttribute("data-empty");
      }
    });
  }

  function injectGenericState(state) {
    var screen = $("#screen-body");
    var injected = $("#state-injected");
    var templates = $("#state-templates");
    if (!screen || !injected || !templates) return;

    $$("[data-injected-error]").forEach(function (node) {
      node.remove();
    });

    screen.hidden = false;
    injected.hidden = true;
    injected.replaceChildren();

    var template = templates.querySelector(
      "template[data-state-template='" + state + "']"
    );

    if (state === "loading" || state === "empty" || state === "auth") {
      if (!template) return;
      injected.appendChild(template.content.cloneNode(true));
      injected.hidden = false;
      screen.hidden = true;
      return;
    }

    if (state === "error") {
      var slot = $("[data-error-slot]") || screen;
      var node;
      if (template) {
        node = document.createElement("div");
        node.setAttribute("data-injected-error", "");
        node.appendChild(template.content.cloneNode(true));
      } else {
        node = document.createElement("div");
        node.setAttribute("data-injected-error", "");
        node.innerHTML =
          '<div class="zn-error-box"><div class="zn-error-title">Could not load this section</div>' +
          '<p class="zn-error-copy">The rest of the page is still here. Try again, or go back to the dashboard.</p>' +
          '<div class="zn-error-actions"><button class="zn-btn zn-btn--secondary" type="button" data-retry>Retry</button></div></div>';
      }
      slot.prepend(node);
    }
  }

  function applyReviewState(state) {
    var list = stateList();
    if (list.indexOf(state) === -1) state = "default";
    currentState = state;
    document.documentElement.setAttribute("data-state", state);
    document.body.setAttribute("data-state", state);
    document.body.classList.toggle("zn-auth-state", state === "auth");

    updateBanners(state);
    updateCredits(state);
    setDisabledGroup("[data-needs-network]", state === "offline");
    setDisabledGroup("[data-needs-voice]", state === "quota");
    injectGenericState(state);

    var page = document.body.getAttribute("data-page");
    if (page === "speaking") setSpeakState(state === "default" ? "idle" : state);
    if (page === "test") setTestState(state);
    if (page === "lesson") {
      var untranslated = $("[data-banner='untranslated']");
      if (untranslated) untranslated.hidden = state !== "untranslated";
      var dockTab = $("[data-dock-tab]");
      if (dockTab) {
        if (state === "quota" || state === "offline") dockTab.hidden = true;
        else if (!consentGranted && !consentDeclined) dockTab.hidden = false;
      }
    }

    var select = $("#review-state");
    if (select && select.value !== state) select.value = state;

    var url = new URL(window.location.href);
    if (state === "default") url.searchParams.delete("state");
    else url.searchParams.set("state", state);
    window.history.replaceState(null, "", url);
  }

  function initState() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("embed") === "1") {
      document.body.setAttribute("data-embed", "1");
      $$("a[href]").forEach(function (link) {
        if (link.getAttribute("href").indexOf("#") !== 0) link.setAttribute("target", "_top");
      });
    }

    buildStateSelect();

    document.addEventListener("click", function (event) {
      var clear = event.target.closest("[data-clear-filters]");
      if (clear) {
        event.preventDefault();
        clearCatalogueFilters();
        return;
      }
      var retry = event.target.closest("[data-retry]");
      if (retry) {
        event.preventDefault();
        applyReviewState("default");
        showToast("Loaded the page again (design example).");
      }
    });

    var initial = params.get("state") || "default";
    applyReviewState(initial);
  }

  /* ---- states page: reduced-motion demo --------------------------------- */

  function initReducedMotionDemo() {
    var button = $("[data-reduce-demo]");
    if (!button) return;
    button.addEventListener("click", function () {
      var on = document.documentElement.classList.toggle("zn-reduce");
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.textContent = on ? "Reduced motion: on" : "Reduced motion: off";
    });
  }

  /* ---- dialogs that are demo-only actions ------------------------------- */

  function initDemoActions() {
    $$("[data-confirm-delete]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = button.closest("dialog");
        if (dialog) dialog.close();
        showToast("Design example: no account or data was deleted.");
      });
    });

    $$("[data-demo-action]").forEach(function (button) {
      button.addEventListener("click", function () {
        showToast(button.getAttribute("data-demo-action"));
      });
    });

    $$("[data-toggle-password]").forEach(function (button) {
      button.addEventListener("click", function () {
        var input = document.getElementById(button.getAttribute("data-toggle-password"));
        if (!input) return;
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        button.textContent = show ? "Hide" : "Show";
        button.setAttribute("aria-pressed", show ? "true" : "false");
      });
    });

    $$("[data-demo-mic]").forEach(function (button) {
      button.addEventListener("click", function () {
        var on = button.getAttribute("aria-pressed") === "true";
        button.setAttribute("aria-pressed", on ? "false" : "true");
      });
    });

    document.addEventListener("click", function (event) {
      var disabledLink = event.target.closest("a[aria-disabled='true']");
      if (disabledLink) {
        event.preventDefault();
        showToast("This action needs a connection. Nothing has been lost.");
      }
    });

    $$("[data-demo-palette]").forEach(function (palette) {
      $$("[data-palette-cell]", palette).forEach(function (cell) {
        cell.addEventListener("click", function () {
          $$("[data-palette-cell]", palette).forEach(function (other) {
            other.removeAttribute("aria-current");
          });
          cell.setAttribute("aria-current", "true");
        });
      });
    });
  }

  /* ---- boot ------------------------------------------------------------- */

  function initPaletteKeys() {
    $$(".zn-palette").forEach(function (palette) {
      var cells = $$("[data-palette-cell]", palette);
      cells.forEach(function (cell, index) {
        cell.addEventListener("keydown", function (event) {
          var next = null;
          if (event.key === "ArrowRight") next = cells[(index + 1) % cells.length];
          if (event.key === "ArrowLeft") next = cells[(index - 1 + cells.length) % cells.length];
          if (event.key === "ArrowDown") next = cells[Math.min(index + 5, cells.length - 1)];
          if (event.key === "ArrowUp") next = cells[Math.max(index - 5, 0)];
          if (event.key === "Home") next = cells[0];
          if (event.key === "End") next = cells[cells.length - 1];
          if (!next) return;
          event.preventDefault();
          next.focus();
        });
      });
    });
  }

  function boot() {
    initMenus();
    initDialogs();
    initTabs();
    initCatalogue();
    initSwitches();
    initSaves();
    initDemoToasts();
    initPen();
    initChecks();
    initHints();
    initLessonChrome();
    initConsent();
    initSpeaking();
    initTest();
    initPaletteKeys();
    initReducedMotionDemo();
    initDemoActions();
    initState();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.ZivonDemo = {
    showToast: showToast,
    applyState: applyReviewState,
    setSpeakingState: setSpeakState
  };
})();
