/*
 * Zivon personalized-learning artifact viewer — the host-side sandbox bridge
 * (PL3, interactive-artifacts.md §5.4/§6; spec.md §4).
 *
 * The artifact document is untrusted generated code. This bridge enforces:
 *  - the iframe contract: sandbox="allow-scripts" ONLY (opaque origin — never
 *    allow-same-origin), allow="" (every permissions-policy feature off),
 *    referrerpolicy="no-referrer", loading="lazy";
 *  - the harness channel: a message is accepted only when
 *    event.source === iframe.contentWindow AND it matches
 *    {source:"zivon-artifact", v:1, type:"ready"|"state"|"fps"|"error"};
 *    nothing from a message is ever rendered as HTML (textContent only);
 *  - the watchdog: no `ready` within 10 s, 60 s of runtime, a SECOND load
 *    event, or a `ready` with a foreign event.source unloads the iframe and
 *    shows the fallback (self-navigation containment, §5.4);
 *  - pause when off-screen (IntersectionObserver → host `pause` message) and
 *    on prefers-reduced-motion (static first frame + Play, §8);
 *  - the viewer src is the server-issued one (data-artifact-src); the client
 *    never constructs artifact URLs (§4.8).
 *
 * Report is dispatched as a DOM event for the session page JS (PL4) to POST
 * /v1/reports (category "broken_sim", course_id "personalized/<chapter_id>",
 * block_id <artifact_id> — data-and-api.md §4.11). No framework, no SPA.
 *
 * Mount: window.ZivonArtifactViewer.mount(document) — idempotent
 * (data-zn-art-mounted). PL4 includes /templates partials/artifact_viewer.html
 * and loads this file with <script src="/assets/personalized-artifact.js" defer>.
 */
