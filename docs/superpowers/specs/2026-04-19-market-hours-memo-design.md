# Design — Mémo horaires des marchés dans le dashboard

**Date** : 2026-04-19
**Statut** : spec à implémenter
**Contexte** : l'utilisateur veut un mémo visible depuis le dashboard des horaires d'ouverture et de fermeture de chaque marché qu'il surveille (forex + crypto + indices + matières premières). L'info existe actuellement uniquement dans `backend/services/coaching.py` et n'est exposée qu'implicitement via le badge `session-markers` du header.

---

## Contexte et objectif

Scalping Radar surveille **16 supports** répartis en 5 classes d'actifs (forex, crypto, equity index, metal, energy). L'utilisateur a régulièrement besoin de savoir :

- À quelle heure ouvre / ferme tel marché
- Quand est le prochain overlap London/NY (heure d'or du scalping)
- Quels marchés sont actuellement actifs

Aujourd'hui cette info n'est disponible que via le badge `session-markers` (affiche juste "Sydney, Tokyo…") et côté backend dans `_active_sessions_utc()`. L'utilisateur la veut **visible depuis le dashboard**, en heure Paris, compacte, live.

## Arbitrage

3 options de placement ont été évaluées (brainstorm du 2026-04-19) :

| Option | Effort | UX | Gain |
|---|---|---|---|
| **A — Panneau dépliable sous le header** ⭐ | ~2h | Scannable, replié par défaut | Pattern cohérent avec le glossaire existant |
| B — Tooltip au hover sur `session-markers` | ~1h | Infos à la demande mais peu découvrable | Zéro UI permanente |
| C — Nouvelle section "Horaires" dans la sub-nav | ~3h | Espace dédié, plus visible | Ajoute du poids à une nav déjà dense |

**Choix : A.** Pattern déjà connu dans l'app (glossaire en bas), découvrable, replié par défaut, codable en vanilla JS sans framework.

3 formats ont aussi été évalués. **Choix : A — tableau compact** avec colonnes Marché / Ouvre / Ferme / Statut. Timeline rejetée car les classes non-forex (crypto 24/7, equity 15:30-22:00, oil 23:00→22:00) cassent le concept de barres superposées forex.

## Décisions structurantes

| Décision | Choix | Justification |
|---|---|---|
| Placement | Panneau dépliable sous `<header>`, trigger `▾ Horaires` dans `.header-status` | Pattern identique au glossaire (`toggle-glossary`) |
| Format | Tableau compact (4 colonnes : Marché / Ouvre / Ferme / Statut) | Uniforme pour toutes classes d'actifs |
| Scope | 4 sessions forex + BTC/ETH + SPX/NDX + XAU/XAG + WTI = **8 lignes** | Couvre tous les supports surveillés |
| Affichage heures | **Heure Paris uniquement**, calcul via `Intl.DateTimeFormat('fr-FR', { timeZone: 'Europe/Paris' })` | Préférence utilisateur, DST géré automatiquement |
| Refresh live | Toutes les **30s** | Plus réactif que les 60s de `session-markers` (on affiche un countdown) |
| Overlap London/NY | Badge `⚡ overlap` dans la colonne Statut quand les deux sont ouverts | Info clé pour le scalping |
| DST | Résolu dynamiquement via `Intl` à chaque render | Évite toute branche manuelle été/hiver |
| Source de vérité horaires | Constante `MARKETS` côté JS, **horaires en UTC fixe** | Même convention que `_active_sessions_utc` backend et `_activeSessions` frontend existants |
| Logique weekend | Réutilise la même règle que `_activeSessions` : fermé sam, dim avant 22h UTC, ven après 22h UTC | Cohérence backend/frontend |

## Architecture

### Fichiers créés

- `frontend/js/modules/market-hours.js` — module ES6 exportant `renderMarketHours()` et `toggleMarketHoursPanel()`

### Fichiers modifiés

- `frontend/index.html` — bouton trigger dans `.header-status`, container `<section id="market-hours-panel" hidden>` après `<header>`
- `frontend/js/app.js` — import du module, enregistrement du handler `data-action="toggle-market-hours"`, premier render + `setInterval(renderMarketHours, 30000)`
- `frontend/css/style.css` — styles `.market-hours-panel`, `.mh-table`, badges statut
- `frontend/sw.js` — ajout de `/js/modules/market-hours.js` à `SHELL_ASSETS`
- `frontend/js/MODULES.md` — doc du nouveau module

### Data model

```js
// Horaires en UTC fixe (même convention que _activeSessions)
// Les jours de trading sont déterminés par la logique weekend partagée.
const MARKETS = [
    { id: 'sydney',  label: 'Sydney',     flag: '🇦🇺', kind: 'forex',     openUTC:  22, closeUTC:  7 },
    { id: 'tokyo',   label: 'Tokyo',      flag: '🇯🇵', kind: 'forex',     openUTC:   0, closeUTC:  9 },
    { id: 'london',  label: 'London',     flag: '🇬🇧', kind: 'forex',     openUTC:   8, closeUTC: 17 },
    { id: 'newyork', label: 'New York',   flag: '🇺🇸', kind: 'forex',     openUTC:  13, closeUTC: 22 },
    { id: 'crypto',  label: 'BTC / ETH',  flag: '⚡', kind: 'always' },
    { id: 'equity',  label: 'SPX / NDX',  flag: '🇺🇸', kind: 'equity',    openUTC:  13.5, closeUTC: 20 },   // 13:30 → 20:00 UTC
    { id: 'metals',  label: 'XAU / XAG',  flag: '🥇', kind: 'forex_follow' },                                // ouvert si n'importe quelle session forex ouverte
    { id: 'oil',     label: 'WTI',        flag: '🛢️', kind: 'commodity', openUTC:  22, closeUTC: 21 },    // quasi-24/5, fermé 21-22 UTC
];
```

### API du module `market-hours.js`

```js
// État par marché à l'instant t
computeMarketStatus(market, nowUTC) → {
    isOpen: boolean,
    statusLabel: string,        // "● ouvert" | "fermé" | "ouvre dans 1h56" | "⚡ overlap"
    opensAtLabel: string,       // "00:00" (heure Paris) | "24/7" | "suit forex"
    closesAtLabel: string,
    isOverlap: boolean,         // true ssi London + NY ouverts simultanément
}

// Render complet du tableau (appelé au boot puis toutes les 30s)
renderMarketHours() → void

// Toggle du panneau (handler pour data-action="toggle-market-hours")
toggleMarketHoursPanel() → void
```

### Logique de statut par `kind`

- `forex` : ouvert si jour de trading valide ET heure ∈ [openUTC, closeUTC). Logique weekend identique à `_activeSessions` (samedi fermé, dimanche avant 22h UTC fermé, vendredi après 22h UTC fermé).
- `always` : toujours ouvert. Statut = `● ouvert`, colonne Ouvre/Ferme = "24/7" (fusionnée).
- `equity` : ouvert lun-ven 13:30-20:00 UTC (cash hours du NYSE/Nasdaq). Pas d'ouverture sam/dim.
- `forex_follow` : ouvert ssi au moins un marché de kind=forex est ouvert.
- `commodity` (WTI) : ouvert dim 22:00 UTC → ven 21:00 UTC, avec 1h de coupure quotidienne 21:00-22:00 UTC sauf ven (fermeture finale 21:00 UTC).

### Countdown "ouvre dans Xh Ym"

Si un marché est fermé, calculer le prochain `opensAt` (next weekday + openUTC) et afficher `ouvre dans <diff>` en heures/minutes arrondies. Si ferme dans < 2h, afficher `ferme dans Xh Ym`.

### Conversion heure Paris

```js
function toParisHHMM(date) {
    return new Intl.DateTimeFormat('fr-FR', {
        timeZone: 'Europe/Paris',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(date);
}
```

Calculer un `Date` UTC pour chaque heure d'ouverture/fermeture puis formater via cette fonction. Gère le DST automatiquement (avril = CEST = UTC+2, donc 13:00 UTC → 15:00 ; novembre = CET = UTC+1, donc 13:00 UTC → 14:00).

### HTML généré

```html
<section id="market-hours-panel" class="market-hours-panel" hidden aria-labelledby="mh-title">
  <h2 id="mh-title" class="mh-title">Horaires des marchés</h2>
  <table class="mh-table">
    <thead>
      <tr><th>Marché</th><th>Ouvre</th><th>Ferme</th><th>Statut</th></tr>
    </thead>
    <tbody id="mh-tbody"><!-- rempli par JS --></tbody>
  </table>
  <p class="mh-footnote">Heures en Paris (Europe/Paris). Mise à jour toutes les 30s.</p>
</section>
```

### Styles (extrait)

- `.market-hours-panel` : `background: var(--surface)`, `padding: 12px 16px`, `border-radius: 8px`, `margin: 0 16px 12px`
- `.mh-table` : `width: 100%`, `font-size: 0.85rem`, cellules `padding: 4px 8px`
- `.mh-status--open` : couleur `var(--success)` + point `●`
- `.mh-status--closed` : couleur `var(--muted)`
- `.mh-status--overlap` : couleur orange + icône `⚡`
- Animation d'ouverture : réutilise `window.Animations.fadeSlideDown` si déjà dispo côté motion.dev, sinon transition CSS `height`

### Accessibilité

- Bouton trigger : `aria-expanded="false"`, `aria-controls="market-hours-panel"`
- Panneau : `hidden` attribute (pas juste `display:none`, pour les screen readers)
- Respect `prefers-reduced-motion` pour l'animation d'ouverture

## Hors scope (exclus volontairement)

- **Jours fériés** (Thanksgiving NYSE, bank holidays UK, etc.) — demande une source externe, ajoutable plus tard
- **Préférences utilisateur** (hide/show par asset class, réordonner) — YAGNI
- **Persistance de l'état ouvert/fermé** en localStorage — le panneau part replié à chaque visite
- **Affichage UTC** en secondaire — non demandé, ajoutable via toggle plus tard
- **Mobile version** (`mobile.html`) — le mémo est desktop-only dans cette itération. Une ligne dédiée pourra être ajoutée plus tard.
- **Alerte ouverture/fermeture** (notification toast à l'ouverture Sydney, etc.) — pas demandé

## Risques et points d'attention

1. **Cohérence avec `_activeSessions`** : trois implémentations existeront (backend `coaching.py`, frontend `app.js:_activeSessions`, nouveau module). Tant qu'on ne les unifie pas, tout changement de règle doit toucher les trois. Noté dans `MODULES.md`.
2. **SPX/NDX cash hours vs futures** : 13:30-20:00 UTC couvre uniquement le cash. Les futures tournent ~23h/24. Convention prise : on affiche les cash hours car plus pertinents pour le scalping d'indice.
3. **WTI 21:00-22:00 UTC coupure** : 1h chaque jour où le marché est techniquement fermé. À vérifier si on veut vraiment gérer cette subtilité ou simplifier en "22:00 → 21:00 (quasi-24/5)".
4. **Service worker** : ajouter `/js/modules/market-hours.js` à `SHELL_ASSETS` dans `sw.js` est critique sinon le module ne fonctionnera pas en offline PWA. L'auto-bump CACHE_VERSION du Dockerfile (commit `49173a7`) garantit que les users récupèrent la nouvelle version au prochain deploy.

## Plan d'implémentation

Sera détaillé dans un plan séparé via `superpowers:writing-plans`. Grandes étapes anticipées :

1. Module `market-hours.js` avec data model + logique statut
2. Intégration HTML + CSS + bouton toggle
3. Tests manuels : sam, dim avant 22h, dim après 22h, overlap London/NY, DST été/hiver
4. Ajout à `SHELL_ASSETS` dans `sw.js`
5. Commit + push + deploy EC2
