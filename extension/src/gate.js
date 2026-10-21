// AdaptiveAI gate: the local, deterministic refusal to do anything that costs
// money or cannot be undone.
//
// WHY THIS LIVES IN THE EXTENSION AND NOT IN THE MODEL. The planner is a remote
// LLM answering over a network; it can be steered, it can be wrong, and it cannot
// see the page the way the user does. A safety rule that only exists in a prompt
// is a suggestion. This file is evaluated in the content script before the click
// is dispatched, so a planner response cannot talk it out of the rule - the only
// thing that opens the gate is an explicit confirmation that came from the user.
//
// Deliberately narrow. Over-gating is its own failure: a user dismissed by four
// false alarms will answer "yes" to the fifth without hearing it. Anything that is
// merely a step forward - Next, Continue, Add to cart, Select seats - is NOT gated.
(function (global) {
  'use strict';

  var COMMIT_PATTERNS = [
    { re: /\bpay\b/i,                                        why: 'it spends money' },
    { re: /\bpayment\b/i,                                     why: 'it spends money' },
    { re: /\bproceed\s+to\s+(the\s+)?pay(ment)?\b/i,           why: 'it opens the payment step' },
    { re: /\bcheckout\b/i,                                    why: 'it commits the order' },
    { re: /\bplace\s+(the\s+|your\s+)?order\b/i,               why: 'it commits an order' },
    { re: /\bconfirm\s+(the\s+|your\s+)?(booking|order|purchase)\b/i, why: 'it confirms a purchase' },
    { re: /\bbook\s+(now|today|it|these|your|a|the)?\b/i,       why: 'it reserves and usually charges' },
    { re: /\bsubmit\s+(the\s+|your\s+)?(application|form|return)\b/i, why: 'it files something official' },
    { re: /\b(add|save)\s+(a\s+|your\s+|new\s+)?card\b/i,       why: 'it stores a payment method' },
    { re: /\bdelete\s+(my\s+)?(account|booking|order)\b/i,      why: 'it cannot be undone' },
    { re: /\bcancel\s+(my\s+|the\s+)?(booking|ticket|order)\b/i, why: 'cancellation may be final' },
    { re: /\bcreate\s+(an?\s+)?account\b/i,                     why: 'it registers you somewhere' },
  ];

  // Payment processors, not "sites". This is a safety predicate: a control inside
  // one of these frames is acting on money no matter how innocuous its label is.
  var PAYMENT_FRAME_HOSTS = [
    'razorpay', 'payu', 'payumoney', 'billdesk', 'accesse', 'cashfree',
    'paypal', 'stripe', 'hopwork', 'dotpay', 'bharatpe',
  ];

  var AMOUNT_RE = /(?:₹|rs\.?|inr|\$|£|€)\s?([0-9][0-9,.]*)|([0-9][0-9,.]*)\s*(?:rupees|inr)/i;

  function parseAmount(text) {
    var m = AMOUNT_RE.exec(text || '');
    if (!m) return null;
    var raw = (m[1] || m[2] || '').replace(/,/g, '');
    var value = parseFloat(raw);
    if (!isFinite(value) || value <= 0) return null;
    var currency = /(\$)/.test(text) ? 'USD' : /(£)/.test(text) ? 'GBP'
      : /(€)/.test(text) ? 'EUR' : 'INR';
    return { value: value, currency: currency, text: m[0].trim() };
  }

  // context: { origin, frameUrl } - frameUrl is the frame the control lives in,
  // which the snapshot already knows.
  function classify(node, context) {
    var name = (node && node.name) || '';
    var ctx = context || {};
    var amount = parseAmount(name);
    var matched = null;
    for (var i = 0; i < COMMIT_PATTERNS.length; i++) {
      if (COMMIT_PATTERNS[i].re.test(name)) { matched = COMMIT_PATTERNS[i]; break; }
    }
    var inPaymentFrame = false;
    var frame = (ctx.frameUrl || '').toLowerCase();
    if (frame && node && node.inPaymentFrame) inPaymentFrame = true;
    if (frame) {
      for (var j = 0; j < PAYMENT_FRAME_HOSTS.length; j++) {
        if (frame.indexOf(PAYMENT_FRAME_HOSTS[j]) !== -1) { inPaymentFrame = true; break; }
      }
    }

    var gated = !!matched || inPaymentFrame;
    return {
      gated: gated,
      name: name,
      reason: gated
        ? (matched ? matched.why : 'it is inside a payment processor frame')
        : null,
      amount: amount,
      // A ceiling above which one confirmation is not enough. The caller supplies
      // it from the user's own settings; nothing here invents a limit.
      exceedsCeiling: !!(amount && ctx.spendCeiling != null && amount.value > ctx.spendCeiling),
      whyNotGated: gated ? null : 'no commitment detected in this control’s name',
    };
  }

  var AdaptiveAIGate = {
    classify: classify,
    parseAmount: parseAmount,
    COMMIT_PATTERNS: COMMIT_PATTERNS,
    PAYMENT_FRAME_HOSTS: PAYMENT_FRAME_HOSTS,
  };

  global.AdaptiveAIGate = AdaptiveAIGate;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIGate;
})(typeof window !== 'undefined' ? window : globalThis);
