// AdaptiveAI profile vault: where a user's own details live, on their machine.
//
// THE POINT. A blind user should say "book a ticket for me" once and never dictate
// a passport number, DOB or phone number again. But the only way that stays safe is
// if the values never leave the device: the planner sends field LABELS and the
// extension resolves them locally. This module is the sole holder of the values, it
// runs in the service worker, and `availableLabels()` is the only thing that may
// cross the network.
(function (global) {
  'use strict';

  var STORE_KEY = 'adaptiveai_profile';
  var injected = null;

  function useStore(store) { injected = store; }

  function store() {
    if (injected) return injected;
    if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
      return chrome.storage.local;
    }
    return null;
  }

  function normalise(label) {
    return String(label || '')
      .toLowerCase()
      .replace(/\((required|optional|mandatory)\)/g, ' ')
      .replace(/\*/g, ' ')
      .replace(/[^a-z0-9 ]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  // Page authors call the same datum many things. This is a naming table, not a
  // site adapter: no selector, no origin, nothing that rots when a vendor ships.
  var SYNONYMS = {
    'email': ['email', 'email address', 'e mail', 'email id'],
    'phone': ['phone', 'mobile', 'mobile number', 'contact number', 'phone number', 'cell'],
    'full name': ['full name', 'name', 'passenger name', 'traveller name',
                  'customer name', 'your name', 'citizen full name'],
    'date of birth': ['date of birth', 'dob', 'birth date', 'birthday'],
    'pan number': ['pan', 'pan number', 'income tax pan', 'permanent account number'],
    'aadhaar number': ['aadhaar', 'aadhaar number', 'uidai', 'adhaar'],
    'city': ['city', 'town', 'location'],
    'address': ['address', 'permanent address', 'current address'],
    'pin code': ['pin code', 'pin', 'zip', 'zip code', 'postal code', 'postcode'],
    'passport': ['passport', 'passport number'],
  };

  // Word boundaries, not substring containment: `"capacity".indexOf("city")`
  // matches, and a field silently filed under the wrong label is worse than one
  // the assistant admits it does not know.
  function mentions(haystack, needle) {
    if (haystack === needle) return true;
    var re = new RegExp('(^| )' + needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '( |$)');
    return re.test(haystack);
  }

  function canonical(label) {
    var n = normalise(label);
    if (!n) return '';
    var keys = Object.keys(SYNONYMS);
    var best = null;
    var bestLength = 0;
    for (var i = 0; i < keys.length; i++) {
      var list = SYNONYMS[keys[i]];
      for (var j = 0; j < list.length; j++) {
        if (mentions(n, list[j]) && list[j].length > bestLength) {
          best = keys[i];
          bestLength = list[j].length;
        }
      }
    }
    return best || n;
  }

  // Passwords and OTPs are not profile data. Storing them would put a credential on
  // disk for no benefit - the user types those, and an assistant that filled them
  // could not tell the site from an attacker.
  var NEVER_STORED = ['password', 'otp', 'one time password', 'cvv', 'cvc', 'pin number'];

  function isNeverStored(label) {
    var n = normalise(label);
    for (var i = 0; i < NEVER_STORED.length; i++) {
      if (mentions(n, NEVER_STORED[i])) return true;
    }
    return false;
  }

  function read() {
    var s = store();
    if (!s) return Promise.resolve({});
    return new Promise(function (resolve) {
      s.get([STORE_KEY], function (data) {
        resolve((data && data[STORE_KEY]) || {});
      });
    });
  }

  function write(map) {
    var s = store();
    if (!s) return Promise.resolve(false);
    return new Promise(function (resolve) {
      var payload = {};
      payload[STORE_KEY] = map;
      s.set(payload, function () { resolve(true); });
    });
  }

  function set(label, value) {
    if (isNeverStored(label)) {
      return Promise.resolve({ ok: false, reason: 'AdaptiveAI never stores ' + label });
    }
    var key = canonical(label);
    if (!key) return Promise.resolve({ ok: false, reason: 'no field name given' });
    return read().then(function (map) {
      map[key] = String(value);
      return write(map).then(function () { return { ok: true, label: key }; });
    });
  }

  function resolve(label) {
    if (isNeverStored(label)) return Promise.resolve(null);
    var key = canonical(label);
    return read().then(function (map) {
      return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : null;
    });
  }

  // The only export that may reach the backend: which fields exist, never what
  // they hold.
  function availableLabels() {
    return read().then(function (map) { return Object.keys(map).sort(); });
  }

  function wipe() {
    var s = store();
    if (!s) return Promise.resolve(false);
    return new Promise(function (resolve) { s.remove([STORE_KEY], function () { resolve(true); }); });
  }

  var AdaptiveAIVault = {
    set: set,
    resolve: resolve,
    availableLabels: availableLabels,
    wipe: wipe,
    canonical: canonical,
    normalise: normalise,
    isNeverStored: isNeverStored,
    useStore: useStore,
  };

  global.AdaptiveAIVault = AdaptiveAIVault;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAIVault;
})(typeof window !== 'undefined' ? window : globalThis);
