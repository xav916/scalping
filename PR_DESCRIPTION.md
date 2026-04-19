# UX/perf/security hardening + session auth + modal 2 étapes

## Pourquoi

Suite à un audit complet du site servi (accessibilité, performance, sécurité, SEO, UX), cette PR applique les correctifs de fond. Découpée en 6 commits atomiques pour faciliter la review.

## Commits (atomiques, chacun compile et valide en syntaxe)

| # | Commit | Résumé |
|---|---|---|
| 1 | `353fe89` | Hardening pass : gzip nginx, Cache-Control, CSP, ARIA, focus-visible, prefers-reduced-motion, accents FR, polling WS gaté, escapeHtml, data-action delegation, mobile 480px touch 44px |
| 2 | `9ebce2b` | Self-host lightweight-charts v4.2.0 (163 KB, Apache 2.0) → CSP `script-src 'self'` sans CDN tiers |
| 3 | `911f203` | Lazy-load glossaire (1 requête init en moins) |
| 4 | `98e2f81` | Modale trade en 2 étapes (pré-MT5 / post-MT5) avec récap + indicateur visuel |
| 5 | `a0fc7a6` | Session cookie HttpOnly + page `/login` + auth WebSocket (Basic Auth reste en fallback) |
| 6 | `796a596` | `app.js` en module ES + helpers purs extraits dans `utils.js` + plan de split fin dans `MODULES.md` |

## Gains mesurables

- **Bande passante** : ~70-80 % en moins sur les assets statiques (gzip activé sur CSS/JS/JSON/SVG).
- **Requêtes init** : 1 fetch glossaire économisé + 1 handshake TLS vers unpkg supprimé.
- **Bande passante runtime** : polling 5s → fallback 60s gaté sur WS → ~700 req/h économisées par onglet.
- **Sécurité** : CSP strict `'self'`, Permissions-Policy, COOP, WebSocket authentifié (avant : ouvert à tous), escape HTML sur 20+ points d'injection, cookies `HttpOnly Secure SameSite=Strict`.

## Breaking changes

- **`backend/auth.py` (nouveau)** remplace la fonction `verify_credentials` locale. Toutes les routes utilisent désormais `authenticate(request)` via l'alias `verify_credentials`. Pas de changement visible côté API : les scripts Basic Auth continuent de marcher.
- **WebSocket `/ws`** : exige maintenant cookie OU Basic Auth quand `AUTH_USERS` est configuré. Les clients non-auth reçoivent code 1008. Si `AUTH_USERS` est vide → WS reste ouvert comme avant.
- **`X-XSS-Protection`** : supprimé (déprécié, contre-productif avec CSP).
- **Trade modal** : workflow en 2 étapes. L'API POST `/api/trades` reste identique.

## Non fait (justifié)

- **Split ES modules complet (9 modules)** : 1600 lignes d'état mutable partagé + zéro test = risque de régression inacceptable. Plan détaillé dans [`frontend/js/MODULES.md`](frontend/js/MODULES.md). À faire après mise en place d'une suite Playwright.

## Test plan (à valider avant merge — pas de tests auto)

- [ ] Build Docker passe : `docker build -t scalping-radar .`
- [ ] `/` sans cookie redirige vers `/login` (303)
- [ ] Login avec bons identifiants pose le cookie `scalping_session`, redirige vers `?next=` ou `/`
- [ ] Login avec mauvais identifiants affiche l'erreur inline
- [ ] `POST /api/logout` supprime le cookie, `/` re-redirige vers `/login`
- [ ] Basic Auth continue de fonctionner (`curl -u user:pwd https://…/api/overview`)
- [ ] WebSocket sans auth → fermé avec 1008 si `AUTH_USERS` défini
- [ ] Modale trade : étape 1 → 2 → enregistrement OK
- [ ] Modale trade : validation form native au clic "Passer l'ordre dans MT5 →"
- [ ] Modale trade : "← Retour" revient bien à l'étape 1 sans perdre le form
- [ ] Glossaire : fetch déclenché uniquement à la 1re ouverture
- [ ] Theme toggle, son, voix : tous opérationnels
- [ ] Reconnexion WebSocket après `docker restart` : heartbeat correctement nettoyé (pas d'empilement de pings)
- [ ] Compression active : `curl -sI -H 'Accept-Encoding: gzip' …/css/style.css` → `Content-Encoding: gzip`
- [ ] CSP : `curl -sI … / | grep -i content-security` renvoie bien `script-src 'self'`
- [ ] Service Worker enregistré : DevTools → Application → Service Workers
- [ ] Manifest PWA : installable depuis Chrome
- [ ] Lighthouse (accessibilité + perf) + axe-core CLI (`npx @axe-core/cli …`)

## À faire séparément (hors scope)

- Ajouter `scalping-key.pem` au `.gitignore` (actuellement untracked mais dans le repo)
- Mettre en place Playwright pour ouvrir la voie au split ES modules fin
- Reprendre éventuellement la migration sessions in-memory → Redis/SQLite (1 fichier à changer : `backend/auth.py`)
