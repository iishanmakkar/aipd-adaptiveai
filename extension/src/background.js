// AdaptiveAI service worker.
//
// Deliberately small. The step -> act -> verify -> narrate loop, the spend gate
// and the profile vault land here in later tasks of the extension plan; nothing
// in this file pretends to plan or execute yet, because a scaffold that returns
// invented results is exactly the failure mode the truth pass just removed.
// Classic worker (no "type": "module"): a module worker has no importScripts and
// would fail to install over one unnecessary line.
chrome.runtime.onInstalled.addListener(function (details) {
  chrome.storage.local.set({ adaptiveai_installed_at: Date.now(),
                             adaptiveai_install_reason: details.reason });
});

// Ask the active tab's content script for its accessibility snapshot.
chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
  if (!message || message.type !== 'adaptiveai:get-page-snapshot') return false;
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
