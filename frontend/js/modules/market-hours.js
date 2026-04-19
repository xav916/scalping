/**
 * Market Hours — mémo des horaires d'ouverture/fermeture des marchés.
 *
 * Horaires stockés en UTC fixe (même convention que _activeSessions dans
 * app.js et _active_sessions_utc dans backend/services/coaching.py).
 * Conversion en heure Paris à l'affichage via Intl.DateTimeFormat — DST
 * géré automatiquement.
 *
 * Structure scindée en :
 *   - Helpers purs (testables en Node) : MARKETS, isForexWeekendClosed,
 *     computeMarketStatus, formatCountdown, toParisHHMM.
 *   - Fonctions DOM (non testées en Node) : renderMarketHours,
 *     toggleMarketHoursPanel.
 */

export const MARKETS = [
    { id: 'sydney',  label: 'Sydney',    flag: '🇦🇺', kind: 'forex',         openUTC: 22,   closeUTC: 7  },
    { id: 'tokyo',   label: 'Tokyo',     flag: '🇯🇵', kind: 'forex',         openUTC: 0,    closeUTC: 9  },
    { id: 'london',  label: 'London',    flag: '🇬🇧', kind: 'forex',         openUTC: 8,    closeUTC: 17 },
    { id: 'newyork', label: 'New York',  flag: '🇺🇸', kind: 'forex',         openUTC: 13,   closeUTC: 22 },
    { id: 'crypto',  label: 'BTC / ETH', flag: '⚡', kind: 'always' },
    { id: 'equity',  label: 'SPX / NDX', flag: '🇺🇸', kind: 'equity',        openUTC: 13.5, closeUTC: 20 },
    { id: 'metals',  label: 'XAU / XAG', flag: '🥇', kind: 'forex_follow' },
    { id: 'oil',     label: 'WTI',       flag: '🛢️', kind: 'commodity',     openUTC: 22,   closeUTC: 21 },
];

// ─── Helpers purs ────────────────────────────────────────────────────

export function isForexWeekendClosed(now) {
    const wd = now.getUTCDay();
    const h = now.getUTCHours();
    if (wd === 6) return true;
    if (wd === 0 && h < 22) return true;
    if (wd === 5 && h >= 22) return true;
    return false;
}

function hourInRange(hUTC, openUTC, closeUTC) {
    if (openUTC < closeUTC) return hUTC >= openUTC && hUTC < closeUTC;
    return hUTC >= openUTC || hUTC < closeUTC;
}

function anyForexOpen(now) {
    if (isForexWeekendClosed(now)) return false;
    const h = now.getUTCHours() + now.getUTCMinutes() / 60;
    return MARKETS.filter(m => m.kind === 'forex')
        .some(m => hourInRange(h, m.openUTC, m.closeUTC));
}

function isLondonNYOverlap(now) {
    if (isForexWeekendClosed(now)) return false;
    const h = now.getUTCHours() + now.getUTCMinutes() / 60;
    const london = MARKETS.find(m => m.id === 'london');
    const ny = MARKETS.find(m => m.id === 'newyork');
    return hourInRange(h, london.openUTC, london.closeUTC) &&
           hourInRange(h, ny.openUTC, ny.closeUTC);
}

function makeUTCAtHour(base, hourUTC) {
    return new Date(Date.UTC(
        base.getUTCFullYear(),
        base.getUTCMonth(),
        base.getUTCDate(),
        Math.floor(hourUTC),
        Math.round((hourUTC % 1) * 60),
        0,
    ));
}

function nextOpenDate(market, now) {
    if (market.kind === 'always' || market.kind === 'forex_follow') return null;
    if (market.openUTC === undefined) return null;

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

        const wd = candidate.getUTCDay();
        if (market.kind === 'forex') {
            if (market.id === 'sydney') {
                if (wd === 6) continue;
            } else {
                if (wd === 0 || wd === 6) continue;
            }
        } else if (market.kind === 'equity') {
            if (wd === 0 || wd === 6) continue;
        } else if (market.kind === 'commodity') {
            // WTI : fermé samedi toute la journée
            if (wd === 6) continue;
        }

        return candidate;
    }
    return null;
}

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
        const next = nextOpenDate(market, now);
        if (next) {
            statusLabel = `ouvre dans ${formatCountdown(next - now)}`;
        } else {
            statusLabel = 'fermé';
        }
    }

    return { isOpen, isOverlap, statusLabel, opensAtLabel, closesAtLabel };
}

export function toParisHHMM(date) {
    return new Intl.DateTimeFormat('fr-FR', {
        timeZone: 'Europe/Paris',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(date);
}

export function formatCountdown(ms) {
    const totalMin = Math.max(0, Math.round(ms / 60000));
    if (totalMin < 60) return `${totalMin} min`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}h${String(m).padStart(2, '0')}`;
}

// ─── Fonctions DOM (non testées en Node) ─────────────────────────────

function escapeText(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

export function renderMarketHours() {
    const tbody = document.getElementById('mh-tbody');
    if (!tbody) return;
    const now = new Date();
    const rows = MARKETS.map(m => {
        const s = computeMarketStatus(m, now);
        const statusClass = s.isOverlap
            ? 'mh-status--overlap'
            : s.isOpen ? 'mh-status--open' : 'mh-status--closed';

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

export function toggleMarketHoursPanel() {
    const panel = document.getElementById('market-hours-panel');
    const btn = document.getElementById('market-hours-toggle');
    if (!panel || !btn) return false;
    const willOpen = panel.hasAttribute('hidden');
    if (willOpen) {
        panel.removeAttribute('hidden');
        btn.setAttribute('aria-expanded', 'true');
        renderMarketHours();
    } else {
        panel.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', 'false');
    }
    return willOpen;
}
