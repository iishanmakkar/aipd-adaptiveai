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
    // A miss is not proof the control is gone: the cached tree may predate a
    // navigation the page did after it. Re-read once before reporting not_found,
    // so a legitimate action is not refused because of the burst cache.
    var fresh = snapshot(true);
    for (var j = 0; j < fresh.nodes.length; j++) {
      if (fresh.nodes[j].ref === ref) return fresh.nodes[j];
    }
    return null;
  }

  function gateContext() {
    var href = '';
    var isTop = true;
    try {
      href = document.location.href;
      isTop = globalThis.top === globalThis;
    } catch (e) { /* sandboxed frame: fall through with what we have */ }
    return { origin: document.location.origin, frameUrl: isTop ? '' : href, isTop: isTop };
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

    if (message.action === 'click') {
      var GATE = globalThis.AdaptiveAIGate;
      if (!GATE) {
        // Fail closed. A page where the gate script failed to load is a page where
        // nothing can vouch that "Pay ₹640" will not be pressed silently, so no
        // click runs at all rather than every click running ungated.
        return { status: 'refused', ref: node.ref,
                 reason: 'the spending gate is unavailable on this page, so nothing is clicked' };
      }
      // The ceiling travels with every action message; without it the gate could
      // never report `exceedsCeiling` and the second, stronger confirmation for
      // an amount above the user's own limit could never fire.
      var verdict = GATE.classify(node, Object.assign(gateContext(), {
        spendCeiling: message.spendCeiling === undefined ? null : message.spendCeiling,
      }));
      if (verdict.gated) {
        if (message.confirm !== true) {
          return { status: 'gated', ref: node.ref, name: node.name, gate: verdict,
                   reason: 'this needs your explicit approval first: ' + verdict.reason };
        }
        if (verdict.exceedsCeiling && message.confirmStrong !== true) {
          return { status: 'gated', ref: node.ref, name: node.name, gate: verdict,
                   reason: 'that is above the spending limit you set, so it needs a second, ' +
                           'separate confirmation' };
        }
      }
    }

    if (message.action === 'fill') return ACTOR.fill(node, message.value, document);
    if (message.action === 'select') return ACTOR.select(node, message.value, document);
    if (message.action === 'focus') return ACTOR.focus(node, document);
    if (message.action === 'click') {
      var WATCH = globalThis.AdaptiveAIWatch;
      // Baseline before the click: "what changed" is only meaningful against what
      // was there when the user agreed to the action.
      var baseline = WATCH ? WATCH.capture(document, node) : null;
      var out = ACTOR.click(node, document);
      if (out.status !== 'pressed' || !message.expect || !WATCH) {
        // No expectation means no upgrade: a bare click stays "pressed", because
        // nothing has proven the page reacted.
        return out;
      }
      return WATCH.waitFor(document, baseline, message.expect, message.timeoutMs)
        .then(function (res) {
          if (res.verified) {
            return { status: 'verified', action: 'click', ref: node.ref,
                     name: node.name, readback: res.evidence };
          }
          return { status: 'failed', action: 'click', ref: node.ref,
                   name: node.name, reason: res.reason };
        });
    }
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
      if (message.type === 'adaptiveai:audit') {
        sendResponse(audit());
        return false;
      }
      if (message.type === 'adaptiveai:act') {
        // A click with an expectation resolves only when the page has reacted, so
        // the channel stays open; returning false here would drop the reply.
        Promise.resolve(runAction(message)).then(function (result) {
          invalidate();
          sendResponse(result);
        });
        return true;
      }
      return false;
    });
  }

  function invalidate() {
    lastSnapshot = null;
    lastTakenAt = 0;
  }

  function audit() {
    // The page's main world cannot see anything here (content scripts run in an
    // isolated world), so a probe of the extension has to ask it, the way the
    // service worker does. Returns structure only - never field values.
    var t0 = (globalThis.performance && globalThis.performance.now)
      ? globalThis.performance.now() : Date.now();
    var snap = snapshot(true);
    var t1 = (globalThis.performance && globalThis.performance.now)
      ? globalThis.performance.now() : Date.now();
    var PRIV = globalThis.AdaptiveAIPrivacy;
    var GATE = globalThis.AdaptiveAIGate;
    var gated = [];
    if (GATE) {
      var ctx = gateContext();
      for (var i = 0; i < snap.nodes.length; i++) {
        var n = snap.nodes[i];
        if (!n.interactive) continue;
        var v = GATE.classify(n, ctx);
        if (v.gated) {
          gated.push({ name: v.name, why: v.reason, amount: v.amount });
        }
      }
    }
    return {
      snapshotMs: Math.round(t1 - t0),
      domElements: document.querySelectorAll('*').length,
      stats: snap.stats,
      url: snap.url,
      title: snap.title,
      redacted: PRIV ? PRIV.redactSnapshot(snap).nodes : null,
      gated: gated,
    };
  }

  globalThis.__adaptiveai = {
    snapshot: snapshot,
    refresh: refresh,
    act: runAction,
    audit: audit,
    // A page that changes under the assistant must not be navigated by an old
    // tree, so the loop needs a cheap way to say "forget the cache".
    invalidate: invalidate,
  };

  // Tell the worker this tab exists. It also wakes the service worker: an MV3
  // worker started lazily meant a cold profile could sit past any fixed timeout
  // before registering, so "wait for the worker" becomes "be the thing that
  // starts it" - which the task runner needs to know about anyway.
  function announceTab() {
    if (typeof chrome === 'undefined' || !chrome.runtime || !chrome.runtime.sendMessage) return;
    try {
      var p = chrome.runtime.sendMessage({
        type: 'adaptiveai:tab-ready', url: document.location.href,
      });
      // No listener yet rejects the promise; an unread rejection is noise.
      if (p && typeof p.catch === 'function') p.catch(function () {});
    } catch (e) { /* no runtime in this context; the page hook still works */ }
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    refresh();
    announceTab();
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      refresh();
      announceTab();
    }, { once: true });
  }
})();
