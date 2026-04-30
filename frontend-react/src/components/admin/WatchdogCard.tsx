import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { motion } from 'motion/react';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';

/**
 * Card Watchdog SL : visualise l'état du circuit breaker (pauses actives,
 * SL 24h, tentatives V1 sur pairs paused) + permet l'unpause manuel.
 *
 * Refresh auto toutes les 15s pour suivre les transitions smart resume.
 */
export function WatchdogCard() {
  const queryClient = useQueryClient();
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'watchdog'],
    queryFn: api.adminWatchdogState,
    retry: 0,
    refetchInterval: 15_000,
    staleTime: 5_000,
  });

  const unpause = useMutation({
    mutationFn: (body: { pair?: string; global?: boolean; all?: boolean }) =>
      api.adminWatchdogUnpause(body),
    onSuccess: (res) => {
      const parts: string[] = [];
      if (res.cleared.pairs.length) parts.push(`pairs: ${res.cleared.pairs.join(', ')}`);
      if (res.cleared.global) parts.push('global');
      setActionMsg(`Unpause OK — ${parts.join(' + ') || 'rien'}`);
      setTimeout(() => setActionMsg(null), 4000);
      queryClient.invalidateQueries({ queryKey: ['admin', 'watchdog'] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : String(err);
      setActionMsg(`Erreur : ${msg}`);
      setTimeout(() => setActionMsg(null), 6000);
    },
  });

  if (isLoading) return <Skeleton className="w-full h-48" />;
  if (error || !data) {
    const msg = error instanceof ApiError ? error.message : 'Indisponible';
    return (
      <GlassCard className="p-4">
        <h3 className="text-sm font-semibold text-rose-300 mb-1">Watchdog SL</h3>
        <p className="text-xs text-white/60">{msg}</p>
      </GlassCard>
    );
  }

  const hasAnyPause = data.paused_pairs_count > 0 || data.global_rafale_pause_active;

  return (
    <GlassCard className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white/85">
            Watchdog stops loss — circuit breaker
          </h3>
          <p className="text-[11px] text-white/40 mt-0.5">
            Refresh 15s · Total SL 24h : {data.total_sl_24h}
          </p>
        </div>
        {hasAnyPause && (
          <button
            onClick={() => {
              if (window.confirm('Clear TOUTES les pauses (global + per-pair) ?')) {
                unpause.mutate({ all: true });
              }
            }}
            disabled={unpause.isPending}
            className="px-3 py-1.5 text-[11px] uppercase tracking-wider rounded-lg
                       bg-rose-500/20 hover:bg-rose-500/30 border border-rose-400/30
                       text-rose-200 disabled:opacity-50"
          >
            Clear all
          </button>
        )}
      </div>

      {/* Pause globale (filet de sécu) */}
      {data.global_rafale_pause_active && data.global_rafale_pause_info && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-3 rounded-lg bg-rose-500/10 border border-rose-400/30 space-y-2"
        >
          <div className="flex items-center gap-2">
            <span className="text-rose-300 text-xs font-semibold">⛔ PAUSE GLOBALE</span>
            <span className="text-[10px] text-white/50">
              {data.global_rafale_pause_info.trigger_type}
            </span>
          </div>
          <div className="text-[11px] text-white/70">
            {data.global_rafale_pause_info.reason}
          </div>
          <div className="text-[10px] text-white/40 font-mono">
            Triggered : {fmtIso(data.global_rafale_pause_info.triggered_at)} ·
            Expire : {fmtIso(data.global_rafale_pause_info.expires_at)}
          </div>
          <button
            onClick={() => unpause.mutate({ global: true })}
            disabled={unpause.isPending}
            className="px-3 py-1 text-[11px] rounded-md bg-white/10 hover:bg-white/20
                       text-white/80 border border-white/20 disabled:opacity-50"
          >
            Unpause global
          </button>
        </motion.div>
      )}

      {/* Pauses per-pair */}
      {data.paused_pairs_count === 0 && !data.global_rafale_pause_active ? (
        <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-400/20 text-center">
          <span className="text-emerald-300 text-xs">
            ✓ Aucune pause active. Circuit breaker en veille.
          </span>
        </div>
      ) : (
        <div className="space-y-2">
          {Object.entries(data.paused_pairs).map(([pair, info]) => (
            <motion.div
              key={pair}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              className="p-3 rounded-lg bg-amber-500/10 border border-amber-400/30 space-y-2"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-amber-200">{pair}</div>
                  <div className="text-[11px] text-white/60">{info.reason}</div>
                </div>
                <button
                  onClick={() => unpause.mutate({ pair })}
                  disabled={unpause.isPending}
                  className="shrink-0 px-3 py-1 text-[11px] rounded-md bg-white/10
                             hover:bg-white/20 text-white/80 border border-white/20
                             disabled:opacity-50"
                >
                  Unpause
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[10px] font-mono text-white/50">
                <div>
                  <div className="text-white/40 uppercase tracking-wider">Pattern</div>
                  <div className="text-white/80">{info.failed_pattern || 'N/A'}</div>
                </div>
                <div>
                  <div className="text-white/40 uppercase tracking-wider">Direction</div>
                  <div className="text-white/80">{info.failed_direction || 'N/A'}</div>
                </div>
                <div>
                  <div className="text-white/40 uppercase tracking-wider">Min resume</div>
                  <div>{fmtIso(info.min_resume_at)}</div>
                </div>
                <div>
                  <div className="text-white/40 uppercase tracking-wider">Max resume</div>
                  <div>{fmtIso(info.max_resume_at)}</div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {actionMsg && (
        <div className="text-[11px] text-cyan-300 px-2 py-1 rounded bg-cyan-500/10 border border-cyan-400/20">
          {actionMsg}
        </div>
      )}

      {/* Breakdown SL 24h */}
      {data.sl_breakdown_24h.length > 0 && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-2">
            SL 24h — top patterns × pairs ({data.sl_breakdown_24h.length})
          </h4>
          <div className="space-y-1">
            {data.sl_breakdown_24h.slice(0, 6).map((row, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between gap-3 text-[11px]
                           px-2 py-1 rounded bg-white/5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-white/80 font-medium">{row.pair}</span>
                  <span className="text-white/40 text-[10px]">{row.pattern || '?'}</span>
                </div>
                <div className="flex items-center gap-3 font-mono text-[10px]">
                  <span className="text-white/60">{row.count} SL</span>
                  <span className={
                    row.pnl_total !== null && row.pnl_total < 0
                      ? 'text-rose-300'
                      : 'text-white/40'
                  }>
                    {row.pnl_total !== null ? `${row.pnl_total.toFixed(2)} €` : '—'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tentatives V1 bloquées sur pair paused — utile pour smart resume diag */}
      {data.rejected_attempts_24h.length > 0 && (
        <div>
          <h4 className="text-[11px] uppercase tracking-wider text-white/40 mb-2">
            V1 a tenté sur pairs paused (24h)
          </h4>
          <div className="space-y-1">
            {data.rejected_attempts_24h.slice(0, 5).map((row, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between gap-3 text-[11px]
                           px-2 py-1 rounded bg-amber-500/5"
              >
                <div className="flex items-center gap-2">
                  <span className="text-white/80">{row.pair}</span>
                  <span className="text-white/40 text-[10px]">{row.pattern || '?'}</span>
                </div>
                <span className="font-mono text-[10px] text-amber-200">
                  {row.count} tentatives
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function fmtIso(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit',
      day: '2-digit',
      month: '2-digit',
    });
  } catch {
    return iso.slice(0, 16);
  }
}
