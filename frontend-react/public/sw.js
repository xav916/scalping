/**
 * Service Worker minimal pour Scalping Radar V2.
 *
 * Stratégie : network-only passthrough.
 * Chrome exige un fetch handler pour considérer le site comme PWA
 * installable (critère des Web App Install Banners). On en fournit un
 * qui NE CACHE RIEN — toutes les requêtes passent au réseau, comme
 * sans SW. Ça garantit aucun écran noir par cache stale, et ça permet
 * quand même l'install (icône, standalone display, etc.).
 *
 * Un vrai cache offline pourra être ajouté plus tard avec versioning
 * strict : scope limité aux assets hashés, jamais le HTML racine.
 */

const SW_VERSION = '2026-04-21-passthrough-v3';

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Purge TOUS les anciens caches (cleanup défensif).
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((n) => n.startsWith('scalping-radar-v2-'))
          .map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

/**
 * Fetch handler passthrough. Ne modifie rien, ne cache rien, laisse
 * juste Chrome détecter que le SW gère les requêtes du scope → active
 * l'éligibilité PWA install.
 */
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (!url.pathname.startsWith('/v2/')) return;
  // event.respondWith(fetch(event.request)) — laisse le browser handle
  // normalement. On se contente de marquer qu'on a vu la requête.
  event.respondWith(fetch(event.request));
});

self.addEventListener('message', (event) => {
  if (event.data === 'VERSION') {
    event.ports[0]?.postMessage(SW_VERSION);
  }
});
