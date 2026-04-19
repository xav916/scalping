# Market Hours Memo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un panneau dépliable "Horaires des marchés" dans le dashboard Scalping Radar, avec un tableau live de 8 marchés (4 sessions forex + BTC/ETH + SPX/NDX + XAU/XAG + WTI) en heure Paris, refresh 30s, overlap London/NY mis en évidence.

**Architecture:** Nouveau module ES6 `frontend/js/modules/market-hours.js` avec helpers purs (testés en Node standalone) + fonctions DOM. Intégration dans le header existant via bouton toggle. Même pattern que le glossaire (`toggle-glossary`). Refresh via `setInterval(30s)`. SW auto-bump déjà en place (commit `49173a7`).

**Tech Stack:** Vanilla JS ES6 modules, HTML5, CSS3 custom properties, `Intl.DateTimeFormat('fr-FR')` pour DST, Node `node:assert` pour tests unitaires des helpers purs, motion.dev (optionnel pour animation d'ouverture).

**Spec de référence :** `docs/superpowers/specs/2026-04-19-market-hours-memo-design.md`

---

## File Structure

**Créés :**
- `frontend/js/modules/market-hours.js` — module principal (data model + helpers purs + render DOM + toggle)
- `tests/frontend/market-hours.test.mjs` — tests Node standalone pour les helpers purs

**Modifiés :**
- `frontend/index.html` — ajout du bouton trigger dans `.header-status` et de la section panneau après `<header>`
- `frontend/js/app.js` — import du module, wiring du handler `toggle-market-hours`, premier render + setInterval
- `frontend/css/style.css` — styles `.market-hours-panel`, `.mh-table`, badges statut
- `frontend/sw.js` — ajout de `/js/modules/market-hours.js` à `SHELL_ASSETS`
- `frontend/js/MODULES.md` — documentation du nouveau module

**Non modifiés (volontairement) :** `frontend/mobile.html`, `backend/services/coaching.py` — hors scope.

---

## Task 1: Data model + helpers purs + tests Node

**Objectif :** créer le module `market-hours.js` avec les fonctions pures (pas de DOM) et valider leur comportement via des tests Node standalone.

**Files:**
- Create: `frontend/js/modules/market-hours.js`
- Create: `tests/frontend/market-hours.test.mjs`

- [ ] **Step 1: Créer le fichier de test Node (failing)**

Créer `tests/frontend/market-hours.test.mjs` avec les assertions de base. Le test importe un module qui n'existe pas encore → va échouer.

```js
// tests/frontend/market-hours.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    MARKETS,
    isForexWeekendClosed,
    computeMarketStatus,
    formatCountdown,
    toParisHHMM,
} from '../../frontend/js/modules/market-hours.js';

// Helper : construit un Date UTC à partir d'une chaîne "YYYY-MM-DD HH:MM"
const atUTC = (s) => new Date(`${s.replace(' ', 'T')}:00Z`);

test('MARKETS contient les 8 marchés attendus', () => {
    assert.equal(MARKETS.length, 8);
    const ids = MARKETS.map(m => m.id);
    assert.deepEqual(ids, ['sydney','tokyo','london','newyork','crypto','equity','metals','oil']);
});

test('isForexWeekendClosed : samedi fermé toute la journée', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-18 12:00')), true);   // sam
});

test('isForexWeekendClosed : dimanche avant 22h UTC fermé', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-19 19:00')), true);   // dim 19h
    assert.equal(isForexWeekendClosed(atUTC('2026-04-19 22:00')), false);  // dim 22h (ouvre)
});

test('isForexWeekendClosed : vendredi après 22h UTC fermé', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-17 22:30')), true);   // ven 22:30
    assert.equal(isForexWeekendClosed(atUTC('2026-04-17 21:00')), false);  // ven 21h
});

test('computeMarketStatus forex : London ouvert à 10h UTC lundi', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-20 10:00'));
    assert.equal(s.isOpen, true);
});

test('computeMarketStatus forex : London fermé dimanche 19h UTC', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-19 19:00'));
    assert.equal(s.isOpen, false);
});

test('computeMarketStatus crypto : toujours ouvert', () => {
    const crypto = MARKETS.find(m => m.id === 'crypto');
    assert.equal(computeMarketStatus(crypto, atUTC('2026-04-19 19:00')).isOpen, true);
    assert.equal(computeMarketStatus(crypto, atUTC('2026-04-18 03:00')).isOpen, true);
});

test('computeMarketStatus equity (SPX) : ouvert lundi 14h UTC, fermé samedi', () => {
    const eq = MARKETS.find(m => m.id === 'equity');
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-20 14:00')).isOpen, true);
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-20 13:00')).isOpen, false); // avant 13:30
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-18 14:00')).isOpen, false); // samedi
});

test('computeMarketStatus forex_follow (metals) : ouvert si au moins une session forex', () => {
    const metals = MARKETS.find(m => m.id === 'metals');
    assert.equal(computeMarketStatus(metals, atUTC('2026-04-20 10:00')).isOpen, true);  // London ouvert
    assert.equal(computeMarketStatus(metals, atUTC('2026-04-19 19:00')).isOpen, false); // dim pas encore ouvert
});

test('computeMarketStatus overlap London/NY : isOverlap à 15h UTC', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-20 15:00'));
    assert.equal(s.isOverlap, true);
});

test('toParisHHMM : 13:00 UTC → 15:00 Paris en avril (CEST)', () => {
    assert.equal(toParisHHMM(atUTC('2026-04-20 13:00')), '15:00');
});

test('toParisHHMM : 13:00 UTC → 14:00 Paris en janvier (CET)', () => {
    assert.equal(toParisHHMM(atUTC('2026-01-15 13:00')), '14:00');
});

test('formatCountdown : arrondit correctement', () => {
    assert.equal(formatCountdown(0), '0 min');
    assert.equal(formatCountdown(45 * 60 * 1000), '45 min');
    assert.equal(formatCountdown(90 * 60 * 1000), '1h30');
    assert.equal(formatCountdown(2 * 60 * 60 * 1000 + 5 * 60 * 1000), '2h05');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/frontend/market-hours.test.mjs`
Expected: FAIL avec `Cannot find module '...market-hours.js'`

- [ ] **Step 3: Écrire l'implémentation minimale du module**

Créer `frontend/js/modules/market-hours.js` :

```js
/**
 * Market Hours — mémo des horaires d'ouverture/fermeture des marchés.
 *
 * Horaires stockés en UTC fixe (même convention que _activeSessions dans app.js
 * et _active_sessions_utc dans backend/services/coaching.py). Conversion en
 * heure Paris à l'affichage via Intl.DateTimeFormat — DST géré automatiquement.
 *
 * Structure volontairement scindée en :
 *   - Helpers purs (testables en Node) : MARKETS, isForexWeekendClosed,
 *     computeMarketStatus, formatCountdown, toParisHHMM.
 *   - Fonctions DOM (non testées en Node) : renderMarketHours,
 *     toggleMarketHoursPanel.
 */

// ─── Data model ──────────────────────────────────────────────────────
// openUTC / closeUTC : heures UTC (0-23.99). Utiliser des décimales pour les
// demi-heures (SPX à 13:30 → 13.5). Quand close < open, la session traverse
// minuit UTC (ex. Sydney 22 → 7 = de 22h UTC à 7h UTC le lendemain).
export const MARKETS = [
    { id: 'sydney',  label: 'Sydney',    flag: '🇦🇺', kind: 'forex',         openUTC: 22,  closeUTC: 7  },
    { id: 'tokyo',   label: 'Tokyo',     flag: '🇯🇵', kind: 'forex',         openUTC: 0,   closeUTC: 9  },
    { id: 'london',  label: 'London',    flag: '🇬🇧', kind: 'forex',         openUTC: 8,   closeUTC: 17 },
    { id: 'newyork', label: 'New York',  flag: '🇺🇸', kind: 'forex',         openUTC: 13,  closeUTC: 22 },
    { id: 'crypto',  label: 'BTC / ETH', flag: '⚡', kind: 'always' },
    { id: 'equity',  label: 'SPX / NDX', flag: '🇺🇸', kind: 'equity',        openUTC: 13.5, closeUTC: 20 },
    { id: 'metals',  label: 'XAU / XAG', flag: '🥇', kind: 'forex_follow' },
    { id: 'oil',     label: 'WTI',       flag: '🛢️', kind: 'commodity',     openUTC: 22,  closeUTC: 21 },
];

// ─── Helpers purs ────────────────────────────────────────────────────

/**
 * Retourne true si le marché forex est fermé à l'instant `now` (UTC) à cause
 * du weekend. Règle : samedi fermé, dimanche avant 22h UTC fermé, vendredi
 * après 22h UTC fermé.
 */
export function isForexWeekendClosed(now) {
    const wd = now.getUTCDay();   // 0=dim, 6=sam
    const h = now.getUTCHours();
    if (wd === 6) return true;
    if (wd === 0 && h < 22) return true;
    if (wd === 5 && h >= 22) return true;
    return false;
}

/**
 * Vrai si [h] ∈ [openUTC, closeUTC), en gérant le cas où la session traverse
 * minuit (closeUTC < openUTC).
 */
function hourInRange(hUTC, openUTC, closeUTC) {
    if (openUTC < closeUTC) return hUTC >= openUTC && hUTC < closeUTC;
    return hUTC >= openUTC || hUTC < closeUTC;
}

/**
 * Vrai si au moins une session forex (hors weekend) est ouverte à l'instant
 * `now`. Utilisé pour les marchés kind=forex_follow (métaux) et pour détecter
 * l'overlap London/NY.
 */
function anyForexOpen(now) {
    if (isForexWeekendClosed(now)) return false;
    const h = now.getUTCHours() + now.getUTCMinutes() / 60;
    return MARKETS.filter(m => m.kind === 'forex')
        .some(m => hourInRange(h, m.openUTC, m.closeUTC));
}

/**
 * Détecte l'overlap London/NY : les deux sessions forex sont ouvertes
 * simultanément (13:00-17:00 UTC hors weekend).
 */
function isLondonNYOverlap(now) {
    if (isForexWeekendClosed(now)) return false;
    const h = now.getUTCHours() + now.getUTCMinutes() / 60;
    const london = MARKETS.find(m => m.id === 'london');
    const ny = MARKETS.find(m => m.id === 'newyork');
    return hourInRange(h, london.openUTC, london.closeUTC) &&
           hourInRange(h, ny.openUTC, ny.closeUTC);
}

/**
 * Calcule le statut d'un marché à l'instant `now` (Date UTC).
 * Retourne { isOpen, isOverlap, statusLabel, opensAtLabel, closesAtLabel }.
 * statusLabel est prêt à afficher. opensAtLabel/closesAtLabel : heures en
 * format "HH:MM" Paris, ou "24/7"/"suit forex" pour les cas spéciaux.
 */
export function computeMarketStatus(market, now) {
    const hFrac = now.getUTCHours() + now.getUTCMinutes() / 60;
    let isOpen = false;
    let opensAtLabel = '';
    let closesAtLabel = '';

    if (market.kind === 'always') {
        isOpen = true;
        opensAtLabel = '24/7';
        closesAtLabel = '';
    } else if (market.kind === 'forex') {
        isOpen = !isForexWeekendClosed(now) && hourInRange(hFrac, market.openUTC, market.closeUTC);
        opensAtLabel = toParisHHMM(makeUTCAtHour(now, market.openUTC));
        closesAtLabel = toParisHHMM(makeUTCAtHour(now, market.closeUTC));
    } else if (market.kind === 'forex_follow') {
        isOpen = anyForexOpen(now);
        opensAtLabel = 'suit forex';
        closesAtLabel = '';
    } else if (market.kind === 'equity') {
        const wd = now.getUTCDay();
        const isWeekday = wd >= 1 && wd <= 5;
        isOpen = isWeekday && hourInRange(hFrac, market.openUTC, market.closeUTC);
        opensAtLabel = toParisHHMM(makeUTCAtHour(now, market.openUTC));
        closesAtLabel = toParisHHMM(makeUTCAtHour(now, market.closeUTC));
    } else if (market.kind === 'commodity') {
        // WTI : ouvert sauf 21:00-22:00 UTC chaque jour + weekend (sam + dim<22h + ven>=21h)
        const wd = now.getUTCDay();
        const hourClosed = hFrac >= 21 && hFrac < 22;
        const weekendClosed = wd === 6 || (wd === 0 && hFrac < 22) || (wd === 5 && hFrac >= 21);
        isOpen = !weekendClosed && !hourClosed;
        opensAtLabel = toParisHHMM(makeUTCAtHour(now, market.openUTC));
        closesAtLabel = toParisHHMM(makeUTCAtHour(now, market.closeUTC));
    }

    const isOverlap = market.kind === 'forex' && isOpen && isLondonNYOverlap(now);

    let statusLabel;
    if (isOverlap && (market.id === 'london' || market.id === 'newyork')) {
        statusLabel = '⚡ overlap';
    } else if (isOpen) {
        statusLabel = '● ouvert';
    } else {
        // Countdown sur prochain ouverture si applicable
        const next = nextOpenDate(market, now);
        if (next) {
            const diff = next - now;
            statusLabel = `ouvre dans ${formatCountdown(diff)}`;
        } else {
            statusLabel = 'fermé';
        }
    }

    return { isOpen, isOverlap, statusLabel, opensAtLabel, closesAtLabel };
}

/**
 * Construit un Date UTC qui a la même date que `base` mais avec l'heure
 * décimale `hourUTC` (ex. 13.5 → 13:30 UTC).
 */
function makeUTCAtHour(base, hourUTC) {
    const d = new Date(Date.UTC(
        base.getUTCFullYear(),
        base.getUTCMonth(),
        base.getUTCDate(),
        Math.floor(hourUTC),
        Math.round((hourUTC % 1) * 60),
        0,
    ));
    return d;
}

/**
 * Retourne la prochaine Date UTC où le marché ouvrira. Utilisé pour le
 * countdown. Retourne null pour les marchés always-on ou sans horaire fixe.
 */
function nextOpenDate(market, now) {
    if (market.kind === 'always' || market.kind === 'forex_follow') return null;
    if (market.openUTC === undefined) return null;

    // Essai : aujourd'hui à openUTC. Si déjà passé ou weekend, on itère sur
    // les 8 prochains jours jusqu'à trouver un jour d'ouverture valide.
    for (let offset = 0; offset < 8; offset++) {
        const candidate = new Date(Date.UTC(
            now.getUTCFullYear(),
            now.getUTCMonth(),
            now.getUTCDate() + offset,
            Math.floor(market.openUTC),
            Math.round((market.openUTC % 1) * 60),
            0,
        ));
        if (candidate <= now) continue;

        // Vérif weekend selon le kind
        const wd = candidate.getUTCDay();
        if (market.kind === 'forex') {
            // Sydney est le seul à ouvrir dim 22h, les autres uniquement lun-ven
            if (market.id === 'sydney') {
                if (wd === 6) continue;  // sam fermé
                // dim 22h : ok, lun-ven : ok
            } else {
                if (wd === 0 || wd === 6) continue;
            }
        } else if (market.kind === 'equity') {
            if (wd === 0 || wd === 6) continue;
        }

        return candidate;
    }
    return null;
}

/**
 * Convertit un Date UTC en chaîne "HH:MM" heure Paris. Gère DST automatiquement.
 */
export function toParisHHMM(date) {
    return new Intl.DateTimeFormat('fr-FR', {
        timeZone: 'Europe/Paris',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(date);
}

/**
 * Formate un intervalle en ms sous forme compacte : "45 min", "1h30", "12h05".
 * Arrondit à la minute.
 */
export function formatCountdown(ms) {
    const totalMin = Math.max(0, Math.round(ms / 60000));
    if (totalMin < 60) return `${totalMin} min`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}h${String(m).padStart(2, '0')}`;
}
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `node --test tests/frontend/market-hours.test.mjs`
Expected: tous les tests PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/js/modules/market-hours.js tests/frontend/market-hours.test.mjs
git commit -m "feat(market-hours): module + helpers purs testés en Node

