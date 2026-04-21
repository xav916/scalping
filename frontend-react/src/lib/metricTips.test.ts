import { describe, it, expect } from 'vitest';
import { TIPS } from './metricTips';

/** Le catalogue de tips est critique : si une clé manque ou change de nom,
 *  des tooltips dans l'UI peuvent afficher `undefined`. Ces tests verrouillent
 *  la présence des clés essentielles. */
describe('TIPS catalog', () => {
  it('contient toutes les sections attendues', () => {
    const expectedSections = [
      'header',
      'killSwitch',
      'alerts',
      'today',
      'capital',
      'repartition',
      'fearGreed',
      'sante',
      'drift',
      'cot',
      'events',
      'trade',
      'setup',
      'macro',
      'session',
      'perf',
      'equity',
      'period',
      'analytics',
      'mistakes',
      'combos',
    ];
    for (const section of expectedSections) {
      expect(TIPS).toHaveProperty(section);
    }
  });

  it('toutes les tips sont des strings non vides', () => {
    const walk = (obj: Record<string, unknown>, path: string[] = []) => {
      for (const [k, v] of Object.entries(obj)) {
        const currentPath = [...path, k];
        if (typeof v === 'string') {
          expect(v.length, `${currentPath.join('.')} ne doit pas être vide`).toBeGreaterThan(0);
        } else if (typeof v === 'object' && v !== null) {
          walk(v as Record<string, unknown>, currentPath);
        }
      }
    };
    walk(TIPS as unknown as Record<string, unknown>);
  });

  it('les tips header couvrent tous les états WebSocket', () => {
    expect(TIPS.header.statusLive).toBeTruthy();
    expect(TIPS.header.statusPoll).toBeTruthy();
    expect(TIPS.header.statusSync).toBeTruthy();
    expect(TIPS.header.statusDown).toBeTruthy();
    expect(TIPS.header.statusUnknown).toBeTruthy();
  });

  it('les tips fearGreed couvrent les 5 classifications', () => {
    expect(TIPS.fearGreed.extreme_fear).toBeTruthy();
    expect(TIPS.fearGreed.fear).toBeTruthy();
    expect(TIPS.fearGreed.neutral).toBeTruthy();
    expect(TIPS.fearGreed.greed).toBeTruthy();
    expect(TIPS.fearGreed.extreme_greed).toBeTruthy();
  });

  it('les tips period couvrent les 5 tabs', () => {
    expect(TIPS.period.tabDay).toBeTruthy();
    expect(TIPS.period.tabWeek).toBeTruthy();
    expect(TIPS.period.tabMonth).toBeTruthy();
    expect(TIPS.period.tabYear).toBeTruthy();
    expect(TIPS.period.tabAll).toBeTruthy();
  });

  it('les acronymes clés sont développés dans les tips', () => {
    // Chaque tip critique doit au moins une fois contenir la définition
    expect(TIPS.today.pnlJour.toLowerCase()).toContain('profit and loss');
    expect(TIPS.trade.stopLoss.toLowerCase()).toContain('stop loss');
    expect(TIPS.trade.takeProfit.toLowerCase()).toContain('take profit');
    expect(TIPS.macro.vix.toLowerCase()).toContain('volatility');
    expect(TIPS.cot.titre.toLowerCase()).toContain('commitments of traders');
  });
});
