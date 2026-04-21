import { useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { ReactiveMeshGradient } from '@/components/ui/ReactiveMeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { EquityCurveMini } from '@/components/performance/EquityCurveMini';
import { KillSwitchModal } from '@/components/cockpit/KillSwitchModal';
import { useCockpit, useKillSwitch, useDrift } from '@/hooks/useCockpit';
import { formatPnl, formatPct, formatPrice } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';
import type {
  ActiveTrade,
  AssetClass,
  CockpitAlert,
  CotExtreme,
  DriftFinding,
  FearGreedSnapshot,
} from '@/types/domain';

export function CockpitPage() {
  const { data, isLoading } = useCockpit();

  return (
    <>
      <ReactiveMeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-6">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight">
            Cockpit <span className="text-white/40 text-sm font-normal ml-2">tour de contrôle temps réel</span>
          </h1>
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

            <TodayStatsCard
              pnl={data.today_stats.pnl}
              pnlPct={data.today_stats.pnl_pct}
              nTrades={data.today_stats.n_trades}
              nOpen={data.today_stats.n_open}
              nClosed={data.today_stats.n_closed}
              capital={data.today_stats.capital}
              unrealizedPnl={data.active_trades.unrealized_pnl}
            />

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              <div className="lg:col-span-5 min-w-0">
                <CapitalAtRiskCard trades={data.active_trades.items} capital={data.today_stats.capital} />
              </div>
              <div className="lg:col-span-4 min-w-0">
                <AssetClassBreakdownCard trades={data.active_trades.items} />
              </div>
              <div className="lg:col-span-3 min-w-0">
                <FearGreedGauge snapshot={data.fear_greed} />
              </div>
            </div>

            <ActiveTradesPanel trades={data.active_trades.items} />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <EquityCurveMini />
              <SystemHealthCard
                healthy={data.system_health.healthy}
                bridgeReachable={data.system_health.bridge.reachable}
                bridgeConfigured={data.system_health.bridge.configured}
                secondsSince={data.system_health.seconds_since_last_cycle}
                wsClients={data.system_health.ws_clients}
                sessionLabel={data.session?.label}
              />
              <DriftCard />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CotExtremesCard items={data.cot_extremes} />
              <NextEventsCard events={data.next_events} />
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
  const [modalOpen, setModalOpen] = useState(false);
  const manualEnabled = query.data?.manual_enabled ?? false;

  const handleClick = () => {
    if (manualEnabled) {
      // désactivation : pas de prompt, on relâche direct
      mutation.mutate({ enabled: false });
    } else {
      setModalOpen(true);
    }
  };

  return (
    <>
      <GlassCard
        variant="elevated"
        className={clsx(
          'p-5 min-w-[240px] flex flex-col gap-3 transition-all',
          active ? 'border-rose-400/40 shadow-[0_0_24px_rgba(244,63,94,0.2)]' : 'border-glass-soft'
        )}
      >
        <div className="flex items-center justify-between">
          <LabelWithInfo
            label={<h3 className="text-xs font-bold uppercase tracking-[0.2em] text-white/60">Kill switch</h3>}
            tip={TIPS.killSwitch.title}
          />
          <Tooltip content={active ? TIPS.killSwitch.active : TIPS.killSwitch.okState}>
            <StatusDot active={active} />
          </Tooltip>
        </div>
        <div>
          <Tooltip content={active ? TIPS.killSwitch.active : TIPS.killSwitch.okState}>
            <div className={clsx('text-2xl font-bold tabular-nums cursor-help', active ? 'text-rose-300' : 'text-emerald-300')}>
              {active ? 'ACTIF' : 'OK'}
            </div>
          </Tooltip>
          {reason && <p className="text-[11px] text-white/50 mt-1 leading-snug">{reason}</p>}
        </div>
        <Tooltip content={TIPS.killSwitch.manualToggle}>
          <button
            type="button"
            onClick={handleClick}
            disabled={mutation.isPending}
            className={clsx(
              'w-full text-xs px-3 py-2 rounded-lg border transition-all font-semibold uppercase tracking-wider',
              manualEnabled
                ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300 hover:bg-emerald-400/20'
                : 'border-rose-400/40 bg-rose-400/10 text-rose-300 hover:bg-rose-400/20',
              mutation.isPending && 'opacity-40 cursor-wait'
            )}
          >
            {manualEnabled ? 'Réactiver auto-exec' : 'Geler auto-exec'}
          </button>
        </Tooltip>
      </GlassCard>
      <KillSwitchModal
        open={modalOpen}
        onConfirm={(r) => {
          mutation.mutate({ enabled: true, reason: r });
          setModalOpen(false);
        }}
        onCancel={() => setModalOpen(false)}
      />
    </>
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
      <Tooltip content={TIPS.alerts.title}>
        <GlassCard className="w-full p-4 flex items-center justify-center text-sm text-white/40 cursor-help">
          Aucune alerte
        </GlassCard>
      </Tooltip>
    );
  }
  const toneFor = (lvl: CockpitAlert['level']) =>
    lvl === 'critical'
      ? 'border-rose-400/40 bg-rose-400/10 text-rose-300'
      : lvl === 'warning'
      ? 'border-amber-400/40 bg-amber-400/10 text-amber-300'
      : 'border-cyan-400/30 bg-cyan-400/5 text-cyan-300';
  const tipForCode = (code: string): string => {
    const map = TIPS.alerts as Record<string, string>;
    return map[code] ?? TIPS.alerts.title;
  };
  return (
    <GlassCard className="p-3">
      <div className="flex items-center justify-between mb-2 px-1">
        <LabelWithInfo
          label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Alertes</span>}
          tip={TIPS.alerts.title}
        />
        <span className="text-[9px] font-mono text-white/40">{alerts.length}</span>
      </div>
      <div className="flex flex-col gap-1.5 max-h-[140px] overflow-y-auto pr-1">
        {alerts.map((a, i) => (
          <Tooltip key={`${a.code}-${i}`} content={tipForCode(a.code)}>
            <motion.div
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.03 }}
              className={clsx('w-full text-xs px-3 py-1.5 rounded-md border leading-snug cursor-help', toneFor(a.level))}
            >
              <span className="font-mono uppercase tracking-wider mr-2 opacity-60">{a.level}</span>
              {a.msg}
            </motion.div>
          </Tooltip>
        ))}
      </div>
    </GlassCard>
  );
}

