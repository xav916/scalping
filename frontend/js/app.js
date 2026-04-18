/**
 * Scalping Radar — Application Frontend
 * Dashboard temps réel pour la détection de signaux de scalping.
 *
 * Ce fichier est chargé en tant que module ES (<script type="module">).
 * Les helpers purs ont été extraits dans ./modules/utils.js afin d'être
 * testables isolément. Un découpage plus fin (ws/render/actions/api) est
 * documenté dans ./MODULES.md — il nécessite des tests pour être fait
 * sans régression, donc non réalisé dans cette passe.
 */

import {
    escapeHtml,
    strengthLabel as _strengthLabel,
    patternLabel as _patternLabel,
    markdownToHtml as _markdownToHtml,
    isExpired as _isExpired,
    countdown as _countdown,
    relativeTime as _relativeTime,
} from './modules/utils.js';

const API_BASE = window.location.origin;
const WS_PROTO = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_PROTO}//${window.location.host}/ws`;

let ws = null;
let reconnectAttempts = 0;
let reconnectTimer = null;
let heartbeatInterval = null;
const MAX_RECONNECT_DELAY = 30000;
// Fallback polling : uniquement si le WS est tombé. Réduit drastiquement la bande passante.
const POLL_FALLBACK_INTERVAL = 60000;
let lastUpdateTime = null;

// ─── Utilitaires locaux ──────────────────────────────────────────────
// escapeHtml et les formatteurs purs (countdown, isExpired, etc.) sont
// dans ./modules/utils.js. Seuls les helpers qui manipulent l'état
// global du module (ws, etc.) restent ici.

/** Vrai quand le WebSocket est ouvert — sert à gater le polling de secours. */
function isWsConnected() {
    return ws && ws.readyState === WebSocket.OPEN;
}

// ─── Intercepteur fetch : redirige vers /login si la session expire ──
// Patch global de window.fetch pour que CHAQUE requête API détecte un 401
// et renvoie l'utilisateur sur la page de login avec ?next=<url_actuelle>.
// Le service worker est bypass (il ne gère que le shell statique).
(function installAuthFetchInterceptor() {
    const originalFetch = window.fetch.bind(window);
    let redirecting = false;
    window.fetch = async (...args) => {
        const res = await originalFetch(...args);
        if (res.status === 401 && !redirecting) {
            redirecting = true;
            const next = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.replace(`/login?next=${next}`);
        }
        return res;
    };
})();

// ─── WebSocket ───────────────────────────────────────────────────────

function connectWebSocket() {
    if (isWsConnected()) return;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        reconnectAttempts = 0;
        setConnectionStatus(true);
        // Empêche l'empilement d'intervalles au reconnect
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        heartbeatInterval = setInterval(() => {
            if (isWsConnected()) ws.send('ping');
        }, 30000);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };

    ws.onclose = () => {
        setConnectionStatus(false);
        if (heartbeatInterval) { clearInterval(heartbeatInterval); heartbeatInterval = null; }
        scheduleReconnect();
    };

    ws.onerror = () => setConnectionStatus(false);
}

function scheduleReconnect() {
    if (reconnectTimer) return; // déjà planifié
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
    reconnectAttempts++;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
    }, delay);
}

function setConnectionStatus(connected) {
    const indicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    if (connected) {
        indicator.classList.remove('disconnected');
        statusText.textContent = 'En ligne';
    } else {
        indicator.classList.add('disconnected');
        statusText.textContent = 'Déconnecté';
    }
}

