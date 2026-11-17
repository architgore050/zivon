/* Zivon app pages (F3): guest -> account sync and saved-section removal.

   The lesson shell (F4) already writes device-local progress and bookmarks:
     localStorage["zivon.progress"]  {v, chapters: {"<course>/<topic>": {...}}}
     localStorage["zivon.bookmarks"] {v, items: [{course, topic, section_id,
                                                 block_id, title, ts}]}
   This file never invents a second store and never deletes the local copy.
   It offers a one-time additive merge into the account through the same-origin
   APIs, marking each part with a fingerprint so an unchanged device does not
   prompt again. A failed merge leaves the marker unset and the local data
   intact.

   F4 handoff: on a page that has `window.ZivonLessonShell`, `getProgress()` is
   the in-memory truth for the current chapter (it is folded into the merge
   payload) and `setProgressSink(fn)` is used to refresh the offer when the
   shell writes. On `/app` neither exists; the store is read directly.

   No third-party host, no free text, no analytics: only the same-origin
   `/v1/progress/events`, `/v1/bookmarks`, and `/catalogue.json`. */
(function () {
  "use strict";

  var PROGRESS_KEY = "zivon.progress";
  var BOOKMARKS_KEY = "zivon.bookmarks";
  var SYNC_KEY = "zivon.sync.v1";
  var DISMISS_KEY = "zivon.sync.dismissed";
  var EVENTS_URL = "/v1/progress/events";
  var BOOKMARKS_URL = "/v1/bookmarks";
  var CATALOGUE_URL = "/catalogue.json";
  var EVENT_CHUNK = 40;

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function readRaw(storageName, key) {
    try {
      var storage = window[storageName];
      return storage ? storage.getItem(key) : null;
    } catch (e) {
      return null;
    }
  }

  function writeRaw(storageName, key, value) {
    try {
      var storage = window[storageName];
      if (!storage) return false;
      storage.setItem(key, value);
      return true;
    } catch (e) {
      return false;
    }
  }

  function readJSON(storageName, key, fallback) {
    var raw = readRaw(storageName, key);
    if (!raw) return fallback;
    try {
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function progressStore() {
    var store = readJSON("localStorage", PROGRESS_KEY, null);
    if (!store || typeof store !== "object" || !store.chapters) {
      store = { v: 1, chapters: {} };
    }
    return withShellRecord(store);
  }

  function bookmarkStore() {
    var store = readJSON("localStorage", BOOKMARKS_KEY, null);
    if (!store || typeof store !== "object" || !Array.isArray(store.items)) {
      store = { v: 1, items: [] };
    }
    return store;
  }

  function readSyncMarker() {
    var marker = readJSON("localStorage", SYNC_KEY, null);
    return marker && typeof marker === "object" ? marker : {};
  }

  function writeSyncMarker(patch) {
    var marker = readSyncMarker();
    Object.keys(patch || {}).forEach(function (key) {
      marker[key] = patch[key];
    });
    marker.merged_at = new Date().toISOString();
    writeRaw("localStorage", SYNC_KEY, JSON.stringify(marker));
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? String(meta.getAttribute("content") || "") : "";
  }

  function lessonChapterKey() {
    var match = /^\/courses\/([^/]+)\/([^/]+)\//.exec(window.location.pathname);
    return match ? match[1] + "/" + match[2] : null;
  }

  function withShellRecord(store) {
    var shell = window.ZivonLessonShell;
    if (!shell || typeof shell.getProgress !== "function") return store;
    var key = lessonChapterKey();
    if (!key) return store;
    var record = null;
    try {
      record = shell.getProgress();
    } catch (e) {
      record = null;
    }
    if (!record || typeof record !== "object") return store;
    var copy = { v: 1, chapters: {} };
    Object.keys(store.chapters || {}).forEach(function (chapterKey) {
      copy.chapters[chapterKey] = store.chapters[chapterKey];
    });
    copy.chapters[key] = record;
    return copy;
  }

  function wireShellSink() {
    var shell = window.ZivonLessonShell;
    if (!shell || typeof shell.setProgressSink !== "function") return false;
    try {
      shell.setProgressSink(function () {
        refresh();
      });
      return true;
    } catch (e) {
      return false;
    }
  }

  function countChapters(store) {
    return Object.keys((store && store.chapters) || {}).filter(function (key) {
      var record = store.chapters[key] || {};
      var sections = record.sections && typeof record.sections === "object"
        ? Object.keys(record.sections).length
        : 0;
      return sections > 0 || Boolean(record.completed) || Number(record.max_scroll_pct) > 0;
    }).length;
  }

  function countSections(store) {
    var total = 0;
    Object.keys((store && store.chapters) || {}).forEach(function (key) {
      var record = store.chapters[key] || {};
      if (record.sections && typeof record.sections === "object") {
        total += Object.keys(record.sections).length;
      }
    });
    return total;
  }

  function progressFingerprint(store) {
    var chapters = (store && store.chapters) || {};
    return Object.keys(chapters)
      .sort()
      .map(function (key) {
        var record = chapters[key] || {};
        var sections = record.sections && typeof record.sections === "object"
          ? Object.keys(record.sections).sort().join(",")
          : "";
        return [
          key,
          sections,
          record.completed ? "1" : "0",
          Number(record.max_scroll_pct || 0)
        ].join(":");
      })
      .join("|");
  }

  function bookmarkFingerprint(store) {
    var items = (store && store.items) || [];
    return items
      .map(function (item) {
        return [
          String(item.topic || ""),
          String(item.section_id || ""),
          String(item.ts || 0)
        ].join(":");
      })
      .sort()
      .join("|");
  }

  function isoFromMs(value) {
    var ms = Number(value);
    if (!isFinite(ms) || ms <= 0) return null;
    var date = new Date(ms);
    if (isNaN(date.getTime())) return null;
    return date.toISOString();
  }

  function clampPct(value) {
    var number = Number(value);
    if (!isFinite(number)) return 0;
    return Math.max(0, Math.min(100, Math.round(number)));
  }

  /* The catalogue entry carries `href` ("courses/<course>/<topic>/index.html"),
     not a separate `topic_slug` (factory/render.py::_catalogue_entry). The
     lesson shell keys its device store by "<course_id>/<topic_slug>" from the
     route, so derive that key from `href` — without it every merged chapter
     falls back to the raw key and lands as an unmatched chapter. */
  function topicKeyFromHref(href) {
    var raw = String(href || "")
      .trim()
      .replace(/^\/+/, "")
      .replace(/\/?index\.html$/, "")
      .replace(/\/+$/, "");
    var parts = raw.split("/");
    if (parts.length >= 3 && parts[0] === "courses") {
      return parts.slice(1).join("/");
    }
    return null;
  }

  function loadCatalogue() {
    return fetch(CATALOGUE_URL, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (data) {
        var topics = data && Array.isArray(data.topics) ? data.topics : [];
        var byKey = {};
        topics.forEach(function (topic) {
          if (!topic) return;
          if (topic.chapter_id) byKey[String(topic.chapter_id)] = topic;
          if (topic.course_id && topic.topic_slug) {
            byKey[String(topic.course_id) + "/" + String(topic.topic_slug)] = topic;
          }
          var derived = topicKeyFromHref(topic.href);
          if (derived) byKey[derived] = topic;
        });
        return { topics: topics, byKey: byKey };
      })
      .catch(function () {
        return null;
      });
  }

  function buildEvents(store, catalogue) {
    var events = [];
    var chapters = (store && store.chapters) || {};
    Object.keys(chapters).forEach(function (key) {
      var record = chapters[key] || {};
      var topic = catalogue && catalogue.byKey ? catalogue.byKey[key] : null;
      var chapterId = topic ? String(topic.chapter_id) : key;
      var occurred = isoFromMs(record.updated_at);
      var conceptBySection = {};
      if (topic && Array.isArray(topic.concepts)) {
        topic.concepts.forEach(function (concept) {
          if (concept && concept.section_id && concept.concept_id) {
            conceptBySection[String(concept.section_id)] = String(concept.concept_id);
          }
        });
      }
      var sections = record.sections && typeof record.sections === "object"
        ? Object.keys(record.sections)
        : [];
      sections.forEach(function (sectionId) {
        var payload = {
          section_id: sectionId,
          blocks_seen: sections.length,
          source: "merge"
        };
        var event = {
          kind: "lesson_block_view",
          chapter_id: chapterId,
          payload: payload
        };
        if (conceptBySection[sectionId]) event.concept_id = conceptBySection[sectionId];
        if (occurred) event.occurred_at = occurred;
        events.push(event);
      });
      if (!sections.length && clampPct(record.max_scroll_pct) > 0) {
        var scrollEvent = {
          kind: "lesson_block_view",
          chapter_id: chapterId,
          payload: { max_scroll_pct: clampPct(record.max_scroll_pct), source: "merge" }
        };
        if (occurred) scrollEvent.occurred_at = occurred;
        events.push(scrollEvent);
      }
      if (record.completed) {
        var completeEvent = {
          kind: "lesson_complete",
          chapter_id: chapterId,
          payload: {
            sections_seen: sections.length,
            max_scroll_pct: clampPct(record.max_scroll_pct),
            source: "merge"
          }
        };
        if (occurred) completeEvent.occurred_at = occurred;
        events.push(completeEvent);
      }
    });
    return events;
  }

  function buildBookmarks(store, catalogue) {
    var seen = {};
    var prepared = [];
    ((store && store.items) || []).forEach(function (item) {
      if (!item || !item.section_id) return;
      var topicKey = String(item.topic || "");
      var topic = catalogue && catalogue.byKey ? catalogue.byKey[topicKey] : null;
      var chapterId = topic ? String(topic.chapter_id) : topicKey;
      if (!chapterId) return;
      var targetId = chapterId + ":" + String(item.section_id);
      if (!/^[a-z0-9][a-z0-9/_:.\-]{0,159}$/.test(targetId)) return;
      if (seen[targetId]) return;
      seen[targetId] = true;
      prepared.push({ target_type: "block", target_id: targetId });
    });
    return prepared;
  }

  function chunk(items, size) {
    var out = [];
    for (var i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
    return out;
  }

  function postJSON(url, body) {
    var token = csrfToken();
    if (!token) return Promise.reject(new Error("missing_csrf"));
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify(body)
    }).then(function (response) {
      if (!response.ok) throw new Error("http_" + response.status);
      return response.json();
    });
  }

  function deleteBookmark(targetType, targetId) {
    var token = csrfToken();
    if (!token) return Promise.reject(new Error("missing_csrf"));
    var query = "?target_type=" + encodeURIComponent(targetType) +
      "&target_id=" + encodeURIComponent(targetId);
    return fetch(BOOKMARKS_URL + query, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": token }
    }).then(function (response) {
      if (!response.ok) throw new Error("http_" + response.status);
      return response.json();
    });
  }

  function pendingParts() {
    var store = progressStore();
    var bookmarks = bookmarkStore();
    var marker = readSyncMarker();
    var progressPrint = progressFingerprint(store);
    var bookmarkPrint = bookmarkFingerprint(bookmarks);
    return {
      store: store,
      bookmarks: bookmarks,
      marker: marker,
      progressPrint: progressPrint,
      bookmarkPrint: bookmarkPrint,
      chapters: countChapters(store),
      sections: countSections(store),
      bookmarkCount: bookmarks.items.length,
      eventsPending: countChapters(store) > 0 && marker.events !== progressPrint,
      bookmarksPending: bookmarks.items.length > 0 && marker.bookmarks !== bookmarkPrint
    };
  }

  function refresh() {
    var panel = $("[data-progress-sync]");
    if (!panel) return;
    var pending = pendingParts();
    var nothing = !pending.eventsPending && !pending.bookmarksPending;
    var combined = pending.progressPrint + "//" + pending.bookmarkPrint;
    var dismissed = readRaw("sessionStorage", DISMISS_KEY);
    if (nothing || dismissed === combined) {
      panel.hidden = true;
      return;
    }
    var summary = $("[data-sync-summary]", panel);
    if (summary) {
      var parts = [];
      if (pending.eventsPending) {
        parts.push(
          pending.chapters + " chapter" + (pending.chapters === 1 ? "" : "s") +
          " (" + pending.sections + " section" + (pending.sections === 1 ? "" : "s") + " read)"
        );
      }
      if (pending.bookmarksPending) {
        parts.push(
          pending.bookmarkCount + " saved section" +
          (pending.bookmarkCount === 1 ? "" : "s")
        );
      }
      summary.textContent = "This device has " + parts.join(" and ") +
        " that are not in your account yet.";
    }
    panel.hidden = false;
  }

  function setStatus(text) {
    var status = $("[data-sync-status]");
    if (status) status.textContent = text;
  }

  function merge() {
    var panel = $("[data-progress-sync]");
    if (!panel) return Promise.resolve(false);
    var pending = pendingParts();
    if (!pending.eventsPending && !pending.bookmarksPending) {
      panel.hidden = true;
      return Promise.resolve(true);
    }
    var mergeButton = $("[data-sync-merge]", panel);
    var dismissButton = $("[data-sync-dismiss]", panel);
    if (mergeButton) {
      mergeButton.disabled = true;
      mergeButton.textContent = "Bringing them in…";
    }
    if (dismissButton) dismissButton.disabled = true;
    setStatus("Bringing your reading into your account…");
    return loadCatalogue()
      .then(function (catalogue) {
        var events = pending.eventsPending
          ? buildEvents(pending.store, catalogue)
          : [];
        var bookmarks = pending.bookmarksPending
          ? buildBookmarks(pending.bookmarks, catalogue)
          : [];
        var batches = chunk(events, EVENT_CHUNK);
        var chain = Promise.resolve();
        batches.forEach(function (batch) {
          chain = chain.then(function () {
            return postJSON(EVENTS_URL, { events: batch }).then(function (result) {
              /* A per-item schema rejection is a failed part, not a success:
                 never mark the device merged while the account is missing
                 rows. The failure copy already says nothing was deleted. */
              if (
                result &&
                Array.isArray(result.rejected) &&
                result.rejected.length > 0
              ) {
                throw new Error("rejected_events");
              }
              return result;
            });
          });
        });
        chain = chain.then(function () {
          /* Mark the events as soon as they land: a later bookmark failure
             must not make a retry re-send every reading event. */
          if (pending.eventsPending) {
            writeSyncMarker({ events: pending.progressPrint });
          }
          if (!bookmarks.length) return null;
          return postJSON(BOOKMARKS_URL, { items: bookmarks }).then(function () {
            if (pending.bookmarksPending) {
              writeSyncMarker({ bookmarks: pending.bookmarkPrint });
            }
            return null;
          });
        });
        return chain.then(function () {
          var broughtChapters = pending.eventsPending ? pending.chapters : 0;
          var broughtBookmarks = pending.bookmarksPending
            ? pending.bookmarkCount
            : 0;
          if (mergeButton) {
            mergeButton.disabled = false;
            mergeButton.textContent = "Bring them in";
          }
          if (dismissButton) dismissButton.disabled = false;
          setStatus(
            "Brought in " + broughtChapters + " chapter" +
            (broughtChapters === 1 ? "" : "s") + " and " +
            broughtBookmarks + " saved section" +
            (broughtBookmarks === 1 ? "" : "s") +
            ". Your device copy is unchanged."
          );
          var link = document.createElement("a");
          link.className = "text-link";
          link.href = "/app";
          link.textContent = "See them on your dashboard";
          var status = $("[data-sync-status]");
          if (status && !$("[data-sync-refresh]", panel)) {
            link.setAttribute("data-sync-refresh", "1");
            status.appendChild(document.createTextNode(" "));
            status.appendChild(link);
          }
          return true;
        });
      })
      .catch(function () {
        if (mergeButton) {
          mergeButton.disabled = false;
          mergeButton.textContent = "Try again";
        }
        if (dismissButton) dismissButton.disabled = false;
        setStatus(
          "Some items could not be brought in. They are still on this device; " +
          "nothing was deleted."
        );
        return false;
      });
  }

  function dismiss() {
    var pending = pendingParts();
    writeRaw(
      "sessionStorage",
      DISMISS_KEY,
      pending.progressPrint + "//" + pending.bookmarkPrint
    );
    var panel = $("[data-progress-sync]");
    if (panel) panel.hidden = true;
  }

  function wireSyncPanel() {
    var panel = $("[data-progress-sync]");
    if (!panel) return;
    var mergeButton = $("[data-sync-merge]", panel);
    var dismissButton = $("[data-sync-dismiss]", panel);
    if (mergeButton) mergeButton.addEventListener("click", function () { merge(); });
    if (dismissButton) dismissButton.addEventListener("click", dismiss);
    refresh();
  }

  function wireBookmarkRemoval() {
    var list = $(".bookmark-list");
    if (!list) return;
    list.addEventListener("click", function (event) {
      var button = event.target.closest("[data-bookmark-remove]");
      if (!button) return;
      var targetType = String(button.getAttribute("data-target-type") || "");
      var targetId = String(button.getAttribute("data-target-id") || "");
      if (!targetType || !targetId) return;
      button.disabled = true;
      deleteBookmark(targetType, targetId)
        .then(function () {
          var row = button.closest("[data-bookmark-row]");
          if (row && row.parentNode) row.parentNode.removeChild(row);
          var heading = $("[data-bookmark-count]");
          if (heading) {
            var remaining = Math.max(
              0,
              Number(heading.getAttribute("data-count") || 1) - 1
            );
            heading.setAttribute("data-count", remaining);
            heading.textContent =
              remaining + " saved " + (remaining === 1 ? "item" : "items");
          }
          var status = $("[data-bookmark-status]");
          if (status) status.textContent = "Removed from your saved sections.";
          if (!$("[data-bookmark-row]")) {
            var empty = document.createElement("p");
            empty.className = "lede";
            empty.textContent = "Nothing saved yet. Save a section from a lesson to see it here.";
            list.parentNode.insertBefore(empty, list);
          }
        })
        .catch(function () {
          button.disabled = false;
          var status = $("[data-bookmark-status]");
          if (status) {
            status.textContent =
              "Could not remove it just now. It is still saved; try again.";
          }
        });
    });
  }

  function boot() {
    wireShellSink();
    wireSyncPanel();
    wireBookmarkRemoval();
  }

  window.ZivonAppProgress = {
    version: 1,
    collect: function () {
      return { progress: progressStore(), bookmarks: bookmarkStore() };
    },
    buildEvents: buildEvents,
    buildBookmarks: buildBookmarks,
    refresh: refresh,
    merge: merge,
    dismiss: dismiss
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
