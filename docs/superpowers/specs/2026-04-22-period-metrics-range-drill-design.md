# Carte Performance — range sélectionnable + graph PnL avec drill-down

**Date** : 2026-04-22
**Statut** : spec validée user, prête pour plan d'implémentation
**Criticité** : moyenne (feature V2, pas de risque sur auto-exec)

---

## Contexte

La carte `PeriodMetricsCard` du cockpit V2 affiche aujourd'hui les KPIs de trading agrégés par périodes fixes (Jour / Semaine / Mois / Année / Tout) via `/api/insights/period-stats?period=X`. Elle ne montre **aucune série temporelle** du PnL et ne permet **aucune sélection de range custom**.

L'utilisateur veut pouvoir :

1. Voir en temps réel l'évolution du PnL dans la carte (pas seulement les KPIs scalaires).
2. Choisir une période d'observation précise (ex : du 15 au 22 avril) pour analyser des fenêtres historiques.
3. Zoomer dans le graph pour comprendre la composition d'une barre (drill-down).

Les 5 tabs actuels restent la porte d'entrée, mais sont enrichis : chaque tab pilote une granularité de bars adaptée, et le range est toujours visible + ajustable.

## Objectifs

- Ajouter un graph PnL combo (barres par bucket de temps + ligne cumul) à l'intérieur de `PeriodMetricsCard`.
- Ajouter un sélecteur de range `Du X → Y` toujours visible, avec popover calendrier.
- Conserver les tabs existants, qui deviennent des raccourcis remplissant start/end + granularité.
- Supporter un drill-down au clic sur une barre (ladder : month → day → hour → 5-min).
- Conserver tous les KPIs actuels sans régression.

## Non-objectifs

- Pas d'export CSV depuis cette carte (la page `/v2/trades` fait déjà ça).
- Pas de comparaison multi-ranges (A vs B) dans la même carte.
- Pas de changement des autres cartes du Cockpit (CapitalAtRisk, SystemHealth, etc.).
- Pas de sélection temporelle sub-5-min (bucket minimum = 5-min, pas 1-min ou tick-level).
- Pas de nouvel onglet ni nouvelle route — tout reste dans `PeriodMetricsCard` sur `/v2/cockpit`.

## User stories

- *En tant qu'opérateur live*, je veux voir le PnL de la journée en cours se construire barre par heure au fil des trades, pour évaluer l'intraday sans changer d'écran.
- *En tant qu'analyste rétro*, je veux choisir une semaine passée précise au calendrier et voir la décomposition jour par jour pour identifier les meilleures/pires sessions.
- *En tant qu'investigateur d'anomalie*, je veux cliquer sur une journée rouge pour voir quelles heures ont saigné, puis cliquer sur l'heure pour voir les 5-min coupables.
- *En tant qu'utilisateur mobile*, je veux que tout marche en tap + swipe sans perdre la lisibilité.

## Architecture

Un seul composant enrichi : **`PeriodMetricsCard.tsx` évolue en place**. Aucune nouvelle carte, aucune nouvelle route. On ajoute trois zones dans la carte, de haut en bas :

1. **Toolbar** : tabs + contrôle range "Du X → Y" + flèches `← →` + bouton Reset.
2. **Breadcrumb drill** : visible uniquement quand `drillPath.length > 0` (ex: `Avril 2026 › 20 avr › 14h UTC`).
3. **Graph** : barres vert/rouge par bucket + ligne cumul cyan overlay, hauteur fixe 200 px.

Les **KPIs existants restent sous le graph**, inchangés, mais alimentés par le même `{since, until}` que le graph.

**Flux de données** :

```
useDateRange()  → { preset, start, end, granularity, drillPath, setPreset, drillInto, drillBack }
                      │
        ┌─────────────┼───────────────┐
        │             │               │
        ▼             ▼               ▼
  usePeriodStats   useDailyPnl   (URL sync via useSearchParams)
  (existant,       (nouveau,
   étendu)          avec WS
                    invalidate)
        │             │
        ▼             ▼
  StatsGrid KPIs   DailyPnlChart (SVG bars + line)
```

