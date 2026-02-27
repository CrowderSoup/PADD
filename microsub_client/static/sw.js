const CACHE_VERSION = 'padd-v2';
const PRECACHE_URLS = [
  '/offline/',
  '/static/css/lcars.css',
  '/static/logo.svg',
  '/static/wordmark.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== CACHE_VERSION)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // JavaScript: network-first so that code changes are always reflected
  // immediately. The browser's HTTP cache (warmed by WhiteNoise's immutable
  // headers on content-hashed files) makes this fast in practice. Falls back
  // to cache for offline use.
  if (url.pathname.endsWith('.js')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Other static assets (CSS, images, fonts): cache-first.
  // These are safe to cache aggressively because WhiteNoise content-hashes
  // their URLs, so a changed file always gets a new URL.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // HTML pages: network-first, fall back to offline page
  if (request.headers.get('Accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request)
        .catch(() => caches.match('/offline/'))
    );
    return;
  }
});
