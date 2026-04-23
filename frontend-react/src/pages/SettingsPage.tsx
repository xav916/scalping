import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';

/**
 * /v2/settings — gestion du compte user :
 *  1. Profil (email, logout)
 *  2. Abonnement (tier effectif, trial days restants, CTA portal/upgrade)
 *  3. Pairs surveillées (édition avec cap par tier)
 *  4. Auto-exec MT5 (optionnel, section repliée par défaut) — Chantier pivot
 *     signal-only. L'user peut configurer son bridge MT5 pour auto-exec,
 *     mais ce n'est plus requis ni central au produit.
 */

const ALL_PAIRS = [
  'EUR/USD', 'GBP/USD', 'USD/JPY', 'EUR/GBP', 'USD/CHF',
  'AUD/USD', 'USD/CAD', 'EUR/JPY', 'GBP/JPY',
  'XAU/USD', 'XAG/USD',
  'BTC/USD', 'ETH/USD',
  'SPX', 'NDX', 'WTI/USD',
];

export function SettingsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { whoami, logout } = useAuth();

  const tier = useQuery({
    queryKey: ['user', 'tier'],
    queryFn: api.userTier,
    retry: 0,
    staleTime: 60_000,
  });

  const pairsQ = useQuery({
    queryKey: ['user', 'watched-pairs'],
    queryFn: api.userWatchedPairsGet,
    staleTime: 60_000,
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Hydrate l'état local depuis l'API quand la query répond.
  useEffect(() => {
    if (pairsQ.data?.pairs) {
      setSelected(new Set(pairsQ.data.pairs));
    }
  }, [pairsQ.data]);

  const cap = pairsQ.data?.cap ?? 1;
  const currentTier = tier.data?.tier ?? 'free';
  const tierLabel = currentTier.charAt(0).toUpperCase() + currentTier.slice(1);

  const savePairsMut = useMutation({
    mutationFn: () => api.userWatchedPairsPut(Array.from(selected)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user', 'watched-pairs'] });
    },
  });

  const portalMut = useMutation({
    mutationFn: () => api.stripePortal(),
    onSuccess: (data) => {
      if (data.url) window.location.href = data.url;
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 400) {
        navigate('/pricing');
      } else {
        alert('Impossible d\'ouvrir le portail Stripe');
      }
    },
  });

  const togglePair = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else if (next.size < cap) next.add(p);
      return next;
    });
  };

  const handleLogout = () => {
    logout.mutate(undefined, {
      onSuccess: () => navigate('/'),
    });
  };

  const pairsDirty =
    pairsQ.data?.pairs &&
    (selected.size !== pairsQ.data.pairs.length ||
      Array.from(selected).some((p) => !pairsQ.data!.pairs.includes(p)));

  // ─── Section Bridge (optionnelle, repliable) ────────────────────
  const brokerQ = useQuery({
    queryKey: ['user', 'broker'],
    queryFn: api.userBrokerGet,
    retry: 0,
    staleTime: 60_000,
  });
  const [bridgeOpen, setBridgeOpen] = useState(false);
  const [bridgeUrl, setBridgeUrl] = useState('');
  const [bridgeApiKey, setBridgeApiKey] = useState('');
  const [bridgeTestResult, setBridgeTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  // Hydrate bridgeUrl depuis la query quand elle répond.
  useEffect(() => {
    if (brokerQ.data?.bridge_url && !bridgeUrl) {
      setBridgeUrl(brokerQ.data.bridge_url);
    }
  }, [brokerQ.data, bridgeUrl]);

  const testBridgeMut = useMutation({
    mutationFn: () => api.userBrokerTest(bridgeUrl, bridgeApiKey),
    onSuccess: (data) => {
      if (data.ok && data.reachable) {
        setBridgeTestResult({ ok: true, msg: 'Bridge joignable ✓' });
      } else {
        setBridgeTestResult({ ok: false, msg: data.error || 'Bridge injoignable' });
      }
    },
    onError: () => setBridgeTestResult({ ok: false, msg: 'Erreur de test' }),
  });

  const saveBridgeMut = useMutation({
    mutationFn: () => api.userBrokerPut(bridgeUrl, bridgeApiKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user', 'broker'] });
      setBridgeApiKey(''); // clear after save
    },
  });

  return (
    <div className="min-h-screen py-10 px-4">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="max-w-3xl mx-auto space-y-6"
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight mb-1">
            <GradientText>Paramètres</GradientText>
          </h1>
          <p className="text-sm text-white/50">Gère ton compte, ton plan et tes paires surveillées.</p>
        </div>

        {/* ─── Profil ─── */}
        <GlassCard variant="elevated" className="p-6">
          <h2 className="text-lg font-semibold mb-4">Profil</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between items-center">
              <dt className="text-white/50">Email</dt>
              <dd className="font-mono">{whoami.data?.username ?? '…'}</dd>
            </div>
            <div className="flex justify-between items-center pt-3 border-t border-white/5">
              <dt className="text-white/50">Session</dt>
              <dd>
                <button
                  onClick={handleLogout}
                  className="text-xs uppercase tracking-wider text-rose-300 hover:text-rose-200"
                >
                  Se déconnecter →
                </button>
              </dd>
            </div>
          </dl>
        </GlassCard>

        {/* ─── Abonnement ─── */}
        <GlassCard variant="elevated" className="p-6">
          <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
            <div>
              <h2 className="text-lg font-semibold mb-1">Abonnement</h2>
              <p className="text-sm text-white/50">
                Tier actuel :{' '}
                <span
                  className={`font-semibold ${
                    currentTier === 'premium'
                      ? 'text-pink-300'
                      : currentTier === 'pro'
                        ? 'text-cyan-300'
                        : 'text-white/80'
                  }`}
                >
                  {tierLabel}
                </span>
                {tier.data?.billing_cycle && (
                  <span className="text-white/40">
                    {' '}
                    · facturation{' '}
                    {tier.data.billing_cycle === 'yearly' ? 'annuelle' : 'mensuelle'}
                  </span>
                )}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => navigate('/pricing')}
                className="px-4 py-2 rounded-xl border border-white/15 text-white/80 text-sm hover:bg-white/5"
              >
                Voir les plans
              </button>
              {tier.data?.stripe_customer_set && (
                <button
                  onClick={() => portalMut.mutate()}
                  disabled={portalMut.isPending}
                  className="px-4 py-2 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-50"
                >
                  {portalMut.isPending ? 'Ouverture…' : 'Gérer (Stripe)'}
                </button>
              )}
            </div>
          </div>

          {tier.data?.trial_active && tier.data.trial_days_left !== null && (
            <div className="p-3 rounded-xl bg-cyan-400/10 border border-cyan-400/30 text-sm">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
                <span className="text-cyan-200">
                  Trial Pro actif — il te reste{' '}
                  <strong>
                    {tier.data.trial_days_left}{' '}
                    jour{(tier.data.trial_days_left ?? 0) > 1 ? 's' : ''}
                  </strong>
                  {tier.data.trial_ends_at && (
                    <>
                      {' '}(jusqu'au{' '}
                      {new Date(tier.data.trial_ends_at).toLocaleDateString('fr-FR')})
                    </>
                  )}
                </span>
              </div>
              <button
                onClick={() => navigate('/pricing')}
                className="mt-2 text-xs uppercase tracking-wider text-cyan-300 hover:text-cyan-200"
              >
                Passer en abonnement payant →
              </button>
            </div>
          )}

          {!tier.data?.stripe_customer_set && !tier.data?.trial_active && currentTier === 'free' && (
            <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-sm text-white/70">
              Tu es sur le plan Free (1 paire, 7j d'historique). Upgrade pour
              débloquer les features complètes.
            </div>
          )}
        </GlassCard>

        {/* ─── Pairs surveillées ─── */}
        <GlassCard variant="elevated" className="p-6">
          <div className="flex items-start justify-between mb-4 flex-wrap gap-2">
            <div>
              <h2 className="text-lg font-semibold mb-1">Paires surveillées</h2>
              <p className="text-sm text-white/50">
                {selected.size} / {cap} sélectionnée{selected.size > 1 ? 's' : ''} ·
                Cap selon tier <strong className="capitalize">{tierLabel}</strong>
              </p>
            </div>
            <button
              onClick={() => savePairsMut.mutate()}
              disabled={!pairsDirty || savePairsMut.isPending || selected.size === 0}
              className="px-4 py-2 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
            >
              {savePairsMut.isPending ? 'Enregistrement…' : 'Enregistrer'}
            </button>
          </div>

          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {ALL_PAIRS.map((p) => {
              const isSel = selected.has(p);
              const isDisabled = !isSel && selected.size >= cap;
              return (
                <button
                  key={p}
                  onClick={() => togglePair(p)}
                  disabled={isDisabled}
                  className={`px-3 py-2 rounded-lg text-sm font-mono transition-all ${
                    isSel
                      ? 'bg-cyan-400/20 border border-cyan-400/50 text-cyan-200'
                      : isDisabled
                        ? 'bg-white/5 border border-white/10 text-white/30 cursor-not-allowed'
                        : 'bg-white/5 border border-white/10 text-white/70 hover:border-white/20'
                  }`}
                >
                  {p}
                </button>
              );
            })}
          </div>

          {savePairsMut.isSuccess && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-xs text-emerald-400 mt-3"
            >
              Paires enregistrées ✓
            </motion.p>
          )}
        </GlassCard>

        {/* ─── Bridge MT5 (optionnel, Premium) ─── */}
        <GlassCard className="p-6">
          <button
            onClick={() => setBridgeOpen((o) => !o)}
            className="w-full flex items-start justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold flex items-center gap-2">
                Auto-exec MT5
                <span className="px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-pink-400/20 text-pink-300 border border-pink-400/30">
                  Premium
                </span>
                <span className="text-xs text-white/40 font-normal">· optionnel</span>
              </h2>
              <p className="text-sm text-white/50 mt-1">
                {brokerQ.data?.api_key_set
                  ? `Bridge configuré : ${brokerQ.data.bridge_url}`
                  : 'Connecte ton bridge MT5 pour auto-exécuter les setups directement sur ton compte.'}
              </p>
            </div>
            <span className="text-white/40 text-xl ml-4 shrink-0">
              {bridgeOpen ? '−' : '+'}
            </span>
          </button>

          {bridgeOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="mt-5 pt-5 border-t border-white/10 space-y-3"
            >
              <p className="text-sm text-white/60">
                Installation requise : <a href="/docs/bridge-setup.html" target="_blank" rel="noopener noreferrer" className="text-cyan-400 hover:text-cyan-300 underline">voir le guide</a>.
                Tu as besoin de Tailscale + MetaTrader 5 + le bridge Windows sur un PC ou VPS 24/5.
              </p>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  URL du bridge
                </label>
                <input
                  type="url"
                  value={bridgeUrl}
                  onChange={(e) => {
                    setBridgeUrl(e.target.value);
                    setBridgeTestResult(null);
                  }}
                  placeholder="http://100.x.y.z:8787"
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:outline-none font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  API key
                </label>
                <input
                  type="password"
                  value={bridgeApiKey}
                  onChange={(e) => {
                    setBridgeApiKey(e.target.value);
                    setBridgeTestResult(null);
                  }}
                  placeholder={brokerQ.data?.api_key_set ? '•••••••• (laisser vide pour ne pas changer)' : 'min 16 caractères'}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:outline-none font-mono text-sm"
                />
              </div>

              {bridgeTestResult && (
                <p className={`text-sm ${bridgeTestResult.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {bridgeTestResult.msg}
                </p>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => testBridgeMut.mutate()}
                  disabled={testBridgeMut.isPending || !bridgeUrl || bridgeApiKey.length < 16}
                  className="flex-1 py-2 rounded-xl border border-cyan-400/30 text-cyan-300 text-sm font-medium disabled:opacity-40 hover:bg-cyan-400/10"
                >
                  {testBridgeMut.isPending ? 'Test…' : 'Tester'}
                </button>
                <button
                  onClick={() => saveBridgeMut.mutate()}
                  disabled={saveBridgeMut.isPending || !bridgeTestResult?.ok}
                  className="flex-1 py-2 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
                >
                  {saveBridgeMut.isPending ? 'Enregistrement…' : 'Enregistrer'}
                </button>
              </div>

              {saveBridgeMut.isSuccess && (
                <p className="text-xs text-emerald-400">Bridge enregistré ✓</p>
              )}
            </motion.div>
          )}
        </GlassCard>

        <p className="text-center text-xs text-white/30 pt-4">
          Scalping Radar v2 · 2026.04
        </p>
      </motion.div>
    </div>
  );
}