(function () {
  'use strict';

  var READY_TIMEOUT_MS = 10000;
  var MAX_RUNTIME_MS = 60000;
  var POLL_INTERVAL_MS = 2000;
  var POLL_MAX_MS = 90000;
  var STATE_THROTTLE_MS = 250;

  function forEachViewer(root, fn) {
    var nodes = root.querySelectorAll('[data-artifact-viewer]');
    for (var i = 0; i < nodes.length; i += 1) {
      if (!nodes[i].getAttribute('data-zn-art-mounted')) {
        nodes[i].setAttribute('data-zn-art-mounted', '1');
        fn(nodes[i]);
      }
    }
  }

  function text(el, value) {
    if (el) {
      el.textContent = value;
    }
  }

  function createViewer(root) {
    var state = {
      root: root,
      id: root.getAttribute('data-artifact-id') || '',
      kind: root.getAttribute('data-artifact-kind') || 'simulation',
      src: root.getAttribute('data-artifact-src') || '',
      statusUrl: root.getAttribute('data-status-url') || '',
      chapterId: root.getAttribute('data-chapter-id') || '',
      fallbackKind: root.getAttribute('data-fallback-kind') || 'text',
      frameBox: root.querySelector('[data-art-frame]'),
      fallbackBox: root.querySelector('[data-art-fallback]'),
      fallbackBody: root.querySelector('[data-art-fallback-body]'),
      fallbackNote: root.querySelector('[data-art-fallback-note]'),
      statusEl: root.querySelector('[data-art-status]'),
      iframe: null,
      readyAt: 0,
      startedAt: 0,
      lastStateAt: 0,
      loadCount: 0,
      watchdogTimer: null,
      pollTimer: null,
      observer: null,
      paused: false,
      dead: false
    };
    root._znArtState = state; // test/PL4 hook

    bindActions(state);

    if (state.src) {
      loadFrame(state);
    } else if (state.statusUrl) {
      text(state.statusEl, 'Building a visual…');
      pollStatus(state);
    } else {
      showFallback(state, 'The visual didn\u2019t build. Here\u2019s the diagram instead.');
    }
  }

  function bindActions(state) {
    // One delegated handler: the buttons never double-fire.
    state.root.addEventListener('click', function (event) {
      var btn = event.target.closest ? event.target.closest('[data-art-action]') : null;
      if (btn) {
        act(state, btn.getAttribute('data-art-action'));
      }
    });
  }

  function act(state, action) {
    if (action === 'reload') {
      if (!state.dead && state.src) {
        unloadFrame(state);
        loadFrame(state);
      } else if (state.statusUrl) {
        pollStatus(state);
      }
      return;
    }
    if (action === 'pause') {
      state.paused = !state.paused;
      postToFrame(state, { source: 'zivon-host', type: state.paused ? 'pause' : 'resume' });
      var btn = state.root.querySelector('[data-art-action="pause"]');
      if (btn) {
        btn.textContent = state.paused ? 'Play' : 'Pause';
        btn.setAttribute('aria-pressed', state.paused ? 'true' : 'false');
      }
      return;
    }
    if (action === 'expand') {
      var expanded = state.root.classList.toggle('zn-art-viewer--expanded');
      state.root.setAttribute('data-expanded', expanded ? 'true' : 'false');
      return;
    }
    if (action === 'report') {
      state.root.dispatchEvent(
        new CustomEvent('zivon-artifact:report', {
          bubbles: true,
          detail: { artifactId: state.id, chapterId: state.chapterId }
        })
      );
      text(state.statusEl, 'Thanks — the report was noted.');
    }
  }

  /* ---- iframe lifecycle ---- */

  function loadFrame(state) {
    if (!state.src) {
      showFallback(state, 'The visual didn\u2019t build. Here\u2019s the diagram instead.');
      return;
    }
    state.dead = false;
    state.startedAt = Date.now();
    state.readyAt = 0;
    state.loadCount = 0;
    text(state.statusEl, 'Loading the visual…');

    var iframe = document.createElement('iframe');
    iframe.setAttribute('sandbox', 'allow-scripts'); // opaque origin — never allow-same-origin
    iframe.setAttribute('allow', '');
    iframe.setAttribute('referrerpolicy', 'no-referrer');
    iframe.setAttribute('loading', 'lazy');
    iframe.setAttribute('title', state.title || iframeTitle(state));
    iframe.style.width = '100%';
    iframe.style.aspectRatio = '3 / 2';
    iframe.style.border = '0';
    iframe.src = state.src; // server-issued; never constructed client-side

    iframe.addEventListener('load', function () {
      state.loadCount += 1;
      // §5.4: the host treats a SECOND load event as a crash — a sandboxed
      // frame may navigate itself, and attacker content must never replace
      // the artifact inside the trusted card.
      if (state.loadCount > 1) {
        crashToFallback(state, 'The visual replaced itself.');
      }
    });

    state.readyMs = parseInt(state.root.getAttribute('data-watchdog-ms'), 10) || READY_TIMEOUT_MS;
    state.iframe = iframe;
    while (state.frameBox.firstChild) {
      state.frameBox.removeChild(state.frameBox.firstChild);
    }
    state.frameBox.appendChild(iframe);
    state.frameBox.hidden = false;
    state.fallbackBox.hidden = true;

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // §8: reduced motion renders a static first frame; start paused.
      state.paused = true;
      var pauseBtn = state.root.querySelector('[data-art-action="pause"]');
      if (pauseBtn) {
        pauseBtn.textContent = 'Play';
        pauseBtn.setAttribute('aria-pressed', 'true');
      }
      setTimeout(function () {
        postToFrame(state, { source: 'zivon-host', type: 'pause' });
      }, 50);
    }
    watchOffscreen(state);
    armWatchdog(state);
    listenForHarness(state);
  }

  function iframeTitle(state) {
    var heading = state.root.querySelector('.zn-art-viewer-title');
    return (heading && heading.textContent ? heading.textContent : 'Generated visual') + ' (isolated preview)';
  }

  function unloadFrame(state) {
    if (state.watchdogTimer) {
      clearTimeout(state.watchdogTimer);
      state.watchdogTimer = null;
    }
    if (state.iframe) {
      var dead = state.iframe;
      dead.src = 'about:blank';
      if (dead.parentNode) {
        dead.parentNode.removeChild(dead);
      }
      state.iframe = null;
    }
  }

  function armWatchdog(state) {
    if (state.watchdogTimer) {
      clearTimeout(state.watchdogTimer);
    }
    state.watchdogTimer = setTimeout(function () {
      if (!state.readyAt) {
        crashToFallback(state, 'The visual didn\u2019t load.');
      } else if (Date.now() - state.startedAt > MAX_RUNTIME_MS) {
        crashToFallback(state, 'The visual ran too long and was stopped.');
      }
    }, state.readyMs || READY_TIMEOUT_MS);
    // Hard runtime wall: 60 s after start the frame is unloaded (§5.4).
    setTimeout(function () {
      if (state.iframe && Date.now() - state.startedAt > MAX_RUNTIME_MS) {
        crashToFallback(state, 'The visual ran too long and was stopped.');
      }
    }, MAX_RUNTIME_MS + 1000);
  }

  function listenForHarness(state) {
    if (state._harnessListener) {
      window.removeEventListener('message', state._harnessListener);
    }
    var listener = function (event) {
      if (!state.iframe || event.source !== state.iframe.contentWindow) {
        return; // foreign window: never trusted
      }
      var msg = event.data;
      if (
        !msg ||
        typeof msg !== 'object' ||
        msg.source !== 'zivon-artifact' ||
        msg.v !== 1
      ) {
        return;
      }
      if (msg.type === 'ready') {
        if (state.readyAt) {
          // A second `ready` from the same frame is the self-navigation tell.
          return crashToFallback(state, 'The visual replaced itself.');
        }
        state.readyAt = Date.now();
        if (state.watchdogTimer) {
          clearTimeout(state.watchdogTimer);
          state.watchdogTimer = null;
        }
        text(state.statusEl, '');
      } else if (msg.type === 'state') {
        var now = Date.now();
        if (now - state.lastStateAt >= STATE_THROTTLE_MS) {
          state.lastStateAt = now;
          // Never rendered as HTML — textContent only (§4).
          text(state.statusEl, String(msg.summary || '').slice(0, 200));
        }
      } else if (msg.type === 'error') {
        crashToFallback(state, 'The visual didn\u2019t load.');
      }
      // `fps` samples are telemetry only; the host does not act on them.
    };
    state._harnessListener = listener;
    window.addEventListener('message', listener);
  }

  function watchOffscreen(state) {
    if (state.observer) {
      state.observer.disconnect();
    }
    if (typeof IntersectionObserver !== 'function') {
      return;
    }
    state.observer = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i += 1) {
        postToFrame(state, {
          source: 'zivon-host',
          type: entries[i].isIntersecting ? 'resume' : 'pause'
        });
      }
    });
    state.observer.observe(state.root);
  }

  function postToFrame(state, msg) {
    if (state.iframe && state.iframe.contentWindow) {
      // The frame is opaque-origin, so no target origin can be named.
      state.iframe.contentWindow.postMessage(msg, '*');
    }
  }

  /* ---- fallback / crash / polling ---- */

  function showFallback(state, note) {
    text(
      state.fallbackNote,
      note || 'The visual didn\u2019t build. Here\u2019s the diagram instead.'
    );
    if (state.fallbackBody && !state.fallbackBody.firstChild) {
      // No server-rendered diagram in the card: the honest text fallback.
      // (The session serializer renders the validated fallback SVG inside
      // data-art-fallback-body when the decide payload carried one.)
      var p = document.createElement('p');
      text(p, 'Ask the tutor to explain with text or a diagram.');
      state.fallbackBody.appendChild(p);
    }
    state.frameBox.hidden = true;
    state.fallbackBox.hidden = false;
  }

  function crashToFallback(state, note) {
    state.dead = true;
    unloadFrame(state);
    showFallback(state, note);
    text(state.statusEl, '');
  }

  function pollStatus(state) {
    var deadline = Date.now() + POLL_MAX_MS;
    var tick = function () {
      fetch(state.statusUrl, { credentials: 'same-origin' })
        .then(function (res) {
          if (!res.ok) {
            throw new Error('status ' + res.status);
          }
          return res.json();
        })
        .then(function (body) {
          if (body.status === 'ready' && body.src) {
            state.src = body.src; // server-issued URL from the status payload
            loadFrame(state);
          } else if (body.status === 'failed') {
            showFallback(state, 'The visual didn\u2019t build. Here\u2019s the diagram instead.');
            text(state.statusEl, '');
          } else if (Date.now() < deadline) {
            state.pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
          } else {
            crashToFallback(state, 'The visual is taking too long. Try Reload.');
          }
        })
        .catch(function () {
          if (Date.now() < deadline) {
            state.pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
          } else {
            crashToFallback(state, 'The visual didn\u2019t load.');
          }
        });
    };
    state.pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
  }

  window.ZivonArtifactViewer = {
    mount: function (root) {
      var doc = root && root.querySelectorAll ? root : document;
      forEachViewer(doc, createViewer);
    }
  };

  function autoMount() {
    window.ZivonArtifactViewer.mount(document);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
  } else {
    autoMount();
  }
})();
