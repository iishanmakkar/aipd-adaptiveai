import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Phase 4.1: offline-first shell cache (no-op when SW unsupported).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => undefined);
  });
}

// Phase 4.1: flush the IndexedDB mutation queue when connectivity returns
// (and once at boot, in case the tab closed mid-outage). 4xx means the entry
// itself is bad — drop it so one poison pill can't head-of-line-block the
// queue; only network errors and 5xx retry.
async function drainOfflineQueue(): Promise<void> {
  try {
    const { drainQueue } = await import('./utils/offlineQueue');
    const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    // Best-effort auth: the UI currently runs tokenless (demo mode), but a
    // future login flow can stash a bearer here and replays will carry it.
    const token = localStorage.getItem('adaptiveai_token');
    await drainQueue(async (entry) => {
      let res: Response;
      try {
        res = await fetch(`${base}${entry.url}`, {
          method: entry.method,
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(entry.body),
        });
      } catch {
        return 'retry';
      }
      if (res.ok) return 'ok';
      return res.status >= 500 ? 'retry' : 'drop';
    });
  } catch {
    // Still offline or IndexedDB unavailable - the queue keeps waiting.
  }
}
window.addEventListener('online', () => void drainOfflineQueue());
void drainOfflineQueue();