**Source des trades** : `is_auto=1 AND status='CLOSED' AND pnl NOT NULL` — identique aux cards insights existantes pour éviter toute divergence.

**Real-time** : les deux hooks s'abonnent au push WebSocket `type='cockpit'` déjà en place ; sur push, invalidation des queries concernées si `end === now`. Aucune nouvelle connexion WS.

## UX détaillée

### Toolbar

```
[Jour] [Semaine•] [Mois] [Année] [Tout]
[←]  Du 15 avr → 22 avr 2026  [▼]  [→]  [Reset]
```

- Clic tab → preset + fill start/end + granularité de base (voir table ci-dessous) + reset du drillPath.
- Clic range `Du X → Y` → popover calendrier (react-day-picker mode="range"), preset devient `'custom'`.
- Flèches `← →` → décalent la range d'une période (désactivées pour `preset='all'` et `preset='custom'`).
- Bouton Reset → visible uniquement si `preset='custom'`, retourne à "Semaine".

### Table tab → granularité de base

| Tab / range | Granularité | N barres typique |
|---|---|---|
| Jour | hour | 24 |
| Semaine | day | 7 |
| Mois | day | 28–31 |
| Année | month | 12 |
| Tout | month | N variable |
| Custom | auto (voir règles) | ≤30 idéal |

**Règles auto pour `preset='custom'`** (span = `until - since`) :

- span ≤ 36 h → granularity `hour`
- 36 h < span ≤ 93 jours → granularity `day`
- span > 93 jours → granularity `month`

### Drill-down

Ladder de granularités : `month → day → hour → 5min`.

Clic sur une barre = zoom in vers le niveau en-dessous, **range restreinte à la barre cliquée** :

| Barre cliquée | Nouveau range | Nouvelle granularity |
|---|---|---|
| month | premier/dernier jour du mois | day |
| day | 00:00 → 23:59 UTC du jour | hour |
| hour | début/fin de l'heure (60 min) | 5min |
| 5min | pas de drill plus bas (tooltip seul) | — |

Le **drillPath** est ajouté au state : `[{label: 'Avril 2026', start, end, granularity}, {label: '20 avr', start, end, granularity}, ...]`.

### Breadcrumb

```
Avril 2026 › 20 avr › 14h UTC
```

- Affiché au-dessus du graph quand `drillPath.length > 0`.
- Chaque segment cliquable → remonte à ce niveau (tronque `drillPath`).
- Flèche "Retour" à gauche du breadcrumb = remonte d'un cran (identique à cliquer l'avant-dernier segment).
- Touche `Esc` = remonte d'un cran.
- Changer de tab ou cliquer Reset = `drillPath = []`.

### Graph

- Barres : 1 par bucket, couleur `emerald-400` si `pnl_day > 0`, `rose-400` si `< 0`, translucide (opacity 0.55) pour laisser respirer la ligne.
- Ligne : cumul du PnL sur la range, couleur cyan (`#22d3ee`), épaisseur 2.5 px, avec un point sur chaque bucket + un "pulse" motion sur le dernier bucket si `end === now`.
- Tooltip au hover : `15 avr · 3 trades · +42.10 € (cumul +89.30 €)`.
- Axe Y : cap visuel `±5 × median(|pnl_day|)` pour éviter qu'un outlier compresse tout. Tooltip affiche toujours la vraie valeur.
- Axe X : labels adaptatifs — si ≤ 10 barres, tous labellés ; sinon espacement en N ≈ 7 labels (1er, milieu, dernier, etc.).
- Hauteur fixe 200 px, largeur 100 % de la carte, responsive mobile.

### État vide

Si `n_trades === 0` sur la range :
- Message existant conservé ("Aucun trade clôturé sur cette période").
- Graph remplacé par axe des buckets grisé vide (pour contexte visuel).

### Raccourcis clavier (bonus)

- `J / S / M / A / T` → tabs.
- `← / →` → décale range (quand applicable).
- `Esc` → drill back d'un cran.

### Persistance & URL

- `useDateRange` persiste le state dans `localStorage` clé `scalping_period_range` (survit aux reloads).
- Encoding dans l'URL via `useSearchParams` : `?preset=week&drill=2026-04-20,14`. Permet deeplinks et partage. Priorité URL > localStorage au mount.

