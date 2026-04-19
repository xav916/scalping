# Design — UI Animations Phase 1 (motion.dev + polish)

**Date** : 2026-04-19 (rédigé a posteriori)
**Statut** : implémenté et livré (5 commits, `a660c7d` → `42ae960`)
**Contexte** : première phase d'un rework visuel en deux temps. Phase 2 (React embed du dashboard) sera faite en session dédiée.

---

## Contexte et objectif

Le dashboard Scalping Radar est techniquement correct mais visuellement "statique" : les setups apparaissent brutalement, les valeurs changent d'un coup, aucun feedback sur les changements de contexte macro, pas d'indication pendant le loading. Objectif : **80% du gain visuel, 20% de l'effort**, sans toucher à l'architecture (pas de migration React).

## Arbitrage initial

3 options ont été considérées :

| Option | Effort | Risque | Gain visuel |
|---|---|---|---|
| **A — Couche d'animations vanilla** ⭐ | 2-4h | Faible | ~80% |
| B — Migration React partielle (dashboard) | 2-3j | Moyen | ~95% |
| C — Rewrite complet React + Next + 21st.dev | 5-10j | Élevé | 100% |

**Choix : A maintenant, B en session dédiée.** C jugée trop risquée vu que le système est en prod active (MT5 bridge, auto-trades, auth, PWA Android, service worker). A + B combinées donnent un résultat proche de C avec un risque bien mieux maîtrisé.

## Décisions structurantes

| Décision | Choix | Justification |
|---|---|---|
| Library animation | **motion.dev v11.11.17** (ex-Framer Motion) | 64KB, API déclarative, pas besoin de React, maintenue activement |
| Hébergement | **Self-hosted** (`frontend/js/vendor/motion.min.js`) | Indispensable pour le PWA offline (le service worker ne peut pas mettre en cache un CDN tiers) |
| Cache PWA | Bump du CACHE_VERSION `v14 → v15` + ajout des nouveaux assets à SHELL_ASSETS | Force le SW à précacher les nouveaux fichiers dès la mise à jour |
| API pattern | **Global `window.Animations`** avec 4 helpers | Simple à appeler depuis app.js (qui est un module ES6), évite de convertir le reste du code |
| Accessibilité | **`prefers-reduced-motion: reduce` respecté partout** | Obligatoire WCAG ; check via `matchMedia` en JS + `@media` en CSS |
| Granularité animation | **Ciblée sur 7 points d'impact visuel fort**, pas partout | Éviter la fatigue oculaire et l'effet "tout bouge" |

## Architecture

### Fichiers créés

- `frontend/js/vendor/motion.min.js` — motion.dev v11.11.17 UMD bundle (64KB)
- `frontend/js/animations.js` — wrapper minimal IIFE qui expose `window.Animations`

### Fichiers modifiés

- `frontend/index.html` — inclusion des 2 scripts (ordre important : motion avant animations), ajout du markup `#setups-skeleton`
- `frontend/js/app.js` — intégrations dans `_renderFilteredSetups()`, `renderMacroBanner()`, et updates de KPIs
- `frontend/css/style.css` — styles skeleton, micro-interactions (127 lignes)
- `frontend/sw.js` — bump v14→v15, ajout des nouveaux assets au cache

### API du module `window.Animations`

```javascript
window.Animations = {
  // Fade + slide-in avec stagger (cartes qui apparaissent)
  staggerIn(elements, { duration, delayStep, yOffset }),

  // Fade-out (cartes qui disparaissent)
  fadeOut(elements, { duration }),

  // Pulse bref (changement de valeur/direction)
  pulse(el, { duration, scale }),

  // Animation d'un nombre vers une cible (ease-out cubique)
  animateNumber(el, endValue, { duration, startValue, formatter })
}
```

