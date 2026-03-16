/**
 * Scalping Radar - Frontend Application
 * Real-time dashboard for scalping signal detection
 */

const API_BASE = window.location.origin;
const WS_URL = `ws://${window.location.host}/ws`;

let ws = null;
let reconnectTimer = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;

// ─── WebSocket Connection ────────────────────────────────────────────

function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        setConnectionStatus(true);

        // Keep alive ping
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
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

    ws.onerror = () => {
        setConnectionStatus(false);
    };
}

function scheduleReconnect() {
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
    reconnectAttempts++;
    console.log(`Reconnecting in ${delay}ms...`);
    reconnectTimer = setTimeout(connectWebSocket, delay);
}

function setConnectionStatus(connected) {
    const indicator = document.getElementById('status-indicator');
    const statusText = document.getElementById('status-text');
    if (connected) {
        indicator.classList.remove('disconnected');
        statusText.textContent = 'Live';
    } else {
        indicator.classList.add('disconnected');
        statusText.textContent = 'Disconnected';
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

// ─── API Calls ───────────────────────────────────────────────────────

async function fetchOverview() {
    try {
        const res = await fetch(`${API_BASE}/api/overview`);
        if (res.status === 202) {
            // Still loading
            setTimeout(fetchOverview, 3000);
            return;
        }
        const data = await res.json();
        renderFullDashboard(data);
    } catch (err) {
        console.error('Failed to fetch overview:', err);
    }
}

async function refreshAnalysis() {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.textContent = 'Analyzing...';
    try {
        await fetch(`${API_BASE}/api/refresh`, { method: 'POST' });
        setTimeout(() => {
            fetchOverview();
            btn.disabled = false;
            btn.textContent = 'Refresh';
        }, 2000);
    } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Refresh';
    }
}

// ─── Rendering ───────────────────────────────────────────────────────

function renderFullDashboard(data) {
    renderSignals(data.signals || []);
    renderVolatility(data.volatility_data || []);
    renderEvents(data.economic_events || []);
    renderTrends(data.trends || []);
    updateLastUpdate(data.last_update);
}

function updateDashboard(data) {
    if (data.volatility) renderVolatilityFromRaw(data.volatility);
    if (data.events) renderEventsFromRaw(data.events);
    if (data.trends) renderTrendsFromRaw(data.trends);
    if (data.last_update) updateLastUpdate(data.last_update);
}

function renderSignals(signals) {
    const container = document.getElementById('signals-list');
    if (!signals.length) {
        container.innerHTML = `
            <div class="empty-state">
                <p><strong>No active signals</strong></p>
                <p>The radar is scanning the market. Signals will appear here when opportunities are detected.</p>
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

    // Keep max 20 visible
    const cards = container.querySelectorAll('.signal-card');
    if (cards.length > 20) {
        cards[cards.length - 1].remove();
    }
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

    let eventsHTML = '';
    if (events.length) {
        eventsHTML = `<div style="margin-top:4px;font-size:12px;color:var(--accent-yellow)">
            Events: ${events.map(e => `${e.name || e.event_name} (${e.impact})`).join(', ')}
        </div>`;
    }

    return `
        <div class="signal-card ${strength}">
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="signal-pair">${s.pair}</span>
                <span class="signal-badge ${strength}">${strength}</span>
                <span class="level-tag ${volLevel}">vol ${volRatio.toFixed(1)}x</span>
            </div>
            <div class="signal-details">
                ${trendDir.toUpperCase()} trend (${(trendStr * 100).toFixed(0)}% strength) |
                Volatility: ${volLevel}
            </div>
            ${eventsHTML}
            ${msg ? `<div class="signal-details" style="margin-top:4px">${msg}</div>` : ''}
            <div class="signal-time">${time}</div>
        </div>`;
}

function renderVolatility(volData) {
    const container = document.getElementById('volatility-body');
    if (!volData.length) {
        container.innerHTML = '<div class="empty-state"><p>Loading volatility data...</p></div>';
        return;
    }

    const sorted = [...volData].sort((a, b) => b.volatility_ratio - a.volatility_ratio);
    const maxRatio = Math.max(...sorted.map(v => v.volatility_ratio), 2);

    container.innerHTML = `
        <table class="vol-table">
            <thead>
                <tr><th>Pair</th><th>Level</th><th>Ratio</th><th>Volatility</th></tr>
            </thead>
            <tbody>
                ${sorted.map(v => {
                    const pct = Math.min((v.volatility_ratio / maxRatio) * 100, 100);
                    return `<tr>
                        <td><strong>${v.pair}</strong></td>
                        <td><span class="level-tag ${v.level}">${v.level}</span></td>
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

function renderVolatilityFromRaw(rawData) {
    renderVolatility(rawData);
}

function renderEvents(events) {
    const container = document.getElementById('events-body');
    if (!events.length) {
        container.innerHTML = '<div class="empty-state"><p>No economic events today</p></div>';
        return;
    }

    container.innerHTML = events.map(e => `
        <div class="event-item">
            <span class="event-time">${e.time || '--:--'}</span>
            <span class="impact-dot ${e.impact}"></span>
            <span class="event-currency">${e.currency}</span>
            <span class="event-name">${e.event_name}</span>
            <span class="event-values">
                ${e.actual ? `A: ${e.actual}` : ''}
                ${e.forecast ? `F: ${e.forecast}` : ''}
                ${e.previous ? `P: ${e.previous}` : ''}
            </span>
        </div>
    `).join('');
}

function renderEventsFromRaw(rawEvents) {
    renderEvents(rawEvents);
}

function renderTrends(trends) {
    // Trends are shown within signals context, but we can add a subtle indicator
    const trendInfo = document.getElementById('trend-info');
    if (!trendInfo) return;

    if (!trends.length) {
        trendInfo.textContent = '';
        return;
    }

    const strong = trends.filter(t => t.strength >= 0.7);
    if (strong.length) {
        trendInfo.textContent = `${strong.length} strong trend(s) detected`;
    } else {
        trendInfo.textContent = 'No strong trends currently';
    }
}

function renderTrendsFromRaw(rawTrends) {
    renderTrends(rawTrends);
}

function updateLastUpdate(timestamp) {
    const el = document.getElementById('last-update');
    if (el && timestamp) {
        const time = new Date(timestamp).toLocaleTimeString();
        el.textContent = `Last update: ${time}`;
    }
}

// ─── Toast Notifications ─────────────────────────────────────────────

function showToast(signal) {
    const container = document.getElementById('toast-container');
    const strength = signal.signal_strength || signal.strength;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
        <div class="toast-title">Scalping Signal: ${signal.pair}</div>
        <div class="toast-body">${signal.message || `${strength} signal detected`}</div>
    `;

    container.appendChild(toast);

    // Auto-remove after 8s
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 8000);
}

// ─── Browser Notifications ───────────────────────────────────────────

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
    const strength = signal.signal_strength || signal.strength;
    new Notification(`Scalping Signal: ${signal.pair}`, {
        body: signal.message || `${strength} opportunity detected`,
        icon: '/favicon.ico',
        tag: `scalp-${signal.pair}`,
        requireInteraction: true,
    });
}

// ─── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Request notification permission early
    if ('Notification' in window && Notification.permission === 'default') {
        // Will ask on first signal
    }

    // Initial data fetch
    fetchOverview();

    // Connect WebSocket for real-time updates
    connectWebSocket();

    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', refreshAnalysis);
});
