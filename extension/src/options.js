// Options page: the only way the vault ever gets filled.
//
// Without this the "fills in my details" claim is unreachable - a user cannot
// store what the assistant is supposed to remember. The page is plain labelled
// form controls in one column with visible focus and a live status region, because
// the person setting this up is the same person who will rely on it later.
(function () {
  'use strict';

  var statusEl = document.getElementById('status');

  // Element id -> the canonical label the vault stores it under. Keeping this
  // list small on purpose: every entry is a field a booking or government form
  // actually asks for, not a generic key/value bag.
  var FIELDS = [
    ['f-full-name', 'full name'],
    ['f-date-of-birth', 'date of birth'],
    ['f-pan-number', 'pan number'],
    ['f-aadhaar-number', 'aadhaar number'],
    ['f-passport', 'passport'],
    ['f-email', 'email'],
    ['f-phone', 'phone'],
    ['f-address', 'address'],
    ['f-city', 'city'],
    ['f-pin-code', 'pin code'],
  ];

  function say(message) { statusEl.textContent = message; }

  function load() {
    var pending = FIELDS.map(function (pair) {
      return AdaptiveAIVault.resolve(pair[1]).then(function (value) {
        if (value) document.getElementById(pair[0]).value = value;
      });
    });
    pending.push(AdaptiveAIVault.spendCeiling().then(function (n) {
      if (n != null) document.getElementById('f-ceiling').value = String(n);
    }));
    Promise.all(pending).then(function () {
      say('Loaded what is already saved on this computer.');
    });
  }

  function save(event) {
    if (event) event.preventDefault();
    var pairs = [];
    FIELDS.forEach(function (pair) {
      var value = document.getElementById(pair[0]).value.trim();
      if (value) pairs.push([pair[1], value]);
    });
    var ceilingRaw = document.getElementById('f-ceiling').value.trim();
    var ceiling = ceilingRaw ? AdaptiveAIVault.setSpendCeiling(ceilingRaw) : Promise.resolve(null);

    // One batched write: concurrent per-field saves each read the same starting
    // map and the last one won, so a filled-in form quietly lost fields.
    AdaptiveAIVault.setMany(pairs).then(function (res) {
      return ceiling.then(function () { return res; });
    }).then(function (res) {
      var n = res.saved;
      say(n === 1 ? 'Saved 1 detail on this computer.'
                  : 'Saved ' + n + ' details on this computer.');
    });
    return false;
  }

  // Two deliberate presses rather than a browser dialog: window.confirm steals
  // focus and is awkward to operate with a screen reader, and an accidental
  // single press should never destroy someone's stored details.
  var armedToDelete = false;
  var armTimer = null;

  function wipe() {
    if (!armedToDelete) {
      armedToDelete = true;
      say('This will delete every saved detail. Press "Delete everything" again '
          + 'within 10 seconds to confirm.');
      armTimer = setTimeout(function () {
        armedToDelete = false;
        say('Delete cancelled. Nothing was removed.');
      }, 10000);
      return;
    }
    clearTimeout(armTimer);
    armedToDelete = false;
    AdaptiveAIVault.wipe().then(function () {
      FIELDS.forEach(function (pair) { document.getElementById(pair[0]).value = ''; });
      document.getElementById('f-ceiling').value = '';
      say('Deleted. No details are stored on this computer any more.');
    });
  }

  document.getElementById('details').addEventListener('submit', save);
  document.getElementById('wipe').addEventListener('click', wipe);
  load();
})();
