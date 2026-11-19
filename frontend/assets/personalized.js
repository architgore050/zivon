/*
 * Zivon personalized-learning session island + settings/hub helpers (PL4).
 *
 * Vanilla JS, no framework, no SPA, no build step. Three idempotent mounts:
 *  - [data-pl-session]      the session screen: the PL2 turn stream
 *                           (POST /v1/personalized/sessions/{id}/turns, SSE),
 *                           check submit, honest actions, offline/error/quota
 *                           states, report bridge;
 *  - [data-pl-start]        the hub: weakness counter + concept filtering;
 *  - [data-pl-instructions] the settings section: the 500-char counter and
 *                           the save-disabled rule (spec.md §1.3).
 *
 * Rules this file enforces:
 *  - the CSRF header comes from the server-rendered meta, never a stored token;
 *  - nothing from the network is ever rendered as HTML — DOM nodes +
 *    textContent only (the same rule as practice.js);
 *  - artifact URLs are only ever the server-issued `src` (data-and-api §4.8);
 *    this file constructs none;
 *  - one announcement per streaming turn ("Zivon is writing…" then the first
 *    line), never per token (spec.md §6.2);
 *  - a failed turn offers Retry with the SAME client_turn_id — the server
 *    replays or completes it idempotently (agent-and-rag.md §3.4);
 *  - reports reuse POST /v1/reports with the §4.11 categories
 *    (wrong_physics for a teaching card, broken_sim for an artifact).
 */
