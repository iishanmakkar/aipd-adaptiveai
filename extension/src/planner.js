// AdaptiveAI planner client: turns the task loop's "what next?" into a call to
// POST /api/extension/step, and the answer into a step the actor can execute.
//
// The boundary the backend contract depends on is enforced here, before anything
// leaves the device: the snapshot is redacted with privacy.js first, so a value
// typed into a field never enters the request, and the profile labels sent are
// names only. The reply then comes back with a ref and *where the value should
// come from*, and this module is the only thing that reads the vault to fill it
// in. A value going out as structure and coming back as a lookup is the whole
// design; if either half is skipped, this file is the one that leaks.
//
// Nothing here invents a step. A 503, a 401, an unparseable body or a reply with
// a ref that is not in the snapshot the caller sent all become a `cannot` control
// with the reason, which the runner narrates and stops on - because a fallback
// plan assembled from keyword matches is exactly the fake that the truth pass
// removed from the server side.
(function (global) {
  'use strict';

  var DEFAULT_BACKEND = 'http://localhost:8000';
  var STEP_PATH = '/api/extension/step';

  function storageGet(key) {
    return new Promise(function (resolve) {
      try {
        chrome.storage.local.get([key], function (data) {
          resolve(chrome.runtime.lastError ? '' : (data && data[key]) || '');
        });
      } catch (e) { resolve(''); }
    });
  }

  function create(options) {
    var opts = options || {};
    var doFetch = opts.fetchImpl || function (url, init) { return fetch(url, init); };
    var vault = opts.vault || global.AdaptiveAIVault;
    var privacy = opts.privacy || global.AdaptiveAIPrivacy;
    var timeoutMs = opts.timeoutMs || 25000;
    var history = [];
    var pending = null;

    function recordOutcome(outcome) {
      if (!pending) return;
      pending.status = outcome && outcome.status ? outcome.status : 'failed';
      pending.change = (outcome && outcome.change && outcome.change.description) || '';
      pending.error = (outcome && outcome.reason) || '';
      history.push(pending);
      if (history.length > 40) history.shift();
      pending = null;
    }

    function control(kind, narration, why) {
      return { control: kind, say: narration || 'I have nothing to report.', why: why || '' };
    }

    async function nextStep(context) {
      if (!context || !context.snapshot) {
        return control('cannot', 'I could not read this page, so I cannot plan a step.',
                       'no snapshot');
      }
      if (context.lastOutcome) recordOutcome(context.lastOutcome);

      var redacted = privacy ? privacy.redactSnapshot(context.snapshot) : context.snapshot;
      var nodes = (redacted && redacted.nodes) || [];
      // What the model is allowed to see: shape, never content.
      var wire = nodes.map(function (n) {
        var out = {
          ref: n.ref, tag: n.tag || '', role: n.role || '', name: n.name || '',
          nameSource: n.nameSource || '', unnamed: !!n.unnamed,
          lowConfidenceName: !!n.lowConfidenceName, interactive: !!n.interactive,
          kind: n.kind || null, hasValue: !!n.hasValue, sensitive: !!n.sensitive,
          states: n.states || {}, inShadow: !!n.inShadow, disabled: !!n.disabled,
        };
        if (n.live) out.live = n.live;
        if (n.options) out.options = n.options.map(function (o) { return { text: o.text }; });
        return out;
      });

      var base = await storageGet('adaptiveai_backend') || DEFAULT_BACKEND;
      var token = await storageGet('adaptiveai_token');
      var body = JSON.stringify({
        goal: context.goal || '',
        url: (redacted && redacted.url) || '',
        title: (redacted && redacted.title) || '',
        nodes: wire,
        available_labels: context.availableLabels || [],
        history: history,
        verbosity: (redacted && redacted.verbosity) || 'standard',
      });

      var reply;
      try {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
        var response = await doFetch(base.replace(/\/+$/, '') + STEP_PATH, {
          method: 'POST',
          headers: token ? { 'content-type': 'application/json',
                             authorization: 'Bearer ' + token }
                         : { 'content-type': 'application/json' },
          body: body,
          signal: controller.signal,
        });
        clearTimeout(timer);
        if (response.status === 401) {
          return control('cannot', 'I need you to sign in before I can plan a step.',
                         'unauthenticated');
        }
        if (response.status === 429) {
          return control('cannot', 'I am being asked too often, so I paused. ' +
                                   'Try again in a minute.', 'rate limited');
        }
        if (!response.ok) {
          var detail = '';
          try { detail = String((await response.json()).detail || ''); } catch (e) { /* */ }
          return control('cannot', 'The planner could not give me a step' +
                     (detail ? ': ' + detail.slice(0, 120) : '.'), 'http ' + response.status);
        }
        reply = await response.json();
      } catch (e) {
        return control('cannot', 'I could not reach the planner at ' + base +
                       ', so nothing was pressed.', String(e).slice(0, 120));
      }

      var status = reply && reply.status;
      if (status === 'done') return control('done', reply.narration, reply.why);
      if (status === 'ask_user') return control('ask', reply.narration, reply.why);
      if (status === 'cannot') return control('cannot', reply.narration, reply.why);
      if (status !== 'act') {
        return control('cannot', 'The planner answered something I do not understand.',
                       'status ' + status);
      }

      var refs = {};
      nodes.forEach(function (n) { refs[n.ref] = n; });
      var node = refs[reply.ref];
      if (!node) {
        // The server checks this too. Checked twice because this is the copy that
        // is about to press something, and the page may have changed in between.
        return control('cannot', 'The planner named a control that is not on this ' +
                       'page, so I did nothing.', 'unknown ref ' + reply.ref);
      }
      if (node.kind === 'password' || node.sensitive) {
        return control('cannot', 'That is a password field. I never fill those - ' +
                       'please type it yourself.', 'password refused');
      }

      var value;
      if (reply.value_from === 'profile') {
        if (!vault) {
          return control('cannot', 'I cannot read your saved details right now.',
                         'no vault');
        }
        value = await vault.resolve(reply.value_label);
        if (value === null || value === undefined || value === '') {
          return control('ask', 'I do not have your ' + reply.value_label +
                         ' saved. Tell me what to enter, or add it in setup.',
                         'missing ' + reply.value_label);
        }
      } else if (reply.value_from === 'literal') {
        value = reply.value_literal;
      }

      pending = { description: reply.narration || (reply.action + ' ' + reply.ref),
                  action: reply.action, ref: reply.ref };
      return {
        action: reply.action,
        ref: reply.ref,
        value: value,
        expect: reply.expect && reply.expect !== 'none' ? reply.expect : null,
        description: reply.narration || (reply.action + ' ' + reply.ref),
        say: null,
      };
    }

    return {
      nextStep: nextStep,
      history: function () { return history.slice(); },
      DEFAULT_BACKEND: DEFAULT_BACKEND,
    };
  }

  var AdaptiveAIPlanner = { create: create, DEFAULT_BACKEND: DEFAULT_BACKEND,
                            STEP_PATH: STEP_PATH };
  global.AdaptiveAIPlanner = AdaptiveAIPlanner;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIPlanner;
})(typeof window !== 'undefined' ? window : globalThis);
