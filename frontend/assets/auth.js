/* ==========================================================================
   Zivon auth/settings island (F2)
   --------------------------------------------------------------------------
   Two enhancements only; the pages are complete without this file.

   1. Password reveal: adds a "Show"/"Hide" button beside every password field
      of a server-rendered form. The button ships only when JS runs, so the
      no-JS page never shows a dead control.
   2. Onboarding goal: the account schema has no goal column yet, so the
      optional goal is stored on this device (`zivon.goal`) and prefilled on a
      return visit. The screen says so; nothing is sent to the server.

   Same-origin only, no network calls, idempotent, no-op when its markup is
   absent. CSP allows this file through `<script src>`.
   ========================================================================== */
(function () {
  "use strict";

  var GOAL_KEY = "zivon.goal";

  function bindPasswordReveal() {
    var inputs = document.querySelectorAll(
      "form.auth-form input[type='password']"
    );
    Array.prototype.forEach.call(inputs, function (input) {
      if (input.dataset.revealBound === "1") return;
      input.dataset.revealBound = "1";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "auth-reveal";
      button.textContent = "Show password";
      button.setAttribute("aria-pressed", "false");
      button.setAttribute(
        "aria-label",
        "Show the password for " + labelFor(input)
      );
      button.addEventListener("click", function () {
        var showing = input.type === "text";
        input.type = showing ? "password" : "text";
        button.setAttribute("aria-pressed", showing ? "false" : "true");
        button.textContent = showing ? "Show password" : "Hide password";
        button.setAttribute(
          "aria-label",
          (showing ? "Show" : "Hide") + " the password for " + labelFor(input)
        );
      });
      input.insertAdjacentElement("afterend", button);
    });
  }

  function labelFor(input) {
    var label = input.id
      ? document.querySelector("label[for='" + input.id + "']")
      : null;
    return (label && label.textContent.trim()) || "this field";
  }

  function readGoal() {
    try {
      return window.localStorage.getItem(GOAL_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function writeGoal(value) {
    try {
      if (value) {
        window.localStorage.setItem(GOAL_KEY, value);
      } else {
        window.localStorage.removeItem(GOAL_KEY);
      }
    } catch (error) {
      /* Private mode: the goal simply is not kept. The field still submits. */
    }
  }

  function bindGoal() {
    var form = document.querySelector("[data-onboarding-form]");
    if (!form) return;
    var input = form.querySelector("input[name='goal']");
    if (!input || input.dataset.goalBound === "1") return;
    input.dataset.goalBound = "1";
    if (!input.value) {
      var saved = readGoal();
      if (saved) input.value = saved;
    }
    form.addEventListener("submit", function () {
      writeGoal(input.value.trim());
    });
  }

  function mount() {
    bindPasswordReveal();
    bindGoal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
