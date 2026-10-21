// Popup controller: reports what the content script could actually see.
//
// The counts are not decoration. "Controls with no name" and "images without
// alt text" are the two things a blind user cannot discover for themselves, and
// this surface says them plainly instead of implying the page was read fine.
(function () {
  'use strict';

  var statusEl = document.getElementById('status');
  var reportEl = document.getElementById('report');
  var interactiveEl = document.getElementById('interactive');
  var unnamedEl = document.getElementById('unnamed');
  var missingAltEl = document.getElementById('missing-alt');

  function say(text) { statusEl.textContent = text; }

  function render(snap) {
    reportEl.hidden = false;
    interactiveEl.textContent = String(snap.stats.interactive);
    unnamedEl.textContent = String(snap.stats.unnamedControls);
    missingAltEl.textContent = String(snap.stats.missingAlt);
    if (snap.stats.interactive === 0) {
      say('I see no controls I can act on here.');
      return;
    }
    var problems = [];
    if (snap.stats.unnamedControls > 0) {
      problems.push(snap.stats.unnamedControls + ' control(s) have no accessible name');
    }
    if (snap.stats.missingAlt > 0) {
      problems.push(snap.stats.missingAlt + ' image(s) have no alt text');
    }
    say('Found ' + snap.stats.interactive + ' act-able controls' +
        (problems.length ? '. Warning: ' + problems.join(', ') : '.'));
  }

  function request() {
    say('Reading this page...');
    chrome.runtime.sendMessage({ type: 'adaptiveai:get-page-snapshot' }, function (reply) {
      if (chrome.runtime.lastError || !reply || !reply.ok) {
        reportEl.hidden = true;
        var why = reply && reply.reason ? reply.reason : String(
          chrome.runtime.lastError && chrome.runtime.lastError.message);
        say('I cannot read this page: ' + why +
            '. Browser pages and ungranted sites are out of reach by design.');
        return;
      }
      render(reply.snapshot);
    });
  }

  document.getElementById('recheck').addEventListener('click', request);
  request();
})();
