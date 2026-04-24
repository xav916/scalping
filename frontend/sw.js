// Legacy Service Worker — v10 (post-migration V2).
//
// Les users qui avaient installé la PWA V1 ont ce SW enregistré sur leur
// browser. Il cache des assets qui n'existent plus. Plutôt que de laisser
// des références cassées, on le remplace par un SW qui se désinstalle
// lui-même : au prochain navigate, il unregister la PWA V1 et le browser
// laisse /v2/sw.js prendre la relève (scope /v2/).

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', async (event) => {
  event.waitUntil(
    (async () => {
      // Vide tous les caches legacy.
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
      // Self-unregister — la PWA V1 disparaît proprement.
      await self.registration.unregister();
      // Force les clients ouverts à recharger (ils tomberont sur /v2/ via 308).
      const clients = await self.clients.matchAll();
      clients.forEach((client) => client.navigate(client.url));
    })()
  );
});

self.addEventListener('fetch', (event) => {
  // Passthrough : on ne cache plus rien. Chrome exige un fetch handler pour
  // installer la PWA — mais ici on n'installe plus, on désinstalle.
  event.respondWith(fetch(event.request));
});
