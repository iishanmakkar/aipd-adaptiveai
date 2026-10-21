// AdaptiveAI service worker.
//
// This is the loop: goal -> plan (backend) -> act (content script) -> verify
// (watch.js) -> narrate (offscreen speech), with the spending gate in front of
// every click and no success claim without a readback. The worker owns the loop
// and nothing else - it holds no model of the page and makes no decision about
// money, both of which live somewhere that can be tested.
// Classic worker (no "type": "module"): a module worker has no importScripts and
// would fail to install over one unnecessary line. The vault is shared with the
// options page through chrome.storage.local, so the worker can read profile labels
// and the spending ceiling without either page holding the values itself.
// Paths are relative to THIS script's URL, so 'vault.js' - writing
// 'src/vault.js' asks for src/src/vault.js, the import throws, and the worker
// silently never activates.
importScripts('vault.js');
importScripts('privacy.js', 'planner.js', 'runner.js', 'speech.js');

chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:get-settings') {
    if (typeof AdaptiveAIVault === 'undefined') {
      // Answer, do not hang: a caller awaiting a reply that never comes turns a
      // broken install into a frozen UI.
      sendResponse({ ok: false, reason: 'vault script not loaded in the worker' });
      return false;
    }
    Promise.all([AdaptiveAIVault.availableLabels(), AdaptiveAIVault.spendCeiling()])
      .then(function (r) { sendResponse({ labels: r[0], spendCeiling: r[1] }); })
      .catch(function (e) {
        // An unavailable store is reported, not answered with an empty profile:
        // "I have no details" and "I could not read my details" are different
        // things to tell a user.
        sendResponse({ ok: false, reason: String(e).slice(0, 120) });
      });
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(function (details) {
  chrome.storage.local.set({ adaptiveai_installed_at: Date.now(),
                             adaptiveai_install_reason: details.reason });
});

// Ask the active tab's content script for its accessibility snapshot.
chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:tab-ready') {
    // A tab announcing itself is also what wakes this worker on a cold profile.
    // Recorded so the task runner knows which tabs are live without asking for
    // the "tabs" permission (which would expose every URL the user visits).
    sendResponse({ ok: true });
    return false;
  }
  if (message.type !== 'adaptiveai:get-page-snapshot') return false;
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var tab = tabs && tabs[0];
    if (!tab || !tab.id) {
      sendResponse({ ok: false, reason: 'no active tab' });
      return;
    }
    snapshotOf(tab.id).then(sendResponse);
  });
  return true;  // asynchronous sendResponse
});

function snapshotOf(tabId) {
  return new Promise(function (resolve) {
    try {
      chrome.tabs.sendMessage(tabId, { type: 'adaptiveai:snapshot', force: true },
        function (snap) {
          if (chrome.runtime.lastError || !snap) {
            // Most common real cause: the tab is a chrome:// page, the Web Store,
            // or an origin the user has not granted yet. Say which, never return
            // an empty snapshot as if the page were simply blank.
            resolve({ ok: false,
                      reason: 'no content script on this page',
                      detail: chrome.runtime.lastError
                        ? chrome.runtime.lastError.message : 'no response' });
            return;
          }
          resolve({ ok: true, snapshot: snap });
        });
    } catch (e) {
      resolve({ ok: false, reason: String(e).slice(0, 120) });
    }
  });
}

// ---- the task loop ------------------------------------------------------------
//
// One run at a time, because two loops pressing controls in the same tab is not
// concurrency, it is a race on a page that a blind user cannot see.
var ACTIVE = null;
var LAST = null;
var ANSWER = null;   // the pending gate question's resolver, if any
var QUESTION = null; // and the words the user is being asked to answer

function clearQuestion() { QUESTION = null; ANSWER = null; }

// How long a spending confirmation waits before it counts as a no. The default is
// 45 s because that is generous enough for someone using a screen reader to find
// the answer control; it is a device-local setting, never something the planner
// or the server can raise.
var DEFAULT_ANSWER_MS = 45000;

function readAnswerTimeout() {
  return new Promise(function (resolve) {
    try {
      chrome.storage.local.get(['adaptiveai_answer_timeout_ms'], function (data) {
        var v = Number(data && data.adaptiveai_answer_timeout_ms);
        resolve(v >= 250 && v <= 120000 ? v : DEFAULT_ANSWER_MS);
      });
    } catch (e) { resolve(DEFAULT_ANSWER_MS); }
  });
}

function remember(result) {
  LAST = result;
  try {
    chrome.storage.session.set({ adaptiveai_last_run: result }, function () {
      void chrome.runtime.lastError;   // session storage is best-effort here
    });
  } catch (e) { /* the in-memory copy above is what the popup reads */ }
}