/* ─────────── Today stats (full width) ─────────── */

function TodayStatsCard({
  pnl,
  pnlPct,
  nTrades,
  nOpen,
  nClosed,
  capital,
  unrealizedPnl,
}: {
  pnl: number;
  pnlPct: number;
  nTrades: number;
  nOpen: number;
  nClosed: number;
  capital: number;
  unrealizedPnl: number;
}) {
  const pnlTone = pnl > 0 ? 'text-emerald-300' : pnl < 0 ? 'text-rose-300' : 'text-white/80';
  const unrealTone =
    unrealizedPnl > 0 ? 'text-emerald-300' : unrealizedPnl < 0 ? 'text-rose-300' : 'text-white/60';
  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold tracking-tight">Aujourd'hui</h3>
        <Tooltip content={TIPS.today.capital}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider cursor-help">
            capital {formatPnl(capital)}
          </span>
        </Tooltip>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Kpi label="PnL jour" tip={TIPS.today.pnlJour} value={<span className={clsx('font-mono', pnlTone)}>{formatPnl(pnl)}</span>} sub={formatPct(pnlPct / 100)} subTip={TIPS.today.pnlPct} />
        <Kpi label="Non réalisé" tip={TIPS.today.nonRealise} value={<span className={clsx('font-mono', unrealTone)}>{formatPnl(unrealizedPnl)}</span>} sub="trades ouverts" />
        <Kpi label="Trades" tip={TIPS.today.trades} value={<GradientText>{String(nTrades)}</GradientText>} sub={`${nClosed} clôturés`} subTip={TIPS.today.closurés} />
        <Kpi label="Ouverts" tip={TIPS.today.ouverts} value={<span className="font-mono">{String(nOpen)}</span>} sub="en cours" />
      </div>
    </GlassCard>
  );
}

