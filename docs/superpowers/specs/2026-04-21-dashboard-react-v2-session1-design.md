# Dashboard React V2 — Session 1 (Dashboard + Login + Performance)

**Date** : 2026-04-21
**Auteur** : session migration frontend, brainstorm validé 2026-04-21
**Scope** : première session sur 3 de la migration complète frontend → React

## Contexte

Le dashboard Scalping Radar est aujourd'hui 100% vanilla JS ES modules (`frontend/index.html` ~530 lignes + `frontend/js/app.js` ~1700 lignes avec état mutable partagé), servi statiquement par FastAPI. Le design system "Trading Desk haute densité" est caractéristique et abouti (bleu-nuit + néon menthe/rose, grille blueprint, JetBrains Mono), mais l'UX des interactions est statique (pas de re-render réactif, animations déclenchées manuellement).

La Phase 1 UI animations (spec `2026-04-19-ui-animations-phase1`) a apporté 80% du polish visuel sans toucher à l'architecture. Cette session lance la **Phase 2** : migration du dashboard principal vers React pour gagner le dernier 20% (réactivité fluide, composition, future-proofing).

La migration est **étalée sur 3 sessions** pour ne pas casser la prod :
- **Session 1 (ce spec)** : Dashboard principal + Login + Performance, route `/v2/*`, coexistence avec l'ancien
- **Session 2** : Mobile view + PWA (manifest, SW) + modal "prendre ce trade" + market hours panel
- **Session 3** : Pages accessoires (risque/equity/stats/CSV) + son/voix + charts + **swap final** `/` → nouvelle app

La coexistence est garantie pendant les 3 sessions : `/` continue de servir l'ancien frontend, `/v2/*` sert le nouveau. Le swap final ne sera fait qu'une fois la session 3 validée.

## Objectif de la session 1

Livrer une V2 visuellement polie du **dashboard principal** (bandeau macro + grille setups + panneau performance + header + login), fonctionnelle bout en bout sur `/v2/*`, exploitant les endpoints REST et WebSocket existants sans aucune modification backend.

## Non-objectifs de cette session

- Pas de PWA / service worker (session 2)
- Pas de modal "prendre ce trade" (session 2)
- Pas de market hours panel dans le header (session 2)
- Pas de son / synthèse vocale (session 3)
- Pas de charts lightweight-charts (session 3)
- Pas de pages risque/equity/stats/CSV (session 3)
- Pas de suppression de l'ancien frontend (session 3)

## Architecture

### Direction esthétique — "Trading Neo + Bento Polish"

Hybride des directions B (Trading Neo) et F (Bento Glassmorphic) validées au brainstorm visuel :
- Fond `linear-gradient(135deg, #0a0e14 0%, #13112a 100%)` + mesh gradient subtil (violet/rose/cyan diffusés)
- Cartes avec glass (`backdrop-filter: blur(20px)`, border `rgba(255,255,255,0.08)`, radius **16-20px**)
- Gradients **cyan→magenta** sur les accents (scores, valeurs clés) via `background-clip: text`
- Ombres profondes teintées violet (`0 4px 24px rgba(139,92,246,0.15)`)
- Typo **Inter** (UI) + **JetBrains Mono** (chiffres, paires)
- Neon buy/sell conservés (`#22d3ee` achat, `#ec4899` vente) en gradients soyeux
- Préférence `prefers-reduced-motion: reduce` respectée partout

### Stack technique

- **Vite 5** + **React 18** + **TypeScript** strict
- **react-router-dom 6** pour router minimal (`/v2/`, `/v2/login`)
- **@tanstack/react-query 5** pour les fetch REST avec cache + refetch + invalidation
- **motion** (ex-framer-motion) pour animations déclaratives
- **Tailwind 3** pour utilities CSS + tokens du design system
- **clsx** pour className conditionnelles
- Build : `vite build` → `frontend-react/dist/` inclus au bundle Docker

### Structure de fichiers

