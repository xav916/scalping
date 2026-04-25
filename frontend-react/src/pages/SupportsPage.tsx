import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Header } from '@/components/layout/Header';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';

interface SupportData {
  symbol: string;
  name: string;
  flag: string;
  economicRole: string;
  driver: string;
  whyItWorks: string;
  whenItStruggles: string;
  // Backtest 6 ans
  pfCumulative: number;
  pfPeriods: { window: string; pf: number; n: number }[];
  sharpe24m: number;
  maxDd24m: number;
  setupsPerMonth: number;
  // Risque
  recommendedSizing: string;
  warningLevel: 'low' | 'medium' | 'high';
}

const SUPPORTS: SupportData[] = [
  {
    symbol: 'XAU/USD',
    name: 'Or vs Dollar US',
    flag: '🥇',
    economicRole: 'Real yields proxy + safe haven structurel',
    driver: 'Inverse aux taux réels US 10Y, force du dollar, flight-to-safety en stress equity',
    whyItWorks: "L'or a une mécanique macro stable dans tous les régimes. Quand les real yields baissent, l'or rallye (coût d'opportunité réduit). Quand le dollar s'affaiblit, l'or monte (priced in USD). Quand l'equity stresse, l'or attire les capitaux. Ces 3 mécanismes se déclenchent à des moments différents → edge persistant cross-régime.",
    whenItStruggles: "Régime de hausse simultanée des real yields + dollar fort + equity bull market parfait (rare). Période 2022 H2 (Fed hawkish + DXY fort) a été le pire sous-régime pour l'or, mais le système est resté positif sur l'année cumulée.",
    pfCumulative: 1.33,
    pfPeriods: [
      { window: '2020-2024 (4 ans pré-bull)', pf: 1.26, n: 837 },
      { window: '2024-2026 (2 ans bull)', pf: 1.41, n: 601 },
      { window: 'Cumul 6 ans', pf: 1.33, n: 1438 },
    ],
    sharpe24m: 1.59,
    maxDd24m: 20.0,
    setupsPerMonth: 25,
    recommendedSizing: '0.5% risk/trade (capital virtuel 10k€ en Phase 4)',
    warningLevel: 'low',
  },
  {
    symbol: 'XAG/USD',
    name: 'Argent vs Dollar US',
    flag: '🥈',
    economicRole: 'Gold-correlated + industrial demand + speculative beta',
    driver: 'Suit XAU avec amplification (~2x volatilité) + composante industrielle (demande solaire, électronique, soldering)',
    whyItWorks: "L'argent profite des mêmes mécaniques que l'or, amplifiées. En bull cycle métaux, XAG sur-performe (PF 1.59 sur 24M vs 1.41 XAU). Les patterns LONG capture cette amplification cyclique.",
    whenItStruggles: "L'argent est plus volatile et plus dépendant du cycle économique. En marché calme, les setups V2_CORE_LONG sur XAG sous-performent (PF 1.16 sur 4 ans pré-bull vs 1.26 pour XAU). MaxDD 124% sur 6 ans = sizing prudent obligatoire.",
    pfCumulative: 1.34,
    pfPeriods: [
      { window: '2020-2024 (4 ans pré-bull)', pf: 1.16, n: 870 },
      { window: '2024-2026 (2 ans bull)', pf: 1.59, n: 546 },
      { window: 'Cumul 6 ans', pf: 1.34, n: 1416 },
    ],
    sharpe24m: 1.55,
    maxDd24m: 25.7,
    setupsPerMonth: 23,
    recommendedSizing: '0.3% risk/trade (sizing réduit vs XAU vu maxDD 6y plus élevé)',
    warningLevel: 'medium',
  },
  {
    symbol: 'WTI/USD',
    name: 'Pétrole brut WTI vs Dollar US',
    flag: '🛢️',
    economicRole: 'USD-priced commodity + geopolitical hedge + inflation proxy',
    driver: 'OPEC+ supply decisions, sanctions Iran/Russie, demande mondiale, USD inverse, événements politiques',
    whyItWorks: "Le pétrole fait beaucoup de range trading entre niveaux OPEC implicites (75-90 USD typique). Les rebonds depuis support sont productifs (range_bounce_up PF 1.25). Productif aussi sur momentum continuations claires (momentum_up PF 1.21). Tient cross-régime sur 5.5 ans incluant choc Ukraine 2022 et tensions Iran 2024-26.",
    whenItStruggles: "Driver politique imprévu : annonces OPEC surprise, sanctions inattendues, gaps sur news geopolitical. Les BREAKOUTS sont TOXIQUES sur WTI (PF 0.73 vs 1.84 sur XAU) — souvent fausses cassures qui se reversent. Les SHORTs perdent (PF 0.74) → LONG only. Driver imprévisible = fat tail risk non capturé en backtest.",
    pfCumulative: 1.20,
    pfPeriods: [
      { window: '2020-10 → 2024-04 (3.5 ans pré-bull)', pf: 1.20, n: 979 },
      { window: '2024-04 → 2026-04 (2 ans récent)', pf: 1.20, n: 612 },
      { window: 'Cumul 5.5 ans (max dispo)', pf: 1.20, n: 1593 },
    ],
    sharpe24m: 0,  // pas calculé sur sample limité
    maxDd24m: 104,
    setupsPerMonth: 24,
    recommendedSizing: '0.3% risk/trade (filter SPÉCIFIQUE V2_WTI_OPTIMAL ≠ V2_CORE_LONG : range_bounce_up à la place de breakout_up)',
    warningLevel: 'medium',
  },
];

