// AdaptiveAI privacy: what may leave the device, and proof that the rest does not.
//
// The planner needs to know the page's SHAPE - "there is an email field, empty,
// labelled 'Email address'" - and never its CONTENT. This module turns a snapshot
// into that structure-only form, and `findLeaks()` is the check the tests run
// against a vault that is full of real values, so "nothing leaked" is a measured
// result rather than a claim about someone's passport number.
(function (global) {
  'use strict';

  // Dropped from every node. `selector` and `identity` are internal plumbing the
  // page-side actor needs and the model does not; `value` is the user's data;
  // `bounds` is layout for a low-vision feature that is out of scope this cycle.
  var DROP = { selector: 1, identity: 1, value: 1, bounds: 1 };

  function redactNode(node) {
    var out = {};
    var keys = Object.keys(node);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (DROP[k]) continue;
      out[k] = node[k];
    }
    // Keep the fact that something was entered without keeping what was entered:
    // the planner needs "this field is already filled" to decide what to ask next.
    out.hasValue = !!node.hasValue;
    if (node.options) {
      out.options = node.options.map(function (o) { return { text: o.text }; });
    }
    return out;
  }

  function redactSnapshot(snapshot) {
    var nodes = (snapshot && snapshot.nodes ? snapshot.nodes : []).map(redactNode);
    return {
      url: snapshot && snapshot.url ? snapshot.url : '',
      title: snapshot && snapshot.title ? snapshot.title : '',
      stats: snapshot && snapshot.stats ? snapshot.stats : {},
      nodes: nodes,
    };
  }

  // Recursively collects every string in an outgoing request body so a test can
  // assert none of them is a stored value.
  function stringsIn(value, acc) {
    acc = acc || [];
    if (typeof value === 'string') { acc.push(value); return acc; }
    if (value && typeof value === 'object') {
      var keys = Object.keys(value);
      for (var i = 0; i < keys.length; i++) stringsIn(value[keys[i]], acc);
    }
    return acc;
  }

  function findLeaks(body, values) {
    var haystack = stringsIn(body);
    var joined = haystack.join('\u0000');
    var leaks = [];
    var list = values || [];
    for (var i = 0; i < list.length; i++) {
      var v = list[i];
      if (typeof v !== 'string' || v.length < 3) continue;
      if (joined.indexOf(v) !== -1) leaks.push(v);
    }
    return leaks;
  }

  var AdaptiveAIPrivacy = {
    redactNode: redactNode,
    redactSnapshot: redactSnapshot,
    findLeaks: findLeaks,
    stringsIn: stringsIn,
  };

  global.AdaptiveAIPrivacy = AdaptiveAIPrivacy;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIPrivacy;
})(typeof window !== 'undefined' ? window : globalThis);