Data model des 8 marchés (forex/crypto/equity/metals/commodity),
computeMarketStatus, toParisHHMM (DST auto), formatCountdown.
13 tests Node standalone, aucune dépendance externe."
```

---

## Task 2: Intégration HTML (bouton + section)

**Objectif :** ajouter le bouton trigger dans le header et la section panneau (vide) dans l'index.

**Files:**
- Modify: `frontend/index.html:30-42` (ajout bouton dans `.header-status`)
- Modify: `frontend/index.html` (ajout section après `</header>`)

- [ ] **Step 1: Ajouter le bouton dans `.header-status`**

Dans `frontend/index.html`, localiser le bloc `<div class="header-status">` et insérer le bouton entre `#session-markers` (ligne 33) et `#trend-info` (ligne 34) :

```html
<span id="session-markers" class="session-markers"></span>
<button
    id="market-hours-toggle"
    class="btn btn-sm"
    type="button"
    data-action="toggle-market-hours"
    aria-expanded="false"
    aria-controls="market-hours-panel"
    title="Afficher / masquer les horaires des marchés">▾ Horaires</button>
<span id="trend-info" class="trend-info"></span>
```

- [ ] **Step 2: Ajouter la section panneau après `</header>`**

Toujours dans `frontend/index.html`, localiser la balise `</header>` (autour de la ligne 43) et insérer juste après :

