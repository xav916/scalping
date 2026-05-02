import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';

/**
 * Card "Auto-exec health" — vue par user des users avec auto_exec_enabled :
 * heartbeat EA, breakdown des ordres 24h, taux de succès, zombies (SENT > 5min,
 * PENDING > 80% TTL), dernier ordre pour preview.
 *
 * Refresh 30s. Lecture seule pour V1 — pas d'action depuis cette card.
 */

const STATUS_TONE = {
  EXECUTED: { bg: 'bg-emerald-500/15', border: 'border-emerald-400/30', text: 'text-emerald-300' },
  PENDING:  { bg: 'bg-cyan-500/10',    border: 'border-cyan-400/25',    text: 'text-cyan-300' },
  SENT:     { bg: 'bg-amber-500/10',   border: 'border-amber-400/25',   text: 'text-amber-300' },
  FAILED:   { bg: 'bg-rose-500/15',    border: 'border-rose-400/30',    text: 'text-rose-300' },
  EXPIRED:  { bg: 'bg-white/5',        border: 'border-white/15',       text: 'text-white/50' },
} as const;

const HEARTBEAT_TONE = {
  LIVE:    { dot: 'bg-emerald-400 animate-pulse', text: 'text-emerald-300' },
  STALE:   { dot: 'bg-amber-400',                 text: 'text-amber-300' },
  OFFLINE: { dot: 'bg-rose-400',                  text: 'text-rose-300' },
};

function formatHeartbeatAge(ageSeconds: number | null): string {
  if (ageSeconds === null) return 'jamais';
  if (ageSeconds < 60) return `${ageSeconds}s`;
  if (ageSeconds < 3600) return `${Math.round(ageSeconds / 60)} min`;
  return `${Math.round(ageSeconds / 3600)} h`;
}

function formatRate(rate: number | null): string {
  if (rate === null) return '—';
  return `${Math.round(rate * 100)}%`;
}

function rateTone(rate: number | null): string {
  if (rate === null) return 'text-white/40';
  if (rate >= 0.9) return 'text-emerald-300';
  if (rate >= 0.7) return 'text-amber-300';
  return 'text-rose-300';
}

export function AutoExecHealthCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'autoExecHealth'],
    queryFn: api.adminAutoExecHealth,
    retry: 0,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  if (isLoading) {
    return <Skeleton className="w-full h-48" />;
  }
  if (error || !data) {
    const msg = error instanceof ApiError ? error.message : 'Indisponible';
    return (
      <GlassCard className="p-4">
        <h3 className="text-sm font-semibold text-rose-300 mb-1">Auto-exec EA</h3>
        <p className="text-xs text-white/60">{msg}</p>
      </GlassCard>
    );
  }

  const t = data.totals;

  return (
    <GlassCard className="p-5 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-white/85">
            Auto-exec EA — santé du pipeline
          </h3>
          <p className="text-[11px] text-white/40 mt-0.5">
            Refresh 30s · {t.users_with_auto_exec} user{t.users_with_auto_exec > 1 ? 's' : ''} actif{t.users_with_auto_exec > 1 ? 's' : ''}
            · {t.orders_24h} ordres 24h
            {t.zombies_total > 0 && (
              <span className="ml-2 text-rose-300 font-semibold">
                · {t.zombies_total} zombie{t.zombies_total > 1 ? 's' : ''}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-400/30">
            {t.users_live} live
          </span>
          {t.users_stale > 0 && (
            <span className="px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-300 border border-amber-400/30">
              {t.users_stale} stale
            </span>
          )}
          {t.users_offline > 0 && (
            <span className="px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-300 border border-rose-400/30">
              {t.users_offline} offline
            </span>
          )}
        </div>
      </div>

      {data.users.length === 0 && (
        <div className="p-3 rounded-lg bg-white/5 border border-white/10 text-center">
          <span className="text-white/60 text-xs">
            Aucun user avec auto_exec_enabled. Active depuis /v2/settings → Auto-exec MT5.
          </span>
        </div>
      )}

      <div className="space-y-2">
        {data.users.map((u) => {
          const hb = HEARTBEAT_TONE[u.heartbeat.status];
          const bs = u.orders_24h.by_status;
          const hasZombies = u.zombies.total > 0;

          return (
            <motion.div
              key={u.user_id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className={`p-3 rounded-lg space-y-2 border ${
                hasZombies
                  ? 'bg-rose-500/5 border-rose-400/30'
                  : 'bg-white/[0.03] border-white/10'
              }`}
            >
              {/* Header user : email + heartbeat */}
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${hb.dot}`} />
                  <span className="text-sm font-mono text-white/85 truncate">
                    {u.email}
                  </span>
                  <span className={`text-[10px] uppercase tracking-wider font-semibold ${hb.text}`}>
                    {u.heartbeat.status}
                  </span>
                  <span className="text-[10px] text-white/40">
                    · {formatHeartbeatAge(u.heartbeat.age_seconds)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="text-white/40">Taux 24h :</span>
                  <span className={`font-semibold tabular-nums ${rateTone(u.orders_24h.executed_rate)}`}>
                    {formatRate(u.orders_24h.executed_rate)}
                  </span>
                </div>
              </div>

              {/* Breakdown chips */}
              {u.orders_24h.total === 0 ? (
                <div className="text-[11px] text-white/40 italic">
                  Aucun ordre sur les 24 dernières heures.
                </div>
              ) : (
                <div className="flex items-center gap-1.5 flex-wrap">
                  {(['EXECUTED', 'PENDING', 'SENT', 'FAILED', 'EXPIRED'] as const).map((st) => {
                    const n = bs[st] ?? 0;
                    if (n === 0) return null;
                    const tone = STATUS_TONE[st];
                    return (
                      <span
                        key={st}
                        className={`px-2 py-0.5 rounded-md text-[10px] font-mono border ${tone.bg} ${tone.border} ${tone.text}`}
                      >
                        {st} {n}
                      </span>
                    );
                  })}
                </div>
              )}

              {/* Zombies en alerte */}
              {hasZombies && (
                <div className="flex items-center gap-2 text-[10px] text-rose-300">
                  <span className="font-semibold">⚠ Zombies :</span>
                  {u.zombies.sent_stale > 0 && (
                    <span>{u.zombies.sent_stale} SENT depuis &gt; 5min</span>
                  )}
                  {u.zombies.pending_overdue > 0 && (
                    <span>· {u.zombies.pending_overdue} PENDING overdue</span>
                  )}
                </div>
              )}

              {/* Dernier ordre */}
              {u.last_order && (
                <div className="text-[10px] text-white/50 font-mono pt-1 border-t border-white/5">
                  Dernier : {u.last_order.pair} {u.last_order.direction?.toUpperCase()}
                  {' · '}
                  <span className={STATUS_TONE[u.last_order.status as keyof typeof STATUS_TONE]?.text ?? 'text-white/60'}>
                    {u.last_order.status}
                  </span>
                  {u.last_order.mt5_ticket != null && (
                    <span className="text-white/40"> · ticket {u.last_order.mt5_ticket}</span>
                  )}
                  {u.last_order.mt5_error && (
                    <span className="text-rose-400"> · {u.last_order.mt5_error}</span>
                  )}
                </div>
              )}
            </motion.div>
          );
        })}
      </div>
    </GlassCard>
  );
}
