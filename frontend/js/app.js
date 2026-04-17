/**
 * Scalping Radar - Application Frontend
 * Dashboard temps réel pour la détection de signaux de scalping
 */

const API_BASE = window.location.origin;
const WS_PROTO = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_PROTO}//${window.location.host}/ws`;

let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;
const AUTO_REFRESH_INTERVAL = 5000; // Polling API toutes les 5s
let lastUpdateTime = null;
let liveClockInterval = null;

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
        _playSignalSound(message.data);
    } else if (message.type === 'update') {
        updateDashboard(message.data);
    } else if (message.type === 'tick') {
        handleTick(message.data);
    }
}

// ─── Sons d'alerte (Web Audio API, aucun asset externe) ────────────

let _audioCtx = null;
function _ensureAudio() {
    if (!_audioCtx) {
        try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
        catch (e) { return null; }
    }
    return _audioCtx;
}

function _beep(freq, duration, gain = 0.15) {
    const ctx = _ensureAudio();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    g.gain.setValueAtTime(gain, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
    osc.connect(g); g.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
}

function _playSignalSound(signal) {
    if (!_soundEnabled()) return;
    const strength = signal.signal_strength || signal.strength;
    // Strong: triple bip aigu, moderate: double medium, weak: simple grave
    if (strength === 'strong') {
        _beep(880, 0.15); setTimeout(() => _beep(1100, 0.15), 180); setTimeout(() => _beep(1320, 0.25), 360);
    } else if (strength === 'moderate') {
        _beep(660, 0.15); setTimeout(() => _beep(880, 0.2), 200);
    } else {
        _beep(440, 0.25);
    }
}

function _soundEnabled() {
    return localStorage.getItem('scalping_sound') !== 'off';
}
function toggleSound() {
    const enabled = !_soundEnabled();
    localStorage.setItem('scalping_sound', enabled ? 'on' : 'off');
    _updateSoundBtn();
    if (enabled) _beep(880, 0.1); // confirmation audible
}
function _updateSoundBtn() {
    const btn = document.getElementById('sound-toggle');
    if (!btn) return;
    btn.textContent = _soundEnabled() ? 'Son ON' : 'Son OFF';
    btn.classList.toggle('sound-off', !_soundEnabled());
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

// ─── Backtest stats ────────────────────────────────────────────────

async function fetchBacktestStats() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/stats`);
        if (!res.ok) return;
        const stats = await res.json();
        renderBacktestStats(stats);
    } catch (err) {
        console.warn('Backtest stats error:', err);
    }
}

function renderBacktestStats(stats) {
    const container = document.getElementById('backtest-stats');
    if (!container) return;
    if (!stats.total_trades) {
        container.innerHTML = '<div class="empty-state"><p>Aucun trade enregistre pour le moment.</p><p>Les stats apparaitront des qu\'un signal aura ete emis.</p></div>';
        return;
    }
    const winRateClass = stats.win_rate_pct >= 60 ? 'conf-high' : stats.win_rate_pct >= 50 ? 'conf-medium' : 'conf-low';
    const pairsHTML = (stats.by_pair || []).map(p => `
        <tr>
            <td><strong>${p.pair}</strong></td>
            <td>${p.wins}W / ${p.losses}L</td>
            <td>${p.total}</td>
            <td><span class="${p.win_rate_pct >= 50 ? 'factor-positive' : 'factor-negative'}">${p.win_rate_pct}%</span></td>
        </tr>`).join('');

    container.innerHTML = `
        <div class="backtest-summary">
            <div class="bt-stat">
                <div class="bt-stat-label">TAUX DE REUSSITE</div>
                <div class="bt-stat-value ${winRateClass}">${stats.win_rate_pct}%</div>
            </div>
            <div class="bt-stat">
                <div class="bt-stat-label">TRADES FERMES</div>
                <div class="bt-stat-value">${stats.closed_trades}</div>
            </div>
            <div class="bt-stat">
                <div class="bt-stat-label">OUVERTS</div>
                <div class="bt-stat-value">${stats.open_trades}</div>
            </div>
            <div class="bt-stat">
                <div class="bt-stat-label">R:R MOYEN</div>
                <div class="bt-stat-value">${stats.avg_rr_realized.toFixed(2)}</div>
            </div>
        </div>
        ${pairsHTML ? `
        <table class="vol-table" style="margin-top:12px">
            <thead><tr><th>Paire</th><th>W / L</th><th>Total</th><th>Win rate</th></tr></thead>
            <tbody>${pairsHTML}</tbody>
        </table>` : ''}
    `;
}

// ─── Theme toggle (light/dark) ─────────────────────────────────────

function _currentTheme() {
    return localStorage.getItem('scalping_theme') || 'dark';
}

function _applyTheme(theme) {
    const root = document.documentElement;
    if (theme === 'light') {
        root.setAttribute('data-theme', 'light');
    } else {
        root.removeAttribute('data-theme');
    }
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = theme === 'light' ? '☀️' : '🌙';
}

function toggleTheme() {
    const next = _currentTheme() === 'light' ? 'dark' : 'light';
    localStorage.setItem('scalping_theme', next);
    _applyTheme(next);
}

// Applique le theme le plus tot possible (avant DOMContentLoaded pour eviter flash)
_applyTheme(_currentTheme());

// ─── Sessions forex (Sydney/Tokyo/London/New York) ─────────────────

const _SESSIONS = [
    { name: 'Sydney',   start: 22, end: 7,  color: '#8e44ad' },
    { name: 'Tokyo',    start: 0,  end: 9,  color: '#e74c3c' },
    { name: 'London',   start: 8,  end: 17, color: '#3498db' },
    { name: 'New York', start: 13, end: 22, color: '#27ae60' },
];

function _activeSessions() {
    const hour = new Date().getUTCHours();
    return _SESSIONS.filter(s =>
        s.start <= s.end ? (hour >= s.start && hour < s.end)
                         : (hour >= s.start || hour < s.end)
    );
}

function _renderSessionMarkers() {
    const el = document.getElementById('session-markers');
    if (!el) return;
    const active = _activeSessions();
    if (!active.length) {
        el.innerHTML = '<span class="session-badge session-closed">Marche ferme</span>';
        return;
    }
    el.innerHTML = active.map(s =>
        `<span class="session-badge" style="background:${s.color}20;border-color:${s.color};color:${s.color}">${s.name}</span>`
    ).join('');
}

// ─── Live Ticks (WebSocket Twelve Data) ─────────────────────────────

const _tickState = {}; // { [pair]: { price, prev, lastTs, history: number[] } }
const SPARKLINE_POINTS = 40;

async function fetchTicks() {
    try {
        const res = await fetch(`${API_BASE}/api/ticks`);
        if (!res.ok) return;
        const data = await res.json();
        if (!data.symbols || data.symbols.length === 0) return;
        document.getElementById('live-ticks-section').style.display = '';
        const info = document.getElementById('live-ticks-info');
        if (info) info.textContent = `${data.symbols.length} symbole(s) streame(s)`;
        // Seed du state avec les derniers ticks deja recus
        Object.entries(data.ticks || {}).forEach(([pair, t]) => {
            _tickState[pair] = { price: t.price, prev: t.price, lastTs: t.timestamp, history: [t.price] };
        });
        renderTicks(data.symbols);
    } catch (err) {
        // WS pas active, on ignore silencieusement
    }
}

function renderTicks(symbols) {
    const grid = document.getElementById('live-ticks-grid');
    if (!grid) return;
    grid.innerHTML = symbols.map(pair => {
        const state = _tickState[pair] || {};
        const price = state.price !== undefined ? state.price.toFixed(pair.includes('JPY') ? 3 : 5) : '—';
        return `
            <div class="tick-card" data-pair="${pair}">
                <div class="tick-pair">${pair}</div>
                <div class="tick-price" data-pair-price="${pair}">${price}</div>
                <svg class="tick-sparkline" data-pair-spark="${pair}" viewBox="0 0 100 30" preserveAspectRatio="none"></svg>
                <div class="tick-ts" data-pair-ts="${pair}">${state.lastTs ? _relativeTime(state.lastTs) : '—'}</div>
            </div>`;
    }).join('');
    symbols.forEach(pair => _drawSparkline(pair));
}

function _drawSparkline(pair) {
    const svg = document.querySelector(`[data-pair-spark="${pair}"]`);
    if (!svg) return;
    const state = _tickState[pair];
    const history = state?.history || [];
    if (history.length < 2) { svg.innerHTML = ''; return; }
    const min = Math.min(...history);
    const max = Math.max(...history);
    const range = (max - min) || 1;
    const step = 100 / (history.length - 1);
    const points = history.map((v, i) => {
        const x = (i * step).toFixed(2);
        const y = (28 - ((v - min) / range) * 26).toFixed(2);
        return `${x},${y}`;
    }).join(' ');
    const last = history[history.length - 1];
    const first = history[0];
    const color = last >= first ? '#26a69a' : '#ef5350';
    svg.innerHTML = `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.2" />`;
}

function handleTick(tick) {
    const section = document.getElementById('live-ticks-section');
    if (section) section.style.display = '';
    const prev = _tickState[tick.pair]?.price;
    const history = _tickState[tick.pair]?.history || [];
    history.push(tick.price);
    while (history.length > SPARKLINE_POINTS) history.shift();
    _tickState[tick.pair] = { price: tick.price, prev: prev ?? tick.price, lastTs: tick.timestamp, history };

    const priceEl = document.querySelector(`[data-pair-price="${tick.pair}"]`);
    const card = document.querySelector(`.tick-card[data-pair="${tick.pair}"]`);
    if (!priceEl) {
        // La carte n'existe pas encore, re-render la grille
        const symbols = Array.from(new Set([...Object.keys(_tickState), tick.pair]));
        renderTicks(symbols);
        return;
    }
    priceEl.textContent = tick.price.toFixed(tick.pair.includes('JPY') ? 3 : 5);

    // Pulse visuel (vert si up, rouge si down)
    if (card && prev !== undefined) {
        card.classList.remove('tick-up', 'tick-down');
        if (tick.price > prev) card.classList.add('tick-up');
        else if (tick.price < prev) card.classList.add('tick-down');
        setTimeout(() => card.classList.remove('tick-up', 'tick-down'), 400);
    }
    const tsEl = document.querySelector(`[data-pair-ts="${tick.pair}"]`);
    if (tsEl) tsEl.textContent = _relativeTime(tick.timestamp);
    _drawSparkline(tick.pair);
}

function _relativeTime(isoTs) {
    const sec = Math.max(0, Math.floor((Date.now() - new Date(isoTs)) / 1000));
    if (sec < 2) return 'maintenant';
    if (sec < 60) return `il y a ${sec}s`;
    return `il y a ${Math.floor(sec / 60)}min`;
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

const _setupFilters = { direction: 'all', pair: 'all' };
let _lastSetups = [];
const _activeCharts = new Map(); // setup_id -> { chart, series }

function renderTradeSetups(setups) {
    _lastSetups = setups || [];
    _updatePairFilterOptions(_lastSetups);
    _renderFilteredSetups();
}

function _renderFilteredSetups() {
    const container = document.getElementById('setups-list');
    const filtered = _lastSetups.filter(s => {
        if (_setupFilters.direction !== 'all' && s.direction !== _setupFilters.direction) return false;
        if (_setupFilters.pair !== 'all' && s.pair !== _setupFilters.pair) return false;
        return true;
    });

    if (!filtered.length) {
        const msg = _lastSetups.length
            ? `<p>Aucun setup ne correspond aux filtres actuels.</p>`
            : `<p><strong>Aucun setup de trade actif</strong></p><p>Les recommandations d'entree/sortie apparaitront quand un pattern sera detecte.</p>`;
        container.innerHTML = `<div class="empty-state">${msg}</div>`;
        _disposeAllCharts();
        return;
    }

    // Nettoyer les charts existants avant re-render
    _disposeAllCharts();
    container.innerHTML = filtered.map(s => tradeSetupHTML(s)).join('');

    // Monter les mini-charts en async
    filtered.forEach(s => _mountMiniChart(s));
}

function _updatePairFilterOptions(setups) {
    const select = document.querySelector('[data-filter="pair"]');
    if (!select) return;
    const pairs = Array.from(new Set(setups.map(s => s.pair))).sort();
    const current = select.value;
    select.innerHTML = '<option value="all">Toutes</option>' +
        pairs.map(p => `<option value="${p}">${p}</option>`).join('');
    if (pairs.includes(current)) select.value = current;
}

function _bindFilters() {
    document.querySelectorAll('#setup-filter-bar .filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const filter = btn.dataset.filter;
            document.querySelectorAll(`#setup-filter-bar .filter-btn[data-filter="${filter}"]`)
                .forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            _setupFilters[filter] = btn.dataset.value;
            _renderFilteredSetups();
        });
    });
    const pairSelect = document.querySelector('#setup-filter-bar [data-filter="pair"]');
    if (pairSelect) {
        pairSelect.addEventListener('change', e => {
            _setupFilters.pair = e.target.value;
            _renderFilteredSetups();
        });
    }
}

