# Design — UI Macro Panels (bandeau + barres d'alignement)

**Date** : 2026-04-19 (rédigé a posteriori)
**Statut** : implémenté et livré (commits `5f3ad10`, `dc69ae9`)
**Dépend de** : `2026-04-19-macro-context-scoring-design.md` (Vague 1)

---

## Contexte et objectif

Après avoir livré la Vague 1 du scoring macro (module backend + persistance), seule trace visible côté UI : un badge `×1.20` / `×0.90` sur chaque carte setup. Insuffisant pour :

1. Visualiser **l'état macro du marché en temps réel**, indépendamment des setups
2. Comprendre **pourquoi** un setup a été boosté ou pénalisé (quels indicateurs l'ont influencé)

Objectif : deux panneaux UI qui exposent le contexte macro de façon permanente (bandeau) et contextuelle (carte setup).

## Décisions

| Décision | Choix | Justification |
|---|---|---|
| Scope | **Bandeau global + barres par setup**, pas d'historique des vetos | L'historique demande une table de persistance dédiée, à faire plus tard quand des vetos auront été accumulés |
| Placement bandeau | Top du dashboard, sous le header, avant le bloc daily | Visible à chaque chargement, sans scroller |
| Auth bandeau | Endpoint **public** (`/api/macro` sans auth) | C'est du market data, pas de donnée privée |
| Fréquence refresh front | 60s (vs 900s côté scheduler) | Affiche l'âge du cache dans l'UI, bandeau toujours frais |
| Format barres | 1 pill par primaire : `INDICATEUR✓`, `INDICATEUR✗`, `INDICATEUR—` | Compact, lisible, hoverable pour le détail |
| Changement shape `apply()` | `(mult, veto, list[dict])` au lieu de `(mult, veto, list[str])` | La forme texte perdait l'info structurée — nécessaire pour les barres |

## Architecture

### Panneau 1 — Bandeau macro permanent

**Backend** : nouvel endpoint `GET /api/macro` dans `backend/app.py`

```python
@app.get("/api/macro")
async def api_macro():
    snap = get_macro_snapshot()
    if snap is None:
        return {"available": False}
    # ... retourne age_sec + indicators dict + risk_regime + spread_trend
```

**Contract JSON** (réponse) :

```json
{
  "available": true,
  "fresh": true,
  "age_seconds": 314.2,
  "indicators": {
    "dxy":    {"direction": "up",        "value": 103.21},
    "spx":    {"direction": "neutral",   "value": 4521.3},
    "vix":    {"level":     "normal",    "value": 17.5},
    "us10y":  {"direction": "strong_up", "value": 4.12},
    "de10y":  {"direction": "up",        "value": 2.45},
    "oil":    {"direction": "down",      "value": 78.2},
    "nikkei": {"direction": "up",        "value": 33421.0},
    "gold":   {"direction": "neutral",   "value": 2031.5}
  },
  "risk_regime": "neutral",
  "spread_trend": "widening"
}
```

**Frontend** :
- Markup HTML dans `frontend/index.html` : `<div id="macro-banner" class="hidden">` avec conteneurs pour les cellules + badge regime + texte âge
- JS dans `frontend/js/app.js` :
  - Constante `MACRO_INDICATORS` (liste des 8 à afficher)
  - Helpers `dirArrow(direction)` (retourne ↑↓⇈⇊→) et `dirClass(direction)` (classe CSS)
  - `renderMacroBanner(data)` remplit les cellules, le regime badge, le texte âge
  - `fetchMacroAndRender()` appelée au DOMContentLoaded puis toutes les 60s via `setInterval`
- CSS dans `frontend/css/style.css` : `.macro-banner-*`, `.macro-cell.*`, `.macro-regime-*`

**Comportement** :
- Si `snap == null` au backend → `{"available": false}` → le bandeau reste `hidden`
- Dès le premier fetch avec données → bandeau se révèle
- Chaque indicateur a une couleur selon sa direction (vert = up, rouge = down, neutre = gris)
- Le VIX est mappé `low → down`, `normal → neutral`, `elevated → up`, `high → strong_up` (unified palette)

### Panneau 2 — Barres d'alignement sur carte setup

**Backend** : 
- Extension de `ConfidenceFactor` dans `backend/models/schemas.py` avec un champ `metadata: dict | None = None`
- Changement de la signature de `macro_scoring.apply()` :
  - Avant : `tuple[float, bool, list[str]]` (multiplier, veto, reasons)
  - Après : `tuple[float, bool, list[dict]]` où chaque dict = `{"indicator": str, "alignment": int∈{-1,0,1}, "reason": str, "is_veto": bool}`
- Dans `enrich_trade_setup()`, la macro factor stocke `metadata={"primaries": primaries, "multiplier": multiplier, "veto": veto}`
- Le texte `detail` reste construit depuis les reasons pour compat

**Frontend** :
- Dans `tradeSetupHTML(s)` :
  - Récupère `macroFactor = s.confidence_factors.find(f => f.source === 'macro')`
  - Construit `primariesHtml` depuis `macroFactor.metadata.primaries` (filtre les `is_veto`)
  - Chaque primaire = `<span class="macro-prim macro-prim-ok|bad|neu" title="<reason>">INDICATEUR✓</span>`
- CSS `.macro-prims-row`, `.macro-prim-ok|bad|neu`

**Choix de conception (traçabilité)** :
- **Zero-alignment primaries exclus du denominator** (comportement hérité de Task 4 scoring) — les primaires qui disent "pas d'info" ne diluent pas la moyenne
- **Zero-alignment primaries aussi exclus de la sortie list** — pour cohérence avec les tests existants et pour ne pas afficher des pills `—` inutiles sur l'UI
- **Veto primary artificiel** ajoutée à la liste quand un veto trigge, avec `is_veto: true` — la front filtre ces entrées (le veto s'affiche autrement, dans le verdict)

### Stack technique

- Vanilla HTML + JS + Tailwind (pas de framework)
- Pas de nouvelle dépendance Python ni JS
- Endpoint FastAPI standard (pas de streaming, pas de WebSocket)

## Tests

### Backend
- `test_macro_scoring.py` adapté : toutes les assertions sur `reasons: list[str]` converties en assertions sur `primaries: list[dict]` avec clés `indicator`, `alignment`, `reason`, `is_veto`
- `test_analysis_engine_macro.py` : nouveau test qui vérifie que `macro_factor.metadata["primaries"]` existe et contient les bonnes clés

### Frontend
- Pas de test auto (JS vanilla, pas de framework de test en place)
- Validation manuelle : ouvrir le dashboard, attendre le 1er refresh macro, vérifier que le bandeau apparaît ; déclencher un setup (simulation ou vraie détection) et vérifier les barres

## Observabilité

- L'endpoint `/api/macro` public n'a pas d'auth — accès depuis navigateur direct pour debug
- L'endpoint admin `/debug/macro` (existant, auth) expose un dump plus verbeux (raw_values, age_seconds précis)

## Ce qui n'est pas inclus (YAGNI)

- **Pas d'historique des vetos** (reporté — demande une table dédiée, pas encore de données réelles à afficher)
- **Pas de graphiques** (pas de visualisation temporelle du DXY/SPX — le bandeau montre juste l'état actuel)
- **Pas de configuration par user** (tous les users voient le même mapping)
- **Pas de clic sur une primaire pour filtrer les setups** (fonctionnalité cool mais overkill en v1)

## Références implémentation

- Endpoint : `backend/app.py` (ajout vers `/api/overview`)
- Renderer bandeau : `frontend/js/app.js::renderMacroBanner`, `fetchMacroAndRender`
- Renderer barres : `frontend/js/app.js::tradeSetupHTML` (bloc `primariesHtml`)
- CSS bandeau : `frontend/css/style.css` (`.macro-banner-*`, `.macro-cell.*`, `.macro-regime-*`)
- CSS barres : `frontend/css/style.css` (`.macro-prims-row`, `.macro-prim-*`)

Commits :
- `5f3ad10 feat(ui): add macro context banner on dashboard`
- `dc69ae9 feat(ui): per-primary alignment bars on setup cards`
