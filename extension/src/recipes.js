// AdaptiveAI recipes: site knowledge as data, and a memory of what actually worked.
//
// A recipe is a JSON file that says "for this kind of task, in this order, look for
// a control whose role is X and whose accessible name contains one of these words".
// It contains no selector, no XPath, no element id, and no value - the first three
// because a per-site CSS rule is the failure mode this design refuses (spec §7): the
// site redesigns, the rule stops matching, and the assistant either does nothing or
// presses the wrong thing. Accessible names are what the user hears, so they are
// what this file is allowed to speak.
//
// A recipe proposes; it never decides. Every proposal still goes through the actor,
// still needs a readback, still stops at the gate, and the trace memory below can
// only reorder *which candidate the words matched* - it cannot make an unverified
// step count as done.
(function (global) {
  'use strict';

  var INDEX = 'recipes/index.json';
  var TRACE_KEY = 'adaptiveai_traces';
  var MAX_STEPS_KEPT = 12;
  var cache = null;
  var invalid = [];

  function urlParts(url) {
    try {
      var u = new URL(url);
      return { host: u.hostname.toLowerCase(), path: u.pathname.toLowerCase() };
    } catch (e) { return { host: '', path: '' }; }
  }

  var SELECTORISH = /(#\w|\/\/|\.\w+\s*[,:]|^\s*[a-z]+\s*[>+~]\s*[.#a-z]|\[\s*(id|class|name|href)\s*[=~^*]?=)/i;

  // The rule that keeps this a data file. `test_recipes.py` runs it over every
  // committed recipe too, so a selector cannot sneak in through a hand edit.
  function validate(recipe) {
    if (!recipe || typeof recipe !== 'object') return 'not an object';
    if (!recipe.id || !Array.isArray(recipe.steps) || !recipe.steps.length) {
      return 'needs an id and at least one step';
    }
    if (!Array.isArray(recipe.hosts) || !recipe.hosts.length) return 'needs hosts';
    for (var i = 0; i < recipe.steps.length; i++) {
      var step = recipe.steps[i];
      if (!step.intent) return 'step ' + i + ' has no intent';
      if (!Array.isArray(step.names) || !step.names.length) {
        return 'step ' + i + ' has no accessible-name words';
      }
      var haystack = JSON.stringify(step);
      if (SELECTORISH.test(haystack) || /id=|class=|xpath|querySelector/i.test(haystack)) {
        return 'step "' + step.intent + '" looks like a selector, which a recipe may not contain';
      }
      if (step.value && !/^profile:[a-z0-9 ._-]+$/i.test(step.value)) {
        return 'step "' + step.intent + '" carries a value; a recipe may only name a profile label';
      }
    }
    return null;
  }

  function load() {
    if (cache) return Promise.resolve(cache);
    return fetch(chrome.runtime.getURL(INDEX))
      .then(function (r) { return r.json(); })
      .then(function (index) { return Promise.all(index.recipes.map(function (name) {
        return fetch(chrome.runtime.getURL('recipes/' + name))
          .then(function (r) { return r.json(); })
          .catch(function (e) { invalid.push({ file: name, reason: String(e).slice(0, 120) }); return null; });
      })); })
      .then(function (list) {
        cache = list.filter(Boolean).map(function (recipe) {
          var problem = validate(recipe);
          if (problem) {
            // Reported, not dropped quietly: a recipe that fails validation is a
            // site the assistant will suddenly stop understanding.
            invalid.push({ file: recipe && recipe.id, reason: problem });
            return null;
          }
          return recipe;
        }).filter(Boolean);
        return cache;
      });
  }

  function matches(recipe, url, goal) {
    var parts = urlParts(url);
    var hostHit = recipe.hosts.some(function (h) {
      return parts.host === h || parts.host.endsWith('.' + h);
    });
    if (!hostHit) return false;
    var text = (goal || '').toLowerCase();
    if (!recipe.matchGoal || !recipe.matchGoal.length) return true;
    return recipe.matchGoal.some(function (w) { return text.indexOf(w.toLowerCase()) !== -1; });
  }

  function wordHit(name, word) {
    // Word boundaries, because "to" as a substring matches "Total price" and
    // "date" matches "candidate" - a name collision is how the wrong control gets
    // pressed. Measured against the vault's own substring bug.
    var n = name.toLowerCase(), w = word.toLowerCase();
    if (n === w) return 3;
    var re = new RegExp('(^|[^a-z0-9])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '([^a-z0-9]|$)', 'i');
    if (re.test(n)) return 2;
    if (n.indexOf(w) !== -1) return 1;
    return 0;
  }

  function findCandidate(step, nodes, tracedName) {
    var pool = nodes.filter(function (n) { return n.interactive && n.name; });
    if (tracedName) {
      var remembered = pool.filter(function (n) {
        return n.name.toLowerCase() === String(tracedName).toLowerCase();
      });
      if (remembered.length === 1) return { status: 'ok', node: remembered[0], via: 'trace' };
    }
    var scored = [];
    pool.forEach(function (n) {
      var best = 0;
      (step.names || []).forEach(function (w) { best = Math.max(best, wordHit(n.name, w)); });
      if (step.role && n.role !== step.role) best = 0;
      if (best && step.kinds && n.kind && step.kinds.indexOf(n.kind) === -1) best = 0;
      // Only an exact or word-boundary hit counts. A word buried inside another
      // word ("to" inside "Total price ₹640", "date" inside "candidate") is not a
      // match, and the alternative is filling a total or a button. Better to
      // report the step as missing and let the model look at the page.
      if (best >= 2) scored.push({ node: n, score: best });
    });
    if (!scored.length) return { status: 'none' };
    scored.sort(function (a, b) { return b.score - a.score; });
    var top = scored.filter(function (s) { return s.score === scored[0].score; });
    if (top.length > 1) {
      return { status: 'ambiguous', candidates: top.map(function (t) { return t.node.name; }) };
    }
    return { status: 'ok', node: top[0].node, via: 'names' };
  }

  function storageGet(key) {
    return new Promise(function (resolve) {
      try {
        chrome.storage.local.get([key], function (data) {
          resolve(chrome.runtime.lastError ? null : (data && data[key]) || null);
        });
      } catch (e) { resolve(null); }
    });
  }

  function tracesFor(url, recipeId) {
    var host = urlParts(url).host;
    return storageGet(TRACE_KEY).then(function (all) {
      return (all && all[host + '#' + recipeId]) || [];
    });
  }

  // The first step whose intent has not been completed yet, as a step the planner
  // would otherwise have asked the model for. `done` is the set of intents the run
  // has already verified - so a recipe can repeat a step the actor failed, which is
  // the point: it retries what the page did not accept, and stops where the gate is.
  function propose(recipe, snapshot, goal, done) {
    if (!recipe || !snapshot || !snapshot.nodes) return Promise.resolve(null);
    return tracesFor(snapshot.url || '', recipe.id).then(function (traces) {
      var stopWords = (recipe.stopAt || []).map(function (w) { return String(w).toLowerCase(); });
      for (var i = 0; i < recipe.steps.length; i++) {
        var step = recipe.steps[i];
        if (done.indexOf(step.intent) !== -1) continue;
        var trace = traces.filter(function (t) { return t.intent === step.intent; })[0];
        var found = findCandidate(step, snapshot.nodes, trace && trace.name);
        if (found.status === 'ambiguous') {
          return { kind: 'ask', intent: step.intent, candidates: found.candidates };
        }
        if (found.status !== 'ok') return { kind: 'missing', intent: step.intent };
        var name = (found.node.name || '').toLowerCase();
        if (stopWords.some(function (w) { return name.indexOf(w) !== -1; })) {
          return { kind: 'stop', intent: step.intent, name: found.node.name };
        }
        return {
          kind: 'step',
          intent: step.intent,
          action: found.node.role === 'combobox' ? 'select'
            : (found.node.kind === 'checkbox' || found.node.kind === 'radio') ? 'click'
              : (step.role === 'button' || found.node.role === 'button') ? 'click' : 'fill',
          ref: found.node.ref,
          value_from: step.value ? (String(step.value).indexOf('profile:') === 0 ? 'profile' : 'none') : 'none',
          value_label: step.value ? String(step.value).replace(/^profile:/i, '') : null,
          expect: found.node.role === 'button' ? 'url_changed' : 'none',
          description: (step.intent + ' (' + found.node.name + ')'),
          via: found.via,
          recipe: recipe.id,
        };
      }
      return { kind: 'complete' };
    });
  }

  // Only verified steps are remembered, and only as (intent, role, accessible name).
  // The ref is deliberately not stored: refs die with the snapshot, and a memory
  // that replays a stale ref is how an assistant presses last week's button.
  function record(snapshot, recipe, intent, node, status) {
    if (status !== 'verified' || !recipe) return Promise.resolve(false);
    var host = urlParts(snapshot && snapshot.url).host;
    if (!host) return Promise.resolve(false);
    return storageGet(TRACE_KEY).then(function (all) {
      var store = all || {};
      var key = host + '#' + recipe;
      var list = (store[key] || []).filter(function (t) { return t.intent !== intent; });
      list.push({ intent: intent, role: node.role, name: node.name });
      store[key] = list.slice(-MAX_STEPS_KEPT);
      // The map is the VALUE of adaptiveai_traces, not the storage root:
      // writing `store` itself put every trace under a bare top-level key the
      // reader never looked at, so memory was silently never written. The
      // promise resolves when the write is acknowledged, and with whether it
      // was accepted, not merely started.
      var payload = {};
      payload[TRACE_KEY] = store;
      return new Promise(function (resolve) {
        try {
          chrome.storage.local.set(payload, function () {
            resolve(!chrome.runtime.lastError);
          });
        } catch (e) { resolve(false); }
      });
    });
  }

  function problems() { return invalid.slice(); }

  function reset() { cache = null; invalid = []; }

  var AdaptiveAIRecipes = {
    load: load, matches: matches, propose: propose, record: record,
    validate: validate, problems: problems, reset: reset, TRACE_KEY: TRACE_KEY,
  };
  global.AdaptiveAIRecipes = AdaptiveAIRecipes;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIRecipes;
})(typeof window !== 'undefined' ? window : globalThis);
