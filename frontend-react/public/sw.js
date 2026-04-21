/**
 * Service Worker minimal pour Scalping Radar V2.
 *
 * Stratégie : PASSTHROUGH uniquement.
 * Le SW est nécessaire pour que "Ajouter à l'écran d'accueil" installe une
 * vraie PWA avec icône + mode standalone. Mais on n'intercepte aucune
 * requête — tout passe en network direct.
 *
 * Pourquoi : un SW avec cache mal configuré sert de vieux bundles JS
 * incompatibles avec le HTML courant → écran noir. Le passthrough évite
 * ça totalement. Un vrai cache offline peut être ajouté plus tard avec
 * des précautions (scope, versioning strict, etc.).
 */

const SW_VERSION = '2026-04-21-passthrough-v2';

self.addEventListener('install', (event) => {
  // Prend le contrôle dès que possible, sans pré-cache.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Purge TOUS les anciens caches (y compris ceux des anciennes versions
      // du SW qui pré-cachaient le shell).
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

// Pas de fetch handler : tout passe au réseau. Le SW existe juste pour
// la compatibilité PWA (install + icône + standalone display).
self.addEventListener('message', (event) => {
  if (event.data === 'VERSION') {
    event.ports[0]?.postMessage(SW_VERSION);
  }
});
