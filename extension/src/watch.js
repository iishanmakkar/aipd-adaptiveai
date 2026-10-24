// AdaptiveAI watch: proving that a click actually did something.
//
// THE PROBLEM THIS EXISTS FOR. "No exception thrown" is not evidence. A single-page
// form can accept a click on "Proceed", re-render with an inline "3 seats remaining"
// error, change no URL, and any assistant that reports success there has told a user
// who cannot see the screen that they are one step closer than they are. This is the
// same class of bug Plan A removed on the server side, and it cannot be fixed by the
// actor alone because the page reacts asynchronously.
//
// So a click carries an EXPECTATION, chosen by the planner, and this module waits for
// that specific kind of change. No match by the deadline is a failure, reported with
// whatever did change - which is often the useful part.
(function (global) {
  'use strict';

  var POLL_MS = 50;

  function collapse(v) { return (v || '').replace(/\s+/g, ' ').trim(); }

  function liveRegions(doc) {
    var out = [];
    var els = doc.querySelectorAll('[aria-live], [role="alert"], [role="status"], [role="log"]');
    for (var i = 0; i < els.length; i++) {
      var text = collapse(els[i].innerText !== undefined ? els[i].innerText : els[i].textContent);
      if (text) out.push(text);
    }
    return out;
  }

  // Baseline is taken BEFORE the action. Everything here is cheap: no tree walk,
  // just the few things a prediction can be about.
  function capture(doc, node) {
    var states = null;
    if (node && node.selector) {
      try {
        var el = doc.querySelector(node.selector);
        if (el) {
          states = {
            checked: !!el.checked,
            expanded: el.getAttribute('aria-expanded'),
            selected: el.getAttribute('aria-selected'),
            disabled: !!el.disabled,
            value: el.value !== undefined ? String(el.value) : null,
          };
        }
      } catch (e) { states = null; }
    }
    var nodeCount = null;
    if (global.AdaptiveAIAX) {
      try { nodeCount = global.AdaptiveAIAX.computeSnapshot(doc).nodes.length; } catch (e) { nodeCount = null; }
    }
    return {
      url: doc.location ? doc.location.href : '',
      title: doc.title || '',
      readyState: doc.readyState,
      live: liveRegions(doc),
      nodeCount: nodeCount,
      nodeRef: node ? node.ref : null,
      states: states,
    };
  }

  function nodePresent(doc, expect, AX) {
    if (!AX) return false;
    var snap = AX.computeSnapshot(doc);
    for (var i = 0; i < snap.nodes.length; i++) {
      var n = snap.nodes[i];
      if (expect.name && n.name !== expect.name) continue;
      if (expect.role && n.role !== expect.role) continue;
      if (expect.name || expect.role) return true;
    }
    return false;
  }

  function evaluate(doc, baseline, expect, AX) {
    // The planner and the recipes both speak of an expectation as a bare kind
    // ("url_changed"); the tests pass an object. Accepting only one shape meant
    // the other arrived as `kind: undefined`, matched nothing, and every click
    // carrying an expectation failed after its full timeout.
    if (typeof expect === 'string') expect = { kind: expect };
    var nowLive = liveRegions(doc);
    var urlChanged = doc.location.href !== baseline.url;
    var titleChanged = (doc.title || '') !== baseline.title;
    var newAnnouncement = nowLive.some(function (t) { return baseline.live.indexOf(t) === -1; });
    if (!urlChanged && !newAnnouncement && nowLive.length < baseline.live.length) {
      // A message DISAPPEARING is a change too (the error cleared), and the user
      // should hear that rather than be told nothing happened.
      newAnnouncement = baseline.live.some(function (t) { return nowLive.indexOf(t) === -1; });
    }

    var kind = expect && expect.kind;
    switch (kind) {
      case 'url_changed':
        return urlChanged ? { matched: true, evidence: 'now at ' + doc.location.href } : null;
      case 'title_changed':
        return titleChanged ? { matched: true, evidence: 'title is now ' + JSON.stringify(doc.title) } : null;
      case 'announcement':
        return newAnnouncement
          ? { matched: true, evidence: 'the page said: ' + JSON.stringify(nowLive.join(' | ').slice(0, 200)) }
          : null;
      case 'node_appears':
        return nodePresent(doc, expect, AX)
          ? { matched: true, evidence: 'found ' + (expect.role || 'node') + ' ' + JSON.stringify(expect.name) }
          : null;
      case 'state_flipped': {
        if (!baseline.states) return null;
        if (!expect.selector) return null;
        var el;
        try { el = doc.querySelector(expect.selector); } catch (e) { return null; }
        if (!el) return null;
        var field = expect.state || 'checked';
        var current = field === 'expanded' ? el.getAttribute('aria-expanded')
          : field === 'selected' ? el.getAttribute('aria-selected')
          : field === 'disabled' ? !!el.disabled : !!el.checked;
        if (String(current) !== String(baseline.states[field])) {
          return { matched: true, evidence: field + ' is now ' + current };
        }
        return null;
      }
      case 'navigation_committed':
        return (urlChanged || titleChanged || doc.readyState === 'complete') &&
               doc.readyState !== 'loading'
          ? { matched: true, evidence: 'page loaded at ' + doc.location.href } : null;
      default:
        return null;
    }
  }

  // Any observed change, matched or not - used so a failure can say what DID happen.
  function describeChange(doc, baseline, AX) {
    var bits = [];
    if (doc.location.href !== baseline.url) bits.push('url changed');
    if ((doc.title || '') !== baseline.title) bits.push('title changed');
    var nowLive = liveRegions(doc);
    if (nowLive.join('|') !== baseline.live.join('|')) {
      bits.push('live text is now ' + JSON.stringify(nowLive.join(' | ').slice(0, 160)));
    }
    if (AX) {
      try {
        var after = AX.computeSnapshot(doc).nodes.length;
        // Only a DIFFERENCE is worth telling the user about; "the page has 9
        // elements" is not a change and would let a dead page look alive.
        if (baseline.nodeCount != null && after !== baseline.nodeCount) {
          bits.push(after > baseline.nodeCount
            ? (after - baseline.nodeCount) + ' element(s) appeared'
            : (baseline.nodeCount - after) + ' element(s) disappeared');
        }
      } catch (e) { /* snapshot failed: report what is known */ }
    }
    return bits.length ? bits.join('; ') : 'nothing observable changed';
  }

  /**
   * waitFor(doc, baseline, expect, timeoutMs) -> Promise<{verified, evidence, reason}>
   *
   * MutationObserver drives the wakeups (a page that settles quietly is not polled
   * into oblivion) with a slow poll behind it, because attribute-only changes such as
   * aria-expanded on a canvas-drawn widget do not always produce childList mutations.
   */
  function waitFor(doc, baseline, expect, timeoutMs) {
    var AX = global.AdaptiveAIAX;
    var limit = timeoutMs || 8000;
    if (typeof expect === 'string') expect = { kind: expect };
    return new Promise(function (resolve) {
      var finished = false, timer = null, observer = null;

      function done(result) {
        if (finished) return;
        finished = true;
        if (timer) global.clearInterval(timer);
        if (observer) { try { observer.disconnect(); } catch (e) {} }
        resolve(result);
      }

      function check() {
        var hit = evaluate(doc, baseline, expect || {}, AX);
        if (hit && hit.matched) {
          done({ verified: true, evidence: hit.evidence });
          return true;
        }
        return false;
      }

      try {
        observer = new global.MutationObserver(check);
        observer.observe(doc.documentElement, {
          childList: true, subtree: true, attributes: true, characterData: true,
        });
      } catch (e) { observer = null; }

      if (check()) return;                       // already changed before we started
      timer = global.setInterval(check, POLL_MS);
      global.setTimeout(function () {
        done({ verified: false,
               reason: 'I expected ' + ((expect && expect.kind) || 'a change') +
                       ' and it did not happen. ' + describeChange(doc, baseline, AX) });
      }, limit);
    });
  }

  var AdaptiveAIWatch = { capture: capture, waitFor: waitFor, evaluate: evaluate };
  global.AdaptiveAIWatch = AdaptiveAIWatch;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIWatch;
})(typeof window !== 'undefined' ? window : globalThis);
