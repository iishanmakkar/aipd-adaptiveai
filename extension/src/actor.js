// AdaptiveAI actor: the only way this extension changes a page.
//
// THE RULE. No action returns a success status without a fact read back off the
// page afterwards. That is not style: a blind user has no way to notice a click
// that did not land, and the assistant's report is the only feedback channel that
// exists. Every branch below either proves what it claims or returns a failure
// with a reason the user can be told.
//
// Runs in the content-script world alongside ax.js (window.AdaptiveAIAX).
(function (global) {
  'use strict';

  function outcome(fields) {
    var base = { status: 'failed', action: null, ref: null, readback: null, reason: null };
    for (var k in fields) if (Object.prototype.hasOwnProperty.call(fields, k)) base[k] = fields[k];
    return base;
  }

  function collapse(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  // A structural selector is only trustworthy next to the identity it was
  // captured with. Acting on whatever now occupies the position could click a
  // different button than the one the user agreed to - so recompute, compare,
  // and refuse when they differ.
  function resolve(node, doc) {
    var el;
    try {
      el = doc.querySelector(node.selector);
    } catch (e) {
      return { error: outcome({ status: 'failed', action: null, ref: node.ref,
                                reason: 'invalid selector: ' + String(e).slice(0, 80) }) };
    }
    if (!el) {
      return { error: outcome({ status: 'not_found', ref: node.ref,
                                reason: 'the ' + node.role + ' "' + (node.name || 'unnamed') +
                                        '" is no longer on the page' }) };
    }
    var current = global.AdaptiveAIAX.describe(el, node.ref);
    if (current.identity !== node.identity) {
      return { error: outcome({ status: 'stale_ref', ref: node.ref,
                                reason: 'that position now holds a different control (' +
                                        current.identity + ' instead of ' + node.identity + ')' }) };
    }
    return { el: el, current: current };
  }

  function editableValue(el) {
    if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea') {
      return el.value === undefined ? '' : String(el.value);
    }
    return collapse(el.textContent);
  }

  function setNativeValue(el, value) {
    // React and friends keep their own copy of an input's value and overwrite a
    // directly-assigned one on the next render, so assign through the prototype
    // setter and then fire the events the framework listens for.
    var proto = el.tagName.toLowerCase() === 'textarea'
      ? global.HTMLTextAreaElement.prototype
      : el.tagName.toLowerCase() === 'input' ? global.HTMLInputElement.prototype : null;
    if (!proto) return false;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (!setter || !setter.set) return false;
    try {
      setter.set.call(el, value);
      el.dispatchEvent(new global.InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
      el.dispatchEvent(new global.Event('change', { bubbles: true }));
      return true;
    } catch (e) {
      return false;
    }
  }

  function insertText(el, value) {
    // Preferred path: focus, select any existing content, and insert through the
    // editing host. This produces genuine beforeinput/input events, so
    // controlled components, contenteditable and validation all see it exactly
    // as they would a keystroke.
    try {
      el.focus();
    } catch (e) { /* not focusable: the readback below decides whether the write worked */ }
    var tag = el.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea') {
      try {
        el.setSelectionRange(0, String(el.value || '').length);
      } catch (e) { /* number/date inputs throw on setSelectionRange */ }
    } else {
      try {
        var sel = global.getSelection();
        var range = global.document.createRange();
        range.selectNodeContents(el);
        sel.removeAllRanges();
        sel.addRange(range);
      } catch (e) { /* no selectable range: fall through */ }
    }
    var ok = false;
    try {
      ok = global.document.execCommand('insertText', false, value);
    } catch (e) {
      ok = false;
    }
    // Only a FAILED command earns the framework-level fallback. If the editing
    // host accepted the insertion but the value came back different, that
    // difference is the page's own constraint (maxlength, or an input handler
    // that vetoes) - pushing through the prototype setter would bypass it and
    // then report a value the site will reject. Found by the maxlength test.
    if (!ok && !setNativeValue(el, value)) return false;
    return editableValue(el) === value;
  }

  function fill(node, value, doc) {
    var r = resolve(node, doc);
    if (r.error) return r.error;
    var el = r.el;
    var kind = r.current.kind;

    if (kind === 'password') {
      // Never autofilled, never read, never echoed. A password manager or the
      // user does this; an assistant that typed it for them would put a
      // credential in a request path it cannot protect.
      return outcome({ status: 'refused', action: 'fill', ref: node.ref,
                       reason: 'password fields are never filled by AdaptiveAI' });
    }
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
      return outcome({ status: 'failed', action: 'fill', ref: node.ref,
                       reason: '"' + (node.name || 'field') + '" is disabled' });
    }
    if (el.readOnly) {
      return outcome({ status: 'failed', action: 'fill', ref: node.ref,
                       reason: '"' + (node.name || 'field') + '" is read-only' });
    }
    if (r.current.inShadow) {
      return outcome({ status: 'failed', action: 'fill', ref: node.ref,
                       reason: 'field is inside a shadow root the snapshot could not reach' });
    }

    var wanted = String(value);
    // Constraints the page itself imposes are checked before writing, because a
    // value the site cannot accept must never be reported as entered.
    var max = el.maxLength;
    if (typeof max === 'number' && max > 0 && wanted.length > max) {
      return outcome({ status: 'failed', action: 'fill', ref: node.ref,
                       readback: editableValue(el),
                       reason: '"' + (node.name || 'field') + '" accepts at most ' + max +
                               ' characters, this is ' + wanted.length });
    }

    var inserted = insertText(el, wanted);
    var readback = editableValue(el);
    if (!inserted || readback !== wanted) {
      return outcome({ status: 'failed', action: 'fill', ref: node.ref, readback: readback,
                       reason: 'the field holds ' + JSON.stringify(readback) +
                               ' after writing ' + JSON.stringify(wanted) });
    }
    return outcome({ status: 'verified', action: 'fill', ref: node.ref, readback: readback,
                     name: node.name });
  }

  function select(node, value, doc) {
    var r = resolve(node, doc);
    if (r.error) return r.error;
    var el = r.el;
    if (!el.options) {
      return outcome({ status: 'failed', action: 'select', ref: node.ref,
                       reason: 'that control is not a dropdown' });
    }
    var target = String(value);
    var match = null;
    for (var i = 0; i < el.options.length; i++) {
      var o = el.options[i];
      if (o.value === target || collapse(o.textContent).toLowerCase() === target.toLowerCase()) {
        match = o;
        break;
      }
    }
    if (!match) {
      var available = [];
      for (var j = 0; j < el.options.length && j < 12; j++) available.push(collapse(el.options[j].textContent));
      return outcome({ status: 'failed', action: 'select', ref: node.ref,
                       reason: '"' + target + '" is not one of: ' + available.join(', ') });
    }
    try {
      el.value = match.value;
    } catch (e) {
      return outcome({ status: 'failed', action: 'select', ref: node.ref, reason: String(e).slice(0, 80) });
    }
    el.dispatchEvent(new global.Event('input', { bubbles: true }));
    el.dispatchEvent(new global.Event('change', { bubbles: true }));

    var chosen = el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
    if (!chosen || chosen.value !== match.value) {
      return outcome({ status: 'failed', action: 'select', ref: node.ref,
                       reason: 'dropdown still shows ' + JSON.stringify(chosen ? chosen.textContent : '') });
    }
    return outcome({ status: 'verified', action: 'select', ref: node.ref,
                     readback: collapse(chosen.textContent), name: node.name });
  }

  function verifyChoice(el) {
    return !!el.checked;
  }

  function click(node, doc) {
    var r = resolve(node, doc);
    if (r.error) return r.error;
    var el = r.el;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
      return outcome({ status: 'failed', action: 'click', ref: node.ref,
                       reason: '"' + (node.name || 'control') + '" is disabled' });
    }
    var isChoice = r.current.role === 'checkbox' || r.current.role === 'radio' ||
                   r.current.kind === 'checkbox' || r.current.kind === 'radio';

    try {
      el.click();
    } catch (e) {
      return outcome({ status: 'failed', action: 'click', ref: node.ref,
                       reason: 'click threw ' + String(e).slice(0, 80) });
    }

    if (isChoice) {
      // A checkbox is verifiable right now, and "clicked" without this check was
      // the exact bug this project spent Plan A removing.
      if (verifyChoice(el)) {
        return outcome({ status: 'verified', action: 'click', ref: node.ref,
                         readback: 'checked', name: node.name });
      }
      try { el.click(); } catch (e2) { /* second pass may not be available */ }
      if (verifyChoice(el)) {
        return outcome({ status: 'verified', action: 'click', ref: node.ref,
                         readback: 'checked after a second pass', name: node.name });
      }
      return outcome({ status: 'failed', action: 'click', ref: node.ref,
                       reason: 'still unchecked after two click passes' });
    }

    // A plain button click has no observable state of its own. The page may or
    // may not have reacted - that is await_change's job, and until it runs this
    // must not be described as the action having worked.
    return outcome({ status: 'pressed', action: 'click', ref: node.ref,
                     name: node.name,
                     reason: 'unverified until the page reports the expected change' });
  }

  function focus(node, doc) {
    var r = resolve(node, doc);
    if (r.error) return r.error;
    var el = r.el;
    try { el.focus(); } catch (e) { /* activeElement comparison below decides */ }
    if (doc.activeElement === el) {
      return outcome({ status: 'verified', action: 'focus', ref: node.ref,
                       readback: 'focused', name: node.name });
    }
    return outcome({ status: 'failed', action: 'focus', ref: node.ref,
                     reason: 'the page kept focus elsewhere' });
  }

  var AdaptiveAIActor = {
    fill: fill,
    click: click,
    select: select,
    focus: focus,
    resolve: resolve,
    OUTCOME_STATUSES: ['verified', 'pressed', 'failed', 'not_found', 'stale_ref', 'refused'],
  };

  global.AdaptiveAIActor = AdaptiveAIActor;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIActor;
})(typeof window !== 'undefined' ? window : globalThis);
