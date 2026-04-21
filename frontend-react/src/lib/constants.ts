/** Filtre de date pour /api/insights/performance : exclut les trades
 *  pré-fix prix (bug prix fantôme corrigé le 2026-04-20 ~21h UTC). */
export const POST_FIX_CUTOFF = '2026-04-20T21:14:00+00:00';

/** Seuil minimum d'affichage d'un setup dans la grille (UI only). */
export const UI_MIN_CONFIDENCE = 50;
