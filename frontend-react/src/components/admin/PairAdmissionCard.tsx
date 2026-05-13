import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';

type State = 'OBSERVED' | 'TELEGRAM' | 'AUTO_EXEC' | 'PAUSED' | 'DEMOTED';

const STATE_STYLES: Record<State, { dot: string; label: string; bg: string }> = {
  OBSERVED: { dot: 'bg-white/30', label: 'text-white/60', bg: 'bg-white/[0.02]' },
  TELEGRAM: { dot: 'bg-amber-400', label: 'text-amber-300', bg: 'bg-amber-500/[0.06]' },
  AUTO_EXEC: { dot: 'bg-emerald-400', label: 'text-emerald-300', bg: 'bg-emerald-500/[0.06]' },
  PAUSED: { dot: 'bg-orange-400', label: 'text-orange-300', bg: 'bg-orange-500/[0.08]' },
  DEMOTED: { dot: 'bg-rose-500', label: 'text-rose-400', bg: 'bg-rose-500/[0.08]' },
};

const VALID_STATES: State[] = ['OBSERVED', 'TELEGRAM', 'AUTO_EXEC', 'PAUSED', 'DEMOTED'];

/**
 * Card admin Pair Admission Controller : matrice (pair × direction) avec
 * état courant + score live + bouton transition manuelle.
 *
 * Source : GET `/api/admin/pair-admission`. Refresh 30s.
 * Transitions : POST `/api/admin/pair-admission/{pair}/transition`.
 */
