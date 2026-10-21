// AdaptiveAI content script bootstrap.
//
// Loaded as ["src/ax.js", "src/content.js"] in the same isolated world, so
// AdaptiveAIAX is already defined here. MV3 gives content scripts no ESM
// imports, and there is deliberately no bundler: what you load unpacked is what
// runs.
(function () {
  'use strict';

  var AX = globalThis.AdaptiveAIAX;
  if (!AX) return;  // ax.js did not load: stay silent rather than half-work

  var lastSnapshot = null;
  var lastTakenAt = 0;

  function snapshot(force) {
    // Cached for 250ms so a burst of requests (popup + voice + task loop on the
    // same turn) does not walk the DOM three times. Re-reading is always safe;
    // reusing a stale tree is what caused Plan A's pattern_cache bug, so this
    // cache holds the DATA, never an action or a status.
    var now = Date.now();
    if (!force && lastSnapshot && now - lastTakenAt < 250) return lastSnapshot;
    lastSnapshot = AX.computeSnapshot(document);
    lastTakenAt = now;
    return lastSnapshot;
  }

  // Readable from the page's main world, which is how the load test confirms a
  // content script actually ran inside a real Chrome rather than only in a
  // harness.
  function publishForPage(snap) {
    var root = document.documentElement;
    root.setAttribute('data-adaptiveai-nodes', String(snap.stats.total));
    root.setAttribute('data-adaptiveai-interactive', String(snap.stats.interactive));
    root.setAttribute('data-adaptiveai-unnamed', String(snap.stats.unnamedControls));
    root.setAttribute('data-adaptiveai-missing-alt', String(snap.stats.missingAlt));
  }

  function refresh() {
    var snap = snapshot(true);
    publishForPage(snap);
    return snap;
  }

  if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
      if (!message || message.type !== 'adaptiveai:snapshot') return false;
      var snap = snapshot(!!message.force);
      publishForPage(snap);
      sendResponse(snap);
      return false;
    });
  }

  globalThis.__adaptiveai = {
    snapshot: snapshot,
    refresh: refresh,
    // A page that changes under the assistant must not be navigated by an old
    // tree, so the loop needs a cheap way to say "forget the cache".
    invalidate: function () { lastSnapshot = null; lastTakenAt = 0; },
  };

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    refresh();
  } else {
    document.addEventListener('DOMContentLoaded', refresh, { once: true });
  }
})();