function Kpi({
  label,
  value,
  sub,
  tip,
  subTip,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  tip?: React.ReactNode;
  subTip?: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1">
        {tip ? (
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
            tip={tip}
          />
        ) : (
          <span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>
        )}
      </div>
      <div className="text-xl font-bold leading-tight">{value}</div>
      {sub && (
        <div className="text-[10px] text-white/40 mt-1 font-mono">
          {subTip ? (
            <Tooltip content={subTip}>
              <span className="cursor-help">{sub}</span>
            </Tooltip>
          ) : (
            sub
          )}
        </div>
      )}
    </div>
  );
}

/* ─────────── Capital at risk ─────────── */

function CapitalAtRiskCard({ trades, capital }: { trades: ActiveTrade[]; capital: number }) {
  const totalRisk = trades.reduce((sum, t) => sum + (t.risk_money ?? 0), 0);
  const totalNotional = trades.reduce((sum, t) => sum + (t.notional ?? 0), 0);
  const riskPct = capital > 0 ? (totalRisk / capital) * 100 : 0;
  const maxRiskPerTrade = trades.length
    ? Math.max(...trades.map((t) => t.risk_money ?? 0))
    : 0;
  const byPair = [...trades]
    .filter((t) => (t.risk_money ?? 0) > 0)
    .sort((a, b) => (b.risk_money ?? 0) - (a.risk_money ?? 0))
    .slice(0, 5);

  return (
    <GlassCard variant="elevated" className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Capital en jeu</h3>}
          tip={TIPS.capital.titre}
        />
        <Tooltip content={TIPS.capital.aRisque}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider cursor-help">
            risque si tous SL touchés
          </span>
        </Tooltip>
      </div>
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">À risque</span>}
            tip={TIPS.capital.aRisque}
            className="mb-1"
          />
          <div className="text-2xl font-bold font-mono tabular-nums text-rose-300">
            {formatPnl(totalRisk)}
          </div>
          <Tooltip content={TIPS.capital.risquePct}>
            <div className="text-[10px] text-white/40 font-mono mt-0.5 cursor-help">
              {riskPct.toFixed(2)}% capital
            </div>
          </Tooltip>
        </div>
        <div>
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Notionnel</span>}
            tip={TIPS.capital.notionnel}
            className="mb-1"
          />
          <div className="text-2xl font-bold font-mono tabular-nums text-white/80">
            {formatPnl(totalNotional)}
          </div>
          <Tooltip content={TIPS.capital.expositionTotale}>
            <div className="text-[10px] text-white/40 font-mono mt-0.5 cursor-help">
              exposition totale
            </div>
          </Tooltip>
        </div>
      </div>

      {byPair.length > 0 ? (
        <div className="space-y-2 pt-3 border-t border-glass-soft">
          <LabelWithInfo
            label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Top 5 par risque</span>}
            tip={TIPS.capital.top5}
          />
          {byPair.map((t) => {
            const pct = maxRiskPerTrade > 0 ? ((t.risk_money ?? 0) / maxRiskPerTrade) * 100 : 0;
            const isBuy = t.direction === 'buy';
            return (
              <div key={t.id} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-mono font-semibold truncate">{t.pair}</span>
                    <span className={clsx(
                      'text-[9px] font-semibold uppercase tracking-widest px-1 rounded',
                      isBuy ? 'bg-cyan-400/10 text-cyan-300' : 'bg-pink-400/10 text-pink-300'
                    )}>
                      {t.direction}
                    </span>
                  </div>
                  <span className="font-mono tabular-nums text-rose-300/90">
                    {formatPnl(t.risk_money ?? 0)}
                  </span>
                </div>
                <div className="w-full h-1 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className="h-full rounded-full bg-gradient-to-r from-rose-400/40 to-pink-400/40"
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-white/40 pt-3 border-t border-glass-soft">Aucun trade ouvert.</p>
      )}
    </GlassCard>
  );
}

/* ─────────── Asset class breakdown ─────────── */

const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  forex: 'Forex',
  metal: 'Métaux',
  crypto: 'Crypto',
  equity_index: 'Indices',
  energy: 'Énergie',
  unknown: 'Autre',
};

const ASSET_CLASS_COLORS: Record<AssetClass, string> = {
  forex: 'from-cyan-400 to-cyan-300',
  metal: 'from-amber-400 to-yellow-300',
  crypto: 'from-purple-400 to-pink-400',
  equity_index: 'from-emerald-400 to-cyan-400',
  energy: 'from-orange-400 to-rose-400',
  unknown: 'from-white/30 to-white/50',
};