export function PairAdmissionCard() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'pair-admission'],
    queryFn: () => api.adminPairAdmission(),
    retry: 0,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const [modal, setModal] = useState<{ pair: string; direction: 'buy' | 'sell'; currentState: State } | null>(null);

  const transitionMut = useMutation({
    mutationFn: (vars: { pair: string; direction: 'buy' | 'sell'; to_state: string; reason: string }) =>
      api.adminPairAdmissionTransition(vars.pair, {
        to_state: vars.to_state,
        reason: vars.reason,
        direction: vars.direction,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'pair-admission'] });
      setModal(null);
    },
  });

  if (isLoading) return <Skeleton className="w-full h-64" />;
  if (error || !data) {
    const msg = error instanceof ApiError ? error.message : 'Indisponible';
    return (
      <GlassCard className="p-4">
        <h3 className="text-sm font-semibold text-rose-300 mb-1">Pair Admission</h3>
        <p className="text-xs text-white/60">{msg}</p>
      </GlassCard>
    );
  }

  // Group buckets par pair pour rendre une row = pair, 2 colonnes = buy + sell
  const byPair: Record<string, { buy?: typeof data.buckets[0]; sell?: typeof data.buckets[0] }> = {};
  for (const b of data.buckets) {
    if (!byPair[b.pair]) byPair[b.pair] = {};
    if (b.direction === 'buy') byPair[b.pair].buy = b;
    if (b.direction === 'sell') byPair[b.pair].sell = b;
  }
  const sortedPairs = Object.keys(byPair).sort();

  return (
    <GlassCard className="p-5 space-y-4 overflow-x-auto">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold tracking-tight">Pair Admission Controller</h3>
          <p className="text-[11px] text-white/50">
            State machine (pair × direction) · refresh 30s · transitions auto + override admin
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[10px]">
          {VALID_STATES.map((s) => (
            <span key={s} className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/5">
              <span className={clsx('w-2 h-2 rounded-full', STATE_STYLES[s].dot)} />
              <span className={STATE_STYLES[s].label}>
                {s}: {data.counts_by_state[s] ?? 0}
              </span>
            </span>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-xs border-separate border-spacing-y-1">
          <thead className="text-[10px] uppercase tracking-wider text-white/40">
            <tr>
              <th className="text-left px-2 py-1">Pair</th>
              <th className="text-left px-2 py-1">BUY</th>
              <th className="text-left px-2 py-1">SELL</th>
            </tr>
          </thead>
          <tbody>
            {sortedPairs.map((pair) => (
              <tr key={pair}>
                <td className="px-2 py-2 font-mono text-white/80 align-top">{pair}</td>
                {(['buy', 'sell'] as const).map((dir) => {
                  const b = byPair[pair][dir];
                  const state = (b?.state ?? 'OBSERVED') as State;
                  const style = STATE_STYLES[state];
                  const score = b?.current_score;
                  return (
                    <td key={dir} className={clsx('px-2 py-2 rounded', style.bg)}>
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <div className="flex items-center gap-1.5">
                          <span className={clsx('w-2 h-2 rounded-full', style.dot)} />
                          <span className={clsx('font-medium text-[11px]', style.label)}>
                            {state}
                          </span>
                        </div>
                        <button
                          onClick={() => setModal({ pair, direction: dir, currentState: state })}
                          className="px-2 py-0.5 rounded text-[10px] bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition"
                        >
                          Transition
                        </button>
                      </div>
                      {score && score.sample > 0 ? (
                        <div className="text-[10px] text-white/50 leading-relaxed">
                          n={score.sample} · pnl=
                          <span className={clsx(score.pnl_pct >= 0 ? 'text-emerald-300' : 'text-rose-300')}>
                            {score.pnl_pct >= 0 ? '+' : ''}
                            {score.pnl_pct}%
                          </span>{' '}
                          · WR {score.wr}% · PF {score.pf}
                          {score.max_dd_pct < 0 && (
                            <> · DD {score.max_dd_pct}%</>
                          )}
                        </div>
                      ) : (
                        <div className="text-[10px] text-white/30">no data</div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="text-[10px] text-white/40">
        <summary className="cursor-pointer hover:text-white/60">Seuils promotion auto (OBSERVED → TELEGRAM)</summary>
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-2">
          <span>sample ≥ {data.thresholds.promote_min_sample}</span>
          <span>pnl_pct ≥ {data.thresholds.promote_min_pnl_pct}%</span>
          <span>WR ≥ {data.thresholds.promote_min_wr_pct}%</span>
          <span>PF ≥ {data.thresholds.promote_min_pf}</span>
          <span>maxDD &gt; -{data.thresholds.promote_max_dd_pct}%</span>
          <span>demote &gt; {data.thresholds.demote_max_re_pauses_60d}× pauses/60j</span>
        </div>
      </details>

      <AnimatePresence>
        {modal && (
          <TransitionModal
            pair={modal.pair}
            direction={modal.direction}
            currentState={modal.currentState}
            onClose={() => setModal(null)}
            onSubmit={(to_state, reason) =>
              transitionMut.mutate({
                pair: modal.pair,
                direction: modal.direction,
                to_state,
                reason,
              })
            }
            isPending={transitionMut.isPending}
            error={transitionMut.error instanceof ApiError ? transitionMut.error.message : null}
          />
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

function TransitionModal({
  pair,
  direction,
  currentState,
  onClose,
  onSubmit,
  isPending,
  error,
}: {
  pair: string;
  direction: 'buy' | 'sell';
  currentState: State;
  onClose: () => void;
  onSubmit: (toState: string, reason: string) => void;
  isPending: boolean;
  error: string | null;
}) {
  const [toState, setToState] = useState<string>(
    VALID_STATES.find((s) => s !== currentState) ?? 'AUTO_EXEC'
  );
  const [reason, setReason] = useState('');

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-white/10 bg-slate-900 p-5 space-y-4 shadow-2xl"
      >
        <div>
          <h3 className="text-sm font-semibold">Transition manuelle</h3>
          <p className="text-xs text-white/50 mt-1">
            <span className="font-mono">{pair}</span> · {direction.toUpperCase()} ·{' '}
            actuellement <span className={STATE_STYLES[currentState].label}>{currentState}</span>
          </p>
        </div>

        <div className="space-y-1">
          <label className="text-[11px] uppercase tracking-wider text-white/40">Nouvel état</label>
          <select
            value={toState}
            onChange={(e) => setToState(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-white/10 text-sm focus:border-cyan-400/40 outline-none"
          >
            {VALID_STATES.filter((s) => s !== currentState).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-[11px] uppercase tracking-wider text-white/40">
            Raison (audit log)
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="ex: V2_CORE_LONG XAU validé gate S6"
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-white/10 text-sm focus:border-cyan-400/40 outline-none resize-none"
          />
        </div>

        {error && (
          <div className="text-xs text-rose-300 px-3 py-2 rounded bg-rose-500/10 border border-rose-500/20">
            {error}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={isPending}
            className="px-3 py-1.5 rounded-lg text-xs text-white/60 hover:text-white/90 transition"
          >
            Annuler
          </button>
          <button
            onClick={() => reason.trim() && onSubmit(toState, reason.trim())}
            disabled={isPending || !reason.trim()}
            className="px-4 py-1.5 rounded-lg text-xs font-medium bg-cyan-400/20 border border-cyan-400/40 text-cyan-200 hover:bg-cyan-400/30 transition disabled:opacity-50"
          >
            {isPending ? 'En cours…' : `Transitionner → ${toState}`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
