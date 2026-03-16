/**
 * Scalping Radar - Application Frontend
 * Dashboard temps réel pour la détection de signaux de scalping
 */

const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws`;

let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;

// ─── WebSocket ───────────────────────────────────────────────────────

function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        reconnectAttempts = 0;
        setConnectionStatus(true);
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 30000);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };

    ws.onclose = () => {
        setConnectionStatus(false);
        scheduleReconnect();
    };

    ws.onerror = () => setConnectionStatus(false);
}

function scheduleReconnect() {
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
    reconnectAttempts++;
    setTimeout(connectWebSocket, delay);
}

function setConnectionStatus(connected) {
    const indicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    if (connected) {
        indicator.classList.remove('disconnected');
        statusText.textContent = 'En ligne';
    } else {
        indicator.classList.add('disconnected');
        statusText.textContent = 'Deconnecte';
    }
}

function handleWebSocketMessage(message) {
    if (message.type === 'signal') {
        addSignalToUI(message.data);
        showToast(message.data);
        requestBrowserNotification(message.data);
    } else if (message.type === 'update') {
        updateDashboard(message.data);
    }
}

// ─── API ─────────────────────────────────────────────────────────────

async function fetchOverview() {
    try {
        const res = await fetch(`${API_BASE}/api/overview`);
        if (res.status === 202) {
            setTimeout(fetchOverview, 3000);
            return;
        }
        const data = await res.json();
        renderFullDashboard(data);
    } catch (err) {
        console.error('Erreur fetch overview:', err);
    }
}

async function refreshAnalysis() {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.textContent = 'Analyse...';
    try {
        await fetch(`${API_BASE}/api/refresh`, { method: 'POST' });
        setTimeout(() => {
            fetchOverview();
            btn.disabled = false;
            btn.textContent = 'Actualiser';
        }, 2000);
    } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Actualiser';
    }
}

// ─── Rendu principal ─────────────────────────────────────────────────

function renderFullDashboard(data) {
    renderTradeSetups(data.trade_setups || []);
    renderSignals(data.signals || []);
    renderPatterns(data.patterns || []);
    renderVolatility(data.volatility_data || []);
    renderEvents(data.economic_events || []);
    renderTrends(data.trends || []);
    updateLastUpdate(data.last_update);
}

function updateDashboard(data) {
    if (data.trade_setups) renderTradeSetups(data.trade_setups);
    if (data.patterns) renderPatterns(data.patterns);
    if (data.volatility) renderVolatility(data.volatility);
    if (data.events) renderEvents(data.events);
    if (data.trends) renderTrends(data.trends);
    if (data.last_update) updateLastUpdate(data.last_update);
}

// ─── Trade Setups (entrée/SL/TP) ────────────────────────────────────

function renderTradeSetups(setups) {
    const container = document.getElementById('setups-list');
    if (!setups.length) {
        container.innerHTML = `
            <div class="empty-state">
                <p><strong>Aucun setup de trade actif</strong></p>
                <p>Les recommandations d'entree/sortie apparaitront quand un pattern sera detecte.</p>
            </div>`;
        return;
    }

    container.innerHTML = setups.map(s => tradeSetupHTML(s)).join('');
}

function tradeSetupHTML(s) {
    const isBuy = s.direction === 'buy';
    const dirClass = isBuy ? 'buy' : 'sell';
    const dirLabel = isBuy ? 'ACHAT' : 'VENTE';
    const dirIcon = isBuy ? '&#9650;' : '&#9660;';

    const patternName = s.pattern?.description || '';
    const confidence = s.pattern?.confidence || 0;
    const confPct = (confidence * 100).toFixed(0);

    const time = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '';
    const simBadge = s.is_simulated
        ? '<span class="data-badge simulated">SIMULE</span>'
        : '<span class="data-badge live">LIVE</span>';

    return `
        <div class="trade-setup ${dirClass}">
            <div class="setup-header">
                <div class="setup-direction ${dirClass}">
                    <span class="dir-icon">${dirIcon}</span>
                    <span class="dir-label">${dirLabel}</span>
                    <span class="setup-pair">${s.pair}</span>
                    ${simBadge}
                </div>
                <div class="setup-confidence">
                    <span class="confidence-bar">
                        <span class="confidence-fill" style="width:${confPct}%"></span>
                    </span>
                    <span class="confidence-text">${confPct}%</span>
                </div>
            </div>

            <div class="setup-levels">
                <div class="level-box entry">
                    <div class="level-label">ENTREE</div>
                    <div class="level-value">${s.entry_price?.toFixed(2)}</div>
                </div>
                <div class="level-box sl">
                    <div class="level-label">STOP LOSS</div>
                    <div class="level-value">${s.stop_loss?.toFixed(2)}</div>
                    <div class="level-pips">${s.risk_pips?.toFixed(2)} pts risque</div>
                </div>
                <div class="level-box tp1">
                    <div class="level-label">TP1 (conservateur)</div>
                    <div class="level-value">${s.take_profit_1?.toFixed(2)}</div>
                    <div class="level-pips">R:R ${s.risk_reward_1?.toFixed(1)}</div>
                </div>
                <div class="level-box tp2">
                    <div class="level-label">TP2 (agressif)</div>
                    <div class="level-value">${s.take_profit_2?.toFixed(2)}</div>
                    <div class="level-pips">R:R ${s.risk_reward_2?.toFixed(1)}</div>
                </div>
            </div>

            <div class="setup-pattern">
                <span class="pattern-tag">${_patternLabel(s.pattern?.pattern)}</span>
                <span class="pattern-desc">${patternName}</span>
            </div>

            <div class="setup-time">${time}</div>
        </div>`;
}

function _patternLabel(pattern) {
    const labels = {
        'breakout_up': 'Cassure Resistance',
        'breakout_down': 'Cassure Support',
        'momentum_up': 'Momentum Haussier',
        'momentum_down': 'Momentum Baissier',
        'range_bounce_up': 'Rebond Support',
        'range_bounce_down': 'Rejet Resistance',
        'mean_reversion_up': 'Retour Moyenne',
        'mean_reversion_down': 'Retour Moyenne',
        'engulfing_bullish': 'Englobante Haussiere',
        'engulfing_bearish': 'Englobante Baissiere',
        'pin_bar_up': 'Pin Bar Haussiere',
        'pin_bar_down': 'Pin Bar Baissiere',
    };
    return labels[pattern] || pattern || '';
}

// ─── Patterns ────────────────────────────────────────────────────────

function renderPatterns(patterns) {
    const container = document.getElementById('patterns-body');
    if (!patterns.length) {
        container.innerHTML = '<div class="empty-state"><p>Aucun pattern detecte</p></div>';
        return;
    }

    container.innerHTML = patterns.map(p => {
        const confPct = (p.confidence * 100).toFixed(0);
        const isBull = p.pattern.includes('up') || p.pattern.includes('bullish');
        const colorClass = isBull ? 'bullish' : 'bearish';

        return `
            <div class="pattern-item ${colorClass}">
                <span class="pattern-tag">${_patternLabel(p.pattern)}</span>
                <span class="pattern-conf">${confPct}%</span>
                <span class="pattern-desc-text">${p.description}</span>
            </div>`;
    }).join('');
}

// ─── Signaux ─────────────────────────────────────────────────────────

function renderSignals(signals) {
    const container = document.getElementById('signals-list');
    if (!signals.length) {
        container.innerHTML = `
            <div class="empty-state">
                <p><strong>Aucun signal actif</strong></p>
                <p>Le radar scanne le marche. Les signaux apparaitront ici.</p>
            </div>`;
        return;
    }
    container.innerHTML = signals.map(s => signalCardHTML(s)).join('');
}

function addSignalToUI(signal) {
    const container = document.getElementById('signals-list');
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) container.innerHTML = '';
    container.insertAdjacentHTML('afterbegin', signalCardHTML(signal));
    const cards = container.querySelectorAll('.signal-card');
    if (cards.length > 20) cards[cards.length - 1].remove();
}

function signalCardHTML(s) {
    const strength = s.signal_strength || s.strength;
    const volRatio = s.volatility?.volatility_ratio || s.volatility_ratio || 0;
    const volLevel = s.volatility?.level || s.volatility_level || 'low';
    const trendDir = s.trend?.direction || s.trend_direction || 'neutral';
    const trendStr = s.trend?.strength || s.trend_strength || 0;
    const msg = s.message || '';
    const time = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '';
    const events = s.nearby_events || [];

    // Si un trade setup est associé
    const setup = s.trade_setup;
    let setupHTML = '';
    if (setup) {
        const dirLabel = setup.direction === 'buy' ? 'ACHAT' : 'VENTE';
        setupHTML = `
            <div class="signal-setup-mini">
                <strong>${dirLabel}</strong> @ ${setup.entry_price?.toFixed(2)} |
                SL: ${setup.stop_loss?.toFixed(2)} |
                TP1: ${setup.take_profit_1?.toFixed(2)} |
                TP2: ${setup.take_profit_2?.toFixed(2)}
            </div>`;
    }

    let eventsHTML = '';
    if (events.length) {
        eventsHTML = `<div style="margin-top:4px;font-size:12px;color:var(--accent-yellow)">
            Evenements: ${events.map(e => `${e.name || e.event_name} (${e.impact})`).join(', ')}
        </div>`;
    }

    const dirLabels = { bullish: 'HAUSSIER', bearish: 'BAISSIER', neutral: 'NEUTRE' };
    const volLabels = { high: 'haute', medium: 'moyenne', low: 'basse' };

    return `
        <div class="signal-card ${strength}">
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="signal-pair">${s.pair}</span>
                <span class="signal-badge ${strength}">${_strengthLabel(strength)}</span>
                <span class="level-tag ${volLevel}">vol ${volRatio.toFixed(1)}x</span>
            </div>
            <div class="signal-details">
                Tendance ${dirLabels[trendDir] || trendDir} (force: ${(trendStr * 100).toFixed(0)}%) |
                Volatilite: ${volLabels[volLevel] || volLevel}
            </div>
            ${setupHTML}
            ${eventsHTML}
            <div class="signal-time">${time}</div>
        </div>`;
}

function _strengthLabel(s) {
    return { strong: 'FORT', moderate: 'MODERE', weak: 'FAIBLE' }[s] || s;
}

// ─── Volatilité ──────────────────────────────────────────────────────

function renderVolatility(volData) {
    const container = document.getElementById('volatility-body');
    if (!volData.length) {
        container.innerHTML = '<div class="empty-state"><p>Chargement...</p></div>';
        return;
    }

    const sorted = [...volData].sort((a, b) => b.volatility_ratio - a.volatility_ratio);
    const maxRatio = Math.max(...sorted.map(v => v.volatility_ratio), 2);

    const volLabels = { high: 'haute', medium: 'moyenne', low: 'basse' };

    container.innerHTML = `
        <table class="vol-table">
            <thead>
                <tr><th>Paire</th><th>Niveau</th><th>Ratio</th><th>Volatilite</th></tr>
            </thead>
            <tbody>
                ${sorted.map(v => {
                    const pct = Math.min((v.volatility_ratio / maxRatio) * 100, 100);
                    return `<tr>
                        <td><strong>${v.pair}</strong></td>
                        <td><span class="level-tag ${v.level}">${volLabels[v.level] || v.level}</span></td>
                        <td>${v.volatility_ratio.toFixed(2)}x</td>
                        <td>
                            <div class="vol-bar">
                                <div class="vol-bar-fill ${v.level}" style="width:${pct}%"></div>
                            </div>
                        </td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
}

// ─── Événements économiques ──────────────────────────────────────────

function renderEvents(events) {
    const container = document.getElementById('events-body');
    if (!events.length) {
        container.innerHTML = '<div class="empty-state"><p>Aucun evenement economique</p></div>';
        return;
    }

    const impactLabels = { high: 'Fort', medium: 'Moyen', low: 'Faible' };

    container.innerHTML = events.map(e => `
        <div class="event-item">
            <span class="event-time">${e.time || '--:--'}</span>
            <span class="impact-dot ${e.impact}"></span>
            <span class="event-currency">${e.currency}</span>
            <span class="event-name">${e.event_name}</span>
            <span class="event-values">
                ${e.actual ? `R: ${e.actual}` : ''}
                ${e.forecast ? `P: ${e.forecast}` : ''}
                ${e.previous ? `Prec: ${e.previous}` : ''}
            </span>
        </div>
    `).join('');
}

// ─── Tendances ───────────────────────────────────────────────────────

function renderTrends(trends) {
    const trendInfo = document.getElementById('trend-info');
    if (!trendInfo || !trends.length) return;

    const strong = trends.filter(t => t.strength >= 0.7);
    if (strong.length) {
        trendInfo.textContent = `${strong.length} tendance(s) forte(s)`;
    } else {
        trendInfo.textContent = 'Pas de tendance forte';
    }
}

function updateLastUpdate(timestamp) {
    const el = document.getElementById('last-update');
    if (el && timestamp) {
        el.textContent = `MAJ: ${new Date(timestamp).toLocaleTimeString()}`;
    }
}

// ─── Notifications toast ─────────────────────────────────────────────

function showToast(signal) {
    const container = document.getElementById('toast-container');
    const strength = signal.signal_strength || signal.strength;

    const toast = document.createElement('div');
    toast.className = 'toast';

    // Si un trade setup est dans le signal
    const setup = signal.trade_setup;
    let setupInfo = '';
    if (setup) {
        const dir = setup.direction === 'buy' ? 'ACHAT' : 'VENTE';
        setupInfo = `${dir} @ ${setup.entry_price?.toFixed(2)} | SL: ${setup.stop_loss?.toFixed(2)} | TP: ${setup.take_profit_1?.toFixed(2)}`;
    }

    toast.innerHTML = `
        <div class="toast-title">Signal Scalping: ${signal.pair}</div>
        <div class="toast-body">${setupInfo || signal.message || `Signal ${_strengthLabel(strength)} detecte`}</div>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 10000);
}

// ─── Notifications navigateur ────────────────────────────────────────

function requestBrowserNotification(signal) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
        sendBrowserNotification(signal);
    } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(perm => {
            if (perm === 'granted') sendBrowserNotification(signal);
        });
    }
}

function sendBrowserNotification(signal) {
    const setup = signal.trade_setup;
    let body = signal.message || 'Opportunite detectee';
    if (setup) {
        const dir = setup.direction === 'buy' ? 'ACHAT' : 'VENTE';
        body = `${dir} @ ${setup.entry_price?.toFixed(2)} | SL: ${setup.stop_loss?.toFixed(2)} | TP: ${setup.take_profit_1?.toFixed(2)}`;
    }

    new Notification(`Scalping: ${signal.pair}`, {
        body: body,
        tag: `scalp-${signal.pair}`,
        requireInteraction: true,
    });
}

// ─── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    fetchOverview();
    connectWebSocket();
    document.getElementById('refresh-btn').addEventListener('click', refreshAnalysis);
});
