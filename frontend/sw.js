/**
 * Service Worker — app shell offline pour Scalping Radar.
 * Stratégie : cache-first pour HTML/CSS/JS, network-only pour /api et /ws.
 * Aucun cache dynamique des données marché : elles doivent toujours être fraîches.
 */

const CACHE_VERSION = 'scalping-shell-v2';
const SHELL_ASSETS = [
    '/',
    '/css/style.css',
    '/js/app.js',
    '/js/vendor/lightweight-charts.standalone.production.js',
    '/manifest.json',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL_ASSETS)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;

    const url = new URL(req.url);
    // Données live : toujours en direct, pas de cache.
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return;

    // Shell : cache-first avec fallback réseau puis mise en cache best-effort.
    event.respondWith(
        caches.match(req).then((cached) => {
            if (cached) return cached;
            return fetch(req)
                .then((res) => {
                    if (res.ok && url.origin === self.location.origin) {
                        const copy = res.clone();
                        caches.open(CACHE_VERSION).then((c) => c.put(req, copy)).catch(() => {});
                    }
                    return res;
                })
                .catch(() => cached);
        })
    );
});