const PATTERNS_RETAINED = [
  {
    name: 'momentum_up',
    desc: "Bougie haussière forte (close proche du high) après une suite de bougies neutres ou baissières. Capture le début de continuation directionnelle.",
    pfXAU: '1.36 (12M) / 1.22 (24M) / 1.33 (6 ans)',
    pfXAG: '2.93 (12M) / 2.09 (24M) — pattern superstar XAG bull cycle',
    triggers: 'Close > open + 0.6×bar_range, ATR-based body',
  },
  {
    name: 'engulfing_bullish',
    desc: 'Bougie haussière dont le corps englobe entièrement la bougie précédente baissière. Signal de retournement / continuation.',
    pfXAU: '1.72 (12M) / 1.68 (24M) — robuste cross-période',
    pfXAG: '1.14 (12M) — moins fort sur XAG mais positif',
    triggers: 'Body[-1] > Body[-2] AND open[-1] < close[-2] AND close[-1] > open[-2]',
  },
  {
    name: 'breakout_up',
    desc: "Cassure d'un range / résistance récente avec momentum. Capture le début d'un mouvement directionnel après accumulation.",
    pfXAU: '2.25 (12M) / 1.84 (24M) / 1.11 (4 ans pré-bull)',
    pfXAG: '1.21 (12M) — productif en bull cycle',
    triggers: 'Close > max(highs[-N:]) avec N=20, ATR-based stops',
  },
];

const REJECTED_EXPERIMENTS = [
  { name: 'V2_EXT (4 patterns + pin_bar_up)', verdict: '-0.04 à -0.09 PF — pin_bar_up dilue les top patterns' },
  { name: 'V2_TIGHT (2 patterns sans breakout_up)', verdict: '-0.10 à -0.15 PF en bull cycle (asymétrique)' },
  { name: 'Filtre macro régime-fixe', verdict: '+0.47 PF sur 24M mais -0.50 PF en pré-bull = régime-spécifique' },
  { name: 'Filtre macro walk-forward (refit mensuel)', verdict: '-0.34 PF — sur-fit au noise mensuel' },
  { name: 'V2_ADAPTIVE (TIGHT/CORE selon régime)', verdict: '-0.02 PF — détecteur DXY+TNX trop crude' },
  { name: 'Cross-asset SPX/NDX H4', verdict: 'PF 0.23-0.73 — gaps overnight cassent les patterns' },
  { name: 'Forex 9 paires', verdict: 'PF 0.6-0.99 sur tous les timeframes — pas d\'edge structurel' },
];