function AssetClassBreakdownCard({ trades }: { trades: ActiveTrade[] }) {
  const grouped = trades.reduce<Record<AssetClass, { risk: number; notional: number; n: number }>>(
    (acc, t) => {
      const cls = t.asset_class ?? 'unknown';
      if (!acc[cls]) acc[cls] = { risk: 0, notional: 0, n: 0 };
      acc[cls].risk += t.risk_money ?? 0;
      acc[cls].notional += t.notional ?? 0;
      acc[cls].n += 1;
      return acc;
    },
    {} as Record<AssetClass, { risk: number; notional: number; n: number }>
  );
  const entries = Object.entries(grouped).sort((a, b) => b[1].risk - a[1].risk);
  const totalRisk = entries.reduce((s, [, v]) => s + v.risk, 0);

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Répartition</h3>}
          tip={TIPS.repartition.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          par classe d'actif
        </span>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-white/40">Aucune exposition.</p>
      ) : (
        <div className="space-y-3">
          {entries.map(([cls, v]) => {
            const ac = cls as AssetClass;
            const pct = totalRisk > 0 ? (v.risk / totalRisk) * 100 : 0;
            const classTip = (TIPS.repartition as Record<string, string>)[cls] ?? TIPS.repartition.unknown;
            return (
              <div key={cls} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <Tooltip content={classTip}>
                    <span className="text-white/80 cursor-help">{ASSET_CLASS_LABELS[ac] ?? cls}</span>
                  </Tooltip>
                  <span className="font-mono tabular-nums text-white/50">
                    {v.n} trade{v.n > 1 ? 's' : ''} · {formatPnl(v.risk)}
                  </span>
                </div>
                <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <motion.div
                    className={clsx('h-full rounded-full bg-gradient-to-r', ASSET_CLASS_COLORS[ac])}
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.6, ease: 'easeOut' }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}

/* ─────────── Active trades (responsive) ─────────── */

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
      {/* Légende colonnes — uniquement desktop */}
      <div className="hidden sm:grid grid-cols-[100px_60px_1fr_90px_90px_90px] items-center gap-4 pb-2 mb-2 px-3 text-[9px] uppercase tracking-[0.2em] text-white/30 font-mono">
        <LabelWithInfo label="Paire" tip={TIPS.trade.pair} />
        <LabelWithInfo label="Sens" tip={TIPS.trade.direction} />
        <LabelWithInfo label="Entry → Now" tip={`${TIPS.trade.entryPrice} · ${TIPS.trade.currentPrice}`} />
        <span className="text-right"><LabelWithInfo label="Dist. SL" tip={TIPS.trade.distanceSl} /></span>
        <span className="text-right"><LabelWithInfo label="Risque" tip={TIPS.trade.riskMoney} /></span>
        <span className="text-right"><LabelWithInfo label="PnL latent" tip={TIPS.trade.pnlUnrealized} /></span>
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
        'rounded-lg border p-3 transition-colors',
        trade.near_sl ? 'border-rose-400/30 bg-rose-400/5' : 'border-glass-soft bg-white/[0.02]'
      )}
    >
      {/* Desktop : grille horizontale, mobile : stack */}
      <div className="grid grid-cols-2 sm:grid-cols-[100px_60px_1fr_90px_90px_90px] items-center gap-2 sm:gap-4">
        <div className="flex items-center gap-2 min-w-0 col-span-2 sm:col-span-1">
          <Tooltip content={TIPS.trade.pair}>
            <span className="font-mono text-sm font-semibold truncate cursor-help">{trade.pair}</span>
          </Tooltip>
          <Tooltip content={TIPS.trade.assetClass}>
            <span className="text-[9px] text-white/30 font-mono hidden sm:inline cursor-help">
              {trade.asset_class}
            </span>
          </Tooltip>
        </div>
        <Tooltip content={TIPS.trade.direction}>
          <span
            className={clsx(
              'text-[9px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded text-center w-fit cursor-help',
              isBuy ? 'bg-cyan-400/10 text-cyan-300' : 'bg-pink-400/10 text-pink-300'
            )}
          >
            {trade.direction}
          </span>
        </Tooltip>
        <Tooltip content={`${TIPS.trade.entryPrice} · ${TIPS.trade.currentPrice}`}>
          <div className="text-xs text-white/60 font-mono tabular-nums truncate cursor-help">
            {formatPrice(trade.entry_price)}
            {trade.current_price !== null && (
              <>
                <span className="mx-1 opacity-40">→</span>
                <span className="text-white/80">{formatPrice(trade.current_price)}</span>
              </>
            )}
          </div>
        </Tooltip>
        <Tooltip content={trade.near_sl ? TIPS.trade.nearSl : TIPS.trade.distanceSl}>
          <div className="text-xs font-mono tabular-nums text-right text-white/50 cursor-help">
            {trade.distance_to_sl_pct !== null ? `SL ${trade.distance_to_sl_pct}%` : '—'}
          </div>
        </Tooltip>
        <Tooltip content={TIPS.trade.riskMoney}>
          <div className="text-xs font-mono tabular-nums text-right text-rose-300/80 cursor-help">
            {trade.risk_money !== null ? `-${formatPnl(trade.risk_money).replace('-', '')}` : '—'}
          </div>
        </Tooltip>
        <Tooltip content={`${TIPS.trade.pnlUnrealized}${trade.pnl_pips !== null ? ` · ${trade.pnl_pips} pips` : ''}`}>
          <div className={clsx('text-sm font-mono font-semibold tabular-nums text-right cursor-help', pnlTone)}>
            {trade.pnl_unrealized !== null ? formatPnl(trade.pnl_unrealized) : '—'}
          </div>
        </Tooltip>
      </div>
    </motion.div>
  );
}