Toutes les fonctions :
- No-op si `window.Motion` n'est pas chargé (fallback silencieux)
- Pas de check `prefers-reduced-motion` interne — c'est l'appelant qui décide (permet d'animer certaines choses même en reduced-motion si pertinent)

## Les 5 tâches et ce qu'elles livrent

### Tâche 1 — Setup motion.dev + module helpers

- Download motion.min.js depuis jsDelivr (v11.11.17)
- Création de `animations.js` avec 4 helpers
- Include dans index.html
- Bump SW cache

### Tâche 2 — Stagger cartes + skeletons

- `_renderFilteredSetups()` hide le skeleton et appelle `staggerIn()` sur les `.trade-setup` à chaque render
- Skeleton = 3 cartes grises avec shimmer animation 1.6s
- Sélecteur : `container.querySelectorAll(':scope > .trade-setup')`
- Comportement : toutes les cartes animées à chaque cycle (3min20) — acceptable, pas de flicker

### Tâche 3 — Macro banner entrance + arrow pulse

- `renderMacroBanner()` capture `wasHidden` AVANT de retirer la classe
- Variable module `_previousMacro` pour comparer snapshot N-1 vs N
- Si `wasHidden` → `staggerIn(cells)` (premier reveal)
- Sinon → pour chaque indicateur dont la direction change → `pulse(arrowEl, { scale: 1.4 })`
- Si `risk_regime` change → `pulse(regimeBadgeEl, { scale: 1.15 })`

### Tâche 4 — Number transitions + confidence ring fill

- 6 KPIs animés : PnL $, PnL delta %, nb trades, winrate %, risk %, risk delta $ + nb positions
- Chaque mise à jour remplace `el.textContent = value` par `animateNumber(el, value, { duration: 600, formatter })`
- Confidence ring : après innerHTML, itère les `.conf-ring-fill` et tween `stroke-dashoffset` de circumference → target via `Motion.animate()` 0.8s cubic-bezier
- Choix : le texte numérique du score dans le ring reste statique (trop invasif de l'animer via template string) — le ring lui-même suffit visuellement

### Tâche 5 — Micro-interactions CSS

- `.trade-setup:hover` → translateY(-3px) + shadow layered
- `button:hover` → brightness(1.08), `:active` → scale(0.97)
- `*:focus-visible` → outline bleu 2px (a11y clavier), `:focus:not(:focus-visible)` → pas d'outline (souris)
- Transitions couleur sur tabs/nav/badges
- `.data-badge.macro:hover`, `.macro-prim:hover`, `.macro-cell:hover` → brightness + translateY léger
- Global `@media (prefers-reduced-motion: reduce)` qui désactive tout

## Accessibilité

Tous les éléments animés respectent **deux** checks :

1. **JS** : `window.matchMedia('(prefers-reduced-motion: reduce)').matches` avant chaque appel `Animations.*`
2. **CSS** : `@media (prefers-reduced-motion: reduce) { transition: none !important; transform: none !important; }` au bas de style.css

Focus keyboard : outline visible sur tous les éléments interactifs (bouton, input, select, link). Outline masqué pour la souris via `:focus:not(:focus-visible)`.

## Tests

- 49 tests backend continuent de passer (aucune modification backend — les animations sont pure front)
- Pas de test frontend auto (pas de framework de test JS en place, scope Phase 1)
- Validation manuelle : ouvrir le dashboard dans Chrome/Firefox/Safari et vérifier chaque animation

## Observabilité / rollback

- Aucune configuration runtime — ces animations tournent dès que le code est déployé
- Kill-switch effectif : l'utilisateur peut activer `prefers-reduced-motion` dans ses préférences OS → tout s'éteint
- Pour désactiver totalement en urgence : retirer les 2 `<script>` tags dans `index.html` — l'app continue de tourner normalement (tous les appels `window.Animations.*` sont no-op si `window.Motion` est absent)

## Ce qui n'est pas inclus

- **Pas de loading spinner global** (les skeletons suffisent)
- **Pas de transitions de page** (site SPA-only, pas de navigation à animer)
- **Pas de parallax** (pas adapté à un dashboard)
- **Pas d'animations sur le login / PWA install popup** (zones stables, pas d'intérêt)
- **Pas de tests JS** (reporté, scope Phase 2 s'il y en a un)

## Références implémentation

Commits (dans l'ordre) :
- `a660c7d feat(ui): self-host motion.dev + animations helpers module`
- `c7b0f97 feat(ui): stagger-in animation + skeleton loaders for setup cards`
- `8b16b3c feat(ui): macro banner stagger reveal + arrow pulse on direction change`
- `a97a0f4 feat(ui): animated number transitions + confidence ring fill`
- `42ae960 feat(ui): micro-interactions hover/focus/transitions`

Fichiers clés :
- `frontend/js/vendor/motion.min.js` (64KB, immutable, pas touché après T1)
- `frontend/js/animations.js` (2.6KB, stable, API figée)
- `frontend/js/app.js` (+~80 lignes pour l'intégration, points d'injection : `renderMacroBanner`, `_renderFilteredSetups`, les 6 updates KPI)
- `frontend/css/style.css` (+~220 lignes : skeleton, micro-interactions)
- `frontend/sw.js` (cache v15)

## Phase 2 (à faire en session dédiée)

Migration React du dashboard principal (cartes setups + bandeau macro uniquement, pas login/PWA/auth). Spec séparée à écrire quand on y viendra. Utilisera les 21st-magic MCP tools pour générer les composants avec design moderne et motion déjà intégré.
