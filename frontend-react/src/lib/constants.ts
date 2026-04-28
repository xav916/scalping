/** Filtre de date pour /api/insights/performance : exclut les trades
 *  pré-fix prix (bug prix fantôme corrigé le 2026-04-20 ~21h UTC). */
export const POST_FIX_CUTOFF = '2026-04-20T21:14:00+00:00';

/** Seuil minimum d'affichage d'un setup dans la grille (UI only). */
export const UI_MIN_CONFIDENCE = 50;

/** Stars du portefeuille V2 — affichées sur le cockpit (home par défaut).
 *  Les 4 paires "live" ont des candles côté Twelve Data. XLI/XLK existent
 *  dans le shadow log mais pas dans les feeds standards. */
export const STAR_PAIRS_LIVE = [
  'XAU/USD',
  'XAG/USD',
  'WTI/USD',
  'ETH/USD',
] as const;

export const STAR_PAIRS_FULL = [
  ...STAR_PAIRS_LIVE,
  'XLI',
  'XLK',
] as const;

/** Anciens supports V1 (avant pivot stars-only du 2026-04-26).
 *  Cantonnés à la page admin /v2/v1-legacy. */
export const V1_LEGACY_PAIRS = [
  'EUR/USD',
  'GBP/USD',
  'USD/JPY',
  'EUR/GBP',
  'USD/CHF',
  'AUD/USD',
  'USD/CAD',
  'EUR/JPY',
  'GBP/JPY',
  'BTC/USD',
  'SPX',
  'NDX',
] as const;
