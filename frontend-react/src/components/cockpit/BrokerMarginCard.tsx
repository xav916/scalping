import { useMemo } from 'react';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import { api } from '@/lib/api';
import { formatPnl } from '@/lib/format';
import type { BrokerAccount } from '@/types/domain';

/** Formate un montant en € sans décimales si > 100, sinon avec 2 décimales. */
function fmtMoney(n: number, currency = 'EUR'): string {
  const abs = Math.abs(n);
  const d = abs >= 100 ? 0 : 2;
  const fmt = n.toLocaleString('fr-FR', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
  return `${fmt} ${currency === 'EUR' ? '€' : currency}`;
}

function marginLevelTone(pct: number | null | undefined): {
  color: string;
  label: string;
} {
  if (pct == null) return { color: 'text-white/60', label: '—' };
  if (pct >= 500) return { color: 'text-emerald-300', label: 'sain' };
  if (pct >= 300) return { color: 'text-cyan-300', label: 'confortable' };
  if (pct >= 150) return { color: 'text-amber-300', label: 'attention' };
  if (pct >= 100) return { color: 'text-rose-300', label: 'critique' };
  return { color: 'text-red-500 font-bold', label: 'margin call' };
}

/** Carte compte broker : équité, marge utilisée/libre, margin level.
 *  Source : bridge `/account` proxifié par backend. Critique en live pour
 *  détecter un margin call imminent. */
export function BrokerMarginCard() {
  const { data, isLoading } = useQuery<BrokerAccount>({
    queryKey: ['broker-account'],
    queryFn: api.brokerAccount,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });

  const level = useMemo(
    () => marginLevelTone(data?.margin_level_pct),
    [data?.margin_level_pct]
  );

  return (
    <GlassCard variant="elevated" className="p-5">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <LabelWithInfo
          label={<h3 className="text-sm font-semibold tracking-tight">Compte broker</h3>}
          tip="État de ton compte Pepperstone demo en direct : balance, équité (balance + PnL flottant), marge utilisée (collatéral bloqué par le broker), marge libre (dispo pour nouveaux ordres), margin level (équité/marge). Critique pour le passage live."
        />
        {data?.reachable && (
          <span className="text-[10px] uppercase tracking-[0.2em] text-white/40 font-mono">
            login {data.login} · {data.currency ?? 'EUR'} · lev {data.leverage ?? '—'}:1
          </span>
        )}
      </div>

      {/* Reservation 120px : 5 KPIs en ligne + footer */}
      <div style={{ minHeight: 120 }}>
        {isLoading && !data ? (
          <Skeleton className="h-[100px] w-full" />
        ) : !data?.reachable ? (
          <div className="py-6 text-center">
            <div className="text-rose-300/80 text-sm font-mono">Bridge injoignable</div>
            <div className="text-white/40 text-[11px] mt-1 font-mono">
              {data?.configured === false
                ? 'Bridge non configuré côté radar'
                : `status ${data?.status ?? '?'} · ${data?.error ?? 'inconnu'}`}
            </div>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 pb-3 border-b border-glass-soft">
              <KpiBlock
                label="Balance"
                tip="Capital du compte, hors PnL des positions ouvertes."
                value={fmtMoney(data.balance ?? 0, data.currency)}
              />
              <KpiBlock
                label="Équité"
                tip="Balance + PnL flottant. = ce que tu aurais en cash si tu fermais tout maintenant."
                value={fmtMoney(data.equity ?? 0, data.currency)}
                sub={
                  <span
                    className={clsx(
                      'font-mono',
                      (data.profit ?? 0) > 0
                        ? 'text-emerald-300'
                        : (data.profit ?? 0) < 0
                        ? 'text-rose-300'
                        : 'text-white/50'
                    )}
                  >
                    {(data.profit ?? 0) >= 0 ? '+' : ''}
                    {formatPnl(data.profit ?? 0)} pnl
                  </span>
                }
              />
              <KpiBlock
                label="Marge utilisée"
                tip="Collatéral bloqué par le broker pour maintenir les positions ouvertes. Libéré au closing."
                value={fmtMoney(data.margin ?? 0, data.currency)}
                sub={
                  <span className="font-mono text-white/50">
                    {data.equity
                      ? `${((data.margin ?? 0) / data.equity * 100).toFixed(1)}% du compte`
                      : '—'}
                  </span>
                }
              />
              <KpiBlock
                label="Marge libre"
                tip="Capital dispo pour ouvrir d'autres positions sans margin call."
                value={
                  <span className="text-emerald-200/90">
                    {fmtMoney(data.margin_free ?? 0, data.currency)}
                  </span>
                }
              />
              <KpiBlock
                label="Margin level"
                tip="Équité / marge × 100. > 100% = safe. Sous 100% = broker ferme tes positions (margin call). Cible > 300% en live."
                value={
                  <span className={clsx('font-mono', level.color)}>
                    {data.margin_level_pct == null
                      ? '—'
                      : data.margin_level_pct >= 10_000
                      ? '∞'
                      : `${Math.round(data.margin_level_pct)}%`}
                  </span>
                }
                sub={<span className={clsx('text-[10px]', level.color)}>{level.label}</span>}
              />
            </div>

            <div className="mt-3 flex items-center justify-between text-[11px] text-white/50">
              <span className="font-mono">
                <span className="text-cyan-300/80">{data.positions_count ?? 0}</span> position
                {(data.positions_count ?? 0) > 1 ? 's' : ''} ouverte
                {(data.positions_count ?? 0) > 1 ? 's' : ''}
              </span>
              <Tooltip content="Latence côté broker via bridge — 1 refetch toutes les 10s.">
                <span className="text-[9px] uppercase tracking-wider text-white/30 font-mono">
                  live · 10s
                </span>
              </Tooltip>
            </div>
          </>
        )}
      </div>
    </GlassCard>
  );
}

function KpiBlock({
  label,
  tip,
  value,
  sub,
}: {
  label: string;
  tip: React.ReactNode;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div>
      <LabelWithInfo
        label={<span className="text-[9px] uppercase tracking-[0.2em] text-white/40">{label}</span>}
        tip={tip}
        className="mb-1"
      />
      <div className="text-lg sm:text-xl font-bold font-mono leading-tight tabular-nums">
        {value}
      </div>
      {sub && <div className="text-[10px] mt-1 font-mono">{sub}</div>}
    </div>
  );
}
