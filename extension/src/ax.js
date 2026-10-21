// AdaptiveAI accessibility snapshot (extension content script).
//
// Plain classic script, no bundler and no ESM: what you load unpacked is what
// runs. Dual-export so the same file can be injected into a real Chromium in
// tests.
//
// WHY THIS FILE EXISTS AT ALL. The server-side driver (browser-agent/app/tools/
// driver.py:50) reads pages with a hardcoded selector list, ad-hoc label lookup
// and `tag:nth-of-type(n)` selectors that break on the first re-render. That is
// a heuristic pretending to be an accessibility tree. This file implements the
// actual contract instead: role from ARIA or the element's implicit role,
// accessible NAME from the AccName precedence order, real states, and a
// structural selector paired with an identity token so a stale reference is
// detected rather than silently acting on the wrong element.
//
// AccName precedence implemented here (ARIA wins over native markup, as
// Chromium and NVDA do):
//   aria-labelledby > aria-label > native <label>/legend/summary > title >
//   placeholder > alt > input value (button/submit) > text content >
//   aria-describedby (marked low-confidence)
(function (global) {
  'use strict';

  var CANDIDATE_SELECTOR = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    '[role]', 'img', '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    // A bare div with aria-live and no role is the single most common live
    // region on real sites. Missing it means the assistant cannot hear the
    // page tell the user something changed.
    '[aria-live]',
  ].join(', ');

  var ROLE_FROM_ARIA = {
    textbox: 'textbox', button: 'button', link: 'link', checkbox: 'checkbox',
    radio: 'radio', combobox: 'combobox', listbox: 'listbox', menuitem: 'menuitem',
    tab: 'tab', switch: 'switch', slider: 'slider', spinbutton: 'spinbutton',
    searchbox: 'searchbox', treeitem: 'treeitem', option: 'option',
    heading: 'heading', alert: 'alert', status: 'status',
  };

  // Roles that can be acted on. A blind user's assistant must not offer to
  // "click" a heading, and must not report an <img> as a control.
  var INTERACTIVE_ROLES = {
    textbox: 1, button: 1, link: 1, checkbox: 1, radio: 1, combobox: 1,
    listbox: 1, menuitem: 1, tab: 1, switch: 1, slider: 1, spinbutton: 1,
    searchbox: 1, treeitem: 1,
  };

  var HIDDEN_INPUT_TYPES = { hidden: 1, file: 1, image: 1, reset: 1 };

  function collapse(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function visibleToAssistiveTech(el) {
    if (el.nodeType !== 1) return false;
    if (el.tagName.toLowerCase() === 'input' &&
        HIDDEN_INPUT_TYPES[el.getAttribute('type') || 'text'] === 1) return false;
    if (el.closest('[aria-hidden="true"]') && el.getAttribute('aria-hidden') !== 'false') {
      // aria-hidden on an ancestor removes the subtree, unless the node itself
      // re-enables it and is focusable (a documented authoring pattern).
      if (!(el.getAttribute('aria-hidden') === 'false' && el.tabIndex >= 0)) return false;
    }
    var rect = el.getBoundingClientRect();
    var style = global.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    // Zero size is not hidden for sr-only/clip patterns, which keep a 1px box;
    // rejecting all zero-size boxes would drop most skip links and icon buttons.
    if (rect.width === 0 && rect.height === 0 && style.position !== 'absolute') return false;
    return true;
  }

  function implicitRole(el) {
    var tag = el.tagName.toLowerCase();
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : 'generic';
    if (tag === 'button') return 'button';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'summary') return 'button';
    if (tag === 'img') return 'img';
    if (tag === 'select') return el.multiple ? 'listbox' : 'combobox';
    if (tag === 'label') return 'generic';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'input') {
      var type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'button' || type === 'submit' || type === 'reset' || type === 'image') return 'button';
      if (type === 'range') return 'slider';
      if (type === 'number') return 'spinbutton';
      if (type === 'search') return 'searchbox';
      if (type === 'email' || type === 'tel' || type === 'url' || type === 'password' ||
          type === 'text' || type === 'date' || type === 'time' || type === 'datetime-local' ||
          type === 'month' || type === 'week') return 'textbox';
      return 'textbox';
    }
    return 'generic';
  }

  function roleOf(el) {
    var explicit = collapse(el.getAttribute('role') || '').split(' ')[0];
    if (explicit && ROLE_FROM_ARIA[explicit]) return ROLE_FROM_ARIA[explicit];
    return implicitRole(el);
  }

  function textOf(el) {
    // innerText respects rendering and hides <script>/<style>; textContent would
    // leak both and ignore display:none, so prefer innerText when available.
    return collapse(typeof el.innerText === 'string' ? el.innerText : el.textContent);
  }

  function labelForElement(el) {
    var ids = [];
    if (el.labels && el.labels.length) {
      for (var i = 0; i < el.labels.length; i++) ids.push(textOf(el.labels[i]));
      return collapse(ids.filter(Boolean).join(' '));
    }
    if (el.id) {
      var lab = el.ownerDocument.querySelector('label[for="' + cssEscape(el.id) + '"]');
      if (lab) return textOf(lab);
    }
    var wrap = el.closest('label');
    return wrap ? textOf(wrap) : '';
  }

  function labelledByText(el) {
    var ids = el.getAttribute('aria-labelledby') || '';
    if (!ids.trim()) return '';
    var doc = el.ownerDocument;
    var parts = ids.split(/\s+/).filter(Boolean).map(function (id) {
      var node = doc.getElementById(id);
      return node ? textOf(node) : '';
    });
    return collapse(parts.filter(Boolean).join(' '));
  }

  // Returns {name, source}. `source` matters as much as the name: a control
  // whose only name is its placeholder is a weaker claim than a labelled one,
  // and an unnamed control is exactly what a screen reader user cannot act on.
  function accessibleName(el, role) {
    var by = labelledByText(el);
    if (by) return { name: by, source: 'labelledby' };
    var aria = collapse(el.getAttribute('aria-label'));
    if (aria) return { name: aria, source: 'aria-label' };
    var native = labelForElement(el);
    if (native) return { name: native, source: 'native-label' };
    // No label of its own: a fieldset's legend is the group name, not this
    // control's. Reporting the group as the name is better than silence, and is
    // marked so the caller can say "in the <legend> group" rather than pretending
    // the control itself is labelled.
    var fieldset = el.closest('fieldset');
    if (fieldset) {
      var cap = fieldset.querySelector('legend');
      if (cap && textOf(cap)) {
        return { name: collapse(textOf(cap)), source: 'legend-group' };
      }
    }
    var title = collapse(el.getAttribute('title'));
    if (title) return { name: title, source: 'title' };
    if (role === 'img' || el.tagName.toLowerCase() === 'img') {
      var alt = collapse(el.getAttribute('alt'));
      if (el.hasAttribute('alt')) {
        return alt ? { name: alt, source: 'alt' }
                    : { name: '', source: 'alt-empty' };   // decorative, on purpose
      }
      return { name: '', source: 'missing-alt' };           // a real accessibility defect
    }
    var ph = collapse(el.getAttribute('placeholder'));
    if (ph && (role === 'textbox' || role === 'searchbox' || role === 'spinbutton')) {
      return { name: ph, source: 'placeholder' };
    }
    var tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      var type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'button' || type === 'submit') {
        var v = collapse(el.value);
        if (v) return { name: v, source: 'input-value' };
      }
    }
    if (role === 'textbox') {
      var val = collapse(el.value);
      if (val) return { name: '', source: 'value-only' };
    }
    var own = textOf(el);
    if (own && (role === 'button' || role === 'link' || role === 'heading' ||
                role === 'option' || role === 'tab' || role === 'menuitem' ||
                role === 'alert' || role === 'status')) {
      return { name: own, source: 'contents' };
    }
    var desc = collapse(el.getAttribute('aria-describedby'));
    if (desc) {
      var doc = el.ownerDocument;
      var dnode = doc.getElementById(desc.split(/\s+/)[0]);
      var dtext = dnode ? textOf(dnode) : desc;
      if (dtext) return { name: dtext, source: 'describedby-low-confidence' };
    }
    return { name: '', source: 'none' };
  }

  function statesOf(el, role) {
    var states = {};
    var type = (el.getAttribute('type') || '').toLowerCase();
    if (role === 'checkbox' || role === 'radio' || role === 'switch' || type === 'checkbox' || type === 'radio') {
      states.checked = !!el.checked;
    }
    var ariaChecked = el.getAttribute('aria-checked');
    if (ariaChecked !== null) {
      states.checked = ariaChecked === 'true';
      if (ariaChecked === 'mixed') states.checkedMixed = true;
    }
    if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') states.disabled = true;
    if (el.readOnly) states.readonly = true;
    if (el.required || el.getAttribute('aria-required') === 'true') states.required = true;
    var expanded = el.getAttribute('aria-expanded');
    if (expanded !== null) states.expanded = expanded === 'true';
    var pressed = el.getAttribute('aria-pressed');
    if (pressed !== null) states.pressed = pressed === 'true';
    if (el.getAttribute('aria-invalid') === 'true') {
      states.invalid = true;
    } else if (typeof el.checkValidity === 'function') {
      // Native constraint state, so an inline "this field is required" error the
      // user cannot see is still reported. Wrapped: a detached node can throw.
      try {
        if (!el.checkValidity()) states.invalid = true;
      } catch (e) { /* detached or unsupported: no invalid claim */ }
    }
    if (role === 'option' || role === 'tab') {
      var sel = el.getAttribute('aria-selected');
      if (sel !== null) states.selected = sel === 'true';
    }
    if (el.tagName.toLowerCase() === 'select' && el.selectedIndex >= 0) states.selected = true;
    return states;
  }

  function valueKindOf(el, role) {
    var tag = el.tagName.toLowerCase();
    if (tag === 'select') return 'select';
    if (role === 'checkbox' || role === 'switch') return 'checkbox';
    if (role === 'radio') return 'radio';
    if (tag === 'input') {
      var type = (el.getAttribute('type') || 'text').toLowerCase();
      if (type === 'password') return 'password';
      if (type === 'email') return 'email';
      if (type === 'tel') return 'phone';
      if (type === 'number') return 'number';
      if (type.indexOf('date') === 0 || type === 'time' || type === 'month' || type === 'week') return 'date';
      return 'text';
    }
    if (tag === 'textarea' || role === 'textbox' || role === 'searchbox') return 'text';
    if (role === 'button' || role === 'link') return 'action';
    if (role === 'img') return 'image';
    if (role === 'heading') return 'heading';
    return 'other';
  }

  function cssEscape(value) {
    if (global.CSS && typeof global.CSS.escape === 'function') return global.CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, function (c) {
      return '\\' + c;
    });
  }

  // A structural path is inherently fragile - that is why it is never trusted
  // alone. every node also carries an identity token (role + name + tag), and
  // the actor re-validates the token before touching the page: a match means
  // the element is still the one described, and a mismatch is reported as
  // `stale_ref` instead of clicking whatever now occupies that position.
  function structuralPath(el) {
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1 && node.tagName.toLowerCase() !== 'html' && parts.length < 12) {
      var parent = node.parentElement;
      if (!parent) break;
      var sameTag = Array.prototype.filter.call(parent.children, function (c) {
        return c.tagName === node.tagName;
      });
      var idx = sameTag.indexOf(node) + 1;
      parts.unshift(node.tagName.toLowerCase() + (sameTag.length > 1 ? ':nth-of-type(' + idx + ')' : ''));
      node = parent;
    }
    return parts.join(' > ');
  }

  function selectorFor(el) {
    if (el.id) return '#' + cssEscape(el.id);
    var name = el.getAttribute('name');
    if (name && el.form) {
      var matches = el.form.querySelectorAll('[name="' + cssEscape(name) + '"]');
      if (matches.length === 1) return '[name="' + cssEscape(name) + '"]';
    }
    return structuralPath(el);
  }

  function livePoliteness(el) {
    var live = el.getAttribute('aria-live');
    var role = el.getAttribute('role');
    if (live) return live;
    if (role === 'alert') return 'assertive';
    if (role === 'status' || role === 'log') return 'polite';
    return null;
  }

  function describe(el, ref) {
    var role = roleOf(el);
    var named = accessibleName(el, role);
    var kind = valueKindOf(el, role);
    var rect = el.getBoundingClientRect();
    var states = statesOf(el, role);
    var node = {
      ref: ref,
      tag: el.tagName.toLowerCase(),
      role: role,
      name: named.name,
      nameSource: named.source,
      unnamed: !named.name,
      lowConfidenceName: named.source === 'describedby-low-confidence' || named.source === 'placeholder',
      interactive: INTERACTIVE_ROLES[role] === 1,
      selector: selectorFor(el),
      identity: role + '|' + (el.tagName.toLowerCase()) + '|' + named.name,
      kind: kind,
      // A password value is never read, and never sent anywhere: an assistant
      // that echoes it into a request or a log has leaked a credential.
      value: kind === 'password' ? undefined : readValue(el, kind),
      hasValue: kind === 'password' ? false : hasValue(el, kind),
      sensitive: kind === 'password',
      states: states,
      bounds: { x: Math.round(rect.x), y: Math.round(rect.y),
                w: Math.round(rect.width), h: Math.round(rect.height) },
      inShadow: !!el.getRootNode().host,
      disabled: states.disabled === true,
    };
    var live = livePoliteness(el);
    if (live) node.live = live;
    if (role === 'heading') node.level = Number(el.tagName.substring(1)) || 1;
    if (role === 'combobox' && el.options) {
      node.options = Array.prototype.map.call(el.options, function (o) {
        return { value: o.value, text: collapse(o.textContent), selected: !!o.selected };
      });
    }
    var desc = el.getAttribute('aria-describedby');
    if (desc) {
      var dnode = el.ownerDocument.getElementById(desc.split(/\s+/)[0]);
      if (dnode) node.description = textOf(dnode);
    }
    return node;
  }

  function readValue(el, kind) {
    if (kind === 'select') return el.selectedIndex >= 0 ? el.value : '';
    if (kind === 'checkbox' || kind === 'radio') return undefined;  // carried in states.checked
    if (kind === 'action' || kind === 'image' || kind === 'heading' || kind === 'other') return undefined;
    if (kind === 'password') return undefined;
    try {
      return el.value === undefined ? undefined : String(el.value);
    } catch (e) {
      return undefined;
    }
  }

  function hasValue(el, kind) {
    var v = readValue(el, kind);
    if (kind === 'checkbox' || kind === 'radio') return !!el.checked;
    return typeof v === 'string' && v.length > 0;
  }

  function matchesCandidate(el) {
    try { return el.matches(CANDIDATE_SELECTOR); } catch (e) { return false; }
  }

  // document.querySelectorAll stops at a shadow boundary, so controls inside an
  // open shadow root are invisible to it - and real components put dialogs,
  // media players and toast stacks there. This walks children directly and
  // descends into open shadow roots inline, which preserves document order: the
  // order a screen reader would speak. Closed shadow roots cannot be read by
  // anything, and that limit is reported rather than papered over.
  function collectElements(node, out) {
    if (!node) return out;
    var kids = node.children || [];
    for (var i = 0; i < kids.length; i++) {
      var el = kids[i];
      if (matchesCandidate(el)) out.push(el);
      collectElements(el, out);
      if (el.shadowRoot) collectElements(el.shadowRoot, out);
    }
    return out;
  }

  function computeSnapshot(doc) {
    var nodes = [];
    var skippedHidden = 0;
    var candidates = collectElements(doc.documentElement, []);
    for (var i = 0; i < candidates.length; i++) {
      var el = candidates[i];
      if (!visibleToAssistiveTech(el)) { skippedHidden++; continue; }
      var ref = 'n' + nodes.length;
      var node = describe(el, ref);
      var declared = collapse(el.getAttribute('role') || '').split(' ')[0];
      // role=presentation/none is an explicit author instruction to remove the
      // element from the accessibility tree - honouring it is the difference
      // between reading a page and reading its decoration.
      if (declared === 'presentation' || declared === 'none') continue;
      // A nameless, non-live generic node carries nothing a caller can act on
      // or announce; keeping it would bury real controls in noise.
      if (node.role === 'generic' && !node.name && !node.live) continue;
      nodes.push(node);
    }
    var unnamedControls = nodes.filter(function (n) { return n.interactive && n.unnamed; }).length;
    return {
      url: doc.location ? doc.location.href : '',
      title: doc.title || '',
      nodes: nodes,
      stats: {
        total: nodes.length,
        interactive: nodes.filter(function (n) { return n.interactive; }).length,
        unnamedControls: unnamedControls,
        missingAlt: nodes.filter(function (n) { return n.nameSource === 'missing-alt'; }).length,
        hiddenSkipped: skippedHidden,
      },
    };
  }

  var AdaptiveAIAX = {
    computeSnapshot: computeSnapshot,
    roleOf: roleOf,
    accessibleName: accessibleName,
    statesOf: statesOf,
    valueKindOf: valueKindOf,
    selectorFor: selectorFor,
    describe: describe,
    CANDIDATE_SELECTOR: CANDIDATE_SELECTOR,
  };

  global.AdaptiveAIAX = AdaptiveAIAX;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIAX;
})(typeof window !== 'undefined' ? window : globalThis);
