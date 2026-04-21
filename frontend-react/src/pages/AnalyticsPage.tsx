import { useMemo } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { Sparkline } from '@/components/ui/Sparkline';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { MistakesCard } from '@/components/analytics/MistakesCard';
import { CombosHeatmap } from '@/components/analytics/CombosHeatmap';
import { useAnalytics } from '@/hooks/useCockpit';
import { formatPnl } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type {
  AnalyticsBreakdownRow,
  AnalyticsReport,
  CloseReasonRow,
  SignalVolume,
  SlippageByPair,
} from '@/types/domain';

export function AnalyticsPage() {
  const { data, isLoading } = useAnalytics();

  return (
    <>
      <ReactiveMeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-6">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <LabelWithInfo
            label={
              <h1 className="text-2xl font-semibold tracking-tight">
                Analytics{' '}
                <span className="text-white/40 text-sm font-normal ml-2">
                  breakdowns du win rate par feature
                </span>
              </h1>
            }
            tip={TIPS.analytics.titre}
          />
        </div>

        {isLoading && <Skeleton className="h-96" />}
        {data?.error && (
          <GlassCard className="p-6 text-sm text-rose-300">
            Erreur : {data.error}
          </GlassCard>
        )}

        {data && !data.error && (
          <>
            <MistakesCard />
            <SignalVolumeCard volume={data.signal_volume} />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <BreakdownCard
                title="Win rate par heure (UTC)"
                tip={TIPS.analytics.byHour}
                rows={data.by_hour_utc}
                accent="cyan"
                sortBy="key"
              />
              <ConfidenceCalibrationCard rows={data.by_confidence_bucket} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <BreakdownCard
                title="Par paire"
                tip={TIPS.analytics.byPair}
                rows={data.by_pair}
                accent="pink"
              />
              <BreakdownCard
                title="Par pattern"
                tip={TIPS.analytics.byPattern}
                rows={data.by_pattern}
                accent="amber"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <BreakdownCard
                title="Par classe d'actif"
                tip={TIPS.analytics.byAssetClass}
                rows={data.by_asset_class}
                accent="emerald"
              />
              <BreakdownCard
                title="Par régime macro"
                tip={TIPS.analytics.byRiskRegime}
                rows={data.by_risk_regime}
                accent="purple"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CloseReasonCard
                rows={data.execution_quality?.close_reason_distribution ?? []}
                totalClosed={data.execution_quality?.total_closed_trades ?? 0}
              />
              <SlippageCard rows={data.execution_quality?.slippage_by_pair ?? []} />
            </div>

            <CombosHeatmap />
          </>
        )}
      </main>
    </>
  );
}

/* ─────────── Signal volume (top widget) ─────────── */

function SignalVolumeCard({ volume }: { volume?: SignalVolume }) {
  if (!volume) return null;
  const series = [...volume.last_30_days].reverse().map((d) => d.count);
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Volume de signaux</h3>}
          tip={TIPS.analytics.signalVolume}
        />
        <div className="flex items-center gap-5 sm:gap-8">
          <KpiBlock label="Total" tip="Nombre cumulé de signaux générés depuis le début de la collecte.">
            <span className="font-mono">{volume.total_signals}</span>
          </KpiBlock>
          <KpiBlock label="TAKE" tip={TIPS.setup.verdictTake}>
            <GradientText>{String(volume.verdict_take)}</GradientText>
          </KpiBlock>
          <KpiBlock label="SKIP" tip={TIPS.setup.verdictSkip}>
            <span className="font-mono text-white/60">{volume.verdict_skip}</span>
          </KpiBlock>
          <KpiBlock label="Take ratio" tip={TIPS.analytics.takeRatio}>
            <span className={clsx('font-mono', ratioTone(volume.take_ratio_pct))}>
              {volume.take_ratio_pct}%
            </span>
          </KpiBlock>
        </div>
      </div>
      {series.length > 1 && (
        <div className="mt-2">
          <Tooltip content="Volume journalier des 30 derniers jours (nb de signaux émis par jour). Chaque point = un jour.">
            <div className="w-full">
              <Sparkline
                values={series}
                width={1200}
                height={54}
                variant="neutral"
              />
            </div>
          </Tooltip>
        </div>
      )}
    </GlassCard>
  );
}

function ratioTone(pct: number): string {
  if (pct < 5) return 'text-rose-300';
  if (pct > 50) return 'text-amber-300';
  return 'text-emerald-300';
}

function KpiBlock({
  label,
  tip,
  children,
}: {
  label: string;
  tip: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <LabelWithInfo
        label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
        tip={tip}
        className="mb-0.5"
      />
      <div className="text-lg font-bold tabular-nums leading-none">{children}</div>
    </div>
  );
}

/* ─────────── Breakdown card (générique) ─────────── */

type Accent = 'cyan' | 'pink' | 'amber' | 'emerald' | 'purple';