function answer(timeoutMs) {
  return new Promise(function (resolve) {
    var timer = setTimeout(function () {
      clearQuestion();
      // Silence is a no. A confirmation that times out as approval would let the
      // most reliable failure - a user who did not hear the question - spend money.
      resolve(false);
    }, timeoutMs || 45000);
    ANSWER = function (reply) {
      clearTimeout(timer);
      clearQuestion();
      resolve(String(reply).toLowerCase() === 'yes' || reply === true);
    };
  });
}

async function runTask(goal) {
  if (ACTIVE) {
    return { ok: false, reason: 'I am already working on: ' + ACTIVE };
  }
  if (!goal || !String(goal).trim()) {
    return { ok: false, reason: 'no goal was given' };
  }
  var tab = await new Promise(function (resolve) {
    chrome.tabs.query({ active: true, currentWindow: true },
                      function (tabs) { resolve(tabs && tabs[0]); });
  });
  if (!tab || !tab.id) return { ok: false, reason: 'no active tab' };

  var first = await snapshotOf(tab.id);
  if (!first.ok) return first;

  ACTIVE = String(goal).slice(0, 200);
  var planner = AdaptiveAIPlanner.create({ vault: AdaptiveAIVault,
                                           privacy: AdaptiveAIPrivacy });
  var ceiling = await AdaptiveAIVault.spendCeiling();
  var confirmMs = await readAnswerTimeout();
  var started = Date.now();
  try {
    var result = await AdaptiveAIRunner.run({
      goal: String(goal),
      spendCeiling: ceiling,
      snapshot: function () { return snapshotOf(tab.id).then(function (r) {
        return r.ok ? r.snapshot : null;
      }); },
      availableLabels: function () { return AdaptiveAIVault.availableLabels(); },
      nextStep: planner.nextStep,
      send: function (action) {
        return new Promise(function (resolve) {
          var message = { type: 'adaptiveai:act' };
          Object.keys(action || {}).forEach(function (k) { message[k] = action[k]; });
          try {
            chrome.tabs.sendMessage(tab.id, message, function (outcome) {
              if (chrome.runtime.lastError) {
                resolve({ status: 'failed',
                          reason: chrome.runtime.lastError.message.slice(0, 140) });
                return;
              }
              resolve(outcome || { status: 'failed', reason: 'no outcome returned' });
            });
          } catch (e) {
            resolve({ status: 'failed', reason: String(e).slice(0, 140) });
          }
        });
      },
      confirm: function (record, verdict) {
        QUESTION = 'About to ' + (record.description || record.action) +
          (verdict.amount && verdict.amount.text
            ? ' for ' + verdict.amount.text : '') +
          (verdict.reason ? '. This ' + verdict.reason : '') +
          '. Do you want me to go ahead?';
        return answer(confirmMs);
      },
      narrate: function (text) { AdaptiveAISpeech.speak(text); },
    });
    result.elapsedMs = Date.now() - started;
    result.historyLength = planner.history().length;
    remember(result);
    return { ok: true, result: result };
  } catch (e) {
    var failure = { goal: goal, status: 'crashed', steps: [], narration: [],
                    stepsVerified: 0, reason: String(e).slice(0, 200) };
    remember(failure);
    return { ok: false, reason: failure.reason, result: failure };
  } finally {
    ACTIVE = null;
  }
}

chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:run-task') {
    runTask(message.goal).then(sendResponse, function (e) {
      sendResponse({ ok: false, reason: String(e).slice(0, 200) });
    });
    return true;
  }
  if (message.type === 'adaptiveai:answer') {
    if (!ANSWER) {
      sendResponse({ ok: false, reason: 'nothing is asking you anything right now' });
      return false;
    }
    ANSWER(message.answer);
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === 'adaptiveai:pending-question') {
    sendResponse({ ok: true, running: ACTIVE, question: QUESTION });
    return false;
  }
  return false;
});

// Two views, because they can disagree: what this worker asked to be said and
// what it was told back, and what the document that owns the engine actually
// saw. A test that reads only one cannot tell "never asked" from "asked and
// the engine refused".
function speechLog() {
  var attempts = (typeof AdaptiveAISpeech !== 'undefined' && AdaptiveAISpeech.log)
    ? AdaptiveAISpeech.log() : [];
  return new Promise(function (resolve) {
    try {
      chrome.runtime.sendMessage({ type: 'adaptiveai:speech-log' }, function (reply) {
        resolve({ ok: true, attempts: attempts,
                  engine: (reply && reply.spoken) || null,
                  reason: chrome.runtime.lastError
                    ? String(chrome.runtime.lastError.message).slice(0, 120) : '' });
      });
    } catch (e) {
      resolve({ ok: true, attempts: attempts, engine: null,
                reason: String(e).slice(0, 120) });
    }
  });
}

// ---- voice in --------------------------------------------------------------

function storageRead(key) {
  return new Promise(function (resolve) {
    try {
      chrome.storage.local.get([key], function (data) {
        resolve(chrome.runtime.lastError ? '' : (data && data[key]) || '');
      });
    } catch (e) { resolve(''); }
  });
}