```
frontend-react/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── index.html
├── .gitignore              # dist/, node_modules/
├── public/
│   └── favicon.svg
└── src/
    ├── main.tsx                       # entrypoint, React Query provider
    ├── App.tsx                        # <BrowserRouter basename="/v2"> + routes
    ├── pages/
    │   ├── DashboardPage.tsx
    │   └── LoginPage.tsx
    ├── components/
    │   ├── layout/
    │   │   └── Header.tsx             # logo + heure Paris live + status WS + logout
    │   ├── macro/
    │   │   └── MacroBanner.tsx        # risk_regime, DXY, SPX, VIX en pills glass
    │   ├── setups/
    │   │   ├── SetupsGrid.tsx         # grille responsive 1/2/3 cols + filtre score min
    │   │   └── SetupCard.tsx          # carte glass, gradient score, animations entry/exit
    │   ├── performance/
    │   │   └── PerformancePanel.tsx   # 6 buckets en tabs : score, asset, direction, regime, session, pair
    │   ├── auth/
    │   │   └── AuthGate.tsx           # check session au boot, redirect /v2/login si KO
    │   └── ui/
    │       ├── GlassCard.tsx          # primitive réutilisable (variant: default | elevated)
    │       ├── GradientText.tsx       # texte en gradient cyan→magenta
    │       ├── Skeleton.tsx           # placeholder loading (pulse motion)
    │       └── MeshGradient.tsx       # background ambiance (fixed, z:-1)
    ├── hooks/
    │   ├── useWebSocket.ts            # /ws avec reconnect exponentiel + heartbeat
    │   ├── useMacro.ts                # /api/macro + refresh 30s
    │   ├── useSetups.ts               # /api/trade-setups + invalidation via WS
    │   ├── usePerformance.ts          # /api/insights/performance?since=...
    │   └── useAuth.ts                 # login / logout / whoami
    ├── types/
    │   └── domain.ts                  # Setup, MacroContext, InsightsBucket, User, WSMessage
    ├── lib/
    │   ├── api.ts                     # fetch wrapper (credentials: 'include', error helpers)
    │   ├── format.ts                  # helpers (price, pct, durée, heure Paris)
    │   └── queryClient.ts             # React Query config (staleTime, retry policy)
    └── styles/
        ├── globals.css                # @tailwind base/components/utilities, variables design tokens
        └── motion.css                 # keyframes réduits si prefers-reduced-motion
```

### Data flow

1. **Boot** : `main.tsx` monte `<QueryClientProvider>` + `<BrowserRouter basename="/v2">`.
2. **AuthGate** (dans `App.tsx`) : au premier render, `useAuth().whoami()` appelle `GET /api/me`. Si 401 → `<Navigate to="/login">`. Si 200 → affiche `<Outlet>`.
3. **DashboardPage** monte en parallèle :
   - `useMacro()` → `GET /api/macro`, staleTime 20s + refetchInterval 30s
   - `useSetups()` → `GET /api/trade-setups`, staleTime 60s. Écoute aussi `useWebSocket` : sur message `setups_update`, `queryClient.invalidateQueries(['setups'])`
   - `usePerformance()` → `GET /api/insights/performance?since=<SINCE>` avec `SINCE` = constante `POST_FIX_CUTOFF` dans `lib/api.ts` (valeur `2026-04-20T21:14:00+00:00` en V1, à ajuster plus tard quand on aura un compteur dynamique), staleTime 60s + refetchInterval 5min
4. **Composants consomment les hooks**, affichent skeletons pendant loading, animent (`motion` `<AnimatePresence>`) sur mount/update/exit.
5. **LoginPage** : form contrôlé → `POST /api/login` → succès = `navigate('/')` (qui devient `/v2/` via basename).
6. **Logout** : `POST /api/logout` → `queryClient.clear()` → `navigate('/login')`.

### Intégration FastAPI (côté `backend/app.py`)

Ajouter 2 blocs en haut des routes de `app.py`, juste après les mounts existants :

```python
# SPA React V2 (coexiste avec l'ancien frontend sur /)
from pathlib import Path
V2_DIST = Path(__file__).parent.parent / "frontend-react" / "dist"
if V2_DIST.exists():
    app.mount(
        "/v2/assets",
        StaticFiles(directory=str(V2_DIST / "assets")),
        name="v2-assets",
    )
    # favicon + autres statiques à la racine de dist/
    for asset in ("favicon.svg", "robots.txt"):
        if (V2_DIST / asset).exists():
            pass  # servi via la route catch-all ci-dessous

    @app.get("/v2/{path:path}", include_in_schema=False)
    async def serve_v2(path: str):
        """SPA fallback : tout ce qui n'est pas un asset tombe sur index.html,
        React Router se charge du routing côté client."""
        # Tenter d'abord un fichier physique dans dist/ (pour favicon etc.)
        file_path = V2_DIST / path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(V2_DIST / "index.html"))
```

### Dockerfile (stage de build)

Ajouter une étape Node avant l'étape Python existante :

