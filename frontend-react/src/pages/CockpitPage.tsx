import clsx from 'clsx';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { useCockpit, useKillSwitch } from '@/hooks/useCockpit';
import { formatPnl, formatPct, formatPrice } from '@/lib/format';
import type {
  ActiveTrade,
  CockpitAlert,
  FearGreedSnapshot,
  CotExtreme,
} from '@/types/domain';

export function CockpitPage() {
  const { data, isLoading } = useCockpit();

  return (
    <>
      <ReactiveMeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-6">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Cockpit <span className="text-white/40 text-sm font-normal ml-2">tour de contrôle temps réel</span>
            </h1>
          </div>
          {data && (
            <span className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
              maj · {new Date(data.generated_at).toLocaleTimeString('fr-FR')}
            </span>
          )}
        </div>

        {isLoading && <Skeleton className="h-32" />}
        {data && (
          <>
            <KillSwitchAndAlerts
              killSwitchActive={data.kill_switch.active}
              killSwitchReason={data.kill_switch.reason}
              alerts={data.alerts}
            />

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <section className="lg:col-span-8 space-y-6 min-w-0">
                <TodayStatsCard
                  pnl={data.today_stats.pnl}
                  pnlPct={data.today_stats.pnl_pct}
                  nTrades={data.today_stats.n_trades}
                  nOpen={data.today_stats.n_open}
                  nClosed={data.today_stats.n_closed}
                  capital={data.today_stats.capital}
                  exposure={data.active_trades.total_exposure_lots}
                  unrealizedPnl={data.active_trades.unrealized_pnl}
                />
                <ActiveTradesPanel trades={data.active_trades.items} />
              </section>

              <aside className="lg:col-span-4 space-y-6 min-w-0">
                <FearGreedGauge snapshot={data.fear_greed} />
                <SystemHealthCard
                  healthy={data.system_health.healthy}
                  bridgeReachable={data.system_health.bridge.reachable}
                  bridgeConfigured={data.system_health.bridge.configured}
                  secondsSince={data.system_health.seconds_since_last_cycle}
                  wsClients={data.system_health.ws_clients}
                  sessionLabel={data.session?.label}
                />
                <CotExtremesCard items={data.cot_extremes} />
              </aside>
            </div>
          </>
        )}
      </main>
    </>
  );
}

/* ─────────── Kill switch + alertes top ─────────── */

function KillSwitchAndAlerts({
  killSwitchActive,
  killSwitchReason,
  alerts,
}: {
  killSwitchActive: boolean;
  killSwitchReason: string | null;
  alerts: CockpitAlert[];
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-4">
      <KillSwitchCard active={killSwitchActive} reason={killSwitchReason} />
      <AlertsStack alerts={alerts} />
    </div>
  );
}

function KillSwitchCard({ active, reason }: { active: boolean; reason: string | null }) {
  const { query, mutation } = useKillSwitch();
  const manualEnabled = query.data?.manual_enabled ?? false;

  const handleToggle = () => {
    const next = !manualEnabled;
    const promptReason = next ? window.prompt('Raison du kill switch manuel ?', 'maintenance') : undefined;
    if (next && promptReason === null) return; // annulé
    mutation.mutate({ enabled: next, reason: promptReason ?? undefined });
  };

  return (
    <GlassCard
      variant="elevated"
      className={clsx(
        'p-5 min-w-[240px] flex flex-col gap-3 transition-all',
        active ? 'border-rose-400/40 shadow-[0_0_24px_rgba(244,63,94,0.2)]' : 'border-glass-soft'
      )}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-white/60">Kill switch</h3>
        <StatusDot active={active} />
      </div>
      <div>
        <div className={clsx('text-2xl font-bold tabular-nums', active ? 'text-rose-300' : 'text-emerald-300')}>
          {active ? 'ACTIF' : 'OK'}
        </div>
        {reason && <p className="text-[11px] text-white/50 mt-1 leading-snug">{reason}</p>}
      </div>
      <button
        type="button"
        onClick={handleToggle}
        disabled={mutation.isPending}
        className={clsx(
          'text-xs px-3 py-2 rounded-lg border transition-all font-semibold uppercase tracking-wider',
          manualEnabled
            ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/20'
            : 'border-rose-400/40 bg-rose-400/10 text-rose-300 hover:bg-rose-400/20',
          mutation.isPending && 'opacity-40 cursor-wait'
        )}
      >
        {manualEnabled ? 'Réactiver auto-exec' : 'Geler auto-exec'}
      </button>
    </GlassCard>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className={clsx('relative inline-block w-2 h-2 rounded-full', active ? 'bg-rose-400' : 'bg-emerald-400')}>
      <motion.span
        aria-hidden
        className={clsx('absolute inset-0 rounded-full', active ? 'bg-rose-400' : 'bg-emerald-400')}
        animate={{ scale: [1, 2.2], opacity: [0.6, 0] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
      />
    </span>
  );
}

function AlertsStack({ alerts }: { alerts: CockpitAlert[] }) {
  if (alerts.length === 0) {
    return (
      <GlassCard className="p-4 flex items-center justify-center text-sm text-white/40">
        Aucune alerte
      </GlassCard>
    );
  }
  const toneFor = (lvl: CockpitAlert['level']) =>
    lvl === 'critical'
      ? 'border-rose-400/40 bg-rose-400/10 text-rose-300'
      : lvl === 'warning'
      ? 'border-amber-400/40 bg-amber-400/10 text-amber-300'
      : 'border-cyan-400/30 bg-cyan-400/5 text-cyan-300';
  return (
    <GlassCard className="p-3">
      <div className="flex flex-col gap-1.5 max-h-[160px] overflow-y-auto pr-1">
        {alerts.map((a, i) => (
          <motion.div
            key={`${a.code}-${i}`}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.03 }}
            className={clsx('text-xs px-3 py-1.5 rounded-md border leading-snug', toneFor(a.level))}
          >
            <span className="font-mono uppercase tracking-wider mr-2 opacity-60">{a.level}</span>
            {a.msg}
          </motion.div>
        ))}
      </div>
    </GlassCard>
  );
}