/* ─────────── Fear & Greed gauge ─────────── */

function FearGreedGauge({ snapshot }: { snapshot: FearGreedSnapshot | null }) {
  if (!snapshot) {
    return (
      <GlassCard className="p-5 h-full">
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
  const classifTip = (TIPS.fearGreed as Record<string, string>)[classif] ?? TIPS.fearGreed.titre;
  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Fear &amp; Greed</h3>}
          tip={TIPS.fearGreed.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">CNN</span>
      </div>
      <Tooltip content={TIPS.fearGreed.titre}>
        <div className="flex items-baseline gap-3 mb-2 cursor-help">
          <span className="text-4xl font-bold font-mono tabular-nums">{v}</span>
          <span className="text-[10px] text-white/40 uppercase tracking-widest">/100</span>
        </div>
      </Tooltip>
      <div className="w-full h-2 rounded-full bg-white/5 overflow-hidden relative">
        <motion.div
          className={clsx('h-full rounded-full bg-gradient-to-r', cfg.tone)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.max(0, Math.min(100, v))}%` }}
          transition={{ duration: 0.7, ease: 'easeOut' }}
        />
      </div>
      <div className="mt-2 text-xs font-semibold uppercase tracking-wider">
        <Tooltip content={classifTip}>
          <span className={clsx('px-2 py-0.5 rounded-md border cursor-help', `bg-gradient-to-r ${cfg.tone} bg-clip-text text-transparent border-glass-soft`)}>
            {cfg.label}
          </span>
        </Tooltip>
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
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Santé système</h3>}
          tip={TIPS.sante.titre}
        />
        <StatusDot active={!healthy} />
      </div>
      <ul className="space-y-1.5 text-xs text-white/70">
        <li className="flex justify-between">
          <LabelWithInfo label="Cycle d'analyse" tip={TIPS.sante.cycle} />
          <span className={clsx('font-mono', healthy ? 'text-emerald-300' : 'text-rose-300')}>
            {secondsSince !== null ? `${Math.round(secondsSince)}s` : '—'}
          </span>
        </li>
        <li className="flex justify-between">
          <LabelWithInfo label="Bridge MT5" tip={TIPS.sante.bridge} />
          <span className={clsx('font-mono', bridgeReachable ? 'text-emerald-300' : bridgeConfigured ? 'text-rose-300' : 'text-white/30')}>
            {bridgeConfigured ? (bridgeReachable ? 'UP' : 'DOWN') : 'N/A'}
          </span>
        </li>
        <li className="flex justify-between">
          <LabelWithInfo label="Clients WS" tip={TIPS.sante.clientsWs} />
          <span className="font-mono">{wsClients}</span>
        </li>
        {sessionLabel && (
          <li className="flex justify-between">
            <LabelWithInfo label="Session" tip={TIPS.sante.session} />
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
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">COT extremes</h3>}
          tip={TIPS.cot.titre}
        />
        <Tooltip content={TIPS.cot.z}>
          <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider cursor-help">
            z ≥ 2σ / 52s
          </span>
        </Tooltip>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-white/40">Aucun extrême cette semaine.</p>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <div key={it.pair} className="border-l-2 border-cyan-400/30 pl-3">
              <div className="text-sm font-mono font-semibold">{it.pair}</div>
              {it.signals.map((s, i) => {
                const actorTip = (TIPS.cot as Record<string, string>)[s.actor] ?? TIPS.cot.titre;
                return (
                  <Tooltip key={i} content={actorTip}>
                    <div className="text-[11px] text-white/60 leading-snug cursor-help">
                      <span className="font-mono tabular-nums text-cyan-300 mr-1.5">z={s.z}</span>
                      {s.interpretation}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

/* ─────────── Drift card ─────────── */

function DriftCard() {
  const { data, isLoading } = useDrift();
  if (isLoading) return <Skeleton className="h-40" />;
  const byPair = data?.by_pair ?? [];
  const byPattern = data?.by_pattern ?? [];
  const top3 = [...byPair, ...byPattern].sort((a, b) => a.delta_pct - b.delta_pct).slice(0, 3);

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Drift détection</h3>}
          tip={TIPS.drift.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          {data?.window_days ?? 7}j vs baseline
        </span>
      </div>
      {data?.error ? (
        <p className="text-xs text-rose-300/80">{data.error}</p>
      ) : top3.length === 0 ? (
        <Tooltip content={TIPS.drift.action}>
          <p className="text-xs text-white/40 cursor-help">Aucune régression détectée.</p>
        </Tooltip>
      ) : (
        <div className="space-y-2">
          {top3.map((f: DriftFinding) => (
            <Tooltip key={f.key} content={`${TIPS.drift.delta} ${TIPS.drift.action}`}>
              <div className="w-full flex items-center justify-between text-xs cursor-help">
                <span className="font-mono text-white/85 truncate">{f.key}</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono tabular-nums text-white/50">
                    {f.recent_win_rate_pct}% ← {f.baseline_win_rate_pct}%
                  </span>
                  <span className="font-mono font-semibold tabular-nums text-rose-300">
                    {f.delta_pct}pts
                  </span>
                </div>
              </div>
            </Tooltip>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

/* ─────────── Next macro events ─────────── */

function NextEventsCard({
  events,
}: {
  events: Array<{ time: string; currency: string; impact: string; event_name: string }>;
}) {
  return (
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Events macro imminents</h3>}
          tip={TIPS.events.titre}
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          ≤ 4h
        </span>
      </div>
      {events.length === 0 ? (
        <p className="text-xs text-white/40">Aucun event imminent.</p>
      ) : (
        <div className="space-y-2">
          {events.map((e, i) => {
            const when = e.time?.includes('T')
              ? new Date(e.time).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
              : e.time;
            const impact = (e.impact || '').toUpperCase();
            const impactTone =
              impact === 'HIGH'
                ? 'text-rose-300 border-rose-400/30 bg-rose-400/5'
                : 'text-amber-300 border-amber-400/30 bg-amber-400/5';
            const impactTip =
              impact === 'HIGH'
                ? TIPS.events.impactHigh
                : impact === 'MEDIUM'
                ? TIPS.events.impactMedium
                : TIPS.events.impactLow;
            return (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-mono tabular-nums text-white/70 w-14 flex-shrink-0">
                    {when}
                  </span>
                  <Tooltip content={impactTip}>
                    <span className={clsx(
                      'text-[9px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border cursor-help',
                      impactTone
                    )}>
                      {e.impact || '—'}
                    </span>
                  </Tooltip>
                  <span className="font-mono text-white/60 text-[11px] flex-shrink-0">
                    {e.currency}
                  </span>
                </div>
                <span className="text-white/80 truncate ml-2 text-right">{e.event_name}</span>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