function handleWebSocketMessage(message) {
    if (message.type === 'signal') {
        addSignalToUI(message.data);
        showToast(message.data);
        requestBrowserNotification(message.data);
        _playSignalSound(message.data);
        _speakSignal(message.data);
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
    // Respecter le mode silencieux (-X% journalier)
    if (_dailyStatus && _dailyStatus.silent_mode) return;
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

// ─── Voice alerts (Web Speech) ─────────────────────────────────────

function _voiceEnabled() {
    return localStorage.getItem('scalping_voice') === 'on';
}
function toggleVoice() {
    const next = !_voiceEnabled();
    localStorage.setItem('scalping_voice', next ? 'on' : 'off');
    _updateVoiceBtn();
    if (next && 'speechSynthesis' in window) _speak('Voix activée');
}
function _updateVoiceBtn() {
    const btn = document.getElementById('voice-toggle');
    if (!btn) return;
    btn.textContent = _voiceEnabled() ? '🔊 Voix' : '🔇 Voix';
    btn.classList.toggle('sound-off', !_voiceEnabled());
}
function _speak(text) {
    if (!('speechSynthesis' in window)) return;
    try {
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = 'fr-FR';
        utter.rate = 1.05;
        speechSynthesis.speak(utter);
    } catch (e) {}
}
function _speakSignal(signal) {
    if (!_voiceEnabled()) return;
    if (_dailyStatus && _dailyStatus.silent_mode) return;
    const setup = signal.trade_setup;
    const dir = setup ? (setup.direction === 'buy' ? 'achat' : 'vente') : '';
    const verdict = setup?.verdict_action;
    const verdictFr = { TAKE: 'prendre', WAIT: 'attendre', SKIP: 'passer' }[verdict] || '';
    const txt = `Signal ${signal.signal_strength || ''} sur ${signal.pair.replace('/', ' ')}${dir ? ', ' + dir : ''}${verdictFr ? ', verdict ' + verdictFr : ''}`;
    _speak(txt);
}
window.toggleVoice = toggleVoice;
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

// ─── Workflow : daily status + modal trade + historique ────────────

let _dailyStatus = null;
let _currentSignalForModal = null;
let _closeTradeId = null;

async function fetchDailyStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/daily-status`);
        if (!res.ok) return;
        _dailyStatus = await res.json();
        _kpiUpdate('daily', _dailyStatus);
        renderDailyBanner(_dailyStatus);
    } catch (e) { /* silent */ }
}

function renderDailyBanner(status) {
    // Met a jour le nom d'utilisateur dans le header des qu'on le recoit
    if (status.display_name) {
        const greet = document.getElementById('user-greeting');
        if (greet) greet.textContent = `Bonjour ${status.display_name}`;
    }
    const banner = document.getElementById('daily-banner');
    if (!banner) return;
    // Toujours afficher le banner (pour le toggle silent mode) meme sans trade
    banner.style.display = '';
    const pnlClass = status.pnl_today > 0 ? 'pnl-positive' : status.pnl_today < 0 ? 'pnl-negative' : '';
    const silentBtnLabel = status.silent_mode ? '🔊 Activer les alertes' : '🔇 Couper les alertes';
    const silentBtnClass = status.silent_mode ? 'btn-primary silent-on' : '';
    const lossAlertHTML = status.loss_alert && !status.silent_mode
        ? `<span class="loss-alert-badge">⚠️ Vous avez atteint -${status.daily_loss_limit_pct}% — envisagez d'arrêter pour aujourd'hui</span>`
        : '';
    const silentStateHTML = status.silent_mode
        ? `<span class="silent-badge">🔇 Mode silencieux actif (pas de son ni Telegram)</span>`
        : '';

    banner.className = 'daily-banner' + (status.silent_mode ? ' silent' : '') + (status.loss_alert ? ' loss-alert' : '');
    banner.innerHTML = `
        <div class="db-stat"><span class="db-label">Aujourd'hui</span><span class="db-value">${status.date}</span></div>
        <div class="db-stat"><span class="db-label">Trades</span><span class="db-value">${status.n_trades_today} (${status.n_open} ouverts)</span></div>
        <div class="db-stat"><span class="db-label">PnL</span><span class="db-value ${pnlClass}">${status.pnl_today >= 0 ? '+' : ''}${status.pnl_today.toFixed(2)} USD (${status.pnl_pct >= 0 ? '+' : ''}${status.pnl_pct.toFixed(2)}%)</span></div>
        <button type="button" class="btn btn-sm ${silentBtnClass}" id="silent-toggle-btn" data-action="toggle-silent">${silentBtnLabel}</button>
        ${silentStateHTML}
        ${lossAlertHTML}
    `;
}

async function toggleSilentMode() {
    if (!_dailyStatus) return;
    const newState = !_dailyStatus.silent_mode;
    try {
        const res = await fetch(`${API_BASE}/api/silent-mode`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled: newState}),
        });
        if (!res.ok) { alert('Erreur toggle silent mode'); return; }
        fetchDailyStatus();
    } catch (e) { alert('Erreur : ' + e.message); }
}

window.toggleSilentMode = toggleSilentMode;

// Expose le bouton "J'ai pris ce signal" depuis tradeSetupHTML
// ─── Calculateur de taille de position ─────────────────────────────

function _computePositionSize() {
    const capital = parseFloat(document.getElementById('calc-capital')?.value) || 0;
    const riskPct = parseFloat(document.getElementById('calc-risk-pct')?.value) || 1;
    const form = document.getElementById('trade-form');
    const entry = parseFloat(form.entry_price.value) || 0;
    const sl = parseFloat(form.stop_loss.value) || 0;
    if (!entry || !sl) return null;
    const riskUsd = capital * (riskPct / 100);
    const distance = Math.abs(entry - sl);
    if (!distance) return null;
    // Pour forex/metaux : 1 lot = 100k unites de devise quotee
    const valuePerLot = distance * 100000;
    const lots = riskUsd / valuePerLot;
    return { riskUsd, lots: Math.max(0.01, Math.round(lots * 100) / 100) };
}

function _refreshCalcDisplay() {
    const result = document.getElementById('calc-result');
    if (!result) return;
    const r = _computePositionSize();
    if (!r) { result.textContent = 'Risque : — | Lots suggérés : —'; return; }
    result.textContent = `Risque : ${r.riskUsd.toFixed(2)} USD | Lots suggérés : ${r.lots.toFixed(2)}`;
}

function applyCalculatedSize() {
    const r = _computePositionSize();
    if (!r) return;
    document.getElementById('trade-form').size_lot.value = r.lots.toFixed(2);
}

window.applyCalculatedSize = applyCalculatedSize;

function openTradeModal(pair, direction, entry, sl, tp1, pattern, confidence) {
    _currentSignalForModal = { pair, direction, entry, sl, tp1, pattern, confidence };
    const modal = document.getElementById('trade-modal');
    const form = document.getElementById('trade-form');
    form.pair.value = pair;
    form.direction.value = direction.toUpperCase();
    form.entry_price.value = entry;
    form.stop_loss.value = sl;
    form.take_profit.value = tp1;
    form.signal_pattern.value = pattern || '';
    form.signal_confidence.value = confidence || '';
    // Reset toutes les checkbox (pre-trade + post-entry)
    modal.querySelectorAll('[data-check], [data-post-entry]').forEach(c => c.checked = false);
    // Reset à l'étape 1 à chaque ouverture
    _showTradeStep(1);
    modal.style.display = '';
    // Check corr warning
    _checkCorrelation(pair, direction);
    // Refresh calculator display
    _refreshCalcDisplay();
    ['calc-capital','calc-risk-pct'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.oninput = _refreshCalcDisplay;
    });
    ['entry_price','stop_loss'].forEach(name => {
        const el = form[name];
        if (el) el.oninput = _refreshCalcDisplay;
    });
}

function closeTradeModal() {
    document.getElementById('trade-modal').style.display = 'none';
    _currentSignalForModal = null;
}

/** Affiche l'étape demandée (1 ou 2) dans la modale trade. */
function _showTradeStep(step) {
    const modal = document.getElementById('trade-modal');
    if (!modal) return;
    modal.dataset.step = String(step);
    modal.querySelectorAll('.modal-step[data-step]').forEach(el => {
        el.hidden = (el.dataset.step !== String(step));
    });
    modal.querySelectorAll('[data-step-dot]').forEach(el => {
        const stepNum = parseInt(el.dataset.stepDot, 10);
        el.classList.toggle('active', stepNum === step);
        el.classList.toggle('completed', stepNum < step);
    });
    // Rendre le récap pour l'étape 2
    if (step === 2) _renderTradeSummary();
}

/** Construit le récap de trade montré à l'étape 2 (synthèse pour validation). */
function _renderTradeSummary() {
    const form = document.getElementById('trade-form');
    const summary = document.getElementById('trade-summary');
    if (!form || !summary) return;
    const pair = form.pair.value;
    const dir = form.direction.value;
    const entry = parseFloat(form.entry_price.value) || 0;
    const sl = parseFloat(form.stop_loss.value) || 0;
    const tp = parseFloat(form.take_profit.value) || 0;
    const size = parseFloat(form.size_lot.value) || 0;
    const risk = Math.abs(entry - sl) * size * 100000;
    summary.innerHTML = `
        <h4>Récapitulatif</h4>
        <ul>
            <li><strong>${escapeHtml(pair)}</strong> · ${escapeHtml(dir)} · ${size} lot(s)</li>
            <li>Entry : ${entry.toFixed(5)} · SL : ${sl.toFixed(5)} · TP : ${tp.toFixed(5)}</li>
            <li>Risque estimé : <strong>${risk.toFixed(2)} USD</strong></li>
        </ul>
    `;
}

/** Passe de l'étape 1 à la 2 après validation des pré-checks et du formulaire. */
function goToTradeStep2() {
    const form = document.getElementById('trade-form');
    // Validité du formulaire natif (champs required)
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    // Checklist pré-trade
    const modal = document.getElementById('trade-modal');
    const preChecks = Array.from(modal.querySelectorAll('[data-check]'));
    const allChecked = preChecks.every(c => c.checked);
    if (!allChecked) {
        if (!confirm('La checklist pré-trade n\'est pas entièrement validée. Continuer quand même ?')) return;
    }
    _showTradeStep(2);
}

function goToTradeStep1() {
    _showTradeStep(1);
}

async function _checkCorrelation(pair, direction) {
    const warn = document.getElementById('correlation-warning');
    warn.style.display = 'none';
    warn.innerHTML = '';
    try {
        const res = await fetch(`${API_BASE}/api/correlation-check`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pair, direction}),
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data.warning && data.correlated_open_trades.length) {
            const list = data.correlated_open_trades
                .map(t => `${escapeHtml(t.pair)} (${escapeHtml(t.direction)})`)
                .join(', ');
            warn.style.display = '';
            warn.innerHTML = `⚠️ <strong>Attention corrélation</strong> — vous avez déjà ces positions ouvertes qui bougent dans le même sens : <strong>${list}</strong>. Prendre ce trade double votre exposition.`;
        }
    } catch (e) {}
}

async function confirmTradeSubmit() {
    const form = document.getElementById('trade-form');
    const modal = document.getElementById('trade-modal');
    // La checklist pré-trade est désormais validée à l'étape 1 (goToTradeStep2).
    // Ici on ne relit que son état pour l'enregistrer dans le payload.
    const preChecks = Array.from(modal.querySelectorAll('[data-check]'));
    const allChecked = preChecks.every(c => c.checked);
    const postEntry = {};
    modal.querySelectorAll('[data-post-entry]').forEach(cb => {
        postEntry[`post_entry_${cb.dataset.postEntry}`] = cb.checked;
    });
    const payload = {
        pair: form.pair.value,
        direction: form.direction.value.toLowerCase(),
        entry_price: parseFloat(form.entry_price.value),
        stop_loss: parseFloat(form.stop_loss.value),
        take_profit: parseFloat(form.take_profit.value),
        size_lot: parseFloat(form.size_lot.value),
        signal_pattern: form.signal_pattern.value || null,
        signal_confidence: form.signal_confidence.value ? parseFloat(form.signal_confidence.value) : null,
        checklist_passed: allChecked,
        notes: form.notes.value || null,
        ...postEntry,
    };
    try {
        const res = await fetch(`${API_BASE}/api/trades`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (!res.ok) { alert('Erreur enregistrement trade'); return; }
        closeTradeModal();
        fetchPersonalTrades();
        fetchDailyStatus();
    } catch (e) { alert('Erreur : ' + e.message); }
}

async function fetchPersonalTrades() {
    try {
        const res = await fetch(`${API_BASE}/api/trades?limit=30`);
        if (!res.ok) return;
        const trades = await res.json();
        renderPersonalTrades(trades);
    } catch (e) {}
}

function renderPersonalTrades(trades) {
    const container = document.getElementById('personal-trades');
    if (!container) return;
    if (!trades.length) {
        container.innerHTML = '<div class="empty-state"><p>Aucun trade enregistré pour l\'instant.</p><p>Cliquez « J\'ai pris ce signal » sur un setup pour commencer.</p></div>';
        return;
    }
    container.innerHTML = `
        <table class="vol-table trades-table">
            <thead>
                <tr>
                    <th>Date</th><th>Paire</th><th>Dir</th><th>Entry</th><th>SL</th><th>TP</th>
                    <th>Taille</th><th>Statut</th><th>PnL</th><th></th>
                </tr>
            </thead>
            <tbody>
                ${trades.map(t => {
                    const dt = new Date(t.created_at).toLocaleString('fr-FR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
                    const pnlClass = t.pnl > 0 ? 'pnl-positive' : t.pnl < 0 ? 'pnl-negative' : '';
                    const action = t.status === 'OPEN'
                        ? `<button type="button" class="btn btn-sm" data-action="close-trade" data-trade-id="${t.id}">Clôturer</button>`
                        : '';
                    return `<tr class="${t.status === 'OPEN' ? 'trade-open' : ''}">
                        <td>${dt}</td>
                        <td><strong>${escapeHtml(t.pair)}</strong></td>
                        <td class="${t.direction === 'buy' ? 'dir-buy' : 'dir-sell'}">${escapeHtml(t.direction.toUpperCase())}</td>
                        <td>${t.entry_price.toFixed(4)}</td>
                        <td>${t.stop_loss.toFixed(4)}</td>
                        <td>${t.take_profit.toFixed(4)}</td>
                        <td>${t.size_lot}</td>
                        <td><span class="trade-status ${escapeHtml((t.status || '').toLowerCase())}">${escapeHtml(t.status)}</span></td>
                        <td class="${pnlClass}">${t.pnl ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2) : '—'}</td>
                        <td>${action}</td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>
    `;
}

function openCloseModal(tradeId) {
    _closeTradeId = tradeId;
    const modal = document.getElementById('close-modal');
    const form = document.getElementById('close-form');
    form.exit_price.value = '';
    form.notes.value = '';
    modal.style.display = '';
}

function closeCloseModal() {
    document.getElementById('close-modal').style.display = 'none';
    _closeTradeId = null;
}

async function confirmCloseTrade() {
    const form = document.getElementById('close-form');
    const exit_price = parseFloat(form.exit_price.value);
    if (!exit_price || !_closeTradeId) return;
    try {
        const res = await fetch(`${API_BASE}/api/trades/${_closeTradeId}`, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({exit_price, notes: form.notes.value || null}),
        });
        if (!res.ok) { alert('Erreur clôture'); return; }
        closeCloseModal();
        fetchPersonalTrades();
        fetchDailyStatus();
    } catch (e) { alert('Erreur : ' + e.message); }
}

// Expose toggleTheme/toggleSound et al. aux onclick inline
window.openTradeModal = openTradeModal;
window.closeTradeModal = closeTradeModal;
window.openCloseModal = openCloseModal;
window.closeCloseModal = closeCloseModal;
window.confirmTradeSubmit = confirmTradeSubmit;
window.confirmCloseTrade = confirmCloseTrade;

// ─── Risk dashboard ─────────────────────────────────────────────────

async function fetchRiskDashboard() {
    try {
        const res = await fetch(`${API_BASE}/api/risk`);
        if (!res.ok) return;
        const data = await res.json();
        _kpiUpdate('risk', data);
        const sec = document.getElementById('risk-section');
        const body = document.getElementById('risk-body');
        if (!sec || !body) return;
        if (!data.n_open) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        const warnHTML = data.warning_over_3pct
            ? `<div class="risk-warning">⚠️ Risque cumulé > 3% du capital — réduire l'exposition</div>` : '';
        const rows = data.by_trade.map(t => `
            <tr><td>${escapeHtml(t.pair)}</td><td>${escapeHtml(t.direction.toUpperCase())}</td><td>${t.size_lot}</td><td>${t.risk_usd.toFixed(2)} USD</td></tr>
        `).join('');
        body.innerHTML = `
            <div class="risk-summary">
                <div class="bt-stat"><span class="bt-label">POSITIONS OUVERTES</span><span class="bt-value">${data.n_open}</span></div>
                <div class="bt-stat"><span class="bt-label">RISQUE CUMULÉ</span><span class="bt-value ${data.warning_over_3pct ? 'pnl-negative' : ''}">${data.total_risk_usd.toFixed(2)} USD</span></div>
                <div class="bt-stat"><span class="bt-label">% CAPITAL</span><span class="bt-value ${data.warning_over_3pct ? 'pnl-negative' : ''}">${data.total_risk_pct.toFixed(2)}%</span></div>
            </div>
            ${warnHTML}
            <table class="vol-table" style="margin-top:10px"><thead><tr><th>Paire</th><th>Dir</th><th>Lots</th><th>Risque</th></tr></thead><tbody>${rows}</tbody></table>
        `;
    } catch (e) {}
}

// ─── Equity curve ───────────────────────────────────────────────────

let _equityChart = null;
async function fetchEquityCurve() {
    try {
        const res = await fetch(`${API_BASE}/api/equity`);
        if (!res.ok) return;
        const data = await res.json();
        const sec = document.getElementById('equity-section');
        if (!sec) return;
        if (!data.points || data.points.length <= 1) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        const profit = data.current_equity - data.capital_initial;
        const profitPct = (profit / data.capital_initial * 100);
        const summary = document.getElementById('equity-summary');
        if (summary) summary.innerHTML = `
            <span class="bt-stat"><span class="bt-label">CAPITAL INIT</span><span class="bt-value">${data.capital_initial.toFixed(2)} USD</span></span>
            <span class="bt-stat"><span class="bt-label">CAPITAL ACTUEL</span><span class="bt-value">${data.current_equity.toFixed(2)} USD</span></span>
            <span class="bt-stat"><span class="bt-label">PROFIT</span><span class="bt-value ${profit >= 0 ? 'pnl-positive' : 'pnl-negative'}">${profit >= 0 ? '+' : ''}${profit.toFixed(2)} USD (${profit >= 0 ? '+' : ''}${profitPct.toFixed(2)}%)</span></span>
        `;
        // Render simple SVG line chart
        const chartEl = document.getElementById('equity-chart');
        if (chartEl) chartEl.innerHTML = _renderEquitySVG(data.points);
    } catch (e) {}
}

function _renderEquitySVG(points) {
    if (points.length < 2) return '';
    const W = 600, H = 200, P = 30;
    const values = points.map(p => p.equity);
    const min = Math.min(...values), max = Math.max(...values);
    const range = (max - min) || 1;
    const stepX = (W - 2 * P) / (points.length - 1);
    const polyPoints = points.map((p, i) => {
        const x = P + i * stepX;
        const y = H - P - ((p.equity - min) / range) * (H - 2 * P);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const last = points[points.length - 1];
    const first = points[0];
    const color = last.equity >= first.equity ? '#26a69a' : '#ef5350';
    return `
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:200px" preserveAspectRatio="none">
            <polyline points="${polyPoints}" fill="none" stroke="${color}" stroke-width="2"/>
            <text x="${P}" y="15" font-size="10" fill="#888">Min ${min.toFixed(2)}</text>
            <text x="${W-P}" y="15" font-size="10" fill="#888" text-anchor="end">Max ${max.toFixed(2)}</text>
        </svg>
    `;
}

function downloadCSV() {
    window.location.href = `${API_BASE}/api/trades.csv`;
}
window.downloadCSV = downloadCSV;

// ─── Stats combos + mistakes ───────────────────────────────────────

async function fetchCombos() {
    try {
        const res = await fetch(`${API_BASE}/api/stats/combos`);
        if (!res.ok) return;
        const data = await res.json();
        const sec = document.getElementById('combos-section');
        const body = document.getElementById('combos-body');
        if (!sec || !body) return;
        if (!data.combos.length) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        const rows = data.combos.slice(0, 20).map(c => {
            const significant = c.total >= data.min_trades_for_significance;
            const wrClass = c.win_rate_pct >= 60 ? 'pnl-positive' : c.win_rate_pct >= 50 ? '' : 'pnl-negative';
            const pnlClass = c.total_pnl > 0 ? 'pnl-positive' : 'pnl-negative';
            return `<tr class="${significant ? '' : 'low-confidence'}">
                <td>${c.pattern}</td><td><strong>${c.pair}</strong></td>
                <td>${c.wins}W / ${c.losses}L</td><td>${c.total}</td>
                <td class="${wrClass}">${c.win_rate_pct}%</td>
                <td class="${pnlClass}">${c.total_pnl >= 0 ? '+' : ''}${c.total_pnl.toFixed(2)} USD</td>
            </tr>`;
        }).join('');
        body.innerHTML = `<table class="vol-table"><thead><tr><th>Pattern</th><th>Paire</th><th>W/L</th><th>Total</th><th>Win rate</th><th>PnL cumulé</th></tr></thead><tbody>${rows}</tbody></table>`;
    } catch (e) {}
}

async function fetchMistakes() {
    try {
        const res = await fetch(`${API_BASE}/api/stats/mistakes`);
        if (!res.ok) return;
        const data = await res.json();
        const sec = document.getElementById('mistakes-section');
        const body = document.getElementById('mistakes-body');
        if (!sec || !body) return;
        if (!data.total_trades) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        const formatBox = (label, count, avgPnl, advice) => {
            const cls = avgPnl > 0 ? 'pnl-positive' : 'pnl-negative';
            return `<div class="mistake-box">
                <div class="mistake-label">${label}</div>
                <div class="mistake-count">${count} trade(s)</div>
                <div class="mistake-pnl ${cls}">PnL moyen : ${avgPnl >= 0 ? '+' : ''}${avgPnl.toFixed(2)} USD</div>
                ${advice ? `<div class="mistake-advice">${advice}</div>` : ''}
            </div>`;
        };
        body.innerHTML = `
            <div class="mistakes-grid">
                ${formatBox('Sans checklist pré-trade', data.without_checklist.count, data.without_checklist.avg_pnl, data.without_checklist.avg_pnl < 0 ? '⚠️ Vos trades sans checklist sont perdants en moyenne. Toujours valider avant.' : '')}
                ${formatBox('Avec checklist complète', data.total_trades - data.without_checklist.count, data.with_checklist_avg_pnl, '')}
                ${formatBox('Sans SL placé dans MT5', data.without_sl_set.count, data.without_sl_set.avg_pnl, data.without_sl_set.count > 0 ? '⛔ Trader sans SL est extrêmement dangereux. Toujours cocher la case post-entry.' : '')}
                ${formatBox('Sans TP placé dans MT5', data.without_tp_set.count, data.without_tp_set.avg_pnl, '')}
            </div>
        `;
    } catch (e) {}
}

// ─── Backtest stats ────────────────────────────────────────────────

async function fetchBacktestStats() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/stats`);
        if (!res.ok) return;
        const stats = await res.json();
        _kpiUpdate('backtest', stats);
        renderBacktestStats(stats);
    } catch (err) {
        console.warn('Backtest stats error:', err);
    }
}

function renderBacktestStats(stats) {
    const container = document.getElementById('backtest-stats');
    if (!container) return;
    if (!stats.total_trades) {
        container.innerHTML = '<div class="empty-state"><p>Aucun trade enregistré pour le moment.</p><p>Les stats apparaîtront dès qu\'un signal aura été émis.</p></div>';
        return;
    }
    const winRateClass = stats.win_rate_pct >= 60 ? 'conf-high' : stats.win_rate_pct >= 50 ? 'conf-medium' : 'conf-low';
    const pairsHTML = (stats.by_pair || []).map(p => `
        <tr>
            <td><strong>${escapeHtml(p.pair)}</strong></td>
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
        el.innerHTML = '<span class="session-badge session-closed">Marché fermé</span>';
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
        // Seed du state avec les derniers ticks déjà reçus
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
        const safePair = escapeHtml(pair);
        return `
            <div class="tick-card" data-pair="${safePair}">
                <div class="tick-pair">${safePair}</div>
                <div class="tick-price" data-pair-price="${safePair}">${price}</div>
                <svg class="tick-sparkline" data-pair-spark="${safePair}" viewBox="0 0 100 30" preserveAspectRatio="none"></svg>
                <div class="tick-ts" data-pair-ts="${safePair}">${state.lastTs ? _relativeTime(state.lastTs) : '—'}</div>
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
            : `<p><strong>Aucun setup de trade actif</strong></p><p>Les recommandations d'entrée/sortie apparaîtront dès qu'un pattern sera détecté.</p>`;
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
        ? '<span class="data-badge simulated">SIMULÉ</span>'
        : '<span class="data-badge live">LIVE</span>';

    // Confidence score color
    const confColor = confScore >= 85 ? 'conf-high' : confScore >= 75 ? 'conf-medium' : 'conf-low';

    // ─── Confidence ring (SVG circular progress) ───
    // circonférence pour r=26 ≈ 163.36. Dasharray = total, dashoffset = total - rempli.
    const ringR = 26;
    const ringC = 2 * Math.PI * ringR;
    const ringDash = Math.max(0, Math.min(confScore, 100)) / 100 * ringC;
    const confRingHTML = `
        <div class="setup-confidence-ring ${confColor}" title="Score de confiance : ${confScoreInt}/100">
            <svg viewBox="0 0 64 64" class="conf-ring-svg" aria-hidden="true">
                <circle class="conf-ring-track" cx="32" cy="32" r="${ringR}" fill="none" stroke-width="5"/>
                <circle class="conf-ring-fill" cx="32" cy="32" r="${ringR}" fill="none" stroke-width="5"
                        stroke-linecap="round" transform="rotate(-90 32 32)"
                        stroke-dasharray="${ringC.toFixed(2)}" stroke-dashoffset="${(ringC - ringDash).toFixed(2)}"/>
            </svg>
            <div class="conf-ring-text">
                <span class="conf-ring-value">${confScoreInt}</span>
                <span class="conf-ring-label">/100</span>
            </div>
        </div>
    `;

    // ─── Ruban "PRENDRE" si verdict TAKE + haute conf : signal fort côté oeil ───
    const isHotTake = s.verdict_action === 'TAKE' && confScore >= 85;
    const takeRibbon = isHotTake
        ? `<div class="setup-hot-ribbon" aria-label="Setup à prendre"><span>⚡ PRENDRE</span></div>`
        : '';

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
        <div class="trade-setup ${dirClass}${isHotTake ? ' is-hot' : ''}">
            ${takeRibbon}
            <div class="setup-header">
                <div class="setup-direction ${dirClass}">
                    <span class="dir-icon">${dirIcon}</span>
                    <span class="dir-label">${dirLabel}</span>
                    <span class="setup-pair">${escapeHtml(s.pair)}</span>
                    ${simBadge}
                </div>
                ${confRingHTML}
            </div>

            <div class="setup-chart" data-chart-id="${_setupChartId(s)}"></div>

            <div class="setup-levels">
                <div class="level-box entry">
                    <div class="level-label">ENTRÉE</div>
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

            <button type="button" class="setup-explanation-toggle" data-action="toggle-explanation" aria-expanded="false">
                Voir l'analyse détaillée
            </button>
            <div class="setup-explanation">
                <div class="explanation-factors">
                    <div class="factors-title">FACTEURS DE CONFIANCE</div>
                    ${factorsHTML}
                </div>
            </div>

            <div class="setup-pattern">
                <span class="pattern-tag">${escapeHtml(_patternLabel(s.pattern?.pattern))}</span>
                <span class="pattern-desc">${escapeHtml(patternName)}</span>
            </div>

            ${_verdictBlockHTML(s)}

            ${s.guidance ? `<div class="setup-guidance">${_markdownToHtml(s.guidance)}</div>` : ''}

            <div class="setup-actions">
                <button type="button" class="btn btn-primary btn-take-signal"
                        data-action="open-trade"
                        data-pair="${escapeHtml(s.pair)}"
                        data-direction="${escapeHtml(s.direction)}"
                        data-entry="${s.entry_price}"
                        data-sl="${s.stop_loss}"
                        data-tp1="${s.take_profit_1}"
                        data-pattern="${escapeHtml(s.pattern?.pattern || '')}"
                        data-confidence="${s.confidence_score || 0}">
                    ✅ J'ai pris ce signal
                </button>
            </div>

            <div class="setup-timestamps">
                <div class="ts-entry">
                    <span class="ts-label">ENTRÉE</span>
                    <span class="ts-value">${s.entry_time ? new Date(s.entry_time).toLocaleTimeString() : time}</span>
                </div>
                <div class="ts-expiry ${_isExpired(s.expiry_time) ? 'expired' : 'active'}">
                    <span class="ts-label">${_isExpired(s.expiry_time) ? 'EXPIRÉ' : 'VALIDE JUSQU\'À'}</span>
                    <span class="ts-value">${s.expiry_time ? new Date(s.expiry_time).toLocaleTimeString() : '--:--'}</span>
                </div>
                <div class="ts-countdown" data-expiry="${s.expiry_time || ''}">
                    <span class="ts-label">TEMPS RESTANT</span>
                    <span class="ts-value countdown-value">${_countdown(s.expiry_time)}</span>
                </div>
                <div class="ts-validity">
                    <span class="ts-label">VALIDITÉ</span>
                    <span class="ts-value">${s.validity_minutes || 15} min</span>
                </div>
            </div>
        </div>`;
}

function _verdictBlockHTML(s) {
    if (!s.verdict_action) return '';
    const cls = { TAKE: 'verdict-take', WAIT: 'verdict-wait', SKIP: 'verdict-skip' }[s.verdict_action] || '';
    const icon = { TAKE: '✅', WAIT: '⏳', SKIP: '⛔' }[s.verdict_action] || '';
    const label = { TAKE: 'PRENDRE', WAIT: 'ATTENDRE', SKIP: 'PASSER' }[s.verdict_action] || s.verdict_action;
    const reasons = (s.verdict_reasons || []).map(r => `<li class="verdict-reason">👍 ${r}</li>`).join('');
    const warns = (s.verdict_warnings || []).map(w => `<li class="verdict-warn">⚠️ ${w}</li>`).join('');
    const blockers = (s.verdict_blockers || []).map(b => `<li class="verdict-block">⛔ ${b}</li>`).join('');
    return `
        <div class="verdict-block ${cls}">
            <div class="verdict-header">
                <span class="verdict-icon">${icon}</span>
                <span class="verdict-label">${label}</span>
                <span class="verdict-summary">${escapeHtml(s.verdict_summary || '')}</span>
            </div>
            ${(reasons || warns || blockers) ? `<ul class="verdict-factors">${blockers}${warns}${reasons}</ul>` : ''}
        </div>`;
}

// ─── Patterns ────────────────────────────────────────────────────────

function renderPatterns(patterns) {
    const container = document.getElementById('patterns-body');
    if (!patterns.length) {
        container.innerHTML = '<div class="empty-state"><p>Aucun pattern détecté</p></div>';
        return;
    }

    container.innerHTML = patterns.map(p => {
        const confPct = (p.confidence * 100).toFixed(0);
        const isBull = p.pattern.includes('up') || p.pattern.includes('bullish');
        const colorClass = isBull ? 'bullish' : 'bearish';

        const explanationHTML = p.explanation ? `<div class="pattern-explanation">${escapeHtml(p.explanation)}</div>` : '';
        const reliabilityHTML = p.reliability ? `<div class="pattern-reliability">${escapeHtml(p.reliability)}</div>` : '';
        const hasDetails = p.explanation || p.reliability;

        return `
            <div class="pattern-item-card ${colorClass}">
                <div class="pattern-item-header">
                    <span class="pattern-tag">${escapeHtml(_patternLabel(p.pattern))}</span>
                    <span class="pattern-conf">${confPct}%</span>
                    <span class="pattern-desc-text">${escapeHtml(p.description)}</span>
                </div>
                ${hasDetails ? `
                <button type="button" class="pattern-details-toggle" data-action="toggle-next" aria-expanded="false">Comprendre ce pattern</button>
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
                <p>Le radar scanne le marché. Les signaux apparaîtront ici.</p>
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
            Événements : ${events.map(e => `${escapeHtml(e.name || e.event_name)} (${escapeHtml(e.impact)})`).join(', ')}
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
                <span class="signal-pair">${escapeHtml(s.pair)}</span>
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
            <button type="button" class="setup-explanation-toggle" data-action="toggle-next" aria-expanded="false">Voir l'analyse détaillée</button>
            <div class="setup-explanation">
                <div class="explanation-factors">
                    <div class="factors-title">FACTEURS DE CONFIANCE</div>
                    ${sigFactorsHTML}
                </div>
            </div>` : ''}
            <div class="signal-time">${time}</div>
        </div>`;
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
                <tr><th>Paire</th><th>Niveau</th><th>Ratio</th><th>Volatilité</th></tr>
            </thead>
            <tbody>
                ${sorted.map(v => {
                    const pct = Math.min((v.volatility_ratio / maxRatio) * 100, 100);
                    return `<tr>
                        <td><strong>${escapeHtml(v.pair)}</strong></td>
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
        container.innerHTML = '<div class="empty-state"><p>Aucun événement économique</p></div>';
        return;
    }

    const impactLabels = { high: 'Fort', medium: 'Moyen', low: 'Faible' };

    container.innerHTML = events.map(e => `
        <div class="event-item">
            <span class="event-time">${escapeHtml(e.time) || '--:--'}</span>
            <span class="impact-dot ${escapeHtml(e.impact)}"></span>
            <span class="event-currency">${escapeHtml(e.currency)}</span>
            <span class="event-name">${escapeHtml(e.event_name)}</span>
            <span class="event-values">
                ${e.actual ? `R : ${escapeHtml(e.actual)}` : ''}
                ${e.forecast ? `P : ${escapeHtml(e.forecast)}` : ''}
                ${e.previous ? `Préc. : ${escapeHtml(e.previous)}` : ''}
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
    const strength = signal.signal_strength || signal.strength; // 'strong' | 'moderate' | 'weak'
    const setup = signal.trade_setup;
    const isBuy = setup && setup.direction === 'buy';
    const dir = setup ? (isBuy ? 'ACHAT' : 'VENTE') : null;
    const pair = signal.pair || '';
    const TTL = 10000;

    // Icône selon direction/force (SVG inline, pas de lib externe)
    let iconSvg;
    if (setup && isBuy) {
        iconSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17l5-5 5 5"/><path d="M7 7l5-5 5 5"/></svg>`;
    } else if (setup && !isBuy) {
        iconSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l5 5 5-5"/><path d="M7 17l5 5 5-5"/></svg>`;
    } else {
        iconSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>`;
    }

    // Détail selon le contexte : setup > message serveur > fallback
    let detailHTML = '';
    if (setup) {
        detailHTML = `
            <div class="toast-row"><span class="toast-kbd">Entry</span><span>${setup.entry_price?.toFixed(5) ?? '—'}</span></div>
            <div class="toast-row"><span class="toast-kbd">SL</span><span class="toast-sl">${setup.stop_loss?.toFixed(5) ?? '—'}</span></div>
            <div class="toast-row"><span class="toast-kbd">TP1</span><span class="toast-tp">${setup.take_profit_1?.toFixed(5) ?? '—'}</span></div>
            ${setup.risk_reward_1 ? `<div class="toast-row"><span class="toast-kbd">R:R</span><span>${setup.risk_reward_1.toFixed(1)}</span></div>` : ''}
        `;
    } else if (signal.message) {
        detailHTML = `<div class="toast-msg">${escapeHtml(signal.message)}</div>`;
    } else {
        detailHTML = `<div class="toast-msg">Signal ${_strengthLabel(strength)} détecté</div>`;
    }

    // Action CTA uniquement si un setup actionnable est joint
    const actionsHTML = setup ? `
        <div class="toast-actions">
            <button type="button" class="toast-btn toast-btn-primary"
                    data-action="open-trade"
                    data-pair="${escapeHtml(pair)}"
                    data-direction="${escapeHtml(setup.direction)}"
                    data-entry="${setup.entry_price}"
                    data-sl="${setup.stop_loss}"
                    data-tp1="${setup.take_profit_1}"
                    data-pattern="${escapeHtml(signal.pattern?.pattern || '')}"
                    data-confidence="${signal.confidence_score || 0}">
                J'ai pris ce signal
            </button>
            <button type="button" class="toast-btn" data-action="dismiss-toast">Ignorer</button>
        </div>
    ` : '';

    const toast = document.createElement('div');
    toast.className = `toast toast-${strength || 'info'}` + (setup ? ` toast-${isBuy ? 'buy' : 'sell'}` : '');
    toast.setAttribute('role', 'status');
    toast.innerHTML = `
        <div class="toast-icon">${iconSvg}</div>
        <div class="toast-body">
            <div class="toast-header">
                <span class="toast-title">${escapeHtml(pair)}${dir ? ' · ' + dir : ''}</span>
                <span class="toast-badge">${_strengthLabel(strength)}</span>
            </div>
            <div class="toast-detail">${detailHTML}</div>
            ${actionsHTML}
        </div>
        <button type="button" class="toast-close" data-action="dismiss-toast" aria-label="Fermer la notification">&times;</button>
        <div class="toast-progress" style="animation-duration: ${TTL}ms"></div>
    `;

    container.appendChild(toast);
    const dismissTimer = setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, TTL);

    // Permet à toast.dismiss-toast / toast.open-trade d'arrêter le timer
    toast._dismiss = () => { clearTimeout(dismissTimer); toast.classList.add('fade-out'); setTimeout(() => toast.remove(), 300); };
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
    let body = signal.message || 'Opportunité détectée';
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
// _isExpired, _countdown, _relativeTime sont dans ./modules/utils.js

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
                expiryEl.querySelector('.ts-label').textContent = 'EXPIRÉ';
            }
        }
    });
}

// ─── Glossaire ──────────────────────────────────────────────────────

let glossaryData = [];
let _glossaryLoaded = false;

async function fetchGlossary() {
    if (_glossaryLoaded) return;
    _glossaryLoaded = true;
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
        container.innerHTML = '<div class="empty-state"><p>Aucun terme trouvé</p></div>';
        return;
    }

    container.innerHTML = items.map(g => `
        <div class="glossary-item">
            <div class="glossary-term">
                <span class="glossary-abbr">${escapeHtml(g.term)}</span>
                <span class="glossary-full">${escapeHtml(g.full)}</span>
            </div>
            <div class="glossary-def">${escapeHtml(g.definition)}</div>
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

// ─── Event delegation (remplace les onclick inline — compatible CSP stricte) ──

function _toggleNextSibling(el) {
    if (!el.nextElementSibling) return;
    const open = el.nextElementSibling.classList.toggle('open');
    if (el.hasAttribute('aria-expanded')) el.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function _handleDelegatedClick(e) {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    switch (el.dataset.action) {
        case 'toggle-explanation': {
            const parent = el.parentElement;
            const panel = parent && parent.querySelector('.setup-explanation');
            if (panel) {
                const open = panel.classList.toggle('open');
                if (el.hasAttribute('aria-expanded')) el.setAttribute('aria-expanded', open ? 'true' : 'false');
            }
            break;
        }
        case 'toggle-next':
            _toggleNextSibling(el);
            break;
        case 'dismiss-toast': {
            const toast = el.closest('.toast');
            if (toast && typeof toast._dismiss === 'function') toast._dismiss();
            else if (toast) toast.remove();
            break;
        }
        case 'toggle-glossary': {
            const body = document.getElementById('glossary-body');
            if (!body) return;
            const open = body.classList.toggle('open');
            if (el.hasAttribute('aria-expanded')) el.setAttribute('aria-expanded', open ? 'true' : 'false');
            // Lazy-load : ne charge le glossaire qu'à la première ouverture
            if (open && !_glossaryLoaded) fetchGlossary();
            break;
        }
        case 'toggle-silent': toggleSilentMode(); break;
        case 'download-csv': downloadCSV(); break;
        case 'close-trade': {
            const id = parseInt(el.dataset.tradeId, 10);
            if (Number.isFinite(id)) openCloseModal(id);
            break;
        }
        case 'open-trade': {
            const d = el.dataset;
            openTradeModal(
                d.pair, d.direction,
                parseFloat(d.entry), parseFloat(d.sl), parseFloat(d.tp1),
                d.pattern || '',
                parseFloat(d.confidence) || 0,
            );
            break;
        }
        case 'close-trade-modal': closeTradeModal(); break;
        case 'goto-step-2': goToTradeStep2(); break;
        case 'goto-step-1': goToTradeStep1(); break;
        case 'confirm-trade': confirmTradeSubmit(); break;
        case 'close-close-modal': closeCloseModal(); break;
        case 'confirm-close-trade': confirmCloseTrade(); break;
        case 'apply-calc-size': applyCalculatedSize(); break;
    }
}

// ─── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    document.body.addEventListener('click', _handleDelegatedClick);
    const glossarySearch = document.getElementById('glossary-search-input');
    if (glossarySearch) glossarySearch.addEventListener('input', (e) => filterGlossary(e.target.value));

    fetchOverview();
    // fetchGlossary() est lazy : déclenché à la 1re ouverture du panneau (cf. _handleDelegatedClick)
    fetchTicks();
    fetchBacktestStats();
    fetchDailyStatus();
    fetchPersonalTrades();
    fetchRiskDashboard();
    fetchEquityCurve();
    fetchCombos();
    fetchMistakes();
    connectWebSocket();
    _bindFilters();
    _renderSessionMarkers();
    _updateSoundBtn();
    _updateVoiceBtn();
    document.getElementById('refresh-btn').addEventListener('click', refreshAnalysis);
    const soundBtn = document.getElementById('sound-toggle');
    if (soundBtn) soundBtn.addEventListener('click', toggleSound);
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
    const voiceBtn = document.getElementById('voice-toggle');
    if (voiceBtn) voiceBtn.addEventListener('click', toggleVoice);

    // Enregistrement best-effort du service worker (PWA app-shell offline)
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }

    // Horloge live + compteurs : mise à jour toutes les secondes
    setInterval(() => {
        _renderClock();
        _updateCountdowns();
    }, 1000);

    // Session markers : recalcul toutes les minutes
    setInterval(_renderSessionMarkers, 60000);

    // Fallback : ne poller l'overview que si le WS est tombé (sinon WS push déjà)
    setInterval(() => {
        if (!isWsConnected()) fetchOverview();
    }, POLL_FALLBACK_INTERVAL);

    // Stats non poussées par le WS : rafraîchir toutes les 60s
    setInterval(fetchBacktestStats, 60000);
    setInterval(() => {
        fetchDailyStatus();
        fetchPersonalTrades();
        fetchRiskDashboard();
        fetchEquityCurve();
        fetchCombos();
        fetchMistakes();
    }, 60000);

    // Bougies live des paires principales — first fetch + refresh 60s
    fetchLiveCharts();
    setInterval(fetchLiveCharts, 60000);
});

// ─── KPI row (barre résumé en haut du dashboard) ─────────────────

const _kpiState = { daily: null, risk: null, backtest: null };

/** Update incrémental : chaque fetch pousse sa slice puis render global. */
function _kpiUpdate(key, data) {
    _kpiState[key] = data;
    _renderKpi();
}

function _renderKpi() {
    const { daily, risk, backtest } = _kpiState;
    const $ = (id) => document.getElementById(id);

    // ─── PnL du jour (bipolaire) ───
    if (daily) {
        const pnl = daily.pnl_today || 0;
        const pnlPct = daily.pnl_pct || 0;
        const limit = daily.daily_loss_limit_pct || 2;
        const sign = pnl >= 0 ? '+' : '';
        $('kpi-pnl').textContent = `${sign}${pnl.toFixed(2)} $`;
        $('kpi-pnl').className = 'text-[26px] leading-tight font-bold font-mono tabular-nums ' +
            (pnl > 0 ? 'text-buy' : pnl < 0 ? 'text-sell' : 'text-foreground');
        $('kpi-pnl-delta').textContent = `${sign}${pnlPct.toFixed(2)} % · ${daily.n_trades_today || 0} trade(s)`;
        $('kpi-pnl-min').textContent = `−${limit}%`;
        $('kpi-pnl-max').textContent = `+${limit}%`;

        // Fill : position et largeur selon valeur clampée à ±limit
        const gauge = document.querySelector('[data-gauge="pnl"]');
        const fill = gauge?.querySelector('.kpi-gauge-fill');
        if (fill) {
            const clamped = Math.max(-limit, Math.min(limit, pnlPct));
            const widthPct = Math.abs(clamped) / limit * 50;
            if (clamped >= 0) {
                fill.style.left = '50%';
                fill.style.right = 'auto';
                fill.style.width = `${widthPct}%`;
            } else {
                fill.style.right = '50%';
                fill.style.left = 'auto';
                fill.style.width = `${widthPct}%`;
            }
            gauge.classList.toggle('negative', clamped < 0);
        }
    }

    // ─── Trades (unipolaire 0 → 10) ───
    if (daily) {
        const n = daily.n_trades_today || 0;
        const nOpen = daily.n_open || 0;
        $('kpi-trades').textContent = `${n}`;
        $('kpi-trades-delta').textContent = nOpen > 0 ? `${nOpen} ouvert(s)` : 'aucun ouvert';
        const gauge = document.querySelector('[data-gauge="trades"]');
        const fill = gauge?.querySelector('.kpi-gauge-fill');
        if (fill) fill.style.width = `${Math.min(100, (n / 10) * 100)}%`;
    }

    // ─── Win rate backtest (0 → 100%) ───
    if (backtest) {
        const wr = backtest.win_rate_pct ?? 0;
        $('kpi-winrate').textContent = `${wr.toFixed(0)} %`;
        $('kpi-winrate').className = 'text-[26px] leading-tight font-bold font-mono tabular-nums ' +
            (wr >= 60 ? 'text-buy' : wr >= 50 ? 'text-foreground' : 'text-sell');
        $('kpi-winrate-delta').textContent = `${backtest.closed_trades || 0} trades fermés`;
        const gauge = document.querySelector('[data-gauge="winrate"]');
        const fill = gauge?.querySelector('.kpi-gauge-fill');
        if (fill) {
            fill.style.width = `${Math.max(0, Math.min(100, wr))}%`;
            gauge.classList.toggle('warn', wr >= 50 && wr < 60);
            gauge.classList.toggle('danger', wr < 50);
        }
    }

    // ─── Risque ouvert (0 → 3%, danger ≥ 3) ───
    if (risk) {
        const pct = risk.total_risk_pct || 0;
        const usd = risk.total_risk_usd || 0;
        $('kpi-risk').textContent = `${pct.toFixed(2)} %`;
        $('kpi-risk').className = 'text-[26px] leading-tight font-bold font-mono tabular-nums ' +
            (pct >= 3 ? 'text-sell' : pct >= 2 ? 'text-foreground' : 'text-foreground');
        $('kpi-risk-delta').textContent = `${usd.toFixed(0)} $ · ${risk.n_open || 0} position(s)`;
        const gauge = document.querySelector('[data-gauge="risk"]');
        const fill = gauge?.querySelector('.kpi-gauge-fill');
        if (fill) {
            fill.style.width = `${Math.max(0, Math.min(100, pct / 3 * 100))}%`;
            gauge.classList.toggle('warn', pct >= 2 && pct < 3);
            gauge.classList.toggle('danger', pct >= 3);
        }
    }
}

// ─── Bougies live (indépendant des setups) ──────────────────────────

const _liveCharts = new Map(); // pair -> { chart, series }
const _LIVE_CHART_PAIRS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'USD/CAD'];

async function fetchLiveCharts() {
    try {
        const res = await fetch(`${API_BASE}/api/candles`);
        if (!res.ok) return;
        const allByPair = await res.json();
        renderLiveCharts(allByPair);
    } catch (err) {
        console.warn('fetchLiveCharts:', err);
    }
}

function renderLiveCharts(allByPair) {
    const grid = document.getElementById('live-charts-grid');
    if (!grid || typeof LightweightCharts === 'undefined') return;

    // Ne garder que les paires de la watchlist ET qui ont au moins 5 bougies
    const pairs = _LIVE_CHART_PAIRS.filter(p => Array.isArray(allByPair[p]) && allByPair[p].length >= 5);
    if (!pairs.length) {
        grid.innerHTML = '<div class="empty-state"><p>Aucune bougie disponible pour le moment.</p></div>';
        return;
    }

    // Premier rendu : construire les conteneurs + monter les charts
    if (grid.querySelector('.empty-state') || grid.children.length === 0) {
        grid.innerHTML = pairs.map(p => `
            <div class="live-chart-card" data-pair="${escapeHtml(p)}">
                <div class="live-chart-header">
                    <span class="live-chart-pair">${escapeHtml(p)}</span>
                    <span class="live-chart-last" data-last="${escapeHtml(p)}"></span>
                </div>
                <div class="live-chart-body" data-chart-host="${escapeHtml(p)}"></div>
            </div>
        `).join('');
        pairs.forEach(p => _mountOrUpdateLiveChart(p, allByPair[p]));
        return;
    }

    // Mise à jour incrémentale : setData sur les séries existantes
    pairs.forEach(p => _mountOrUpdateLiveChart(p, allByPair[p]));
}

function _mountOrUpdateLiveChart(pair, candles) {
    const host = document.querySelector(`[data-chart-host="${CSS.escape(pair)}"]`);
    if (!host) return;
    const data = candles.map(c => ({
        time: Math.floor(new Date(c.timestamp).getTime() / 1000),
        open: c.open, high: c.high, low: c.low, close: c.close,
    }));
    const lastClose = data[data.length - 1]?.close;
    const firstClose = data[0]?.close;
    const lastEl = document.querySelector(`[data-last="${CSS.escape(pair)}"]`);
    if (lastEl && lastClose !== undefined) {
        const changePct = firstClose ? ((lastClose - firstClose) / firstClose * 100) : 0;
        const sign = changePct >= 0 ? '+' : '';
        lastEl.textContent = `${lastClose.toFixed(pair.includes('JPY') ? 3 : 5)}  ${sign}${changePct.toFixed(2)}%`;
        lastEl.classList.toggle('up', changePct > 0);
        lastEl.classList.toggle('down', changePct < 0);
    }

    let entry = _liveCharts.get(pair);
    if (!entry) {
        const chart = LightweightCharts.createChart(host, {
            width: host.clientWidth,
            height: 140,
            layout: { background: { color: 'transparent' }, textColor: '#8b949e', fontSize: 10 },
            grid: { vertLines: { color: 'rgba(30, 38, 54, 0.6)' }, horzLines: { color: 'rgba(30, 38, 54, 0.6)' } },
            rightPriceScale: { borderColor: 'rgba(30, 38, 54, 0.6)' },
            timeScale: { borderColor: 'rgba(30, 38, 54, 0.6)', timeVisible: true, secondsVisible: false },
            handleScale: false,
            handleScroll: false,
        });
        const series = chart.addCandlestickSeries({
            upColor: '#00ffa3', downColor: '#ff4976', borderVisible: false,
            wickUpColor: '#00ffa3', wickDownColor: '#ff4976',
        });
        entry = { chart, series };
        _liveCharts.set(pair, entry);
        // Ajuster la taille quand la fenêtre bouge (debounce simple)
        const ro = new ResizeObserver(() => chart.resize(host.clientWidth, 140));
        ro.observe(host);
    }
    entry.series.setData(data);
    entry.chart.timeScale().fitContent();
}