```html
</header>

<!-- Mémo horaires des marchés — replié par défaut, affiche un tableau live
     des sessions forex + crypto + SPX/NDX + XAU/XAG + WTI en heure Paris. -->
<section id="market-hours-panel" class="market-hours-panel" hidden aria-labelledby="mh-title">
    <h2 id="mh-title" class="mh-title">Horaires des marchés</h2>
    <table class="mh-table">
        <thead>
            <tr>
                <th scope="col">Marché</th>
                <th scope="col">Ouvre</th>
                <th scope="col">Ferme</th>
                <th scope="col">Statut</th>
            </tr>
        </thead>
        <tbody id="mh-tbody"><!-- rempli par market-hours.js --></tbody>
    </table>
    <p class="mh-footnote">Heures en Paris (Europe/Paris). Mise à jour toutes les 30 s.</p>
</section>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): bouton + section vide pour le panneau horaires"
```

---

## Task 3: Rendering DOM + fonction toggle

**Objectif :** ajouter `renderMarketHours()` et `toggleMarketHoursPanel()` au module, qui lisent le DOM créé à la Task 2.

**Files:**
- Modify: `frontend/js/modules/market-hours.js` (ajout fonctions DOM à la fin)

- [ ] **Step 1: Ajouter les fonctions DOM au module**