const ACCENT_GRADIENTS: Record<Accent, { good: string; mid: string; bad: string }> = {
  cyan: {
    good: 'from-cyan-400 to-emerald-400',
    mid: 'from-cyan-400 to-amber-300',
    bad: 'from-pink-400 to-rose-400',
  },
  pink: {
    good: 'from-pink-400 to-emerald-400',
    mid: 'from-pink-400 to-amber-300',
    bad: 'from-pink-400 to-rose-400',
  },
  amber: {
    good: 'from-amber-400 to-emerald-400',
    mid: 'from-amber-400 to-cyan-300',
    bad: 'from-amber-400 to-rose-400',
  },
  emerald: {
    good: 'from-emerald-400 to-cyan-400',
    mid: 'from-emerald-400 to-amber-300',
    bad: 'from-emerald-400 to-rose-400',
  },
  purple: {
    good: 'from-purple-400 to-emerald-400',
    mid: 'from-purple-400 to-cyan-300',
    bad: 'from-purple-400 to-rose-400',
  },
};

function BreakdownCard({
  title,
  tip,
  rows,
  accent,
  sortBy = 'total',
}: {
  title: string;
  tip: React.ReactNode;
  rows?: AnalyticsBreakdownRow[];
  accent: Accent;
  sortBy?: 'total' | 'key';
}) {
  const sorted = useMemo(() => {
    if (!rows) return [];
    if (sortBy === 'key') return [...rows].sort((a, b) => a.key.localeCompare(b.key));
    return [...rows].sort((a, b) => b.total - a.total);
  }, [rows, sortBy]);

  const maxTotal = sorted.reduce((max, r) => Math.max(max, r.total), 0);

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">{title}</h3>}
          tip={tip}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {sorted.length} bucket{sorted.length > 1 ? 's' : ''}
        </span>
      </div>
      {sorted.length === 0 ? (
        <p className="text-xs text-white/40">Pas encore de données.</p>
      ) : (
        <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
          {sorted.map((r, i) => (
            <BreakdownRow key={r.key} row={r} index={i} maxTotal={maxTotal} accent={accent} />
          ))}
        </div>
      )}
    </GlassCard>
  );
}

