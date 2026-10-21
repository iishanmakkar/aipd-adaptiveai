// Speech output for the service worker, through an offscreen document.
//
// A MV3 service worker has no DOM and no `speechSynthesis`, so an extension that
// must be *heard* by a blind user needs a document that does. This file is the
// worker-side half: it creates that document on demand and asks it to speak.
//
// `speak()` resolves only with what the document actually reported. Chromium
// raises `speechSynthesis` errors asynchronously and an utterance that no engine
// accepted still fires neither `onend` nor `onerror` on some configurations, so
// the default answer is "it was not spoken" - a narrator that always returns
// success is how an assistant ends up silent while the user waits.
(function (global) {
  'use strict';

  var URL = 'offscreen.html';
  // Long enough for the longest announcement this extension makes (the spending
  // confirmation), short enough that a dead engine is reported rather than
  // waited on forever.
  var SPEAK_DEADLINE_MS = 45000;

  function send(message) {
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage(message, function (reply) {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, reason: chrome.runtime.lastError.message });
            return;
          }
          resolve(reply || { ok: false, reason: 'no reply from the speech document' });
        });
      } catch (e) {
        resolve({ ok: false, reason: String(e).slice(0, 120) });
      }
    });
  }

  function ensureDocument() {
    if (!chrome.offscreen || !chrome.offscreen.createDocument) {
      return Promise.resolve({ ok: false,
                               reason: 'this browser has no offscreen documents' });
    }
    return new Promise(function (resolve) {
      try {
        // `justification`, not `reason`: this Chrome rejects `reason` as an
        // unexpected property and demands `justification` (Chromium 156, read from
        // its own error - "Missing required property 'justification'"). And the
        // throw is synchronous, so it has to be caught: uncaught, it rejected this
        // promise while the caller - the runner's narrate() - never looked at the
        // result, so announcements would have failed with nothing recorded.
        chrome.offscreen.createDocument({
          url: URL,
          reasons: ['AUDIO_PLAYBACK'],
          justification: 'Reading page state aloud to a blind user',
        }, function () {
          if (chrome.runtime.lastError) {
            var msg = String(chrome.runtime.lastError.message || '');
            // "Only a single offscreen document may be created" means one already
            // exists - the state we wanted, reached by a different route than
            // hasDocument() reported. Anything else is a real failure.
            resolve({ ok: /single offscreen document|already exists|only one/i.test(msg),
                      reason: msg || 'createDocument failed' });
            return;
          }
          resolve({ ok: true });
        });
      } catch (e) {
        resolve({ ok: false, reason: String(e && e.message || e).slice(0, 160) });
      }
    });
  }

  var attempts = [];

  function record(text, outcome) {
    attempts.push({ text: String(text).slice(0, 200), ok: !!(outcome && outcome.ok),
                    reason: (outcome && outcome.reason) || '',
                    status: (outcome && outcome.status) || '' });
    if (attempts.length > 50) attempts.shift();
  }

  // `createDocument` resolves as soon as the document is *registered*, which is
  // before its script has run. Sending the first announcement into that window
  // returned "Could not establish connection. Receiving end does not exist" and
  // the user heard nothing at all - so an announcement waits for the document to
  // answer its own health check before it sends words to it.
  function waitUntilReady(deadlineMs) {
    var stopAt = Date.now() + (deadlineMs || 4000);
    function attempt() {
      return send({ type: 'adaptiveai:ping' }).then(function (reply) {
        if (reply && reply.ok) return true;
        if (Date.now() >= stopAt) return false;
        return new Promise(function (res) { setTimeout(res, 120); }).then(attempt);
      });
    }
    return attempt();
  }

  // Ask, don't assume. `chrome.offscreen.hasDocument()` measured true on this
  // Chromium (156) with no document ever created, which is the worst possible
  // answer: gating creation on it meant the document was never made and every
  // announcement failed with a connection error. A ping costs one message and
  // cannot be wrong about whether something is listening.
  function ensureLive() {
    return send({ type: 'adaptiveai:ping' }).then(function (reply) {
      if (reply && reply.ok) return { ok: true };
      return ensureDocument().then(function (state) {
        if (!state.ok) return state;
        return waitUntilReady().then(function (live) {
          return live ? { ok: true }
                      : { ok: false, reason: 'created but never answered its health check' };
        });
      });
    });
  }

  function speak(text) {
    if (!text) return Promise.resolve({ ok: false, reason: 'nothing to say' });
    return ensureLive().then(function (state) {
      if (!state || !state.ok) {
        var failure = { ok: false, reason: 'speech document unavailable: ' +
                       (state && state.reason || 'not created') };
        record(text, failure);
        return failure;
      }
      return send({ type: 'adaptiveai:speak', text: String(text) })
        .then(function (outcome) { record(text, outcome); return outcome; });
    });
  }

  function log() {
    return attempts.slice();
  }

  function stop() {
    return send({ type: 'adaptiveai:stop-speaking' });
  }

  var AdaptiveAISpeech = { speak: speak, stop: stop, log: log,
                           ensureDocument: ensureDocument, URL: URL };
  global.AdaptiveAISpeech = AdaptiveAISpeech;
  if (typeof module !== 'undefined' && module.exports) module.exports = AdaptiveAISpeech;
})(typeof window !== 'undefined' ? window : globalThis);