(function () {
  'use strict';

  var WEAKNESS_MAX = 500;
  var MESSAGE_MAX = 2000;

  var STAGE_LABELS = {
    diagnose: 'Checking what you know',
    teach: 'Teaching',
    check: 'Checking',
    adapt: 'Explaining another way',
    worked_example: 'Worked example',
    advance: 'Next concept',
    harder: 'Harder practice',
    board: 'Board-style practice',
    mastery: 'Mastery summary',
    done: 'Finished'
  };

  /* ---------------- shared helpers ---------------- */

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clearChildren(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }

  function announce(live, message) {
    if (live) live.textContent = message || '';
  }

  function quotaLine(container, payload) {
    if (!container) return;
    // The wire shape is the §3.2 `turn.done` payload ({remaining, reset_at});
    // the hub/session SSR strips and the assembled-JSON variant carry the
    // same number under the usage view's turns.remaining — accept all three.
    var remaining = null;
    if (payload && payload.turns && typeof payload.turns.remaining === 'number') {
      remaining = payload.turns.remaining;
    } else if (payload && typeof payload.remaining === 'number') {
      remaining = payload.remaining;
    } else if (payload && typeof payload.turns_remaining === 'number') {
      remaining = payload.turns_remaining;
    }
    var scope = payload && payload.scope;
    var enabled = !payload || payload.enabled !== false;
    var text;
    if (!enabled) text = 'Personalized learning is paused.';
    else if (scope === 'global') text = 'Zivon is at its daily limit.';
    else if (remaining === null) return;
    else if (remaining <= 0 || scope === 'user') text = "You've used today's turns.";
    else text = remaining + ' turns left today';
    container.textContent = text + ' \u00b7 resets 00:00 IST';
  }

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken()
      },
      body: JSON.stringify(body)
    }).catch(function () {
      /* reports are best-effort; a failed report never blocks a turn */
    });
  }

  /* ---------------- settings: instructions counter ---------------- */

  function mountInstructions(section) {
    if (section.getAttribute('data-pl-mounted')) return;
    section.setAttribute('data-pl-mounted', '1');
    var field = section.querySelector('[data-pl-instructions-field]');
    var counter = section.querySelector('[data-pl-instructions-count]');
    var save = section.querySelector('[data-pl-instructions-save]');
    if (!field || !save) return;
    var initial = field.value;

    function update() {
      var length = field.value.length;
      if (counter) counter.textContent = String(length);
      // Save is disabled while unchanged (spec.md §1.3); maxlength guards
      // the rest server-side, where validation is authoritative.
      save.disabled = field.value === initial || length > WEAKNESS_MAX;
    }

    field.addEventListener('input', update);
    update();
  }

  /* ---------------- hub: weakness counter + concept filter ---------------- */

  function mountStartForm(form) {
    if (form.getAttribute('data-pl-mounted')) return;
    form.setAttribute('data-pl-mounted', '1');
    var weakness = form.querySelector('[data-pl-weakness]');
    var counter = form.querySelector('[data-pl-weakness-count]');
    var chapterSelect = form.querySelector('[data-pl-chapter-select]');
    var conceptSelect = form.querySelector('[data-pl-concept-select]');

    if (weakness && counter) {
      weakness.addEventListener('input', function () {
        counter.textContent = String(weakness.value.length);
      });
    }

    if (chapterSelect && conceptSelect) {
      chapterSelect.addEventListener('change', function () {
        var chapterId = chapterSelect.value;
        clearChildren(conceptSelect);
        var placeholder = el('option', '', 'Any concept in the chapter');
        placeholder.value = '';
        conceptSelect.appendChild(placeholder);
        if (!chapterId) {
          conceptSelect.disabled = true;
          conceptSelect.selectedIndex = 0;
          return;
        }
        conceptSelect.disabled = false;
        var groups = conceptSelect.querySelectorAll('optgroup[data-pl-concepts-for]');
        for (var i = 0; i < groups.length; i += 1) {
          if (groups[i].getAttribute('data-pl-concepts-for') === chapterId) {
            var options = groups[i].querySelectorAll('option');
            for (var j = 0; j < options.length; j += 1) {
              conceptSelect.appendChild(options[j].cloneNode(true));
            }
            break;
          }
        }
        conceptSelect.selectedIndex = 0;
      });
    }
  }

  /* ---------------- session island ---------------- */

  function mountSession(root) {
    if (root.getAttribute('data-pl-mounted')) return;
    root.setAttribute('data-pl-mounted', '1');

    var sessionId = root.getAttribute('data-session-id') || '';
    var canSend = root.getAttribute('data-can-send') === 'true';
    var active = root.getAttribute('data-session-status') === 'active';
    var transcript = root.querySelector('[data-pl-transcript]');
    var live = root.querySelector('[data-pl-live]');
    var errorLine = root.querySelector('[data-pl-error]');
    var quotaEl = root.querySelector('[data-pl-quota]');
    var composer = root.querySelector('[data-pl-composer]');
    var messageInput = root.querySelector('[data-pl-message]');
    if (!sessionId || !transcript) return;

    var streaming = false;
    var teachCard = null;
    var teachText = '';
    var firstLineAnnounced = false;

    function showError(message) {
      if (!errorLine) return;
      errorLine.textContent = message;
      errorLine.hidden = false;
    }

    function clearError() {
      if (!errorLine) return;
      errorLine.textContent = '';
      errorLine.hidden = true;
    }

    function setComposerEnabled(enabled) {
      if (!composer) return;
      var buttons = composer.querySelectorAll('button');
      for (var i = 0; i < buttons.length; i += 1) buttons[i].disabled = !enabled;
      if (messageInput) messageInput.disabled = !enabled;
    }

    function openCheckCard() {
      return transcript.querySelector('[data-pl-check][data-check-answered="false"]');
    }

    function syncActions() {
      if (!active || !canSend) return;
      var checkOpen = !!openCheckCard();
      // Teach-side actions (explain directly, hint) need no open check —
      // the contract rejects them otherwise (turn_router prevalidation).
      if (composer) {
        var actionButtons = composer.querySelectorAll('[data-pl-action]');
        for (var i = 0; i < actionButtons.length; i += 1) {
          actionButtons[i].disabled = streaming || checkOpen;
          actionButtons[i].title = checkOpen
            ? 'Submit the open check first'
            : '';
        }
        var send = composer.querySelector('[data-pl-send]');
        if (send) send.disabled = streaming;
        if (messageInput) messageInput.disabled = streaming;
      }
      var card = openCheckCard();
      if (card) {
        var controls = card.querySelectorAll('[data-pl-answer], [data-pl-check-submit], [data-pl-not-sure]');
        for (var j = 0; j < controls.length; j += 1) controls[j].disabled = streaming;
      }
    }

    /* ---- card builders (DOM nodes only; all strings via textContent) ---- */

    function appendCard(node) {
      var li = el('li', 'pl-item pl-item--live');
      li.appendChild(node);
      transcript.appendChild(li);
      return li;
    }

    function buildCheckCard(payload) {
      var card = el('article', 'pl-card pl-card--check');
      card.setAttribute('data-pl-check', '1');
      card.setAttribute('data-check-id', payload.check_id || '');
      card.setAttribute('data-check-kind', payload.kind || 'mcq');
      card.setAttribute('data-check-answered', 'false');
      card.appendChild(el('p', 'pl-check-kicker', 'Check'));
      card.appendChild(el('p', 'pl-check-question', payload.question || ''));
      if (payload.kind === 'numeric') {
        var wrap = el('div', 'pl-numeric');
        var label = el('label', 'pl-option', 'Your answer');
        label.setAttribute('for', 'answer-' + (payload.check_id || ''));
        wrap.appendChild(label);
        var input = el('input', 'input pl-numeric-input');
        input.type = 'text';
        input.inputMode = 'decimal';
        input.id = 'answer-' + (payload.check_id || '');
        input.setAttribute('data-pl-answer', '1');
        wrap.appendChild(input);
        if (payload.unit) wrap.appendChild(el('span', 'pl-unit', payload.unit));
        card.appendChild(wrap);
      } else {
        var group = el('div', 'pl-options');
        group.setAttribute('role', 'radiogroup');
        group.setAttribute('aria-label', 'Answer options');
        var options = payload.options || [];
        for (var i = 0; i < options.length; i += 1) {
          var label2 = el('label', 'pl-option');
          var radio = el('input');
          radio.type = 'radio';
          radio.name = 'answer_' + (payload.check_id || '');
          radio.value = (options[i] && options[i].id) || '';
          radio.setAttribute('data-pl-answer', '1');
          label2.appendChild(radio);
          label2.appendChild(el('span', '', (options[i] && options[i].text) || ''));
          group.appendChild(label2);
        }
        card.appendChild(group);
      }
      var actions = el('div', 'pl-check-actions');
      var check = el('button', 'btn btn--sm', 'Check');
      check.type = 'button';
      check.setAttribute('data-pl-check-submit', '1');
      actions.appendChild(check);
      var notSure = el('button', 'btn btn--sm btn--outline', 'Not sure');
      notSure.type = 'button';
      notSure.setAttribute('data-pl-not-sure', '1');
      actions.appendChild(notSure);
      card.appendChild(actions);
      return card;
    }

    function applyFeedback(card, payload) {
      if (!card) return;
      var box = el(
        'div',
        'pl-feedback ' + (payload.correct ? 'pl-feedback--ok' : 'pl-feedback--no')
      );
      var head = payload.correct ? 'Correct.' : 'Not yet \u2014 let\u2019s look again.';
      if (payload.expected) head += ' Expected: ' + payload.expected + '.';
      box.appendChild(el('p', '', head));
      if (payload.explanation) box.appendChild(el('p', '', payload.explanation));
      if (payload.misconception) box.appendChild(el('p', '', payload.misconception));
      card.appendChild(box);
      var controls = card.querySelectorAll('[data-pl-answer], [data-pl-check-submit], [data-pl-not-sure]');
      for (var i = 0; i < controls.length; i += 1) controls[i].disabled = true;
      var actions = card.querySelector('.pl-check-actions');
      if (actions) actions.hidden = true;
      card.setAttribute('data-check-answered', 'true');
    }

    function buildArtifactCard(payload) {
      // The PL3 viewer markup as nodes; the src is server-issued only.
      var card = el('div', 'zn-art-viewer');
      card.setAttribute('data-artifact-viewer', '1');
      card.setAttribute('data-artifact-id', payload.artifact_id || '');
      card.setAttribute('data-artifact-kind', payload.kind || 'simulation');
      card.setAttribute('data-artifact-status', payload.status || 'pending');
      card.setAttribute('data-artifact-src', payload.src || '');
      card.setAttribute(
        'data-status-url',
        '/v1/personalized/artifacts/' + (payload.artifact_id || '') + '/status'
      );
      card.setAttribute('data-fallback-kind', 'text');
      var titleId = 'zn-art-title-' + (payload.artifact_id || 'live');
      card.setAttribute('aria-labelledby', titleId);
      var head = el('div', 'zn-art-viewer-head');
      var title = el('h3', 'zn-art-viewer-title', payload.title || 'Generated visual');
      title.id = titleId;
      head.appendChild(title);
      head.appendChild(el('span', 'zn-art-viewer-kind', payload.kind || 'simulation'));
      card.appendChild(head);
      card.appendChild(el('div', 'zn-art-viewer-frame'));
      card.appendChild(el('div', 'zn-art-viewer-fallback'));
      card.appendChild(el('p', 'zn-art-viewer-status', 'Building a visual…'));
      var actions = el('div', 'zn-art-viewer-actions');
      var labels = ['reload', 'pause', 'expand', 'report'];
      for (var i = 0; i < labels.length; i += 1) {
        var name = labels[i];
        var btn = el(
          'button',
          'zn-art-viewer-btn',
          name.charAt(0).toUpperCase() + name.slice(1)
        );
        btn.type = 'button';
        btn.setAttribute('data-art-action', name);
        actions.appendChild(btn);
      }
      card.appendChild(actions);
      card.appendChild(
        el('p', 'zn-art-viewer-meta', 'Runs isolated — no network, no access to your account.')
      );
      return card;
    }

    function buildErrorCard(code, retryable, clientTurnId) {
      var card = el('article', 'pl-card pl-card--error');
      var copy = {
        'E-PL-MODEL-DOWN': "Zivon can't think right now. Your transcript is safe.",
        'E-QUOTA-EXHAUSTED':
          "You've used today's turns. This session is saved; it resets at 00:00 IST.",
        'E-PL-TURN-OPEN': 'A check is open — submit it first.',
        'E-RATE-LIMIT': 'Too many turns in a minute. Wait a few seconds and retry.'
      }[code] || "That answer didn't come through. Nothing was lost.";
      card.appendChild(el('p', 'pl-honest-note', copy));
      if (retryable) {
        var retry = el('button', 'btn btn--sm btn--outline', 'Retry');
        retry.type = 'button';
        retry.setAttribute('data-pl-retry', clientTurnId || '');
        card.appendChild(retry);
      }
      return card;
    }

    /* ---- one handler for both transports (SSE stream and the assembled
       JSON turn object — agent-and-rag.md §3.2) ---- */

    function handleEvent(event, clientTurnId) {
      var payload = (event && event.payload) || {};
      if (event.name === 'turn.stage') {
        var chip = root.querySelector('[data-pl-stage]');
        if (chip && payload.stage && STAGE_LABELS[payload.stage]) {
          chip.textContent = STAGE_LABELS[payload.stage];
        }
      } else if (event.name === 'turn.teach.start') {
        announce(live, 'Zivon is writing\u2026');
        teachCard = el('article', 'pl-card pl-card--teach');
        teachCard.setAttribute('data-pl-streaming', '1');
        teachText = '';
        firstLineAnnounced = false;
        appendCard(teachCard);
      } else if (event.name === 'turn.teach.delta') {
        teachText += String(payload.text || '');
        if (teachCard) {
          clearChildren(teachCard);
          var paragraphs = teachText.split(/\n\s*\n/);
          for (var i = 0; i < paragraphs.length; i += 1) {
            if (paragraphs[i].trim()) {
              teachCard.appendChild(el('p', '', paragraphs[i].trim()));
            }
          }
        }
        // One first-line announcement per turn, never per token (§6.2).
        if (!firstLineAnnounced && teachText.length >= 60) {
          firstLineAnnounced = true;
          announce(live, teachText.slice(0, 80).trim());
        }
      } else if (event.name === 'turn.check') {
        finishStreamingCard();
        appendCard(buildCheckCard(payload));
      } else if (event.name === 'turn.feedback') {
        var openCard = openCheckCard();
        if (openCard) applyFeedback(openCard, payload);
        else {
          var loose = el('article', 'pl-card');
          applyFeedback(loose, payload);
          appendCard(loose);
        }
      } else if (event.name === 'turn.artifact') {
        appendCard(buildArtifactCard(payload));
        if (window.ZivonArtifactViewer) window.ZivonArtifactViewer.mount(transcript);
      } else if (event.name === 'turn.artifact.ready') {
        var viewer = transcript.querySelector(
          '[data-artifact-viewer][data-artifact-id="' + (payload.artifact_id || '') + '"]'
        );
        if (viewer) {
          viewer.setAttribute('data-artifact-status', 'ready');
          viewer.setAttribute('data-artifact-src', payload.src || '');
          var titleEl = viewer.querySelector('.zn-art-viewer-title');
          if (titleEl && payload.title) titleEl.textContent = payload.title;
          if (window.ZivonArtifactViewer) window.ZivonArtifactViewer.mount(root);
        }
      } else if (event.name === 'turn.next') {
        var stage = String(payload.stage || '');
        if (stage) {
          appendCard(
            el('p', 'pl-stage-line', 'Now: ' + (STAGE_LABELS[stage] || stage))
          );
        }
      } else if (event.name === 'turn.done') {
        finishStreamingCard();
        announce(live, 'Done.');
        quotaLine(quotaEl, payload.quota || {});
      } else if (event.name === 'turn.error') {
        if (teachCard && teachText) {
          var partialCard = el('article', 'pl-card pl-card--teach');
          partialCard.appendChild(el('p', '', teachText));
          partialCard.appendChild(
            el('p', 'pl-honest-note', 'Answer cut short. Nothing was lost; retry to finish it.')
          );
          teachCard.parentNode.replaceChild(partialCard, teachCard);
        }
        finishStreamingCard();
        appendCard(
          buildErrorCard(String(payload.code || ''), payload.retryable !== false, clientTurnId)
        );
        announce(live, 'Something went wrong; the card below says what to do.');
      }
      syncActions();
    }

    function finishStreamingCard() {
      if (teachCard) teachCard.removeAttribute('data-pl-streaming');
      teachCard = null;
    }

    /* ---- SSE parsing (event/data frames; one object per frame) ---- */

    function parseSseChunk(buffer) {
      var events = [];
      var frames = buffer.split('\n\n');
      var remainder = frames.pop() || '';
      for (var i = 0; i < frames.length; i += 1) {
        var lines = frames[i].split('\n');
        var name = '';
        var data = '';
        for (var j = 0; j < lines.length; j += 1) {
          var line = lines[j];
          if (line.indexOf('event:') === 0) name = line.slice(6).trim();
          else if (line.indexOf('data:') === 0) data += (data ? '\n' : '') + line.slice(5).trim();
        }
        if (name && data) {
          var payload = {};
          try {
            payload = JSON.parse(data);
          } catch (err) {
            payload = {};
          }
          events.push({ name: name, payload: payload });
        }
      }
      return { events: events, remainder: remainder };
    }

    function consumeStream(response, clientTurnId) {
      var reader = response.body && response.body.getReader ? response.body.getReader() : null;
      if (!reader) return consumeJsonTurn(clientTurnId);
      var decoder = new TextDecoder();
      var buffer = '';

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            if (buffer) {
              var tail = parseSseChunk(buffer + '\n\n');
              for (var t = 0; t < tail.events.length; t += 1) {
                handleEvent(tail.events[t], clientTurnId);
              }
            }
            return null;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var parsed = parseSseChunk(buffer);
          buffer = parsed.remainder;
          for (var i = 0; i < parsed.events.length; i += 1) {
            handleEvent(parsed.events[i], clientTurnId);
          }
          return pump();
        });
      }

      return pump();
    }

    // Text/event-stream without ReadableStream: the same contract, one body.
    function consumeJsonTurn(clientTurnId) {
      return fetch(
        '/v1/personalized/sessions/' + encodeURIComponent(sessionId) + '/turns',
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': csrfToken(),
            Accept: 'application/json'
          },
          body: JSON.stringify({ client_turn_id: clientTurnId, action: 'continue' })
        }
      )
        .then(function (response) {
          if (!response.ok) throw new Error('status ' + response.status);
          return response.json();
        })
        .then(function (body) {
          var events = (body && body.events) || [];
          for (var i = 0; i < events.length; i += 1) {
            handleEvent(
              { name: events[i].event, payload: events[i].payload || {} },
              clientTurnId
            );
          }
        });
    }

    function startTurn(action, extra, fixedClientTurnId) {
      if (streaming) return;
      var clientTurnId =
        fixedClientTurnId ||
        'c-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
      streaming = true;
      clearError();
      setComposerEnabled(false);
      syncActions();
      var body = { client_turn_id: clientTurnId, action: action };
      if (extra) {
        for (var key in extra) {
          if (Object.prototype.hasOwnProperty.call(extra, key)) body[key] = extra[key];
        }
      }

      function attempt(isRetry) {
        return fetch(
          '/v1/personalized/sessions/' + encodeURIComponent(sessionId) + '/turns',
          {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-Token': csrfToken()
            },
            body: JSON.stringify(body)
          }
        )
          .then(function (response) {
            if (response.status === 401 || response.status === 403) {
              // The session or its CSRF died between render and submit:
              // a reload lands the guard's 303 with `next` back here (PL-F9).
              window.location.reload();
              return null;
            }
            if (!response.ok) throw new Error('status ' + response.status);
            return consumeStream(response, clientTurnId);
          })
          .catch(function (err) {
            if (err && err.name === 'AbortError') return null;
            // One idempotent retry with the same client_turn_id; the server
            // replays the stored result instead of re-calling the model.
            if (!isRetry) {
              window.setTimeout(function () {
                attempt(true);
              }, 1500);
              return null;
            }
            appendCard(buildErrorCard('', true, clientTurnId));
            showError(
              navigator.onLine === false
                ? "You're offline. Reconnect to continue — nothing was lost."
                : "That answer didn't come through. Try again."
            );
            return null;
          })
          .then(function () {
            streaming = false;
            setComposerEnabled(true);
            syncActions();
          });
      }

      attempt(false);
    }

    /* ---- delegated actions ---- */

    root.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) return;

      var retryBtn = target.closest('[data-pl-retry]');
      if (retryBtn) {
        // Replaying the same id is safe (§3.4): the server returns the
        // stored result instead of a second model call.
        startTurn('continue', null, retryBtn.getAttribute('data-pl-retry'));
        return;
      }
      var actionBtn = target.closest('[data-pl-action]');
      if (actionBtn && !actionBtn.disabled) {
        startTurn(actionBtn.getAttribute('data-pl-action'));
        return;
      }
      var sendBtn = target.closest('[data-pl-send]');
      if (sendBtn && !sendBtn.disabled && messageInput && messageInput.value.trim()) {
        var text = messageInput.value.trim().slice(0, MESSAGE_MAX);
        startTurn('message', { text: text });
        messageInput.value = '';
        return;
      }
      var submitBtn = target.closest('[data-pl-check-submit]');
      if (submitBtn && !submitBtn.disabled) {
        submitAnswer(false);
        return;
      }
      var notSureBtn = target.closest('[data-pl-not-sure]');
      if (notSureBtn && !notSureBtn.disabled) {
        submitAnswer(true);
        return;
      }
      var reportBtn = target.closest('[data-pl-report]');
      if (reportBtn && !reportBtn.disabled) {
        postJson('/v1/reports', {
          category: reportBtn.getAttribute('data-report-category') || 'wrong_physics',
          course_id: root.getAttribute('data-report-course') || '',
          block_id: reportBtn.getAttribute('data-report-block') || null
        });
        reportBtn.textContent = 'Report noted.';
        reportBtn.disabled = true;
        return;
      }
      var earlierBtn = target.closest('[data-pl-load-earlier]');
      if (earlierBtn) loadEarlier(earlierBtn);
    });

    root.addEventListener('zivon-artifact:report', function (event) {
      var detail = event.detail || {};
      postJson('/v1/reports', {
        category: 'broken_sim',
        course_id: root.getAttribute('data-report-course') || '',
        block_id: detail.artifactId || null
      });
    });

    function submitAnswer(notSure) {
      var card = openCheckCard();
      if (!card || streaming) return;
      var checkId = card.getAttribute('data-check-id') || '';
      var kind = card.getAttribute('data-check-kind') || 'mcq';
      var answer;
      if (notSure) {
        answer = 'not sure';
      } else if (kind === 'numeric') {
        var input = card.querySelector('[data-pl-answer]');
        answer = input && input.value ? input.value.trim() : '';
        if (!answer) return;
      } else {
        var selected = card.querySelector('[data-pl-answer]:checked');
        answer = selected ? selected.value : '';
        if (!answer) return;
      }
      startTurn('answer', { check_id: checkId, answer: answer });
    }

    function loadEarlier(button) {
      var before = button.getAttribute('data-before') || '';
      button.disabled = true;
      fetch(
        '/v1/personalized/sessions/' + encodeURIComponent(sessionId) +
          '/messages?before=' + encodeURIComponent(before) + '&limit=50',
        { credentials: 'same-origin' }
      )
        .then(function (response) {
          if (!response.ok) throw new Error('status ' + response.status);
          return response.json();
        })
        .then(function (body) {
          var items = (body && body.items) || [];
          var firstChild = transcript.firstChild;
          for (var i = items.length - 1; i >= 0; i -= 1) {
            var message = items[i];
            var node;
            if (message.kind === 'text' && message.role === 'tutor') {
              node = el('article', 'pl-card pl-card--teach');
              node.appendChild(el('p', '', message.text || ''));
            } else if (message.kind === 'text' && message.role === 'student') {
              node = el('article', 'pl-card pl-card--student');
              node.appendChild(el('p', '', message.text || ''));
            } else if (message.kind === 'check_result') {
              var feedback = message.payload || {};
              node = el(
                'div',
                'pl-feedback ' + (feedback.correct ? 'pl-feedback--ok' : 'pl-feedback--no')
              );
              node.appendChild(
                el(
                  'p',
                  '',
                  (feedback.correct ? 'Correct.' : 'Not yet.') +
                    (feedback.expected ? ' Expected: ' + feedback.expected + '.' : '')
                )
              );
              if (feedback.explanation) node.appendChild(el('p', '', feedback.explanation));
            } else {
              node = el('p', 'pl-stage-line', 'Earlier turn');
            }
            var li = el('li', 'pl-item');
            li.appendChild(node);
            transcript.insertBefore(li, firstChild);
          }
          button.hidden = true; // one page back is the R1 scope (spec.md §2.7)
        })
        .catch(function () {
          button.disabled = false;
          showError('Earlier turns could not be loaded. They are still saved.');
        });
    }

    if (navigator.onLine === false) setComposerEnabled(false);
    window.addEventListener('offline', function () {
      setComposerEnabled(false);
      showError("You're offline. Reconnect to continue — the transcript stays readable.");
    });
    window.addEventListener('online', function () {
      clearError();
      setComposerEnabled(true);
      syncActions();
    });

    syncActions();
  }

  /* ---------------- mount (idempotent) ---------------- */

  function mount() {
    var nodes = document.querySelectorAll('[data-pl-session]');
    for (var i = 0; i < nodes.length; i += 1) mountSession(nodes[i]);
    nodes = document.querySelectorAll('[data-pl-start]');
    for (var j = 0; j < nodes.length; j += 1) mountStartForm(nodes[j]);
    nodes = document.querySelectorAll('[data-pl-instructions]');
    for (var k = 0; k < nodes.length; k += 1) mountInstructions(nodes[k]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  window.ZivonPersonalized = { mount: mount };
})();
