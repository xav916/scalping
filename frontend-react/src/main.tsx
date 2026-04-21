import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

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