Append à la fin de `frontend/js/modules/market-hours.js` :

```js
// ─── Fonctions DOM (non testées en Node) ─────────────────────────────

/**
 * Escape HTML pour éviter les injections via les labels. Copié de utils.js
 * pour éviter une dépendance circulaire au boot.
 */
function escapeText(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

/**
 * Rend le <tbody> du panneau. Appelé au boot puis toutes les 30s.
 * No-op silencieux si le panneau n'existe pas (ex. login.html, mobile.html).
 */
export function renderMarketHours() {
    const tbody = document.getElementById('mh-tbody');
    if (!tbody) return;
    const now = new Date();
    const rows = MARKETS.map(m => {
        const s = computeMarketStatus(m, now);
        const statusClass = s.isOverlap
            ? 'mh-status--overlap'
            : s.isOpen ? 'mh-status--open' : 'mh-status--closed';

        // Colonnes "Ouvre"/"Ferme" fusionnées pour les cas spéciaux
        const opensCell = s.closesAtLabel
            ? `<td>${escapeText(s.opensAtLabel)}</td><td>${escapeText(s.closesAtLabel)}</td>`
            : `<td colspan="2" class="mh-spanned">${escapeText(s.opensAtLabel)}</td>`;

        return `
            <tr data-market="${m.id}">
                <td><span class="mh-flag">${m.flag}</span> ${escapeText(m.label)}</td>
                ${opensCell}
                <td><span class="mh-status ${statusClass}">${escapeText(s.statusLabel)}</span></td>
            </tr>`;
    }).join('');
    tbody.innerHTML = rows;
}

/**
 * Toggle l'état ouvert/fermé du panneau. Synchronise aria-expanded et
 * l'attribut hidden. Retourne l'état ouvert (true) ou fermé (false).
 */
export function toggleMarketHoursPanel() {
    const panel = document.getElementById('market-hours-panel');
    const btn = document.getElementById('market-hours-toggle');
    if (!panel || !btn) return false;
    const willOpen = panel.hasAttribute('hidden');
    if (willOpen) {
        panel.removeAttribute('hidden');
        btn.setAttribute('aria-expanded', 'true');
        btn.textContent = '▴ Horaires';
        renderMarketHours();   // refresh immédiat à l'ouverture
    } else {
        panel.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', 'false');
        btn.textContent = '▾ Horaires';
    }
    return willOpen;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/js/modules/market-hours.js
git commit -m "feat(market-hours): renderMarketHours + toggleMarketHoursPanel"
```