function WarningBadge({ level }: { level: SupportData['warningLevel'] }) {
  const colors = {
    low: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    medium: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
    high: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
  };
  const labels = { low: 'Risque faible', medium: 'Risque modéré', high: 'Risque élevé' };
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded-full border', colors[level])}>
      {labels[level]}
    </span>
  );
}

export function SupportsPage() {
  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1400px] mx-auto space-y-6">
        {/* Header */}
        <div>
          <Link
            to="/dashboard"
            className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1 mb-1"
          >
            ← Dashboard
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">Supports & Système V2_CORE_LONG</h1>
          <p className="text-sm text-white/50 mt-1">
            Toutes les informations retenues sur les supports analysés et le système identifié — issu de 31 expériences de recherche sur 6 ans de data.
          </p>
        </div>

        {/* Synthèse globale */}
        <GlassCard className="p-5">
          <h2 className="text-lg font-semibold mb-3">Synthèse système · 3 candidats retenus</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <div className="text-xs text-white/50 uppercase">Méthodologie</div>
              <div className="font-medium mt-1">Pattern detection LONG only</div>
              <div className="text-xs text-white/40 mt-1">Filter par asset (CORE pour XAU/XAG, OPTIMAL pour WTI)</div>
            </div>
            <div>
              <div className="text-xs text-white/50 uppercase">Timeframe</div>
              <div className="font-medium mt-1">H4 (4 heures)</div>
              <div className="text-xs text-white/40 mt-1">Aggregé depuis H1 buckets 00/04/08/12/16/20 UTC</div>
            </div>
            <div>
              <div className="text-xs text-white/50 uppercase">Validation backtest</div>
              <div className="font-medium mt-1">5.5-6 ans cross-régime</div>
              <div className="text-xs text-white/40 mt-1">COVID + bear 2022 + Ukraine + bull 2024-26</div>
            </div>
            <div>
              <div className="text-xs text-white/50 uppercase">PF cumul</div>
              <div className="font-medium mt-1 text-emerald-400">1.33 (XAU) / 1.34 (XAG) / 1.20 (WTI)</div>
              <div className="text-xs text-white/40 mt-1">3 actifs validés (sur 15 testés)</div>
            </div>
          </div>
        </GlassCard>

        {/* Cards par support */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {SUPPORTS.map((s) => (
            <GlassCard key={s.symbol} className="p-5 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-3xl">{s.flag}</span>
                    <div>
                      <h3 className="text-xl font-semibold">{s.symbol}</h3>
                      <div className="text-xs text-white/50">{s.name}</div>
                    </div>
                  </div>
                </div>
                <WarningBadge level={s.warningLevel} />
              </div>

              <div className="space-y-2 text-sm">
                <div>
                  <div className="text-xs text-white/50 uppercase mb-0.5">Rôle économique</div>
                  <div className="text-white/80">{s.economicRole}</div>
                </div>
                <div>
                  <div className="text-xs text-white/50 uppercase mb-0.5">Drivers</div>
                  <div className="text-white/70 text-sm">{s.driver}</div>
                </div>
              </div>

              <div className="bg-white/5 rounded-lg p-3 space-y-2 text-xs">
                <div>
                  <div className="text-emerald-400 font-medium uppercase">Pourquoi ça marche</div>
                  <div className="text-white/70 mt-1">{s.whyItWorks}</div>
                </div>
                <div>
                  <div className="text-amber-400 font-medium uppercase">Quand ça galère</div>
                  <div className="text-white/70 mt-1">{s.whenItStruggles}</div>
                </div>
              </div>

              {/* PF par période */}
              <div>
                <div className="text-xs text-white/50 uppercase mb-2">Profit Factor par période</div>
                <table className="w-full text-xs">
                  <thead className="text-white/40">
                    <tr>
                      <th className="text-left font-medium pb-1">Fenêtre</th>
                      <th className="text-right font-medium pb-1">PF</th>
                      <th className="text-right font-medium pb-1">N trades</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.pfPeriods.map((p) => (
                      <tr key={p.window} className="border-t border-white/5">
                        <td className="py-1.5 text-white/70">{p.window}</td>
                        <td className={clsx('py-1.5 text-right tabular-nums font-medium',
                          p.pf >= 1.30 ? 'text-emerald-400' : p.pf >= 1.15 ? 'text-amber-400' : 'text-rose-400/80')}>
                          {p.pf.toFixed(2)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-white/50">{p.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Cibles risk-adjusted */}
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-white/5 rounded-lg p-2">
                  <div className="text-xs text-white/50">Sharpe 24M</div>
                  <div className="text-base font-semibold text-emerald-400">{s.sharpe24m.toFixed(2)}</div>
                </div>
                <div className="bg-white/5 rounded-lg p-2">
                  <div className="text-xs text-white/50">maxDD 24M</div>
                  <div className="text-base font-semibold">{s.maxDd24m.toFixed(1)}%</div>
                </div>
                <div className="bg-white/5 rounded-lg p-2">
                  <div className="text-xs text-white/50">Setups/mois</div>
                  <div className="text-base font-semibold">~{s.setupsPerMonth}</div>
                </div>
              </div>

              <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-2.5">
                <div className="text-xs text-cyan-300 uppercase font-medium">Sizing recommandé Phase 4</div>
                <div className="text-sm text-white/80 mt-1">{s.recommendedSizing}</div>
              </div>
            </GlassCard>
          ))}
        </div>

        {/* Patterns retenus */}
        <GlassCard className="p-5">
          <h2 className="text-lg font-semibold mb-1">Système V2_CORE_LONG — 3 patterns retenus</h2>
          <p className="text-xs text-white/50 mb-4">
            Sur 12 patterns testés, seuls 3 patterns BUY sont conservés. Les SHORTs sont exclus (saigne en bull cycle XAG).
            Chaque extension testée (4 patterns, 2 patterns, filtre régime, walk-forward) a été soit neutre soit pire.
          </p>
          <div className="space-y-3">
            {PATTERNS_RETAINED.map((p) => (
              <div key={p.name} className="bg-white/5 rounded-lg p-3 border border-white/5">
                <div className="flex items-baseline justify-between mb-2">
                  <code className="text-sm font-mono text-cyan-300">{p.name}</code>
                  <span className="text-xs text-white/40">BUY only</span>
                </div>
                <div className="text-sm text-white/80 mb-2">{p.desc}</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <div>
                    <span className="text-white/40">PF XAU H4 :</span> <span className="text-white/70">{p.pfXAU}</span>
                  </div>
                  <div>
                    <span className="text-white/40">PF XAG H4 :</span> <span className="text-white/70">{p.pfXAG}</span>
                  </div>
                  <div className="md:col-span-2">
                    <span className="text-white/40">Triggers :</span> <code className="text-white/60 text-[11px]">{p.triggers}</code>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Tentatives rejetées */}
        <GlassCard className="p-5">
          <h2 className="text-lg font-semibold mb-1">Tentatives d'optimisation testées et REJETÉES</h2>
          <p className="text-xs text-white/50 mb-4">
            Toutes les extensions ont été testées rigoureusement et rejetées : la simplicité actuelle est l'optimum local
            atteignable. C'est en fait une bonne nouvelle (système résistant au tinkering).
          </p>
          <div className="space-y-1.5">
            {REJECTED_EXPERIMENTS.map((e) => (
              <div key={e.name} className="flex items-start gap-3 py-1.5 border-b border-white/5 last:border-0">
                <span className="text-rose-400/60 mt-0.5">✗</span>
                <div className="flex-1">
                  <div className="text-sm font-medium text-white/80">{e.name}</div>
                  <div className="text-xs text-white/50 mt-0.5">{e.verdict}</div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Limitations */}
        <GlassCard className="p-5 border-amber-500/20 bg-amber-500/5">
          <h2 className="text-lg font-semibold mb-3 text-amber-300">⚠ Limitations connues du backtest</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Coûts sous-modélisés</div>
              <div className="text-white/70 text-xs">
                Backtest à 0.02% spread/slippage. Live attendu 0.05-0.08% sur Pepperstone démo retail.
                PF 1.59 backtest peut tomber à 1.20-1.40 en live.
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Sample size modeste</div>
              <div className="text-white/70 text-xs">
                1441 trades XAU sur 6 ans = 240/an. Sharpe IC 95% ± 0.4 → vraie Sharpe entre 1.2 et 2.0.
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Multiple testing</div>
              <div className="text-white/70 text-xs">
                7 variantes testées et meilleure gardée → biais d'overfitting indirect malgré walk-forward strict.
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Régime futur incertain</div>
              <div className="text-white/70 text-xs">
                Edge cycle-amplifié : PF 1.32 cumul 6 ans vs 1.59 bull cycle. En régime calme, attendre PF 1.10-1.20.
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Long-only</div>
              <div className="text-white/70 text-xs">
                Performe mal en bear durables. Aucune protection symétrique testée (les SHORTs sont exclus).
              </div>
            </div>
            <div>
              <div className="text-xs text-amber-400/80 uppercase mb-1">Pas testé pré-2020</div>
              <div className="text-white/70 text-xs">
                Twelve Data Grow plafonne à ~6 ans. Comportement durant 2008-2020 inconnu.
              </div>
            </div>
          </div>
        </GlassCard>

        {/* Roadmap */}
        <GlassCard className="p-5">
          <h2 className="text-lg font-semibold mb-3">Roadmap Phase 4 → Phase 6</h2>
          <div className="space-y-2 text-sm">
            <div className="flex items-start gap-3">
              <span className="text-emerald-400">●</span>
              <div className="flex-1">
                <span className="font-medium">Phase 4 — Shadow log live (4-8 sem)</span>
                <span className="text-white/40 mx-1">·</span>
                <span className="text-emerald-300">EN COURS</span>
                <div className="text-xs text-white/50 mt-0.5">
                  Détection live sans auto-exec. Vérifier que setups arrivent à la cadence backtest et prix d'entrée cohérents.
                  Gate S6 le 2026-06-06.
                </div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-white/30">○</span>
              <div className="flex-1">
                <span className="font-medium">Phase 5 — Auto-exec démo Pepperstone (2-3 mois)</span>
                <span className="text-white/40 mx-1">·</span>
                <span className="text-white/40">CONDITIONNEL gate S6</span>
                <div className="text-xs text-white/50 mt-0.5">
                  Si Phase 4 confirme : ≥ 50 setups, WR ≥ 45%, PF ≥ 1.15, maxDD &lt; 30%, slippage &lt; 0.08%.
                </div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-white/30">○</span>
              <div className="flex-1">
                <span className="font-medium">Phase 6 — Live réel (6+ mois)</span>
                <span className="text-white/40 mx-1">·</span>
                <span className="text-white/40">CONDITIONNEL Phase 5</span>
                <div className="text-xs text-white/50 mt-0.5">
                  Capital décidé par user. Sizing 0.1-0.5% risk/trade. Gestion live + ajustements en continu.
                </div>
              </div>
            </div>
          </div>
        </GlassCard>

        {/* Liens utiles */}
        <div className="text-xs text-white/40 text-center">
          Voir aussi :{' '}
          <Link to="/shadow-log" className="text-cyan-400 hover:text-cyan-300">/shadow-log (KPIs live)</Link>
          {' · '}
          <Link to="/dashboard" className="text-cyan-400 hover:text-cyan-300">/dashboard</Link>
        </div>
      </main>
    </>
  );
}
