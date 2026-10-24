// Minimal offline shell cache so the driver app opens even with no signal at all.
const CACHE = 'coldtrace-driver-v1';
const SHELL = ['/driver/', '/driver/index.html', '/driver/driver.js', '/css/tokens.css'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener('activate', (e) => { self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;   // never cache API writes
  e.respondWith(
    fetch(e.request).then((res) => {
      if (res.ok && e.request.url.startsWith(self.location.origin)) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match(e.request)),
  );
});
