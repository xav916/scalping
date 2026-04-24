import { useState } from 'react';
import { motion } from 'motion/react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';

/**
 * /v2/admin — Backoffice privé :
 *  - KPIs : total users, signups 7j/30j, trials actifs, MRR estimé
 *  - Table users avec tier effectif, cycle, trial days restants, Stripe status
 *
 * Accès gated côté backend (require_admin : ADMIN_EMAILS env + legacy).
 * Si 403, on redirige l'utilisateur vers le dashboard.
 */
export function AdminPage() {
  const queryClient = useQueryClient();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: api.adminUsers,
    retry: 0,
    refetchInterval: 30_000,  // live-ish
    staleTime: 10_000,
  });

  const deleteUser = useMutation({
    mutationFn: (userId: number) => api.adminDeleteUser(userId),
    onSuccess: () => {
      setDeleteError(null);
      queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError ? err.message || `HTTP ${err.status}` : String(err);
      setDeleteError(msg);
    },
  });

  const onDelete = (userId: number, email: string) => {
    if (!window.confirm(`Supprimer définitivement ${email} ?\n\nRéservé aux users de test. Un user avec des trades liés sera refusé (409) — utiliser le soft delete côté user.`)) {
      return;
    }
    deleteUser.mutate(userId);
  };

  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <GlassCard className="p-8 max-w-sm text-center">
          <p className="text-white/80 mb-4">Accès admin requis.</p>
          <Link to="/dashboard" className="text-cyan-400 hover:text-cyan-300 text-sm">
            ← Retour au dashboard
          </Link>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="min-h-screen py-10 px-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="max-w-6xl mx-auto space-y-6"
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-1">
            <GradientText>Backoffice admin</GradientText>
          </h1>
          <p className="text-sm text-white/50">
            Vue interne : users, trials, MRR. Refresh toutes les 30s.
          </p>
        </div>

        {isLoading && <Skeleton className="w-full h-48" />}

        {data && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard label="Total users" value={data.totals.total_users} />
              <KpiCard
                label="Signups 7j"
                value={data.totals.signups_7d}
                sub={`${data.totals.signups_30d} sur 30j`}
              />
              <KpiCard
                label="Trials actifs"
                value={data.totals.trials_active}
                sub={
                  data.totals.trials_j3_or_less > 0
                    ? `${data.totals.trials_j3_or_less} à J-3 ou moins`
                    : 'aucun urgent'
                }
                accent={data.totals.trials_j3_or_less > 0 ? 'amber' : undefined}
              />
              <KpiCard
                label="MRR estimé"
                value={`${data.totals.mrr_eur.toFixed(2)}€`}
                sub="Revenu mensuel récurrent"
                accent="cyan"
              />
            </div>

            {/* Breakdown by tier */}
            <GlassCard className="p-4">
              <h2 className="text-sm uppercase tracking-wider text-white/50 mb-3">
                Répartition par tier effectif
              </h2>
              <div className="flex gap-4 flex-wrap text-sm">
                <TierBadge tier="free" count={data.totals.by_tier.free ?? 0} />
                <TierBadge tier="pro" count={data.totals.by_tier.pro ?? 0} />
                <TierBadge tier="premium" count={data.totals.by_tier.premium ?? 0} />
              </div>
            </GlassCard>

            {/* Users table */}
            <GlassCard variant="elevated" className="p-4 overflow-x-auto">
              <h2 className="text-sm uppercase tracking-wider text-white/50 mb-3">
                Tous les users ({data.users.length})
              </h2>
              <table className="w-full text-xs">
                <thead className="text-white/40 border-b border-white/10">
                  <tr>
                    <th className="text-left py-2 font-medium">Email</th>
                    <th className="text-left font-medium">Tier</th>
                    <th className="text-left font-medium">Cycle</th>
                    <th className="text-left font-medium">Trial</th>
                    <th className="text-left font-medium">Stripe</th>
                    <th className="text-left font-medium">Signup</th>
                    <th className="text-left font-medium">Last login</th>
                    <th className="text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <tr key={u.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                      <td className="py-2 font-mono">
                        {u.email}
                        {!u.is_active && (
                          <span className="ml-2 text-rose-400 text-[10px]">INACTIF</span>
                        )}
                      </td>
                      <td>
                        <TierPill tier={u.tier_effective} />
                        {u.tier_stored !== u.tier_effective && (
                          <span className="ml-1 text-white/30 text-[10px]">
                            ({u.tier_stored})
                          </span>
                        )}
                      </td>
                      <td className="text-white/60">{u.billing_cycle ?? '—'}</td>
                      <td>
                        {u.trial_active && u.trial_days_left !== null ? (
                          <span
                            className={
                              u.trial_days_left <= 3 ? 'text-amber-300' : 'text-cyan-300'
                            }
                          >
                            J-{u.trial_days_left}
                          </span>
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="text-white/60">
                        {u.stripe_subscription_set
                          ? '💳 sub'
                          : u.stripe_customer_set
                            ? 'customer'
                            : '—'}
                      </td>
                      <td className="text-white/50">
                        {u.created_at
                          ? new Date(u.created_at).toLocaleDateString('fr-FR')
                          : '—'}
                      </td>
                      <td className="text-white/50">
                        {u.last_login_at
                          ? new Date(u.last_login_at).toLocaleDateString('fr-FR')
                          : 'jamais'}
                      </td>
                      <td className="text-right">
                        <button
                          onClick={() => onDelete(u.id, u.email)}
                          disabled={deleteUser.isPending}
                          className="text-rose-400/70 hover:text-rose-300 disabled:opacity-30 text-[11px] uppercase tracking-wider transition-colors"
                          title="Hard delete (users de test). Les users avec trades sont bloqués 409."
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {deleteError && (
                <div className="mt-3 text-[11px] text-rose-300/80">
                  Erreur delete : {deleteError}
                </div>
              )}
            </GlassCard>
          </>
        )}
      </motion.div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: 'cyan' | 'amber';
}) {
  const accentClass =
    accent === 'cyan' ? 'text-cyan-300' : accent === 'amber' ? 'text-amber-300' : 'text-white';
  return (
    <GlassCard className="p-4">
      <div className="text-[10px] uppercase tracking-wider text-white/40">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accentClass}`}>{value}</div>
      {sub && <div className="text-[11px] text-white/50 mt-0.5">{sub}</div>}
    </GlassCard>
  );
}

function TierBadge({ tier, count }: { tier: string; count: number }) {
  return (
    <div className="flex items-center gap-2">
      <TierPill tier={tier} />
      <span className="font-mono">{count}</span>
    </div>
  );
}

function TierPill({ tier }: { tier: string }) {
  const styles =
    tier === 'premium'
      ? 'bg-pink-400/20 text-pink-200 border-pink-400/30'
      : tier === 'pro'
        ? 'bg-cyan-400/20 text-cyan-200 border-cyan-400/30'
        : 'bg-white/10 text-white/60 border-white/10';
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider border ${styles}`}>
      {tier}
    </span>
  );
}
