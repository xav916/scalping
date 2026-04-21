/**
 * Service Worker minimal pour Scalping Radar V2.
 * Strategy : network-first pour les assets, fallback cache.
 * N'intercepte PAS /api/* ni /ws (doivent toujours frapper le réseau live).
 */

const CACHE_NAME = 'scalping-radar-v2-20260421-1';
const SCOPE_PREFIX = '/v2/';
const SHELL = [
  '/v2/',
  '/v2/index.html',
  '/v2/manifest.json',
  '/v2/icons/radar-512.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL).catch(() => null))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((n) => n.startsWith('scalping-radar-v2-') && n !== CACHE_NAME)
            .map((n) => caches.delete(n))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Ne pas intercepter les requêtes API ou WebSocket.
  if (!url.pathname.startsWith(SCOPE_PREFIX)) return;

  // Network-first pour HTML (navigation) pour toujours prendre la dernière version,
  // cache-first pour les assets figés (JS/CSS/SVG avec hash dans le nom).
  const isNavigation =
    req.mode === 'navigate' ||
    url.pathname === SCOPE_PREFIX ||
    url.pathname.endsWith('/index.html');

  if (isNavigation) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, clone).catch(() => null));
          return res;
        })
        .catch(() => caches.match(req).then((m) => m || caches.match('/v2/index.html')))
    );
    return;
  }

  // Assets : cache-first.
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, clone).catch(() => null));
        }
        return res;
      });
    })
  );
});