// ─── Mini-charts (lightweight-charts) ────────────────────────────────

function _setupChartId(s) {
    return `${s.pair}-${s.direction}-${s.entry_price}`.replace(/[^a-zA-Z0-9-]/g, '_');
}

function _disposeAllCharts() {
    _activeCharts.forEach(({ chart }) => { try { chart.remove(); } catch (e) {} });
    _activeCharts.clear();
}

async function _mountMiniChart(setup) {
    if (typeof LightweightCharts === 'undefined') return;
    const id = _setupChartId(setup);
    const el = document.querySelector(`[data-chart-id="${id}"]`);
    if (!el) return;

    try {
        const res = await fetch(`${API_BASE}/api/candles/${encodeURIComponent(setup.pair)}`);
        if (!res.ok) return;
        const data = await res.json();
        const candles = data.candles || [];
        if (!candles.length) return;

        const chart = LightweightCharts.createChart(el, {
            width: el.clientWidth,
            height: 180,
            layout: { background: { color: 'transparent' }, textColor: '#aaa', fontSize: 10 },
            grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
            rightPriceScale: { borderColor: '#333' },
            timeScale: { borderColor: '#333', timeVisible: true, secondsVisible: false },
        });
        const series = chart.addCandlestickSeries({
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
            wickUpColor: '#26a69a', wickDownColor: '#ef5350',
        });
        series.setData(candles.map(c => ({
            time: Math.floor(new Date(c.timestamp).getTime() / 1000),
            open: c.open, high: c.high, low: c.low, close: c.close,
        })));

        // Marqueurs de niveaux : entry, SL, TP1, TP2
        series.createPriceLine({ price: setup.entry_price, color: '#f1c40f', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'Entry' });
        series.createPriceLine({ price: setup.stop_loss,   color: '#ef5350', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
        series.createPriceLine({ price: setup.take_profit_1, color: '#26a69a', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP1' });
        series.createPriceLine({ price: setup.take_profit_2, color: '#2ecc71', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'TP2' });

        chart.timeScale().fitContent();
        _activeCharts.set(id, { chart, series });
    } catch (e) {
        console.warn('Chart error for', setup.pair, e);
    }
}

function tradeSetupHTML(s) {
    const isBuy = s.direction === 'buy';
    const dirClass = isBuy ? 'buy' : 'sell';
    const dirLabel = isBuy ? 'ACHAT' : 'VENTE';
    const dirIcon = isBuy ? '&#9650;' : '&#9660;';

    const patternName = s.pattern?.description || '';
    const confScore = s.confidence_score || 0;
    const confScoreInt = confScore.toFixed(0);

    const time = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '';
    const simBadge = s.is_simulated
        ? '<span class="data-badge simulated">SIMULE</span>'
        : '<span class="data-badge live">LIVE</span>';

    // Confidence score color
    const confColor = confScore >= 85 ? 'conf-high' : confScore >= 75 ? 'conf-medium' : 'conf-low';

    // Confidence factors
    const factors = s.confidence_factors || [];
    const factorsHTML = factors.map(f => {
        const icon = f.positive ? '+' : '-';
        const cls = f.positive ? 'factor-positive' : 'factor-negative';
        return `<div class="confidence-factor ${cls}">
            <span class="factor-icon">${icon}</span>
            <span class="factor-name">${f.name}</span>
            <span class="factor-score">${f.score.toFixed(0)}</span>
            <span class="factor-detail">${f.detail}</span>
        </div>`;
    }).join('');

    // Money management
    const suggestedAmt = s.suggested_amount || 0;
    const riskAmt = s.risk_amount || 0;
    const gain1 = s.estimated_gain_1 || 0;
    const gain2 = s.estimated_gain_2 || 0;

    return `
        <div class="trade-setup ${dirClass}">
            <div class="setup-header">
                <div class="setup-direction ${dirClass}">
                    <span class="dir-icon">${dirIcon}</span>
                    <span class="dir-label">${dirLabel}</span>
                    <span class="setup-pair">${s.pair}</span>
                    ${simBadge}
                </div>
                <div class="setup-confidence-score ${confColor}">
                    <span class="conf-score-value">${confScoreInt}</span>
                    <span class="conf-score-label">/100</span>
                </div>
            </div>

            <div class="setup-chart" data-chart-id="${_setupChartId(s)}"></div>

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

            <div class="setup-money">
                <div class="money-box suggested">
                    <div class="money-label">POSITION</div>
                    <div class="money-value">${suggestedAmt.toFixed(0)} $</div>
                </div>
                <div class="money-box risk">
                    <div class="money-label">RISQUE MAX</div>
                    <div class="money-value">-${riskAmt.toFixed(0)} $</div>
                </div>
                <div class="money-box gain1">
                    <div class="money-label">GAIN TP1</div>
                    <div class="money-value">+${gain1.toFixed(0)} $</div>
                </div>
                <div class="money-box gain2">
                    <div class="money-label">GAIN TP2</div>
                    <div class="money-value">+${gain2.toFixed(0)} $</div>
                </div>
            </div>

            <div class="setup-explanation-toggle" onclick="this.parentElement.querySelector('.setup-explanation').classList.toggle('open')">
                Voir l'analyse detaillee
            </div>
            <div class="setup-explanation">
                <div class="explanation-factors">
                    <div class="factors-title">FACTEURS DE CONFIANCE</div>
                    ${factorsHTML}
                </div>
            </div>

            <div class="setup-pattern">
                <span class="pattern-tag">${_patternLabel(s.pattern?.pattern)}</span>
                <span class="pattern-desc">${patternName}</span>
            </div>

            <div class="setup-timestamps">
                <div class="ts-entry">
                    <span class="ts-label">ENTREE</span>
                    <span class="ts-value">${s.entry_time ? new Date(s.entry_time).toLocaleTimeString() : time}</span>
                </div>
                <div class="ts-expiry ${_isExpired(s.expiry_time) ? 'expired' : 'active'}">
                    <span class="ts-label">${_isExpired(s.expiry_time) ? 'EXPIRE' : 'VALIDE JUSQU\'A'}</span>
                    <span class="ts-value">${s.expiry_time ? new Date(s.expiry_time).toLocaleTimeString() : '--:--'}</span>
                </div>
                <div class="ts-countdown" data-expiry="${s.expiry_time || ''}">
                    <span class="ts-label">TEMPS RESTANT</span>
                    <span class="ts-value countdown-value">${_countdown(s.expiry_time)}</span>
                </div>
                <div class="ts-validity">
                    <span class="ts-label">VALIDITE</span>
                    <span class="ts-value">${s.validity_minutes || 15} min</span>
                </div>
            </div>
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

        const explanationHTML = p.explanation ? `<div class="pattern-explanation">${p.explanation}</div>` : '';
        const reliabilityHTML = p.reliability ? `<div class="pattern-reliability">${p.reliability}</div>` : '';
        const hasDetails = p.explanation || p.reliability;

        return `
            <div class="pattern-item-card ${colorClass}">
                <div class="pattern-item-header">
                    <span class="pattern-tag">${_patternLabel(p.pattern)}</span>
                    <span class="pattern-conf">${confPct}%</span>
                    <span class="pattern-desc-text">${p.description}</span>
                </div>
                ${hasDetails ? `
                <div class="pattern-details-toggle" onclick="this.nextElementSibling.classList.toggle('open')">Comprendre ce pattern</div>
                <div class="pattern-details-panel">
                    ${explanationHTML}
                    ${reliabilityHTML}
                </div>` : ''}
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

    const sigScore = s.confidence_score || 0;
    const sigScoreInt = sigScore.toFixed(0);
    const sigConfColor = sigScore >= 70 ? 'conf-high' : sigScore >= 50 ? 'conf-medium' : 'conf-low';

    const sigFactors = s.confidence_factors || [];
    const sigFactorsHTML = sigFactors.length ? sigFactors.map(f => {
        const icon = f.positive ? '+' : '-';
        const cls = f.positive ? 'factor-positive' : 'factor-negative';
        return `<div class="confidence-factor ${cls}">
            <span class="factor-icon">${icon}</span>
            <span class="factor-name">${f.name}</span>
            <span class="factor-score">${f.score.toFixed(0)}</span>
            <span class="factor-detail">${f.detail}</span>
        </div>`;
    }).join('') : '';

    return `
        <div class="signal-card ${strength}">
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="signal-pair">${s.pair}</span>
                <span class="signal-badge ${strength}">${_strengthLabel(strength)}</span>
                <span class="level-tag ${volLevel}">vol ${volRatio.toFixed(1)}x</span>
                <span class="setup-confidence-score ${sigConfColor}" style="margin-left:auto;padding:3px 8px;">
                    <span class="conf-score-value" style="font-size:16px;">${sigScoreInt}</span>
                    <span class="conf-score-label">/100</span>
                </span>
            </div>
            <div class="signal-details">
                Tendance ${dirLabels[trendDir] || trendDir} (force: ${(trendStr * 100).toFixed(0)}%) |
                Volatilite: ${volLabels[volLevel] || volLevel}
            </div>
            ${setupHTML}
            ${eventsHTML}
            ${sigFactorsHTML ? `
            <div class="setup-explanation-toggle" onclick="this.nextElementSibling.classList.toggle('open')">Voir l'analyse detaillee</div>
            <div class="setup-explanation">
                <div class="explanation-factors">
                    <div class="factors-title">FACTEURS DE CONFIANCE</div>
                    ${sigFactorsHTML}
                </div>
            </div>` : ''}
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
    if (timestamp) {
        lastUpdateTime = new Date(timestamp);
    }
    _renderClock();
}

function _renderClock() {
    const el = document.getElementById('last-update');
    const clockEl = document.getElementById('live-clock');
    if (!el) return;

    const now = new Date();

    // Horloge live
    if (clockEl) {
        clockEl.textContent = now.toLocaleTimeString();
    }

    if (lastUpdateTime) {
        const diffSec = Math.floor((now - lastUpdateTime) / 1000);
        if (diffSec < 60) {
            el.textContent = `MAJ: il y a ${diffSec}s`;
        } else {
            const diffMin = Math.floor(diffSec / 60);
            el.textContent = `MAJ: il y a ${diffMin}min`;
        }
        el.className = diffSec > 30 ? 'last-update stale' : 'last-update fresh';
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

// ─── Timestamps helpers ─────────────────────────────────────────────

function _isExpired(expiryTime) {
    if (!expiryTime) return false;
    return new Date() > new Date(expiryTime);
}

function _countdown(expiryTime) {
    if (!expiryTime) return '--:--';
    const diff = new Date(expiryTime) - new Date();
    if (diff <= 0) return 'EXPIRE';
    const min = Math.floor(diff / 60000);
    const sec = Math.floor((diff % 60000) / 1000);
    return `${min}:${sec.toString().padStart(2, '0')}`;
}

function _updateCountdowns() {
    document.querySelectorAll('.ts-countdown').forEach(el => {
        const expiry = el.dataset.expiry;
        if (!expiry) return;
        const val = el.querySelector('.countdown-value');
        if (val) val.textContent = _countdown(expiry);

        // Mettre à jour le style expired/active
        const expiryEl = el.parentElement?.querySelector('.ts-expiry');
        if (expiryEl) {
            if (_isExpired(expiry)) {
                expiryEl.classList.add('expired');
                expiryEl.classList.remove('active');
                expiryEl.querySelector('.ts-label').textContent = 'EXPIRE';
            }
        }
    });
}

// ─── Glossaire ──────────────────────────────────────────────────────

let glossaryData = [];

async function fetchGlossary() {
    try {
        const res = await fetch(`${API_BASE}/api/glossary`);
        glossaryData = await res.json();
        renderGlossary(glossaryData);
    } catch (err) {
        console.error('Erreur fetch glossaire:', err);
    }
}

function renderGlossary(items) {
    const container = document.getElementById('glossary-list');
    if (!items.length) {
        container.innerHTML = '<div class="empty-state"><p>Aucun terme trouve</p></div>';
        return;
    }

    container.innerHTML = items.map(g => `
        <div class="glossary-item">
            <div class="glossary-term">
                <span class="glossary-abbr">${g.term}</span>
                <span class="glossary-full">${g.full}</span>
            </div>
            <div class="glossary-def">${g.definition}</div>
        </div>
    `).join('');
}

function filterGlossary(query) {
    const q = query.toLowerCase().trim();
    if (!q) {
        renderGlossary(glossaryData);
        return;
    }
    const filtered = glossaryData.filter(g =>
        g.term.toLowerCase().includes(q) ||
        g.full.toLowerCase().includes(q) ||
        g.definition.toLowerCase().includes(q)
    );
    renderGlossary(filtered);
}

// ─── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    fetchOverview();
    fetchGlossary();
    fetchTicks();
    fetchBacktestStats();
    connectWebSocket();
    _bindFilters();
    _renderSessionMarkers();
    _updateSoundBtn();
    document.getElementById('refresh-btn').addEventListener('click', refreshAnalysis);
    const soundBtn = document.getElementById('sound-toggle');
    if (soundBtn) soundBtn.addEventListener('click', toggleSound);
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);

    // Horloge live + compteurs : mise à jour toutes les secondes
    setInterval(() => {
        _renderClock();
        _updateCountdowns();
    }, 1000);

    // Session markers : recalcul toutes les minutes
    setInterval(_renderSessionMarkers, 60000);

    // Auto-refresh des données toutes les 5 secondes
    setInterval(fetchOverview, AUTO_REFRESH_INTERVAL);

    // Refresh des stats backtest toutes les 30s
    setInterval(fetchBacktestStats, 30000);
});
