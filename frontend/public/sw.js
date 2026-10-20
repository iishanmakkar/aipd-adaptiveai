/* Phase 4.1 — offline-first service worker: cache app shell, pass through APIs. */
const CACHE = 'adaptiveai-shell-v3';
const SHELL = ['/', '/index.html', '/manifest.webmanifest'];

/* Vite's dev server serves the app itself as /src/*.tsx, /@vite/*, /@id/* and
   /node_modules/.vite/* - all unhashed URLs whose content changes on every
   edit. Cache-first on those would freeze a developer (or this stack's own
   `npm run dev` container) on the first version they ever loaded, so they are
   always served from the network. That is what lets the worker be registered
   in dev as well as in a production build. */
const DEV_SERVER_PATHS = [/^\/src\//, /^\/@vite/, /^\/@id\//, /^\/node_modules\/\.vite\//, /\.tsx?$/, /\.ts$/, /\.map$/];

self.addEventListener('install', (event) => {
  event.waitUntil(
    // Only take over when the shell actually cached: claiming with an empty
    // cache (first load while offline) would serve nothing at all.
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch(() => undefined),
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
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/v1/') || event.request.method !== 'GET') return;
  if (DEV_SERVER_PATHS.some((pattern) => pattern.test(url.pathname))) return;
  if (event.request.mode === 'navigate') {
    // Navigations (/, /index.html) are network-first: cache-first on the
    // entry HTML pinned installed apps to the deploy they first saw, because
    // the hashed-asset URLs inside the old HTML stay valid forever.
    event.respondWith(
      fetch(event.request).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => undefined);
        }
        return res;
      }).catch(() => caches.match(event.request).then((hit) => hit ?? caches.match('/index.html'))),
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((hit) => hit ?? fetch(event.request).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy)).catch(() => undefined);
      }
      return res;
    }).catch(() => Response.error())),
  );
});
