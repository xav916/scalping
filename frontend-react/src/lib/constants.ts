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

/** Candidats en observation shadow log (pas encore tradés en live).
 *  Visibles dans la page /v2/candidates avec leurs stats shadow. */
export const CANDIDATE_SYSTEMS = [
  {
    pair: 'XLI',
    system_id: 'V2_TIGHT_LONG_XLI_1D',
    tf: '1d',
    filter: 'V2_TIGHT_LONG',
    rationale:
      'Industrial sector US — driver manufacturing PMI / cycle économique. Mean PF 2.14 sur scan systématique J1, Sharpe 12M 2.74.',
  },
  {
    pair: 'XLK',
    system_id: 'V2_WTI_OPTIMAL_XLK_1D',
    tf: '1d',
    filter: 'V2_WTI_OPTIMAL',
    rationale:
      'Tech sector US — driver earnings tech / AI cycle. Mean PF 1.69, Sharpe 12M 1.01.',
  },
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