---

## Task 4: Wiring dans app.js

**Objectif :** importer le module, enregistrer le handler du bouton dans le delegated click, faire un premier render + setInterval 30s.

**Files:**
- Modify: `frontend/js/app.js:12-20` (ajout import)
- Modify: `frontend/js/app.js:~1955` (ajout case dans `_handleDelegatedClick`)
- Modify: `frontend/js/app.js:~1987` (ajout premier render)
- Modify: `frontend/js/app.js:~2010` (ajout setInterval 30s)

- [ ] **Step 1: Ajouter l'import en tête de fichier**

Dans `frontend/js/app.js`, modifier le bloc d'imports (lignes 12-20) pour ajouter le nouveau module :

```js
import {
    escapeHtml,
    strengthLabel as _strengthLabel,
    patternLabel as _patternLabel,
    markdownToHtml as _markdownToHtml,
    isExpired as _isExpired,
    countdown as _countdown,
    relativeTime as _relativeTime,
} from './modules/utils.js';
import {
    renderMarketHours,
    toggleMarketHoursPanel,
} from './modules/market-hours.js';
```

- [ ] **Step 2: Enregistrer le handler `toggle-market-hours` dans `_handleDelegatedClick`**

Localiser le switch `data-action` dans `_handleDelegatedClick` (~ligne 1904+). Après le case `toggle-glossary` (ligne 1929-1937), ajouter :

