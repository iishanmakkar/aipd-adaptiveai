// AdaptiveAI service worker.
//
// Deliberately small. The step -> act -> verify -> narrate loop, the spend gate
// and the profile vault land here in later tasks of the extension plan; nothing
// in this file pretends to plan or execute yet, because a scaffold that returns
// invented results is exactly the failure mode the truth pass just removed.
// Classic worker (no "type": "module"): a module worker has no importScripts and
// would fail to install over one unnecessary line. The vault is shared with the
// options page through chrome.storage.local, so the worker can read profile labels
// and the spending ceiling without either page holding the values itself.
// Paths are relative to THIS script's URL, so 'vault.js' - writing
// 'src/vault.js' asks for src/src/vault.js, the import throws, and the worker
// silently never activates.
importScripts('vault.js');

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
    chrome.tabs.sendMessage(tab.id, { type: 'adaptiveai:snapshot', force: true },
      function (snap) {
        if (chrome.runtime.lastError || !snap) {
          // Most common real cause: the tab is a chrome:// page, the Web Store,
          // or an origin the user has not granted yet. Say which, never return
          // an empty snapshot as if the page were simply blank.
          sendResponse({ ok: false,
                         reason: 'no content script on this page',
                         detail: chrome.runtime.lastError
                           ? chrome.runtime.lastError.message : 'no response' });
          return;
        }
        sendResponse({ ok: true, snapshot: snap });
      });
    return;
  });
  return true;  // asynchronous sendResponse
});
