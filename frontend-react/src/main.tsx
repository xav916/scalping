import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// Reload auto si un chunk lazy 404 après deploy. Vite émet vite:preloadError
// quand un chunk hashé devenu obsolète n'est plus servi — sans ce handler,
// la nav cliente reste bloquée sur Suspense fallback (page blanche), forçant
// l'user à rafraîchir manuellement. Une seule tentative pour éviter une
// boucle de reload infinie si le 404 est causé par autre chose.
if (typeof window !== 'undefined') {
  const RELOAD_FLAG = '__sr_chunk_reloaded__';
  window.addEventListener('vite:preloadError', () => {
    if (!sessionStorage.getItem(RELOAD_FLAG)) {
      sessionStorage.setItem(RELOAD_FLAG, '1');
      window.location.reload();
    }
  });
  // Reset le flag dès qu'une nav réussie a eu lieu (évite de bloquer la
  // boucle si l'user navigue normalement après un reload).
  window.addEventListener('pageshow', () => {
    setTimeout(() => sessionStorage.removeItem(RELOAD_FLAG), 5_000);
  });
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Enregistrement du Service Worker (PWA) — seulement en production,
// scope limité à /v2/ pour ne pas intercepter l'ancien frontend.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/v2/sw.js', { scope: '/v2/' })
      .catch((err) => console.warn('SW register failed:', err));
  });
}