```js
case 'toggle-market-hours': {
    toggleMarketHoursPanel();
    break;
}
```

- [ ] **Step 3: Appeler `renderMarketHours()` au DOMContentLoaded**

Dans le handler DOMContentLoaded (~ligne 1980), après `_renderSessionMarkers();`, ajouter :

```js
_renderSessionMarkers();
renderMarketHours();       // premier render (le panneau est hidden mais le tbody est pré-rempli)
_updateSoundBtn();
```

- [ ] **Step 4: Ajouter le setInterval 30s**

Après le `setInterval(_renderSessionMarkers, 60000);` (~ligne 2010), ajouter :

```js
setInterval(_renderSessionMarkers, 60000);

// Market hours panel : refresh toutes les 30s (plus réactif que sessions
// à cause du countdown "ouvre dans Xh Ym")
setInterval(renderMarketHours, 30000);
```

- [ ] **Step 5: Commit**

```bash
git add frontend/js/app.js
git commit -m "feat(ui): wire market hours panel (toggle + refresh 30s)"
```

---

## Task 5: Styles CSS

**Objectif :** styler le panneau, le tableau et les badges de statut pour rester cohérent avec le thème existant.

**Files:**
- Modify: `frontend/css/style.css` (ajout à la fin)

- [ ] **Step 1: Ajouter le bloc CSS**

