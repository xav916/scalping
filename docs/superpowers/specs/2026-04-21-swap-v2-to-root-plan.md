# Plan de cutover `/v2/` → `/` — remplacement de l'ancien frontend

**Date** : 2026-04-21
**Statut** : spec, pas d'exécution sans validation explicite user
**Criticité** : HAUTE (modification prod visible, rollback requis)

---

## Contexte

Le V2 React (sur `/v2/`) a atteint la parité fonctionnelle avec le legacy (sur `/`) — et la dépasse sur Cockpit, Analytics, Period Metrics, Mistakes, Combos. Le legacy est devenu techniquement obsolète : Jinja + vanilla JS + Tailwind compilé au build, aucun test, pas de TypeScript.

**Le passage à la V1 sur `/` définitif** signifie :
- L'utilisateur accède à `https://scalping-radar.duckdns.org/` et voit la V2 React (pas l'ancien dashboard)
- Les bookmarks `/` des users continuent de marcher
- Le legacy reste accessible temporairement sur `/legacy/*` pour rollback rapide
- Les routes `/v2/*` deviennent alias ou redirections vers `/`

## Avant de cutover — prérequis

### ✅ Parité fonctionnelle (validée)
- [x] Dashboard : setups, macro, session clock, equity, performance
- [x] Cockpit : kill switch, alerts, capital at risk, répartition, F&G, trades actifs, équité, santé, drift, COT, events
- [x] Analytics : signal volume, breakdowns, mistakes, combos, close reasons, slippage
- [x] Trades : liste + filtres
- [x] Auth : login / logout / cookie session
- [x] PWA : manifest + SW + icônes
- [x] Mobile responsive : bottom nav + layouts adaptés

