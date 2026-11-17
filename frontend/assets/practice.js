/* Zivon practice player (F5): inline answer check over the same-origin API.

   The server form is the real path: without JavaScript, Check posts to
   `/app/practice/{id}/answer` and the server renders the feedback. This island
   upgrades that same form to an inline check against
   `POST /v1/practice/sessions/{id}/answers` — one endpoint, one server-side
   grader, no answer key in the page before the student commits.

   It never sends free text, never stores anything, and never talks to a
   third-party host. Feedback is built with DOM nodes and `textContent`, so the
   server's explanation cannot become markup. */
(function () {
  "use strict";

  var root = document.querySelector("[data-practice-player]");
  if (!root) return;

  var form = root.querySelector("[data-practice-form]");
  if (!form) return;

  var sessionId = root.getAttribute("data-session-id") || "";
  var answerUrl =
    "/v1/practice/sessions/" + encodeURIComponent(sessionId) + "/answers";
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.getAttribute("content") || "" : "";
  var feedbackBox = root.querySelector("[data-feedback]");
  var nextWrap = root.querySelector("[data-next-wrap]");
  var nextLink = root.querySelector("[data-next-link]");
  var finishForm = root.querySelector("[data-finish-form]");
  var checkButton = form.querySelector("[data-check]");
  var hintToggle = root.querySelector("[data-hint-toggle]");
  var hintPanel = root.querySelector("[data-hint-panel]");
  var hintsField = form.querySelector("[data-hints-used]");
  var timeField = form.querySelector("[data-time-ms]");
  var lessonUrl = root.getAttribute("data-lesson-url") || "";
  var startedAt = Date.now();
  var sending = false;

  if (!sessionId || !feedbackBox) return;

  function optionTexts() {
    var texts = [];
    var inputs = form.querySelectorAll('input[name="answer_index"]');
    for (var i = 0; i < inputs.length; i += 1) {
      var label = inputs[i].closest(".practice-option");
      var span = label ? label.querySelector(".practice-option-text") : null;
      texts.push(span ? span.textContent.trim() : "");
    }
    return texts;
  }

  function formatNumber(value) {
    var number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return String(Number(number.toPrecision(12)));
  }

  function clearChildren(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function paragraph(text, className) {
    var p = document.createElement("p");
    if (className) p.className = className;
    p.textContent = text;
    return p;
  }

  function errorNode() {
    var node = root.querySelector("[data-answer-error]");
    if (node) return node;
    node = document.createElement("div");
    node.className = "notice notice--error";
    node.setAttribute("role", "alert");
    node.setAttribute("tabindex", "-1");
    node.setAttribute("data-answer-error", "");
    feedbackBox.parentNode.insertBefore(node, feedbackBox);
    return node;
  }

  function showError(message) {
    var node = errorNode();
    clearChildren(node);
    node.appendChild(paragraph(message));
    node.hidden = false;
    node.focus && node.focus();
  }

  function hideError() {
    var node = root.querySelector("[data-answer-error]");
    if (node) {
      node.hidden = true;
      clearChildren(node);
    }
  }

  function disableForm(disabled) {
    var inputs = form.querySelectorAll("input, button");
    for (var i = 0; i < inputs.length; i += 1) {
      inputs[i].disabled = disabled;
    }
  }

  function readAnswer() {
    var kind = (form.querySelector('[name="answer_kind"]') || {}).value || "";
    if (kind === "value") {
      var field = form.querySelector('[name="answer_value"]');
      var raw = field ? String(field.value || "").trim() : "";
      if (!raw) return { error: "Enter a number like 15 or 0.5 before checking." };
      var value = Number(raw);
      if (!Number.isFinite(value)) {
        return { error: "Enter a number like 15 or 0.5 before checking." };
      }
      return { answer: { value: value } };
    }
    var checked = form.querySelector('input[name="answer_index"]:checked');
    if (!checked) return { error: "Choose one option before checking." };
    return { answer: { index: Number(checked.value) } };
  }

  function renderFeedback(payload) {
    var feedback = payload.feedback || {};
    var texts = optionTexts();
    var answer = feedback.answer || {};
    var chosen = (payload.attempt && payload.attempt.answer) || {};
    var answerText = "";
    var chosenText = "";
    if (typeof answer.index === "number" && texts[answer.index]) {
      answerText = texts[answer.index];
    } else if (answer.value !== undefined && answer.value !== null) {
      answerText = formatNumber(answer.value);
      if (feedback.unit) answerText += " " + feedback.unit;
    }
    if (typeof chosen.index === "number" && texts[chosen.index]) {
      chosenText = texts[chosen.index];
    } else if (chosen.value !== undefined && chosen.value !== null) {
      chosenText = formatNumber(chosen.value);
    }

    clearChildren(feedbackBox);
    var inner = document.createElement("div");
    inner.className =
      "practice-feedback-inner practice-feedback--" +
      (feedback.correct ? "correct" : "wrong");

    var verdict = document.createElement("p");
    verdict.className = "practice-verdict";
    var strong = document.createElement("strong");
    strong.textContent = feedback.correct ? "Correct." : "Not quite.";
    verdict.appendChild(strong);
    if (answerText) {
      verdict.appendChild(
        document.createTextNode(" The answer is " + answerText + ".")
      );
    }
    inner.appendChild(verdict);

    if (chosenText && !feedback.correct) {
      inner.appendChild(paragraph("You chose: " + chosenText + ".", "meta"));
    }
    if (feedback.misconception) {
      inner.appendChild(paragraph("Common mix-up: " + feedback.misconception, "meta"));
    }
    if (feedback.explanation) {
      var details = document.createElement("details");
      details.className = "why";
      details.open = true;
      var summary = document.createElement("summary");
      summary.textContent = "Why?";
      details.appendChild(summary);
      var answerBox = document.createElement("div");
      answerBox.className = "answer";
      answerBox.appendChild(paragraph(feedback.explanation));
      details.appendChild(answerBox);
      inner.appendChild(details);
    }
    var tutor = document.createElement("p");
    tutor.className = "practice-tutor";
    if (lessonUrl) {
      tutor.appendChild(document.createTextNode("Still unsure? "));
      var link = document.createElement("a");
      link.href = lessonUrl;
      link.textContent = "Ask the tutor on this chapter";
      tutor.appendChild(link);
      tutor.appendChild(
        document.createTextNode(" — the voice dock lives on the lesson page.")
      );
    } else {
      tutor.textContent =
        "Still unsure? This chapter's lesson is not published yet, so the voice tutor cannot open from here.";
    }
    inner.appendChild(tutor);
    feedbackBox.appendChild(inner);

    var answered = Number(payload.answered_count || 0);
    var count = Number(payload.question_count || 0);
    var progress = root.querySelector(".practice-progress");
    if (progress) {
      progress.value = answered;
      progress.textContent = answered + " of " + count;
    }
    var status = root.querySelector(".practice-status .meta");
    if (status) status.textContent = answered + " of " + count + " answered";

    if (nextWrap) nextWrap.hidden = false;
    var complete = Boolean(payload.complete_available);
    if (nextLink) nextLink.hidden = complete || payload.next_index === null;
    if (finishForm) finishForm.hidden = !complete;
    addRetryButton();
    disableForm(true);
    feedbackBox.focus();
  }

  function addRetryButton() {
    if (!nextWrap || nextWrap.querySelector("[data-retry]")) return;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--quiet";
    button.setAttribute("data-retry", "");
    button.textContent = "Try this one again";
    button.addEventListener("click", retry);
    nextWrap.appendChild(button);
  }

  function retry() {
    clearChildren(feedbackBox);
    hideError();
    if (nextWrap) nextWrap.hidden = true;
    if (nextLink) nextLink.hidden = true;
    if (finishForm) finishForm.hidden = true;
    disableForm(false);
    if (checkButton) checkButton.disabled = false;
    startedAt = Date.now();
    var first = form.querySelector('input[name="answer_index"]');
    var value = form.querySelector('input[name="answer_value"]');
    if (first) first.focus();
    else if (value) value.focus();
  }

  function submitAnswer(answer) {
    if (sending || !csrf) {
      showError(
        "This page cannot check the answer right now. Reload the page and sign in again."
      );
      return;
    }
    sending = true;
    hideError();
    if (checkButton) checkButton.disabled = true;
    form.setAttribute("aria-busy", "true");
    if (timeField) timeField.value = String(Math.min(Date.now() - startedAt, 3600000));

    fetch(answerUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf
      },
      body: JSON.stringify({
        question_id: (form.querySelector('[name="question_id"]') || {}).value || "",
        answer: answer,
        time_ms: Number(timeField ? timeField.value : 0),
        hints_used: Number(hintsField ? hintsField.value : 0)
      })
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return {};
          })
          .then(function (payload) {
            return { response: response, payload: payload };
          });
      })
      .then(function (result) {
        var response = result.response;
        var payload = result.payload || {};
        if (response.ok) {
          renderFeedback(payload);
          return;
        }
        if (response.status === 409) {
          showError("This set is already finished. Open its summary from the practice page.");
          return;
        }
        if (response.status === 403) {
          showError("This page expired. Reload it and try again.");
          return;
        }
        if (response.status === 429) {
          showError("Too many checks from this connection. Wait a minute and try again.");
          return;
        }
        if (response.status === 422) {
          showError("That answer could not be read. Check the number or choice and try again.");
          return;
        }
        showError("Could not check that just now — your answer was not saved. Try again.");
      })
      .catch(function () {
        showError(
          "Could not reach the server — your answer was not saved. Check your connection and try again."
        );
      })
      .then(function () {
        sending = false;
        form.removeAttribute("aria-busy");
        if (checkButton && (!nextWrap || nextWrap.hidden)) {
          checkButton.disabled = false;
        }
      });
  }

  form.addEventListener("submit", function (event) {
    if (!window.fetch) return; // let the server form handle it
    event.preventDefault();
    var read = readAnswer();
    if (read.error) {
      showError(read.error);
      return;
    }
    submitAnswer(read.answer);
  });

  if (hintToggle && hintPanel) {
    hintToggle.addEventListener("click", function () {
      var open = hintToggle.getAttribute("aria-expanded") === "true";
      hintToggle.setAttribute("aria-expanded", open ? "false" : "true");
      hintPanel.hidden = open;
      if (!open && hintsField) hintsField.value = "1";
      if (!open) hintPanel.focus && hintPanel.focus();
    });
  }
})();
