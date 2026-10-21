// The offscreen document's controller: the only place in this extension with a
// speech engine, and (next task) a microphone.
//
// `speak` answers with what the engine did, not with what was asked for. A
// `speechSynthesis` call that no voice accepted still returns without throwing,
// so an assistant that replies "spoken" here can leave a blind user sitting in
// silence while every log says the announcement happened.
(function () {
  'use strict';

  // What this document actually did with each request, kept for the tests and for
  // a later "what did it say?" review. Not a claim of success: `status` says which
  // of the engine's own events came back.
  var spoken = [];

  function hasVoices() {
    if (!('speechSynthesis' in globalThis)) return false;
    try { return (speechSynthesis.getVoices() || []).length > 0; } catch (e) { return false; }
  }

  function speak(text) {
    if (!('speechSynthesis' in globalThis)) {
      return Promise.resolve({ ok: false, reason: 'this browser has no speech engine here' });
    }
    var entry = { text: text, status: 'queued', at: Date.now() };
    spoken.push(entry);
    if (spoken.length > 50) spoken.shift();

    return new Promise(function (resolve) {
      var settled = false;
      var utterance = new SpeechSynthesisUtterance(String(text));
      utterance.rate = 1;

      function finish(status, ok, reason) {
        if (settled) return;
        settled = true;
        entry.status = status;
        entry.reason = reason || '';
        resolve({ ok: ok, reason: reason || '', status: status });
      }

      utterance.onend = function () { finish('ended', true); };
      utterance.onerror = function (event) {
        // 'canceled'/'interrupted' means stop was pressed - the words were
        // replaced on purpose, not lost to a failure.
        var why = (event && event.error) || 'speech error';
        finish('error', why === 'interrupted' || why === 'canceled', why);
      };

      try {
        // No cancel() here on purpose. `speechSynthesis` already queues, and a
        // task narrates several sentences in a row: interrupting each one to play
        // the next means a blind user hears only the last thing said. Stopping is
        // an explicit action (`adaptiveai:stop-speaking`), never a side effect of
        // speaking.
        speechSynthesis.speak(utterance);
      } catch (e) {
        finish('throw', false, String(e).slice(0, 120));
        return;
      }

      // Engines fail in two directions: one that rejects every utterance fires
      // neither event, and one that is backed up behind a previous sentence is
      // still working. This check can only declare failure, and only when the
      // engine says it is doing nothing at all.
      setTimeout(function () {
        if (settled) return;
        if (!speechSynthesis.speaking && !speechSynthesis.pending) {
          finish(hasVoices() ? 'silent' : 'no-voices', false,
                 hasVoices() ? 'the speech engine accepted nothing'
                              : 'no speech voices are available on this system');
        }
      }, 3000);

      // A long announcement may legitimately outlive that check; never let the
      // caller wait forever on an engine that stopped reporting.
      setTimeout(function () {
        if (settled) return;
        finish(speechSynthesis.speaking ? 'speaking' : 'no-event',
               speechSynthesis.speaking, 'no end event from the speech engine');
      }, 20000);
    });
  }

  function stopSpeaking() {
    try { speechSynthesis.cancel(); } catch (e) { /* nothing playing */ }
    return { ok: true };
  }

  // ---- microphone ----------------------------------------------------------
  //
  // This document is the only place in the extension with `navigator.mediaDevices`,
  // which is why the offscreen document owns both directions of the voice path.
  // Audio goes back to the worker as bytes and no further: it is posted straight to
  // the user's own backend for transcription and is never written to storage, never
  // logged, and never part of the run transcript.
  var recording = null;

  function listen(maxMs) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return Promise.resolve({ ok: false, reason: 'this browser exposes no microphone here' });
    }
    if (recording) return Promise.resolve({ ok: false, reason: 'already listening' });
    var limit = Math.min(Math.max(Number(maxMs) || 8000, 500), 60000);
    return navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var chunks = [];
      var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : '';
      var recorder = mime ? new MediaRecorder(stream, { mimeType: mime })
                          : new MediaRecorder(stream);
      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      var stopped = new Promise(function (resolve) {
        recorder.onstop = function () {
          stream.getTracks().forEach(function (t) { t.stop(); });
          var blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
          recording = null;
          resolve(blob.arrayBuffer().then(function (buffer) {
            // Base64, not the ArrayBuffer: extension messaging hands a worker an
            // `{}` where an ArrayBuffer was sent, so the first version of this
            // reported "the microphone captured nothing" for a microphone that had
            // recorded 24 KB. The byte count travels beside it so a caller can tell
            // an empty take from a working one without decoding anything.
            var view = new Uint8Array(buffer);
            var binary = '';
            for (var i = 0; i < view.length; i++) binary += String.fromCharCode(view[i]);
            return { ok: true, mime: blob.type, bytes: buffer.byteLength,
                     audioB64: btoa(binary) };
          }));
        };
      });
      // The 250 ms timeslice is not a nicety: `start()` with no timeslice fired no
      // `dataavailable` before `stop` on this Chromium, so the recorder produced a
      // valid webm header with zero audio and the extension reported "the
      // microphone captured nothing" for a microphone that was working.
      recorder.start(250);
      recording = { recorder: recorder, stopped: stopped, stream: stream };
      // A hard ceiling, not a guess at how long the user needs: a held-open
      // microphone keeps recording into a buffer with no bound and no notice.
      var timer = setTimeout(function () { stopListening(); }, limit);
      return stopped.then(function (result) { clearTimeout(timer); return result; });
    }, function (e) {
      // A refused or absent device is reported as itself. "I could not hear you"
      // and "you did not grant the microphone" are different instructions.
      return { ok: false, reason: String(e && e.name || e).slice(0, 120) };
    });
  }

  function stopListening() {
    if (!recording) return { ok: false, reason: 'not listening' };
    try { recording.recorder.stop(); } catch (e) { return { ok: false, reason: String(e) }; }
    return { ok: true };
  }

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || !message.type) return false;
    if (message.type === 'adaptiveai:listen') {
      listen(message.maxMs).then(sendResponse);
      return true;
    }
    if (message.type === 'adaptiveai:stop-listening') {
      sendResponse(stopListening());
      return false;
    }
    if (message.type === 'adaptiveai:ping') {
      // A health check, not a no-op: `createDocument` resolves before this script
      // has run, so the worker's first announcement used to arrive at a document
      // that could not yet answer for it.
      sendResponse({ ok: true, speech: 'speechSynthesis' in globalThis });
      return false;
    }
    if (message.type === 'adaptiveai:speak') {
      speak(message.text).then(sendResponse);
      return true;
    }
    if (message.type === 'adaptiveai:stop-speaking') {
      sendResponse(stopSpeaking());
      return false;
    }
    if (message.type === 'adaptiveai:speech-log') {
      sendResponse({ ok: true, spoken: spoken });
      return false;
    }
    return false;
  });

  // The message surface a test reads. Written by offscreen.js itself, so what a
  // test observes is the same object the engine updated, not a copy.
  globalThis.__adaptiveai_spoken = spoken;
})();