function BreakdownRow({
  row,
  index,
  maxTotal,
  accent,
}: {
  row: AnalyticsBreakdownRow;
  index: number;
  maxTotal: number;
  accent: Accent;
}) {
  const wrPct = row.win_rate_pct;
  const tier = wrPct >= 60 ? 'good' : wrPct >= 45 ? 'mid' : 'bad';
  const gradient = ACCENT_GRADIENTS[accent][tier];
  const wrTone = tier === 'good' ? 'text-emerald-300' : tier === 'mid' ? 'text-amber-300' : 'text-rose-300';
  const volumePct = maxTotal > 0 ? (row.total / maxTotal) * 100 : 0;

  return (
    <motion.div
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03 }}
      className="grid grid-cols-[100px_1fr_56px_70px] items-center gap-3 text-xs"
    >
      <Tooltip content={TIPS.analytics.totalTrades}>
        <div className="font-mono text-white/85 truncate">{row.key}</div>
      </Tooltip>
      <div className="space-y-1">
        <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
          <motion.div
            className={clsx('h-full rounded-full bg-gradient-to-r', gradient)}
            initial={{ width: 0 }}
            animate={{ width: `${wrPct}%` }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          />
        </div>
        <div className="w-full h-0.5 rounded-full bg-white/5 overflow-hidden">
          <motion.div
            className="h-full rounded-full bg-white/20"
            initial={{ width: 0 }}
            animate={{ width: `${volumePct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
      </div>
      <Tooltip content={TIPS.analytics.totalTrades}>
        <div className="text-[10px] text-white/40 tabular-nums uppercase tracking-wider text-right">
          {row.total}
        </div>
      </Tooltip>
      <Tooltip content={TIPS.analytics.winRatePct}>
        <div className={clsx('font-mono font-semibold tabular-nums text-right', wrTone)}>
          {wrPct}%
        </div>
      </Tooltip>
    </motion.div>
  );
}

/* ─────────── Confidence calibration (special : sorted by bucket order) ─────────── */

const CONFIDENCE_ORDER: Record<string, number> = {
  '0-50': 0,
  '50-60': 1,
  '60-70': 2,
  '70-80': 3,
  '80-90': 4,
  '90-100': 5,
};

function ConfidenceCalibrationCard({ rows }: { rows?: AnalyticsBreakdownRow[] }) {
  const ordered = useMemo(() => {
    if (!rows) return [];
    return [...rows].sort((a, b) => (CONFIDENCE_ORDER[a.key] ?? 99) - (CONFIDENCE_ORDER[b.key] ?? 99));
  }, [rows]);

  const isCalibrated = useMemo(() => {
    if (ordered.length < 3) return null;
    const rates = ordered.map((r) => r.win_rate_pct);
    const diffs = rates.slice(1).map((r, i) => r - rates[i]);
    const monotonic = diffs.filter((d) => d >= -3).length / diffs.length;
    return monotonic >= 0.7;
  }, [ordered]);

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Calibration du score</h3>}
          tip={TIPS.analytics.byConfidence}
        />
        {isCalibrated !== null && (
          <Tooltip content={
            isCalibrated
              ? 'Modèle calibré : le win rate tend à monter avec le score de confiance. Le scoring a du signal.'
              : 'Modèle NON calibré : le win rate ne suit pas le score. Revoir les poids des features de confidence.'
          }>
            <span className={clsx(
              'text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded border',
              isCalibrated
                ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
                : 'border-rose-400/30 bg-rose-400/10 text-rose-300'
            )}>
              {isCalibrated ? 'Calibré' : 'À revoir'}
            </span>
          </Tooltip>
        )}
      </div>
      {ordered.length === 0 ? (
        <p className="text-xs text-white/40">Pas encore de données.</p>
      ) : (
        <div className="space-y-2">
          {ordered.map((r, i) => {
            const tier = r.win_rate_pct >= 60 ? 'good' : r.win_rate_pct >= 45 ? 'mid' : 'bad';
            const gradient = ACCENT_GRADIENTS.cyan[tier];
            const wrTone = tier === 'good' ? 'text-emerald-300' : tier === 'mid' ? 'text-amber-300' : 'text-rose-300';
            return (
              <motion.div
                key={r.key}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.04 }}
                className="grid grid-cols-[80px_1fr_60px_60px] items-center gap-3 text-xs"
              >
                <span className="font-mono text-white/80 tabular-nums">{r.key}</span>
                <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className={clsx('h-full rounded-full bg-gradient-to-r', gradient)}
                    initial={{ width: 0 }}
                    animate={{ width: `${r.win_rate_pct}%` }}
                    transition={{ duration: 0.6, ease: 'easeOut' }}
                  />
                </div>
                <span className="text-[10px] text-white/40 tabular-nums text-right">
                  {r.total}
                </span>
                <span className={clsx('font-mono font-semibold tabular-nums text-right', wrTone)}>
                  {r.win_rate_pct}%
                </span>
              </motion.div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}

/* ─────────── Close reason distribution ─────────── */

function CloseReasonCard({
  rows,
  totalClosed,
}: {
  rows: CloseReasonRow[];
  totalClosed: number;
}) {
  const ordered = [...rows].sort((a, b) => b.count - a.count);
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Raisons de fermeture</h3>}
          tip={TIPS.analytics.closeReason}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {totalClosed} clôturés
        </span>
      </div>
      {ordered.length === 0 ? (
        <p className="text-xs text-white/40">Pas encore de trades clôturés avec raison renseignée.</p>
      ) : (
        <div className="space-y-2">
          {ordered.map((r, i) => {
            const pnlTone = r.avg_pnl > 0 ? 'text-emerald-300' : r.avg_pnl < 0 ? 'text-rose-300' : 'text-white/70';
            const reasonTone =
              r.reason === 'TP1' || r.reason === 'TP2' ? 'from-emerald-400 to-cyan-400'
              : r.reason === 'SL' ? 'from-rose-400 to-pink-400'
              : 'from-white/20 to-white/30';
            return (
              <motion.div
                key={r.reason}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.04 }}
                className="space-y-1"
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-white/85">{r.reason}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-white/50 tabular-nums">
                      {r.count} · {r.pct}%
                    </span>
                    <span className={clsx('font-mono font-semibold tabular-nums w-20 text-right', pnlTone)}>
                      {formatPnl(r.avg_pnl)}
                    </span>
                  </div>
                </div>
                <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className={clsx('h-full rounded-full bg-gradient-to-r', reasonTone)}
                    initial={{ width: 0 }}
                    animate={{ width: `${r.pct}%` }}
                    transition={{ duration: 0.6, ease: 'easeOut' }}
                  />
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}

/* ─────────── Slippage ─────────── */

function SlippageCard({ rows }: { rows: SlippageByPair[] }) {
  const ordered = [...rows].sort((a, b) => b.n - a.n);
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Slippage par paire</h3>}
          tip={TIPS.analytics.slippage}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          en pips
        </span>
      </div>
      {ordered.length === 0 ? (
        <p className="text-xs text-white/40">
          Pas encore de slippage logué (colonne slippage_pips remplie après quelques trades auto).
        </p>
      ) : (
        <div className="space-y-1.5 max-h-[320px] overflow-y-auto pr-1">
          {ordered.map((r, i) => {
            const avgTone = r.avg_pips > 0 ? 'text-emerald-300' : r.avg_pips < 0 ? 'text-rose-300' : 'text-white/70';
            return (
              <motion.div
                key={r.pair}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.03 }}
                className="grid grid-cols-[100px_60px_1fr] items-center gap-3 text-xs"
              >
                <span className="font-mono text-white/85 truncate">{r.pair}</span>
                <span className="text-white/40 tabular-nums text-[10px] uppercase tracking-wider">
                  n={r.n}
                </span>
                <div className="flex items-center justify-end gap-3 text-[10px] font-mono tabular-nums">
                  <span className="text-white/40">min {r.min_pips}</span>
                  <span className="text-white/40">max {r.max_pips}</span>
                  <span className={clsx('font-semibold text-xs', avgTone)}>
                    avg {r.avg_pips > 0 ? '+' : ''}{r.avg_pips}
                  </span>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}

// Keep type usage even in tree-shaken builds (silences ts6133 on unused types)
export type { AnalyticsReport };
