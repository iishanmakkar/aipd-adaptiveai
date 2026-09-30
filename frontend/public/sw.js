/* Phase 4.1 — offline-first service worker: cache app shell, pass through APIs. */
const CACHE = 'adaptiveai-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL).catch(() => undefined)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Never cache API/mutation traffic — queueing lives in IndexedDB (offlineQueue.ts).
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/v1/') || event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then((hit) => hit ?? fetch(event.request).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => undefined);
      return res;
    }).catch(() => caches.match('/index.html'))),
  );
});