Append à la fin de `frontend/css/style.css` :

```css
/* ─── Market hours panel ─────────────────────────────────────────── */

.market-hours-panel {
    background: var(--surface, #161b22);
    border: 1px solid var(--border, #30363d);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 0 16px 12px;
    color: var(--text, #c9d1d9);
    font-size: 0.85rem;
}

.market-hours-panel[hidden] {
    display: none;
}

.mh-title {
    font-size: 0.9rem;
    font-weight: 600;
    margin: 0 0 8px 0;
    color: var(--text-muted, #8b949e);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.mh-table {
    width: 100%;
    border-collapse: collapse;
}

.mh-table th {
    text-align: left;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted, #6e7681);
    padding: 4px 8px 6px 0;
    border-bottom: 1px solid var(--border, #21262d);
}

.mh-table td {
    padding: 6px 8px 6px 0;
    border-bottom: 1px solid var(--border-subtle, #1f2937);
}

.mh-table tr:last-child td {
    border-bottom: none;
}

.mh-flag {
    display: inline-block;
    width: 1.4em;
    text-align: center;
    margin-right: 2px;
}

.mh-spanned {
    color: var(--text-muted, #8b949e);
    font-style: italic;
}

.mh-status {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
}

.mh-status--open {
    color: var(--success, #27ae60);
    background: rgba(39, 174, 96, 0.1);
}

.mh-status--closed {
    color: var(--text-muted, #8b949e);
}

.mh-status--overlap {
    color: var(--warning, #d29922);
    background: rgba(210, 153, 34, 0.15);
    font-weight: 600;
}

.mh-footnote {
    font-size: 0.7rem;
    color: var(--text-muted, #6e7681);
    margin: 8px 0 0 0;
    font-style: italic;
}

/* Bouton toggle dans le header — hérite de .btn.btn-sm, juste un peu plus
   compact et sans padding latéral excessif */
#market-hours-toggle {
    font-size: 0.75rem;
    padding: 3px 8px;
    min-width: 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/css/style.css
git commit -m "style(market-hours): thème du panneau + badges statut"
```

---

## Task 6: Service worker + documentation

**Objectif :** enregistrer le nouveau module dans le SW pour qu'il soit cacheable offline, et documenter dans MODULES.md.

**Files:**
- Modify: `frontend/sw.js:8-21` (ajout à `SHELL_ASSETS`)
- Modify: `frontend/js/MODULES.md`

- [ ] **Step 1: Ajouter le module à `SHELL_ASSETS` dans `sw.js`**

Dans `frontend/sw.js`, localiser `SHELL_ASSETS` (ligne 8) et ajouter `/js/modules/market-hours.js` juste après `/js/modules/utils.js` :

```js
const SHELL_ASSETS = [
    '/',
    '/css/tailwind.css',
    '/css/style.css',
    '/js/app.js',
    '/js/login.js',
    '/js/animations.js',
    '/js/modules/utils.js',
    '/js/modules/market-hours.js',
    '/js/vendor/lightweight-charts.standalone.production.js',
    '/js/vendor/motion.min.js',
    '/manifest.json',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
];
```

Note : pas besoin de bumper CACHE_VERSION — le Dockerfile (commit `49173a7`) le fait automatiquement à chaque `docker build`.

- [ ] **Step 2: Mettre à jour MODULES.md**

Dans `frontend/js/MODULES.md`, trouver la section "État actuel" avec le tree ASCII et ajouter `market-hours.js` :

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

Et ajouter un paragraphe sous "Ce qui a été fait" :

