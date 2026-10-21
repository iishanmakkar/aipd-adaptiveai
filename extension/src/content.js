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

  function findNode(ref) {
    var snap = snapshot(false);
    for (var i = 0; i < snap.nodes.length; i++) {
      if (snap.nodes[i].ref === ref) return snap.nodes[i];
    }
    return null;
  }

  function runAction(message) {
    var ACTOR = globalThis.AdaptiveAIActor;
    if (!ACTOR) {
      return { status: 'failed', reason: 'actor script did not load on this page' };
    }
    var node = findNode(message.ref);
    if (!node) {
      // Never fall back to guessing a selector: acting on the wrong control is
      // worse than doing nothing.
      return { status: 'not_found', ref: message.ref,
               reason: 'that control is not in the current page snapshot' };
    }
    if (message.action === 'fill') return ACTOR.fill(node, message.value, document);
    if (message.action === 'select') return ACTOR.select(node, message.value, document);
    if (message.action === 'click') return ACTOR.click(node, document);
    if (message.action === 'focus') return ACTOR.focus(node, document);
    return { status: 'failed', ref: message.ref,
             reason: 'unknown action ' + String(message.action) };
  }

  if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
      if (!message) return false;
      if (message.type === 'adaptiveai:snapshot') {
        var snap = snapshot(!!message.force);
        publishForPage(snap);
        sendResponse(snap);
        return false;
      }
      if (message.type === 'adaptiveai:act') {
        var result = runAction(message);
        // The tree may have changed under us (validation message appeared, row
        // re-rendered), so the next snapshot must be built fresh rather than
        // served from the 250ms cache.
        invalidate();
        sendResponse(result);
        return false;
      }
      return false;
    });
  }

  function invalidate() {
    lastSnapshot = null;
    lastTakenAt = 0;
  }

  globalThis.__adaptiveai = {
    snapshot: snapshot,
    refresh: refresh,
    act: runAction,
    // A page that changes under the assistant must not be navigated by an old
    // tree, so the loop needs a cheap way to say "forget the cache".
    invalidate: invalidate,
  };

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    refresh();
  } else {
    document.addEventListener('DOMContentLoaded', refresh, { once: true });
  }
})();
