import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Phase 4.1: offline-first shell cache (no-op when SW unsupported). Registered
// in dev too, because the documented way to run this stack is `npm run dev` in
// a container - gating on PROD meant the offline path never actually installed
// anywhere the README told people to look. sw.js serves Vite's own dev module
// URLs from the network, so hot reload still works.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      // A failed registration used to vanish silently, leaving the app
      // believing it was offline-capable when it was not.
      console.warn('[SW] registration failed; offline shell disabled:', err);
    });
  });
}

// Phase 4.1: flush the IndexedDB mutation queue when connectivity returns
// (and once at boot, in case the tab closed mid-outage). 4xx means the entry
// itself is bad — drop it so one poison pill can't head-of-line-block the
// queue; only network errors and 5xx retry.
// One drain at a time: the browser fires 'online' AND a synthetic dispatch
// (or two rapid connectivity flaps) can start two concurrent drains, and two
// drainQueue passes reading the same entries before either deletes them would
// send every queued mutation — and every queued query — twice.
let draining = false;
async function drainOfflineQueue(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    const { drainQueue } = await import('./utils/offlineQueue');
    const { getToken } = await import('./utils/auth');
    const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    await drainQueue(async (entry) => {
      // Fresh token per entry: re-login mid-drain must not replay on dead bearer.
      const token = getToken();
      let res: Response;
      const isQuery = entry.url === '/api/query';
      const timeoutMs = isQuery ? 180000 : 30000;
      let ctrl: AbortController | undefined;
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        if (typeof AbortSignal.timeout === 'function') {
          res = await fetch(`${base}${entry.url}`, {
            method: entry.method,
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(entry.body),
            signal: AbortSignal.timeout(timeoutMs),
          });
        } else {
          ctrl = new AbortController();
          timer = setTimeout(() => ctrl!.abort(), timeoutMs);
          res = await fetch(`${base}${entry.url}`, {
            method: entry.method,
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify(entry.body),
            signal: ctrl.signal,
          });
        }
      } catch (e) {
        // Abort = may have committed server-side: drop, do not duplicate.
        // AbortSignal.timeout rejects with name 'TimeoutError' (the legacy
        // AbortController path rejects with 'AbortError') - only the legacy
        // name was mapped, so a TIMED-OUT queued query was kept and re-sent
        // after the server had already committed the answer: double answer,
        // double NIM run, double speech.
        if (e instanceof DOMException && (e.name === 'AbortError' || e.name === 'TimeoutError')) {
          return 'drop';
        }
        return 'retry';
      } finally {
        if (timer) clearTimeout(timer);
      }
      if (res.ok) {
        // A replayed chat query has a real answer on the wire. Publish it so
        // the open tab can append + speak it; if the tab is gone or the body
        // is not JSON, the answer is still persisted server-side.
        if (entry.url === '/api/query') {
          try {
            const response = await res.json();
            window.dispatchEvent(new CustomEvent('adaptiveai:queued-answer', {
              detail: { request: entry.body, response },
            }));
          } catch {
            /* answer persisted server-side; the UI event is best-effort */
          }
        }
        return 'ok';
      }
      // A dead/expired token on a queued chat query is NOT a poison pill:
      // dropping it permanently discards the user's question, contradicting
      // the "saved and will be sent" promise. Retry once a live token exists.
      if (res.status === 401) return 'retry';
      if (res.status === 429 || res.status === 408) return 'retry';
      return res.status >= 500 ? 'retry' : 'drop';
    });
  } catch {
    // Still offline or IndexedDB unavailable - the queue keeps waiting.
  } finally {
    draining = false;
  }
}
window.addEventListener('online', () => void drainOfflineQueue());
void drainOfflineQueue();