```
- `market-hours.js` isole le nouveau panneau "Horaires des marchés" (8
  marchés surveillés, heure Paris). Les helpers purs (computeMarketStatus,
  toParisHHMM, formatCountdown, isForexWeekendClosed) sont couverts par
  `tests/frontend/market-hours.test.mjs` (runnable via `node --test`).
  Les fonctions DOM (renderMarketHours, toggleMarketHoursPanel) sont
  appelées depuis app.js au DOMContentLoaded et toutes les 30s.
```

- [ ] **Step 3: Commit**

```bash
git add frontend/sw.js frontend/js/MODULES.md
git commit -m "chore(pwa): cache market-hours.js + update MODULES.md"
```

---

## Task 7: Tests manuels navigateur + deploy

**Objectif :** valider le comportement réel dans un navigateur et déployer.

**Files:** aucun (tests manuels)

- [ ] **Step 1: Tester en local si possible**

Si tu as un moyen de lancer le frontend localement (`docker build -t scalping-radar:local . && docker run -p 8000:8000 scalping-radar:local` ou équivalent), ouvre `http://localhost:8000/` et vérifie :

- [ ] Bouton `▾ Horaires` visible dans le header, à côté de `session-markers`
- [ ] Clic → panneau s'affiche avec 8 lignes
- [ ] Heures affichées en Paris (ex. London 10:00→19:00, NY 15:00→00:00 en avril)
- [ ] Colonnes fusionnées : BTC "24/7", XAU "suit forex", WTI sur une ligne
- [ ] Statut correct pour l'heure actuelle (ouvert vert, fermé gris, overlap orange)
- [ ] Bouton repasse à `▴ Horaires` quand ouvert
- [ ] Clic à nouveau → se ferme
- [ ] Après 30s (ou recharge), le countdown se met à jour
- [ ] Pas d'erreur console

Si pas de moyen local : skip et valider directement en prod après deploy.

- [ ] **Step 2: Push + deploy EC2**

```bash
git push origin main
```

Puis sur EC2 :

```bash
cd /home/ec2-user/scalping && git pull && sudo docker build -t scalping-radar:latest . && sudo systemctl restart scalping
```

Le Dockerfile auto-bumpe `CACHE_VERSION` du SW, donc les navigateurs vont récupérer le nouveau module au prochain chargement.

- [ ] **Step 3: Validation en prod**

Ouvrir `https://scalping-radar.duckdns.org/`, hard-refresh (Ctrl+Shift+R) la première fois pour que le SW s'active en nouvelle version. Vérifier à nouveau la checklist du Step 1.

Scenarios supplémentaires à tester en prod :
- [ ] Dimanche avant 22h : sessions forex "fermé", BTC "ouvert", equity "fermé", countdown Sydney correct
- [ ] Lundi 15h-17h Paris : London+NY affichent `⚡ overlap`
- [ ] Samedi : toutes sessions forex fermées, BTC seul ouvert

- [ ] **Step 4: Commit final s'il y a eu des fixs post-tests**

Si des corrections ont été nécessaires (ex. labels emoji, bug DST sur un marché), faire un commit dédié `fix(market-hours): ...`, push, rebuild.

---

## Notes d'exécution

- **Ordre strict** : Tasks 1→7. La Task 4 dépend de 1 et 3 (le module doit exister et exporter les fonctions). La Task 7 dépend de tout.
- **Aucun subagent ne doit unifier `_activeSessions` existant et le nouveau module** dans le cadre de ce plan — c'est hors scope (noté dans le spec, sera un chantier futur de refactor).
- **Si Task 1 tests échouent** : le plus probable est un edge case DST (ex. le test "13:00 UTC → 15:00 Paris en avril" peut tomber en faux si Node est en timezone non-UTC). Forcer le run avec `TZ=UTC node --test tests/frontend/market-hours.test.mjs` si nécessaire.
- **Frequent commits** : 7 commits minimum, un par task. Plus si un task se décompose (ex. fixes après tests manuels).
