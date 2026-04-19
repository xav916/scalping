# Frontend JS — état et plan de modularisation

## État actuel (après cette passe)

```
frontend/js/
├── app.js                   ← entrypoint, chargé en <script type="module">
├── modules/
│   ├── utils.js             ← helpers purs (escapeHtml, countdown, patternLabel…)
│   └── market-hours.js      ← mémo horaires des marchés (data model + helpers purs + DOM)
├── vendor/
│   └── lightweight-charts.standalone.production.js   ← self-hosté
└── MODULES.md               ← ce document
```

**Ce qui a été fait** :
- `app.js` est maintenant un module ES (strict mode automatique, scope isolé).
- Les 7 helpers purs ont été extraits dans `utils.js` (testables sans DOM).
- `market-hours.js` isole le nouveau panneau "Horaires des marchés" (8
  marchés surveillés, heure Paris). Les helpers purs (`computeMarketStatus`,
  `toParisHHMM`, `formatCountdown`, `isForexWeekendClosed`) sont couverts par
  `tests/frontend/market-hours.test.mjs` (runnable via `node --test`). Les
  fonctions DOM (`renderMarketHours`, `toggleMarketHoursPanel`) sont appelées
  depuis `app.js` au DOMContentLoaded et toutes les 30 s.
- Pas d'autre découpage : les 1600+ lignes restantes partagent un état mutable
  (ws, _tickState, _activeCharts, _currentSignalForModal, etc.) qui demande
  une stratégie d'exposition propre (objet partagé, live bindings, ou events)
  avant d'être splitté sans régression.

## Plan de découpage fin (à faire quand on aura des tests)

```
modules/
├── utils.js          # déjà fait
├── state.js          # objet mutable partagé : { ws, tickState, activeCharts, ... }
├── audio.js          # Web Audio (bip), speech synthesis (voix)
├── theme.js          # light/dark toggle + application au DOMReady
├── sessions.js       # forex trading sessions (Sydney/Tokyo/London/NY)
├── api.js            # tous les fetch* vers /api/*
├── ws.js             # WebSocket : connect, reconnect, heartbeat, dispatch
├── render.js         # toutes les fonctions render*/tradeSetupHTML/...
├── actions.js        # openTradeModal, confirmTradeSubmit, _handleDelegatedClick…
└── main.js           # entrypoint : importe tout, wire DOMContentLoaded
```

### Graphe de dépendances cible (pas de cycles)

```
utils, state            (couche basse, sans dépendance)
   ↓
render                  (utils + state)
   ↓
api, audio, theme, sessions   (render + utils + state)
   ↓
ws                      (render + audio + state)
   ↓
actions                 (api + render + state)
   ↓
main                    (everything, wire init)
```

### Points d'attention pour la migration

1. **État partagé** : exporter un `state` namespace depuis `state.js` et remplacer
   toutes les refs globales (`ws` → `state.ws`, `_tickState` → `state.tickState`,
   etc.). Vigilance sur les reassignations : avec `state.ws = new WebSocket()` ça
   fonctionne ; avec `export let ws` + `ws = new WebSocket()` aussi (live bindings)
   mais un consommateur ne peut pas écrire dans la variable importée → préférer
   l'approche objet.

2. **Theme FOUC** : `_applyTheme(_currentTheme())` tourne à l'import du module ;
   `theme.js` doit être importé en premier dans `main.js` (ou le `<link
   rel="modulepreload">` peut forcer l'ordre).

3. **Event delegation** : `_handleDelegatedClick` dans `actions.js` doit pouvoir
   appeler des fonctions de `render.js` (rare) + toutes les actions. Pas de
   cycle si `render` n'importe pas `actions`.

4. **Tests suggérés** avant de splitter :
   - `utils.test.js` : escapeHtml sur strings bizarres, countdown sur dates
     limites, patternLabel sur clés connues/inconnues.
   - Smoke test Playwright : connexion, ouverture trade modal étape 1→2,
     clôture, changement de thème, bascule son.

5. **Le SW doit lister chaque module ES** dans `SHELL_ASSETS` pour que l'app
   fonctionne offline. Chaque ajout de module = ligne ajoutée + bump de
   `CACHE_VERSION` dans `sw.js`.

## Pourquoi ne pas avoir tout splitté maintenant

- ~1700 lignes avec état mutable partagé partout → chaque extraction crée un
  risque de régression subtile (ordre d'exécution, références mortes, etc.).
- Aucun test automatisé n'existe pour valider un comportement post-refactor.
- Le bénéfice lisibilité d'un split aujourd'hui est moins important que le
  risque de casser le dashboard en prod.

Faire cette migration en un seul gros PR sans tests serait irresponsable. La
plan est ici, prêt à être exécuté une fois que la suite de tests aura été
mise en place (Playwright recommandé pour l'UI, Vitest/Jest pour `utils.js`).
