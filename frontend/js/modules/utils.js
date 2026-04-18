/**
 * Helpers purs, sans dépendance ni état partagé.
 * Extraits depuis app.js pour pouvoir être testés indépendamment.
 */

/** Échappe une valeur dynamique avant insertion via innerHTML. */
export function escapeHtml(v) {
    if (v === null || v === undefined) return '';
    return String(v)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Libellé humain à partir d'un strength enum. */
export function strengthLabel(s) {
    return { strong: 'FORT', moderate: 'MODÉRÉ', weak: 'FAIBLE' }[s] || s;
}

/** Libellé humain pour un pattern technique. */
export function patternLabel(pattern) {
    const labels = {
        'breakout_up': 'Cassure Résistance',
        'breakout_down': 'Cassure Support',
        'momentum_up': 'Momentum Haussier',
        'momentum_down': 'Momentum Baissier',
        'range_bounce_up': 'Rebond Support',
        'range_bounce_down': 'Rejet Résistance',
        'mean_reversion_up': 'Retour Moyenne',
        'mean_reversion_down': 'Retour Moyenne',
        'engulfing_bullish': 'Englobante Haussière',
        'engulfing_bearish': 'Englobante Baissière',
        'pin_bar_up': 'Pin Bar Haussière',
        'pin_bar_down': 'Pin Bar Baissière',
    };
    return labels[pattern] || pattern || '';
}

/** Mini-parseur markdown → HTML (gras, italique, paragraphes, code inline). */
export function markdownToHtml(text) {
    if (!text) return '';
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return esc(text)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>');
}

/** Vrai si l'ISO timestamp est déjà passé. */
export function isExpired(expiryTime) {
    if (!expiryTime) return false;
    return new Date() > new Date(expiryTime);
}

/** Mini-compteur de temps restant au format "M:SS" (ou 'EXPIRÉ'). */
export function countdown(expiryTime) {
    if (!expiryTime) return '--:--';
    const diff = new Date(expiryTime) - new Date();
    if (diff <= 0) return 'EXPIRÉ';
    const min = Math.floor(diff / 60000);
    const sec = Math.floor((diff % 60000) / 1000);
    return `${min}:${sec.toString().padStart(2, '0')}`;
}

/** Durée humaine relative ("maintenant", "il y a 12s", "il y a 3min"). */
export function relativeTime(isoTs) {
    const sec = Math.max(0, Math.floor((Date.now() - new Date(isoTs)) / 1000));
    if (sec < 2) return 'maintenant';
    if (sec < 60) return `il y a ${sec}s`;
    return `il y a ${Math.floor(sec / 60)}min`;
}