### ⏳ Validation opérationnelle (à faire avant cutover)
- [ ] **Smoke test end-to-end d'un trade démo** (Task #37) : suivre 1 trade de A à Z, screenshots à chaque étape
- [ ] **Vitest setup + tests critiques** (Task #36) : safety net pour éviter les régressions silencieuses
- [ ] **Hard refresh test** : vider cache + SW + revenir sur `/v2/` → tout doit remonter en < 3s
- [ ] **Mobile iOS Safari test** : PWA installable, navigation, tooltips accessibles
- [ ] **Mobile Android Chrome test** : idem
- [ ] **Desktop Chrome/Firefox test** : idem
- [ ] **Vérifier que tous les endpoints `/api/*` utilisés par V2 sont auth-gated et fonctionnels** : `/api/me`, `/api/overview`, `/api/macro`, `/api/candles`, `/api/insights/performance`, `/api/insights/equity-curve`, `/api/insights/period-stats`, `/api/cockpit`, `/api/analytics`, `/api/drift`, `/api/cot`, `/api/fear-greed`, `/api/kill-switch`, `/api/stats/mistakes`, `/api/stats/combos`, `/api/health`, `/api/status`, `/api/trades`, WebSocket `/ws`
- [ ] **Vérifier la cohérence de l'auth** : le même cookie `scalping_session` authentifie `/v2/*` et `/` (déjà le cas via `SameSite=Lax`)

### ⏳ Préparation infrastructure
- [ ] **Nginx config** : prévoir la route `/legacy/` pour accès rollback au Jinja + conserver les routes `/v2/*` en alias
- [ ] **FastAPI routing** : réorganiser les mounts pour que `/` serve le V2 et `/legacy/` serve le Jinja
- [ ] **Service Worker scope** : élargir le SW de `/v2/` à `/` (ou déposer un nouveau SW racine + conserver le V2 SW)
- [ ] **Manifest PWA** : mettre à jour `scope` et `start_url` de `/v2/` vers `/`
- [ ] **Tous les liens internes V2** : `to="/login"` fonctionne toujours (pas de `/v2/login` hardcodé dans le code React — à auditer)

---

## Plan de cutover par étapes

### Étape 1 — Préparation backend (non disruptive)

Modifier `backend/app.py` :

```python
# Avant
@app.get("/")
async def index(request: Request):
    try:
        authenticate(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "index.html"))

# Après
@app.get("/")
async def index(request: Request):
    """Root : sert désormais le V2 React (pas le legacy Jinja).
    L'ancien frontend reste accessible sur /legacy/ pour rollback."""
    try:
        authenticate(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(str(_V2_DIST / "index.html"), headers={"Cache-Control": "no-cache, must-revalidate"})

# Ajout : mount /legacy pour accès rollback au Jinja
app.mount("/legacy/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="legacy-css")
app.mount("/legacy/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="legacy-js")

@app.get("/legacy", include_in_schema=False)
async def legacy_root(request: Request):
    try:
        authenticate(request)
    except HTTPException:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "index.html"))
```

**Tester** :
- `curl https://scalping-radar.duckdns.org/` doit retourner le V2 index.html
- `curl https://scalping-radar.duckdns.org/legacy` doit retourner le Jinja index.html
- `curl https://scalping-radar.duckdns.org/v2/` doit continuer à marcher

### Étape 2 — BrowserRouter basename

Modifier `frontend-react/src/App.tsx` :

```tsx
// Avant
<BrowserRouter basename="/v2">

// Après
<BrowserRouter basename="/">
```

**Attention** : cela casse les URLs `/v2/cockpit`, `/v2/analytics`, `/v2/trades`. Il faut une redirection serveur de `/v2/*` vers `/*` pour les bookmarks existants.

Ajouter dans `backend/app.py` :

```python
@app.get("/v2", include_in_schema=False)
@app.get("/v2/", include_in_schema=False)
async def redirect_v2_root():
    return RedirectResponse("/", status_code=301)

@app.get("/v2/{path:path}", include_in_schema=False)
async def redirect_v2_subpaths(path: str):
    # Exclure les assets (ils sont servis par le mount static)
    if path.startswith("assets/") or path in ("manifest.json", "sw.js", "icons"):
        return FileResponse(str(_V2_DIST / path))
    return RedirectResponse(f"/{path}", status_code=301)
```

### Étape 3 — Service Worker et PWA

Modifier `frontend-react/public/manifest.json` :

```json
{
  "scope": "/",
  "start_url": "/"
}
```

Modifier `frontend-react/public/sw.js` : changer `if (!url.pathname.startsWith('/v2/')) return;` par `if (url.pathname.startsWith('/legacy/')) return;` (on ne veut pas gérer le legacy via SW).

Bumper `SW_VERSION` pour forcer update.

Modifier `frontend-react/src/main.tsx` :
```tsx
navigator.serviceWorker.register('/sw.js', { scope: '/' })
```

Modifier le path du SW dans `backend/app.py` pour qu'il soit servi depuis `/sw.js` (actuellement sur `/v2/sw.js`).

### Étape 4 — Build + deploy

- `bash deploy-v2.sh` avec toutes les modifs
- Vérifier que :
  - `/` sert le V2
  - `/v2/` redirige vers `/`
  - `/legacy/` sert le Jinja (fallback)
  - `/sw.js` accessible
  - `/manifest.json` a `scope: "/"`

### Étape 5 — Test client

Ordre strict :
1. Hard refresh desktop Chrome (`Ctrl+Shift+R`)
2. DevTools → Application → SW → Unregister old V2 SW
3. Reload : nouveau SW doit s'enregistrer avec scope `/`
4. Naviguer sur `/` (Dashboard), `/cockpit`, `/analytics`, `/trades`
5. Tester command palette ⌘K
6. Mobile : désinstaller ancienne PWA, reinstaller → doit pointer vers `/`
7. Tester bookmark `/v2/cockpit` → doit rediriger vers `/cockpit`

### Étape 6 — Monitoring 24h

- Surveiller `/api/status` côté WS clients (doit rester stable)
- Logs Docker : pas de 500 inattendus
- Telegram : pas d'alerte silent_mode déclenchée par le cutover
- Si un user en prod (toi) reporte un problème visuel → rollback immédiat

---

## Rollback — comment annuler en 2 minutes

Si problème critique après cutover :

```bash
git revert <commit-cutover>
bash deploy-v2.sh
```

Ou bascule manuelle côté Nginx / FastAPI :
- Dans `backend/app.py`, remettre `return FileResponse(str(FRONTEND_DIR / "index.html"))` pour `/`
- Redeploy

Le legacy reste entièrement fonctionnel sur `/legacy/*` donc zéro risque de perte d'accès aux données utilisateur. Les utilisateurs actifs n'ont qu'à taper `/legacy` pour retrouver l'ancienne UI.

---

## Risques identifiés

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| SW cache stale sert vieux HTML après cutover | Moyenne | Utilisateur bloqué sur vieille version | `no-cache` sur index.html + bump SW_VERSION |
| Bookmark `/v2/xxx` cassé sans redirection | Haute | Erreur 404 | Redirections `/v2/*` → `/*` côté backend |
| PWA installée reste sur l'ancien scope `/v2/` | Haute | App pointée vers vieux scope | User doit réinstaller PWA |
| Route cassée dans V2 (ex: `/login` absolu) | Moyenne | Page blanche | Audit pré-cutover : grep `href="/v2"` |
| WebSocket `/ws` cesse de fonctionner | Basse | Dashboard passe en POLL | Inchangé côté backend, `/ws` au même chemin |
| Cookie session invalidé | Basse | User déconnecté | SameSite=Lax + Path=/ déjà configurés |

---

## Décision — quand lancer le cutover ?

**Prérequis non négociables** :
1. ☐ Vitest + 20 tests critiques passent (Task #36)
2. ☐ Smoke test end-to-end d'un trade démo (Task #37)
3. ☐ Accumulation 50+ trades post-fix pour que `/v2/analytics` ait vraiment à afficher
4. ☐ User valide explicitement la fenêtre de cutover (pas un mardi à 15h pendant NFP)

**Fenêtre recommandée** : week-end, marché fermé (samedi UTC 22h → dimanche UTC 22h). Zéro trade en cours, zéro pression temps réel si quelque chose casse.

---

## Notes d'implémentation

- Ne pas oublier de migrer les scripts externes (cron, monitoring, Telegram bots) qui pointent vers des URLs `/v2/` spécifiques si applicable
- Commit le cutover **en une seule passe atomique** (un seul commit, un seul deploy) : ne pas déployer en plusieurs étapes qui laisseraient le système dans un état incohérent
- Après 2 semaines de stabilité : envisager la suppression complète du legacy (`backend/FRONTEND_DIR`, `frontend/*.html`, `frontend/js/app.js`) pour alléger l'image Docker