```dockerfile
# Stage 1 : build React
FROM node:20-alpine AS react-builder
WORKDIR /build
COPY frontend-react/package*.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build

# Stage 2 : image finale Python existante (Dockerfile actuel = python:3.11-slim)
FROM python:3.11-slim
# ... (existing setup)
COPY --from=react-builder /build/dist /app/frontend-react/dist
# ... (suite existante)
```

### Package.json (dépendances précises)

```json
{
  "name": "scalping-radar-v2",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2",
    "@tanstack/react-query": "^5.56.2",
    "motion": "^11.11.17",
    "clsx": "^2.1.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.13",
    "typescript": "^5.5.4",
    "vite": "^5.4.8"
  }
}
```

### Tokens design (tailwind.config.ts extend)

```ts
colors: {
  // Neon trading
  'neon-buy': '#22d3ee',
  'neon-sell': '#ec4899',
  // Backgrounds
  'radar-deep': '#0a0e14',
  'radar-surface': '#13112a',
  // Glass borders
  'glass-soft': 'rgba(255,255,255,0.08)',
  'glass-strong': 'rgba(255,255,255,0.15)',
},
fontFamily: {
  sans: ['Inter', 'system-ui', 'sans-serif'],
  mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
},
backdropBlur: { glass: '20px' },
boxShadow: {
  'glass-ambient': '0 4px 24px rgba(139,92,246,0.15)',
  'glass-elevated': '0 8px 32px rgba(139,92,246,0.25)',
},
```

## Tests

Session 1 = scope UI + data flow. Tests retenus :

- **Typecheck** : `npm run typecheck` (strict TypeScript, 0 erreur)
- **Smoke manuel** end-to-end :
  1. Ouvrir `http://scalping-radar.duckdns.org/v2/` sans session → redirect `/v2/login`
  2. Login valide → redirect `/v2/` → dashboard affiche macro + setups + performance
  3. Observer au moins 1 cycle setup (3min20) → une carte apparaît/disparaît avec animation motion
  4. Ouvrir dev tools → 0 erreur console, 0 warning sur dependency loop React Query
  5. Redimensionner fenêtre desktop → grille setups passe 3 / 2 / 1 col fluide
  6. Logout → retour login, cookie effacé

Pas de tests unit Vitest en V1 — scope trop large, bénéfice faible sur du code UI qui va encore bouger en sessions 2-3.

## Déploiement

1. `frontend-react/` créé à la racine du repo, configuré (Vite + TS + Tailwind + React).
2. Smoke local : `cd frontend-react && npm install && npm run dev` sur port 5173, vérifier dashboard.
3. Build : `npm run build` → `dist/` généré, inspecté.
4. Modification `backend/app.py` (mount + catch-all v2).
5. Modification `Dockerfile` (stage node:20-alpine).
6. Commit + push, pull + build + restart sur EC2.
7. Smoke prod sur `/v2/`.
8. Ancien `/` inchangé, reste fonctionnel.

## Rollback

Additive uniquement — si `/v2/*` présente un bug :
1. Option rapide : git revert du commit + redeploy (5 min).
2. Option chirurgicale : commenter les 2 blocs du mount `/v2/` dans `app.py` + restart (2 min, laisse le reste du commit en place).

Dans les deux cas, `/` reste fonctionnel car inchangé par cette session.

## Critères de succès

- [ ] `GET /v2/login` retourne le bundle React (200, HTML `<div id="root">`).
- [ ] Login valide → redirect `/v2/` avec cookie session.
- [ ] MacroBanner affiche les vraies données macro (risk_regime, DXY, SPX, VIX).
- [ ] SetupsGrid affiche les setups live (≥ 50 score), avec animations motion sur entry/exit via WebSocket.
- [ ] PerformancePanel affiche les 6 buckets de `/api/insights/performance`.
- [ ] Lighthouse desktop : performance > 85, best practices > 90.
- [ ] Aucune erreur console au chargement, aucun warning `tsc`.
- [ ] Ancien dashboard `/` reste intégralement fonctionnel, sans régression.

## Dépendances amont / aval

- **Amont (prérequis)** : aucun. Les endpoints `/api/macro`, `/api/trade-setups`, `/api/insights/performance`, `/api/login`, `/api/logout`, `/api/me`, `/ws` existent déjà en prod et sont stables.
- **Aval (unlock)** : session 2 (Mobile + PWA + modal + market hours) peut démarrer dès que session 1 est mergée. Session 3 dépend de session 2 pour le swap final.