## Backend

### Endpoint étendu : `/api/insights/period-stats`

```
GET /api/insights/period-stats
    ?period=day|week|month|year|all    # mode legacy
    |
    ?since=ISO&until=ISO               # mode custom
```

- Si `since` OU `until` fourni → mode custom (les deux requis, sinon 400).
- Sinon `period` (défaut `'day'`) → mode legacy.
- Réponse identique au schéma actuel (PeriodStats).

Le service `insights_service.py` extrait une fonction pure `_compute_period_stats_in_range(since_iso, until_iso)` qui calcule tous les KPIs à partir d'un range. `get_period_stats(period)` devient un wrapper qui calcule `(since, until)` à partir du preset puis appelle la fonction pure.

### Nouveau endpoint : `/api/insights/pnl-buckets`

```
GET /api/insights/pnl-buckets
    ?since=ISO                          # requis
    &until=ISO                          # requis
    &granularity=5min|hour|day|month|auto   # défaut auto
```

Réponse :

```json
{
  "buckets": [
    {
      "bucket_start": "2026-04-20T00:00:00+00:00",
      "bucket_end":   "2026-04-20T23:59:59+00:00",
      "pnl": 42.10,
      "cumulative_pnl": 42.10,
      "n_trades": 3
    },
    ...
  ],
  "granularity_used": "day",
  "total_trades": 22,
  "final_pnl": 187.42,
  "since": "2026-04-15T00:00:00+00:00",
  "until": "2026-04-22T23:59:59+00:00"
}
```

**Implémentation SQL** : `GROUP BY strftime(fmt, closed_at)` avec `fmt` selon granularity :

- `5min` → `strftime('%Y-%m-%d %H:', closed_at) || printf('%02d', (cast(strftime('%M', closed_at) as int) / 5) * 5)`
- `hour` → `strftime('%Y-%m-%dT%H:00:00', closed_at)`
- `day` → `strftime('%Y-%m-%d', closed_at)`
- `month` → `strftime('%Y-%m', closed_at)`

Filtres : `is_auto=1 AND status='CLOSED' AND pnl NOT NULL AND closed_at BETWEEN since AND until`.

**Remplissage buckets vides** : côté Python, on itère de `since` à `until` par pas de granularity et on remplit les buckets absents avec `{pnl: 0, cumulative_pnl: cumul_precedent, n_trades: 0}`. Garde le cumul monotone dans les trous.

**Résolution de `granularity=auto`** : même logique que côté frontend (span-based). Le serveur renvoie la granularity utilisée dans `granularity_used`.