// One utterance in, words out. The audio exists only inside this call: it is
// posted to the user's own backend for transcription and never written to storage,
// put in the run transcript, or logged - a recording is the user's voice, and a
// "helpful" debug line that includes it is a leak with good intentions behind it.
async function transcribe(maxMs) {
  var capture = await AdaptiveAISpeech.listen(maxMs || 8000);
  if (!capture || !capture.ok) {
    return { ok: false, reason: (capture && capture.reason) || 'the microphone did not work' };
  }
  var bytes = capture.audioB64;
  capture.audioB64 = null;
  if (!bytes || !capture.bytes) {
    return { ok: false, reason: 'the microphone captured nothing' };
  }
  var binary = atob(bytes);
  var buffer = new Uint8Array(binary.length);
  for (var i = 0; i < binary.length; i++) buffer[i] = binary.charCodeAt(i);
  var base = await storageRead('adaptiveai_backend') || 'http://localhost:8000';
  var token = await storageRead('adaptiveai_token');
  var form = new FormData();
  form.append('audio', new Blob([buffer], { type: capture.mime || 'audio/webm' }),
              'utterance.webm');
  try {
    var response = await fetch(base.replace(/\/+$/, '') + '/api/transcribe', {
      method: 'POST',
      headers: token ? { authorization: 'Bearer ' + token } : {},
      body: form,
    });
  } catch (e) {
    return { ok: false, reason: 'I could not reach the transcriber at ' + base };
  }
  if (!response.ok) {
    var detail = '';
    try { detail = String((await response.json()).detail || ''); } catch (e) { /* */ }
    return { ok: false, reason: 'the transcriber answered ' + response.status +
                                (detail ? ': ' + detail.slice(0, 120) : '') };
  }
  var data = await response.json();
  // The route's field is `transcript`. Reading `text` here returned '' for every
  // successful transcription, which the user experienced as "I heard no words in
  // that" while the server had answered correctly - the kind of bug only an
  // end-to-end call to the real route finds.
  var text = String(data.transcript || data.text || '').trim();
  if (!text) return { ok: false, reason: 'I heard no words in that' };
  return { ok: true, text: text, language: data.language || null,
           duration: data.duration || null };
}

chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:voice') {
    transcribe(message.maxMs).then(sendResponse, function (e) {
      sendResponse({ ok: false, reason: String(e).slice(0, 160) });
    });
    return true;
  }
  if (message.type === 'adaptiveai:stop-listening') {
    AdaptiveAISpeech.stopListening();
    sendResponse({ ok: true });
    return false;
  }
  return false;
});

// ---- keyboard commands -----------------------------------------------------
//
// A blind user should not have to find and open a popup to use a voice assistant,
// and should always be able to shut it up. `listen` captures one utterance, says it
// back so the user hears what was understood, and runs it; `stop-talking` cuts the
// current announcement.
//
// The command is called `listen`, not `hold-listen`: MV3 commands deliver no
// key-release event, so "hold to speak" cannot be implemented, and shipping a
// name that promises it is a lie in the keyboard-shortcuts page. The take ends
// after its ceiling or when silence is captured, whichever comes first.
async function handleCommand(name) {
  if (name === 'stop-talking') {
    AdaptiveAISpeech.stopListening();
    return AdaptiveAISpeech.stop();
  }
  if (name !== 'listen') return { ok: false, reason: 'unknown command ' + name };
  if (ACTIVE) return { ok: false, reason: 'I am already working on: ' + ACTIVE };
  var heard = await transcribe(8000);
  if (!heard.ok) {
    await AdaptiveAISpeech.speak('I could not hear you. ' + heard.reason);
    return heard;
  }
  // Spoken back before it is acted on: the one moment to notice that the wrong
  // thing was understood is before anything has been pressed.
  await AdaptiveAISpeech.speak('You said: ' + heard.text);
  var run = await runTask(heard.text);
  return { ok: run.ok, text: heard.text, result: run.result, reason: run.reason };
}

chrome.commands.onCommand.addListener(function (name) {
  handleCommand(name).then(null, function (e) {
    // A command that dies silently leaves the user with no idea whether anything
    // happened, so the failure is spoken rather than logged.
    AdaptiveAISpeech.speak('Something went wrong: ' + String(e).slice(0, 80));
  });
});

chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:command') {
    handleCommand(message.name).then(sendResponse, function (e) {
      sendResponse({ ok: false, reason: String(e).slice(0, 160) });
    });
    return true;
  }
  return false;
});

chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message) return false;
  if (message.type === 'adaptiveai:speech-log') {
    speechLog().then(sendResponse);
    return true;
  }
  if (message.type === 'adaptiveai:last-run') {
    sendResponse({ ok: true, running: ACTIVE, result: LAST });
    return false;
  }
  if (message.type === 'adaptiveai:stop') {
    AdaptiveAISpeech.stop();
    sendResponse({ ok: true, running: ACTIVE });
    return false;
  }
  return false;
});
