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
  document.getElementById('setup').addEventListener('click', function () {
    chrome.runtime.openOptionsPage();
  });
  request();

  // ---- the task surface ----------------------------------------------------
  //
  // Typing a goal here drives the same loop the voice path drives. The reply
  // arrives when the RUN ends, not when the first step does, so the status line
  // says it is working rather than going quiet; and if this popup is dismissed
  // mid-run the loop keeps going in the worker, because it never lived here.
  var goalEl = document.getElementById('goal');
  var askEl = document.getElementById('ask');
  var askText = document.getElementById('ask-text');
  var transcriptEl = document.getElementById('transcript');
  var transcriptTitle = document.getElementById('transcript-title');
  var noteEl = document.getElementById('transcript-note');

  function send(message) {
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage(message, function (reply) {
          resolve(chrome.runtime.lastError ? null : reply);
        });
      } catch (e) { resolve(null); }
    });
  }

  function renderRun(result) {
    if (!result) return;
    transcriptTitle.hidden = false;
    transcriptEl.textContent = '';
    (result.steps || []).forEach(function (step) {
      var li = document.createElement('li');
      li.className = 'step';
      li.textContent = (step.description || step.action || '(no description)') +
        ' — ' + step.status + (step.reason ? ' (' + step.reason + ')' : '');
      transcriptEl.appendChild(li);
    });
    noteEl.textContent = 'Result: ' + result.status + '. ' +
      (result.stepsVerified || 0) + ' of ' + (result.steps || []).length +
      ' step(s) verified.';
  }

  async function runTask() {
    var goal = (goalEl.value || '').trim();
    if (!goal) { say('Tell me what to do first.'); goalEl.focus(); return; }
    say('Working on: ' + goal);
    var reply = await send({ type: 'adaptiveai:run-task', goal: goal });
    if (!reply) { say('The assistant did not answer. Its service worker may have stopped - try again.'); return; }
    if (!reply.ok) { say('I could not start: ' + (reply.reason || 'unknown reason')); return; }
    renderRun(reply.result);
  }

  async function pollQuestion() {
    var reply = await send({ type: 'adaptiveai:pending-question' });
    if (reply && reply.question) {
      askEl.hidden = false;
      askText.textContent = reply.question;
    } else {
      askEl.hidden = true;
    }
    if (reply && reply.running) {
      var last = await send({ type: 'adaptiveai:last-run' });
      if (last && last.result) renderRun(last.result);
    }
  }

  document.getElementById('run').addEventListener('click', runTask);
  document.getElementById('listen').addEventListener('click', async function () {
    say('Listening. Speak now.');
    // The capture and the transcription both happen in the worker; this page only
    // shows the words. If the microphone, the permission or the transcriber
    // failed, the reason is said plainly rather than leaving an empty box.
    var reply = await send({ type: 'adaptiveai:voice', maxMs: 8000 });
    if (!reply || !reply.ok) {
      say('I could not hear you: ' + ((reply && reply.reason) || 'no answer'));
      return;
    }
    goalEl.value = reply.text;
    say('You said: ' + reply.text);
  });
  goalEl.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); runTask(); }
  });
  [['yes', 'yes'], ['no', 'no']].forEach(function (pair) {
    document.getElementById(pair[0]).addEventListener('click', async function () {
      await send({ type: 'adaptiveai:answer', answer: pair[1] });
      askEl.hidden = true;
      say(pair[1] === 'yes' ? 'Answered yes.' : 'Answered no.');
    });
  });
  setInterval(pollQuestion, 700);
  pollQuestion();
  send({ type: 'adaptiveai:last-run' }).then(function (reply) {
    if (reply && reply.result) renderRun(reply.result);
  });
})();
