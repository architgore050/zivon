/* Zivon test player island (F7).
   Progressive enhancement over the server-rendered form: the clock is a
   display of the server-derived deadline, and answer changes autosave through
   the same-origin JSON endpoint with the session CSRF token. With JavaScript
   off, the form's Save answer / Mark for review buttons are the real path.

   No external host, no eval, no inline handlers. Every failure is announced in
   the save-status live region; nothing is silently dropped. */
(function () {
  "use strict";

  var THRESHOLDS = [600, 300, 60];

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function formatClock(seconds) {
    var safe = Math.max(0, Math.floor(seconds));
    var minutes = Math.floor(safe / 60);
    var rest = safe % 60;
    return (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function setSaveState(node, text, kind) {
    if (!node) {
      return;
    }
    node.textContent = text;
    node.classList.remove("tests-save--ok", "tests-save--error");
    if (kind === "ok") {
      node.classList.add("tests-save--ok");
    } else if (kind === "error") {
      node.classList.add("tests-save--error");
    }
  }

  function submitPaper(attemptId) {
    var form = document.createElement("form");
    form.method = "post";
    form.action = "/app/tests/" + encodeURIComponent(attemptId) + "/submit";
    form.hidden = true;
    var token = document.createElement("input");
    token.type = "hidden";
    token.name = "csrf_token";
    token.value = csrfToken();
    form.appendChild(token);
    document.body.appendChild(form);
    form.submit();
  }

  function initPlayer(root) {
    var attemptId = root.getAttribute("data-attempt-id") || "";
    var deadlineRaw = root.getAttribute("data-deadline") || "";
    var clock = root.querySelector("[data-tests-clock]");
    var announce = root.querySelector("[data-tests-clock-announce]");
    var saveState = root.querySelector("[data-tests-save]");
    var form = root.querySelector("[data-tests-form]");
    if (!attemptId || !clock || !form) {
      return;
    }
    var deadline = deadlineRaw ? new Date(deadlineRaw).getTime() : NaN;
    var expired = root.getAttribute("data-expired") === "1";
    var announceAt = THRESHOLDS.slice();
    var firstTick = true;
    var saving = false;
    var pending = false;
    var pendingSubmit = false;
    var startedAt = Date.now();
    var questionInput = form.querySelector('input[name="question_id"]');
    var questionId = questionInput ? questionInput.value : "";
    var timeInput = form.querySelector("[data-tests-time]");
    var flagInput = form.querySelector("[data-tests-flag]");
    var radioInputs = form.querySelectorAll('input[name="answer_index"]');
    var numericInput = form.querySelector('input[name="answer_value"]');
    var debounce = null;

    function elapsedMs() {
      return Math.max(0, Math.min(3600000, Date.now() - startedAt));
    }

    function markExpired() {
      expired = true;
      root.setAttribute("data-expired", "1");
      setSaveState(saveState, "Time is up — submitting the paper", "error");
      if (announce) {
        announce.textContent = "Time is up. The paper is being submitted.";
      }
      if (saving) {
        pendingSubmit = true;
        return;
      }
      submitPaper(attemptId);
    }

    function tick() {
      if (isNaN(deadline)) {
        return;
      }
      var remaining = Math.ceil((deadline - Date.now()) / 1000);
      clock.textContent = formatClock(remaining);
      if (firstTick) {
        announceAt = announceAt.filter(function (seconds) {
          return remaining < seconds;
        });
        firstTick = false;
      }
      if (remaining <= 0 && !expired) {
        markExpired();
        return;
      }
      if (remaining > 0) {
        while (announceAt.length && remaining <= announceAt[0]) {
          var seconds = announceAt.shift();
          if (announce) {
            announce.textContent =
              seconds >= 60
                ? Math.round(seconds / 60) + " minutes left."
                : "One minute left.";
          }
        }
      }
    }

    function payloadFor(answer) {
      var body = {
        question_id: questionId,
        time_ms: elapsedMs()
      };
      if (flagInput) {
        body.flagged = flagInput.checked;
      }
      if (answer) {
        body.answer = answer;
      }
      return body;
    }

    function save(answer) {
      if (expired) {
        return;
      }
      if (saving) {
        pending = true;
        return;
      }
      saving = true;
      setSaveState(saveState, "Saving…", null);
      var token = csrfToken();
      fetch("/v1/tests/attempts/" + encodeURIComponent(attemptId) + "/answers", {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": token
        },
        body: JSON.stringify(payloadFor(answer))
      })
        .then(function (response) {
          if (response.status === 409) {
            markExpired();
            return null;
          }
          if (!response.ok) {
            throw new Error("save failed");
          }
          return response.json();
        })
        .then(function (payload) {
          if (payload) {
            setSaveState(saveState, "Saved", "ok");
            if (timeInput) {
              timeInput.value = String(elapsedMs());
            }
          }
        })
        .catch(function () {
          setSaveState(saveState, "Not saved — press Save answer", "error");
        })
        .then(function () {
          saving = false;
          if (pendingSubmit) {
            pendingSubmit = false;
            submitPaper(attemptId);
            return;
          }
          if (pending) {
            pending = false;
            save(selectedAnswer());
          }
        });
    }

    function selectedAnswer() {
      for (var index = 0; index < radioInputs.length; index += 1) {
        if (radioInputs[index].checked) {
          return { index: Number(radioInputs[index].value) };
        }
      }
      if (numericInput) {
        var raw = numericInput.value.trim();
        if (raw === "") {
          return null;
        }
        var value = Number(raw);
        if (!isFinite(value)) {
          return null;
        }
        return { value: value };
      }
      return null;
    }

    for (var index = 0; index < radioInputs.length; index += 1) {
      radioInputs[index].addEventListener("change", function () {
        save(selectedAnswer());
      });
    }

    if (numericInput) {
      numericInput.addEventListener("input", function () {
        if (debounce) {
          window.clearTimeout(debounce);
        }
        debounce = window.setTimeout(function () {
          save(selectedAnswer());
        }, 900);
      });
      numericInput.addEventListener("change", function () {
        if (debounce) {
          window.clearTimeout(debounce);
        }
        save(selectedAnswer());
      });
    }

    if (flagInput) {
      flagInput.addEventListener("change", function () {
        save(selectedAnswer());
      });
    }

    form.addEventListener("submit", function () {
      if (expired) {
        return;
      }
      setSaveState(saveState, "Saving…", null);
    });

    tick();
    window.setInterval(tick, 1000);
    setSaveState(saveState, "Saved answers are kept across reloads", "ok");
  }

  function init() {
    var players = document.querySelectorAll("[data-tests-player]");
    for (var index = 0; index < players.length; index += 1) {
      initPlayer(players[index]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