/* ─────────── Today stats ─────────── */

function TodayStatsCard({
  pnl,
  pnlPct,
  nTrades,
  nOpen,
  nClosed,
  capital,
  exposure,
  unrealizedPnl,
}: {
  pnl: number;
  pnlPct: number;
  nTrades: number;
  nOpen: number;
  nClosed: number;
  capital: number;
  exposure: number;
  unrealizedPnl: number;
}) {
  const pnlTone = pnl > 0 ? 'text-emerald-300' : pnl < 0 ? 'text-rose-300' : 'text-white/80';
  const unrealTone =
    unrealizedPnl > 0 ? 'text-emerald-300' : unrealizedPnl < 0 ? 'text-rose-300' : 'text-white/60';
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Aujourd'hui</h3>
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          capital {formatPnl(capital)}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Kpi label="PnL jour" value={<span className={clsx('font-mono', pnlTone)}>{formatPnl(pnl)}</span>} sub={`${formatPct(pnlPct / 100)}`} />
        <Kpi label="Non réalisé" value={<span className={clsx('font-mono', unrealTone)}>{formatPnl(unrealizedPnl)}</span>} sub={`exposition ${exposure.toFixed(2)}`} />
        <Kpi label="Trades" value={<GradientText>{String(nTrades)}</GradientText>} sub={`${nClosed} clôturés`} />
        <Kpi label="Ouverts" value={<span className="font-mono">{String(nOpen)}</span>} sub="en cours" />
      </div>
    </GlassCard>
  );
}

function Kpi({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.2em] text-white/40 mb-1">{label}</div>
      <div className="text-xl font-bold leading-tight">{value}</div>
      {sub && <div className="text-[10px] text-white/40 mt-1 font-mono">{sub}</div>}
    </div>
  );
}

/* ─────────── Active trades ─────────── */

function ActiveTradesPanel({ trades }: { trades: ActiveTrade[] }) {
  if (trades.length === 0) {
    return (
      <GlassCard className="p-6 text-sm text-white/50 text-center">
        Aucun trade ouvert en ce moment.
      </GlassCard>
    );
  }
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Trades actifs</h3>
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {trades.length} ouvert{trades.length > 1 ? 's' : ''}
        </span>
      </div>
      <div className="space-y-2">
        {trades.map((t) => (
          <ActiveTradeRow key={t.id} trade={t} />
        ))}
      </div>
    </GlassCard>
  );
}

function ActiveTradeRow({ trade }: { trade: ActiveTrade }) {
  const isBuy = trade.direction === 'buy';
  const pnl = trade.pnl_unrealized ?? 0;
  const pnlTone = pnl > 0 ? 'text-emerald-300' : pnl < 0 ? 'text-rose-300' : 'text-white/70';
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={clsx(
        'grid grid-cols-[80px_60px_1fr_70px_80px] items-center gap-3 py-2 px-3 rounded-lg border',
        trade.near_sl ? 'border-rose-400/30 bg-rose-400/5' : 'border-glass-soft bg-white/[0.02]'
      )}
    >
      <div className="font-mono text-sm font-semibold truncate">{trade.pair}</div>
      <span
        className={clsx(
          'text-[9px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded text-center',
          isBuy ? 'bg-cyan-400/10 text-cyan-300' : 'bg-pink-400/10 text-pink-300'
        )}
      >
        {trade.direction}
      </span>
      <div className="text-xs text-white/60 font-mono tabular-nums truncate">
        {formatPrice(trade.entry_price)}
        {trade.current_price !== null && (
          <>
            <span className="mx-1 opacity-40">→</span>
            <span className="text-white/80">{formatPrice(trade.current_price)}</span>
          </>
        )}
      </div>
      <div className="text-xs font-mono tabular-nums text-right text-white/50">
        {trade.distance_to_sl_pct !== null ? `SL ${trade.distance_to_sl_pct}%` : '—'}
      </div>
      <div className={clsx('text-xs font-mono font-semibold tabular-nums text-right', pnlTone)}>
        {trade.pnl_unrealized !== null ? formatPnl(trade.pnl_unrealized) : '—'}
      </div>
    </motion.div>
  );
}