**Garde-fous** :
- Si `granularity='5min'` et `until - since > 24h` → 400 (trop de buckets, non pertinent pour l'UX).
- Cache par query clé (react-query), staleTime variable : 5min → 2 s, hour → 5 s, day → 10 s, month → 60 s.

## Frontend

### Nouveaux modules

```
frontend-react/src/
├── hooks/
│   ├── useDateRange.ts              # NEW — state central
│   └── usePnlBuckets.ts             # NEW — react-query + WS invalidate
├── components/
│   ├── ui/
│   │   └── DateRangePopover.tsx     # NEW — wrapper react-day-picker
│   └── cockpit/
│       ├── DailyPnlChart.tsx        # NEW — SVG bars + line + tooltip
│       ├── RangeToolbar.tsx         # NEW — tabs + range + flèches + reset
│       └── DrillBreadcrumb.tsx      # NEW — path cliquable + retour
```

### `useDateRange`

Signature :

```ts
type Preset = 'day' | 'week' | 'month' | 'year' | 'all' | 'custom';
type Granularity = '5min' | 'hour' | 'day' | 'month';

interface DateRangeState {
  preset: Preset;
  start: string;        // ISO
  end: string;          // ISO (typiquement now si preset != 'custom')
  granularity: Granularity;
  drillPath: Array<{ label: string; start: string; end: string; granularity: Granularity }>;
}

interface UseDateRange extends DateRangeState {
  setPreset(p: Preset): void;                          // + reset drillPath
  setCustomRange(start: string, end: string): void;    // preset='custom'
  shiftRange(dir: -1 | 1): void;                       // flèches ← →
  drillInto(bucket: { label; start; end }): void;      // clic barre
  drillBack(levels?: number): void;                    // breadcrumb / Esc
  reset(): void;                                       // retour preset par défaut
}
```

Source de vérité : URL `useSearchParams`, fallback `localStorage`, fallback default `'week'`.

### `usePnlBuckets`

```ts
function usePnlBuckets({ since, until, granularity }: ...): UseQueryResult<BucketsResponse>
```

- `useQuery(['pnl-buckets', since, until, granularity], fetcher, { staleTime: per-granularity })`.
- S'abonne au WS cockpit push via `useEffect` + `queryClient.invalidateQueries` si `end === now` (debounce 1 s).

### `DateRangePopover`

Wrapper autour de `react-day-picker` v9, mode `range`, localisation fr-FR, styles Tailwind custom matching glass/cyan. Placé via `createPortal` sur `document.body` avec z-index 9999 pour éviter le piège GlassCard + `backdrop-blur`.

### `DailyPnlChart`

Composant SVG pur (pattern existant `Sparkline`). Props : `{ buckets, granularity, onBarClick }`. Hauteur 200 px, largeur 100 %, responsive. Animation motion sur la dernière barre si live (`end === now`).

### `RangeToolbar` et `DrillBreadcrumb`

Petits composants présentationnels, stylés comme la toolbar existante (glass soft + tabs cyan).

### Modifications existantes

- `hooks/useCockpit.ts::usePeriodStats(period)` → `usePeriodStats({ since, until })`, migré pour accepter le range. Appelants existants passent `{since, until}` calculé depuis preset.
- `components/cockpit/PeriodMetricsCard.tsx` → wire `useDateRange` + orchestration.

### Dépendance ajoutée

- `react-day-picker` v9 — headless, ~12 KB gzipped, zéro sub-dep. Ajouté dans `package.json` dependencies.

## Real-time

- WebSocket channel existant `type='cockpit'` pushé depuis le scheduler backend toutes les 5 s + sur fermeture de trade.
- `usePnlBuckets` listen ce push (via le même mécanisme que `useCockpit`) → invalide la query si `range.end === now` (± 1 min de tolérance).
- `usePeriodStats` idem.
- Animation : barre "en cours" scale-up subtil à chaque invalidation (motion layoutId).

## Tests

### Backend (`backend/tests/test_insights_service.py`, `test_app.py`)

- `_compute_period_stats_in_range` avec : range vide, 1 jour, weekend sans trades, 6 mois avec multiple close_reasons.
- `get_pnl_buckets` : granularity `day` avec trous (fill à 0, cumul monotone), granularity `hour` / `5min` sur 1 jour précis, granularity `auto` résolution correcte.
- Cohérence croisée : `sum(buckets.pnl) === period_stats.pnl` sur le même range.
- Backward compat : `GET /api/insights/period-stats?period=week` inchangé (même JSON).
- Garde-fous 400 : `5min` avec range > 24 h → 400, `since` sans `until` → 400.

### Frontend (Vitest)

- `useDateRange` : chaque preset → bonnes bornes, flèches décalent correctement (edge cases mois court 28/29/30/31 jours, année bissextile, DST non applicable car UTC), drillInto + drillBack idempotent.
- `DateRangePopover` : sélection range, annulation, apply, clic extérieur ferme.
- `DailyPnlChart` : rendu 1/7/30/365 buckets, clic émet `onBarClick({start, end, label})`, tooltip apparaît au hover.
- `PeriodMetricsCard` (integration) : changement tab, drill-down 3 niveaux, back browser reset correctement.

### Smoke E2E manuel

- Session Chromium locale : tabs → range custom → flèche avance/recule → drill day → hour → 5min → retour.
- Simuler un trade close (via `/debug` ou vraie exécution) → la barre live grandit sans refresh.

## Rollout

1. Branche `feat/period-metrics-range-drill`.
2. Commits atomiques suggérés :
   - `feat(backend): extend period-stats avec since/until + refactor range pur`
   - `feat(backend): /api/insights/pnl-buckets avec granularity`
   - `feat(v2): useDateRange hook + URL sync + localStorage`
   - `feat(v2): DateRangePopover via react-day-picker`
   - `feat(v2): DailyPnlChart SVG bars + line + tooltip`
   - `feat(v2): wire PeriodMetricsCard avec range + graph + drill`
   - `test: tests insights_service + useDateRange + chart`
3. Push origin + `bash deploy-v2.sh`.
4. Smoke test sur `https://scalping-radar.duckdns.org/v2/cockpit` : tabs, range, drill, back.
5. Surveillance Sentry / Docker logs 1 h pour détecter régressions silencieuses.

## Risques et mitigations

| Risque | Proba | Mitigation |
|---|---|---|
| Range `Tout` (2 ans) + granularity day → 730 barres illisibles | Haute | `auto` escalade à `month` dès > 93 jours ; user peut forcer day mais avec warning |
| 1 outlier 5-min compresse l'axe Y | Haute | Cap visuel `±5 × median(|pnl|)` ; outlier reste visible avec clip marker, tooltip donne vraie valeur |
| Popover calendrier clippé par GlassCard `backdrop-blur` | Certaine (bug connu) | `createPortal` obligatoire, z-index 9999, même pattern que `Tooltip` |
| WS invalidate trop agressif = re-fetch bridge massif | Moyenne | Debounce 1 s dans `usePnlBuckets`, invalidate seulement si range inclut `now` |
| Tests datetime flaky entre fuseaux | Moyenne | Tout en UTC, `vi.useFakeTimers()` + `vi.setSystemTime(new Date('2026-04-22T05:30:00Z'))` |
| Drill state + back browser = deeplink cassé au refresh | Moyenne | URL encode via useSearchParams ; au mount restore depuis URL avant localStorage |
| Granularity `5min` + trading intense = 60 buckets denses sur 1 h | Basse | Contrainte backend (span ≤ 24h), largeur min 8 px par barre, chart horizontal scrollable si > 40 barres |
| Régression des KPIs existants par refactor `_compute_period_stats_in_range` | Moyenne | Tests de non-régression : mêmes snapshots JSON entrée/sortie qu'avant sur presets `day/week/month/year/all` |

## Hors scope explicite

- Granularité `1min` ou tick-level : non pertinent pour du scalping demo à ~1-3 trades/h. Si besoin futur, extension triviale du ladder.
- Compare mode (overlay A vs B) : utile pour analyser "cette semaine vs semaine passée" mais hors scope.
- Annotations sur le graph (events macro, news) : chantier séparé (Vague 3).
- Export du graph en PNG / CSV.
- Changement des autres widgets du cockpit (seul `PeriodMetricsCard` est touché).

## Questions ouvertes

Aucune à ce stade — toutes les décisions de scope ont été tranchées lors du brainstorming. Les détails d'implémentation (nommage exact des classNames Tailwind, signatures précises des fonctions utilitaires) seront précisés dans le plan d'implémentation.

## Fichiers impactés (récapitulatif)

```
backend/
  app.py                                          # +params since/until, +route /api/insights/pnl-buckets
  services/insights_service.py                    # refactor pure + nouvelle fonction get_pnl_buckets
  tests/test_insights_service.py                  # +tests range & buckets
  tests/test_app.py                               # +tests garde-fous 400

frontend-react/
  package.json                                    # +react-day-picker v9
  src/hooks/useDateRange.ts                       # NEW
  src/hooks/usePnlBuckets.ts                      # NEW
  src/hooks/useCockpit.ts                         # usePeriodStats accepte {since, until}
  src/components/ui/DateRangePopover.tsx          # NEW
  src/components/cockpit/DailyPnlChart.tsx        # NEW
  src/components/cockpit/RangeToolbar.tsx         # NEW
  src/components/cockpit/DrillBreadcrumb.tsx      # NEW
  src/components/cockpit/PeriodMetricsCard.tsx   # wire tout
  src/test/useDateRange.test.ts                   # NEW
  src/test/DailyPnlChart.test.tsx                 # NEW
  src/test/DateRangePopover.test.tsx              # NEW
```