/* ─────────── Fear & Greed gauge ─────────── */

function FearGreedGauge({ snapshot }: { snapshot: FearGreedSnapshot | null }) {
  if (!snapshot) {
    return (
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold tracking-tight mb-2">Fear &amp; Greed</h3>
        <p className="text-xs text-white/40">Pas de données — prochain fetch 22:30 UTC.</p>
      </GlassCard>
    );
  }
  const v = snapshot.value;
  const classif = snapshot.classification;
  const labelMap: Record<FearGreedSnapshot['classification'], { label: string; tone: string }> = {
    extreme_fear: { label: 'Extreme Fear', tone: 'from-rose-500 to-pink-400' },
    fear: { label: 'Fear', tone: 'from-pink-400 to-amber-300' },
    neutral: { label: 'Neutral', tone: 'from-amber-300 to-cyan-300' },
    greed: { label: 'Greed', tone: 'from-cyan-300 to-emerald-400' },
    extreme_greed: { label: 'Extreme Greed', tone: 'from-emerald-400 to-lime-300' },
  };
  const cfg = labelMap[classif];
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold tracking-tight">Fear &amp; Greed</h3>
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">CNN</span>
      </div>
      <div className="flex items-baseline gap-3 mb-2">
        <span className="text-4xl font-bold font-mono tabular-nums">{v}</span>
        <span className="text-[10px] text-white/40 uppercase tracking-widest">/100</span>
      </div>
      <div className="w-full h-2 rounded-full bg-white/5 overflow-hidden relative">
        <motion.div
          className={clsx('h-full rounded-full bg-gradient-to-r', cfg.tone)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.max(0, Math.min(100, v))}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
      <div className="mt-2 text-xs font-semibold uppercase tracking-wider">
        <span className={clsx('px-2 py-0.5 rounded-md border', `bg-gradient-to-r ${cfg.tone} bg-clip-text text-transparent border-glass-soft`)}>
          {cfg.label}
        </span>
      </div>
    </GlassCard>
  );
}

/* ─────────── System health ─────────── */

function SystemHealthCard({
  healthy,
  bridgeReachable,
  bridgeConfigured,
  secondsSince,
  wsClients,
  sessionLabel,
}: {
  healthy: boolean;
  bridgeReachable: boolean;
  bridgeConfigured: boolean;
  secondsSince: number | null;
  wsClients: number;
  sessionLabel?: string;
}) {
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold tracking-tight">Santé système</h3>
        <StatusDot active={!healthy} />
      </div>
      <ul className="space-y-1.5 text-xs text-white/70">
        <li className="flex justify-between">
          <span>Cycle d'analyse</span>
          <span className={clsx('font-mono', healthy ? 'text-emerald-300' : 'text-rose-300')}>
            {secondsSince !== null ? `${Math.round(secondsSince)}s` : '—'}
          </span>
        </li>
        <li className="flex justify-between">
          <span>Bridge MT5</span>
          <span className={clsx('font-mono', bridgeReachable ? 'text-emerald-300' : bridgeConfigured ? 'text-rose-300' : 'text-white/30')}>
            {bridgeConfigured ? (bridgeReachable ? 'UP' : 'DOWN') : 'N/A'}
          </span>
        </li>
        <li className="flex justify-between">
          <span>Clients WS</span>
          <span className="font-mono">{wsClients}</span>
        </li>
        {sessionLabel && (
          <li className="flex justify-between">
            <span>Session</span>
            <span className="font-mono text-cyan-300">{sessionLabel}</span>
          </li>
        )}
      </ul>
    </GlassCard>
  );
}

/* ─────────── COT extremes ─────────── */

function CotExtremesCard({ items }: { items: CotExtreme[] }) {
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold tracking-tight">COT extremes</h3>
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          z ≥ 2σ / 52s
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-white/40">Aucun extrême cette semaine.</p>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <div key={it.pair} className="border-l-2 border-cyan-400/30 pl-3">
              <div className="text-sm font-mono font-semibold">{it.pair}</div>
              {it.signals.map((s, i) => (
                <div key={i} className="text-[11px] text-white/60 leading-snug">
                  <span className="font-mono tabular-nums text-cyan-300 mr-1.5">z={s.z}</span>
                  {s.interpretation}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
