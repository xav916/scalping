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

  // ─── Section Auto-exec EA MQL5 (Phase MQL.E) ─────────────────────
  const brokerQ = useQuery({
    queryKey: ['user', 'broker'],
    queryFn: api.userBrokerGet,
    retry: 0,
    staleTime: 60_000,
  });
  const [eaOpen, setEaOpen] = useState(false);
  const [revealedApiKey, setRevealedApiKey] = useState<string | null>(null);
  const [showRegenWarning, setShowRegenWarning] = useState(false);
  const [copiedKey, setCopiedKey] = useState(false);

  const generateApiKeyMut = useMutation({
    mutationFn: () => api.userBrokerGenerateApiKey(),
    onSuccess: (data) => {
      setRevealedApiKey(data.api_key);
      setShowRegenWarning(false);
      setCopiedKey(false);
      qc.invalidateQueries({ queryKey: ['user', 'broker'] });
    },
  });

  // Heartbeat indicator : "actif" < 5 min, "récent" < 1 h, "offline" sinon.
  const heartbeatStatus = (() => {
    const ts = brokerQ.data?.last_ea_heartbeat;
    if (!ts) return { label: 'Jamais vu', color: 'text-white/40', dot: 'bg-white/20' };
    const ageSec = (Date.now() - new Date(ts).getTime()) / 1000;
    if (ageSec < 300) return { label: 'Actif', color: 'text-emerald-300', dot: 'bg-emerald-400 animate-pulse' };
    if (ageSec < 3600) {
      const mins = Math.round(ageSec / 60);
      return { label: `Vu il y a ${mins} min`, color: 'text-amber-300', dot: 'bg-amber-400' };
    }
    return { label: 'Hors ligne', color: 'text-rose-300', dot: 'bg-rose-400' };
  })();

  // ─── Auto-exec toggle (Phase D du multi-tenant bridge routing) ──
  const [demoConfirmed, setDemoConfirmed] = useState(false);
  const [autoExecError, setAutoExecError] = useState<string | null>(null);

  const autoExecMut = useMutation({
    mutationFn: (enabled: boolean) =>
      api.userBrokerAutoExec(enabled, enabled ? demoConfirmed : undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user', 'broker'] });
      setDemoConfirmed(false);
      setAutoExecError(null);
    },
    onError: (err) => {
      setAutoExecError(
        err instanceof ApiError ? err.message || 'Erreur' : 'Erreur'
      );
    },
  });

  // ─── Change password section ──────────────────────────────────
  const [pwOpen, setPwOpen] = useState(false);
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwConfirm, setPwConfirm] = useState('');
  const [pwError, setPwError] = useState<string | null>(null);

  const changePwMut = useMutation({
    mutationFn: () => api.changePassword(pwCurrent, pwNew),
    onSuccess: () => {
      setPwCurrent(''); setPwNew(''); setPwConfirm(''); setPwError(null);
    },
    onError: (err) => {
      setPwError(err instanceof ApiError ? err.message || 'Erreur' : 'Erreur');
    },
  });

  const submitChangePw = (e: React.FormEvent) => {
    e.preventDefault();
    setPwError(null);
    if (pwNew.length < 8) { setPwError('Min 8 caractères'); return; }
    if (pwNew !== pwConfirm) { setPwError('Les mots de passe ne correspondent pas'); return; }
    changePwMut.mutate();
  };

  // ─── Delete account section ──────────────────────────────────
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePw, setDeletePw] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const deleteMut = useMutation({
    mutationFn: () => api.deleteAccount(deletePw),
    onSuccess: () => navigate('/'),
    onError: (err) => {
      setDeleteError(err instanceof ApiError ? err.message || 'Erreur' : 'Erreur');
    },
  });

  const submitDelete = (e: React.FormEvent) => {
    e.preventDefault();
    setDeleteError(null);
    if (deleteConfirm !== 'SUPPRIMER') {
      setDeleteError('Tape SUPPRIMER pour confirmer');
      return;
    }
    deleteMut.mutate();
  };

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

        {/* ─── Auto-exec EA MQL5 (Phase MQL.E) ─── */}
        <GlassCard className="p-6">
          <button
            onClick={() => setEaOpen((o) => !o)}
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
                  ? `EA configuré · ${heartbeatStatus.label}`
                  : 'Auto-exécute les setups dans MetaTrader 5 via un Expert Advisor (5 min de setup).'}
              </p>
            </div>
            <span className="text-white/40 text-xl ml-4 shrink-0">
              {eaOpen ? '−' : '+'}
            </span>
          </button>

          {eaOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="mt-5 pt-5 border-t border-white/10 space-y-5"
            >
              {/* Étape 1 — API key */}
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-white/80">
                  1. Génère ton API key
                </h3>
                {!brokerQ.data?.api_key_set ? (
                  <button
                    onClick={() => generateApiKeyMut.mutate()}
                    disabled={generateApiKeyMut.isPending}
                    className="w-full py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
                  >
                    {generateApiKeyMut.isPending ? 'Génération…' : 'Générer mon API key'}
                  </button>
                ) : (
                  <div className="flex items-center justify-between gap-3 p-3 rounded-xl bg-emerald-400/10 border border-emerald-400/20">
                    <span className="text-xs text-emerald-200">
                      ✓ API key configurée
                    </span>
                    <button
                      onClick={() => setShowRegenWarning(true)}
                      className="text-xs text-white/60 hover:text-white/90 underline underline-offset-2"
                    >
                      Régénérer
                    </button>
                  </div>
                )}

                {showRegenWarning && (
                  <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 space-y-2">
                    <p className="text-xs text-amber-200">
                      ⚠️ Régénérer va invalider l'ancienne clé immédiatement.
                      Tu devras mettre à jour l'input <code>ApiKey</code> de
                      l'EA dans MT5 sinon les ordres ne passeront plus.
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => generateApiKeyMut.mutate()}
                        disabled={generateApiKeyMut.isPending}
                        className="flex-1 py-2 rounded-lg bg-amber-500/30 border border-amber-400/40 text-amber-100 text-xs font-semibold disabled:opacity-40"
                      >
                        Confirmer la régénération
                      </button>
                      <button
                        onClick={() => setShowRegenWarning(false)}
                        className="px-4 py-2 rounded-lg border border-white/15 text-white/60 text-xs"
                      >
                        Annuler
                      </button>
                    </div>
                  </div>
                )}

                {revealedApiKey && (
                  <div className="rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 space-y-2">
                    <p className="text-xs text-cyan-100">
                      Copie cette clé maintenant — elle ne sera plus affichée :
                    </p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 px-3 py-2 rounded-lg bg-slate-900/60 font-mono text-xs text-white break-all">
                        {revealedApiKey}
                      </code>
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(revealedApiKey);
                          setCopiedKey(true);
                          setTimeout(() => setCopiedKey(false), 2000);
                        }}
                        className="px-3 py-2 rounded-lg bg-cyan-400/20 border border-cyan-400/40 text-cyan-200 text-xs font-medium"
                      >
                        {copiedKey ? 'Copié ✓' : 'Copier'}
                      </button>
                    </div>
                    <button
                      onClick={() => setRevealedApiKey(null)}
                      className="w-full py-1.5 rounded-lg text-xs text-white/60 hover:text-white/90"
                    >
                      J'ai sauvegardé la clé, fermer
                    </button>
                  </div>
                )}
              </div>

              {/* Étape 2 — Download */}
              <div className="space-y-2">
                <h3 className="text-sm font-semibold text-white/80">
                  2. Télécharge l'Expert Advisor
                </h3>
                <a
                  href="/api/ea/download"
                  download="ScalpingRadarEA.mq5"
                  className="block w-full py-2.5 rounded-xl border border-cyan-400/30 text-cyan-300 text-sm font-medium text-center hover:bg-cyan-400/10"
                >
                  📥 Télécharger ScalpingRadarEA.mq5
                </a>
                <p className="text-xs text-white/50 leading-relaxed">
                  Place le fichier dans <code className="text-white/70">{'<MT5 Data Folder>/MQL5/Experts/'}</code>,
                  compile-le dans MetaEditor (F7), puis attache l'EA à un
                  chart en saisissant ton API key dans les inputs.
                  N'oublie pas d'ajouter <code className="text-white/70">https://app.scalping-radar.online</code> dans
                  Tools → Options → Expert Advisors → Allow WebRequest.
                </p>
                <a
                  href="/docs/ea-setup.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block text-xs text-cyan-400 hover:text-cyan-300 underline underline-offset-2"
                >
                  Voir le guide d'installation détaillé →
                </a>
              </div>

              {/* Étape 3 — Statut + toggle */}
              {brokerQ.data?.api_key_set && (
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-white/80">
                    3. Active l'auto-exec
                  </h3>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${heartbeatStatus.dot}`} />
                      <span className={`text-xs ${heartbeatStatus.color}`}>
                        Statut EA · {heartbeatStatus.label}
                      </span>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider ${
                        brokerQ.data.auto_exec_enabled
                          ? 'bg-emerald-400/20 text-emerald-300 border border-emerald-400/30'
                          : 'bg-white/10 text-white/60 border border-white/15'
                      }`}
                    >
                      Auto-exec {brokerQ.data.auto_exec_enabled ? 'ON' : 'OFF'}
                    </span>
                  </div>

                  {brokerQ.data.auto_exec_enabled ? (
                    <button
                      onClick={() => autoExecMut.mutate(false)}
                      disabled={autoExecMut.isPending}
                      className="w-full py-2 rounded-xl border border-rose-400/30 text-rose-300 text-sm hover:bg-rose-400/10 disabled:opacity-40"
                    >
                      {autoExecMut.isPending ? 'Désactivation…' : 'Désactiver l\'auto-exec'}
                    </button>
                  ) : (
                    <div className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 space-y-2">
                      <p className="text-xs text-amber-200 leading-relaxed">
                        ⚠️ Activer va déclencher des ordres réels sur le
                        compte MT5 où l'EA est attaché. Vérifie qu'il s'agit
                        bien d'un <strong>compte DÉMO</strong> pour ta
                        première activation.
                      </p>
                      <label className="flex items-start gap-2 text-xs text-white/80 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={demoConfirmed}
                          onChange={(e) => setDemoConfirmed(e.target.checked)}
                          className="mt-0.5 accent-cyan-400"
                        />
                        <span>
                          Je confirme que l'EA tourne sur un compte
                          <strong> démo</strong> (j'accepte les risques sinon).
                        </span>
                      </label>
                      <button
                        onClick={() => autoExecMut.mutate(true)}
                        disabled={!demoConfirmed || autoExecMut.isPending}
                        className="w-full py-2 rounded-xl bg-gradient-to-br from-amber-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
                      >
                        {autoExecMut.isPending ? 'Activation…' : 'Activer l\'auto-exec'}
                      </button>
                    </div>
                  )}

                  {autoExecError && (
                    <p className="text-xs text-rose-400">{autoExecError}</p>
                  )}
                </div>
              )}

              {brokerQ.data?.mode === 'bridge' && (
                <p className="text-xs text-white/50 italic border-t border-white/10 pt-3">
                  ℹ️ Compte legacy : bridge Python encore configuré
                  ({brokerQ.data.bridge_url}). L'EA utilise la même API key —
                  tu peux désinstaller le bridge Python quand tu veux.
                </p>
              )}
            </motion.div>
          )}
        </GlassCard>

        {/* ─── Change password ─── */}
        <GlassCard className="p-6">
          <button
            onClick={() => setPwOpen((o) => !o)}
            className="w-full flex items-start justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold">Changer mon mot de passe</h2>
              <p className="text-sm text-white/50 mt-1">
                Min 8 caractères. Vérification du password actuel requise.
              </p>
            </div>
            <span className="text-white/40 text-xl ml-4 shrink-0">
              {pwOpen ? '−' : '+'}
            </span>
          </button>

          {pwOpen && (
            <motion.form
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              onSubmit={submitChangePw}
              className="mt-5 pt-5 border-t border-white/10 space-y-3"
            >
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Mot de passe actuel
                </label>
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={pwCurrent}
                  onChange={(e) => setPwCurrent(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:outline-none font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Nouveau mot de passe
                </label>
                <input
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  value={pwNew}
                  onChange={(e) => setPwNew(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:outline-none font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Confirmer
                </label>
                <input
                  type="password"
                  autoComplete="new-password"
                  required
                  value={pwConfirm}
                  onChange={(e) => setPwConfirm(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:outline-none font-mono text-sm"
                />
              </div>
              {pwError && <p className="text-xs text-rose-400">{pwError}</p>}
              {changePwMut.isSuccess && (
                <p className="text-xs text-emerald-400">Mot de passe changé ✓</p>
              )}
              <button
                type="submit"
                disabled={changePwMut.isPending}
                className="w-full py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
              >
                {changePwMut.isPending ? 'Mise à jour…' : 'Mettre à jour'}
              </button>
            </motion.form>
          )}
        </GlassCard>

        {/* ─── Delete account ─── */}
        <GlassCard className="p-6 border-rose-400/30">
          <button
            onClick={() => setDeleteOpen((o) => !o)}
            className="w-full flex items-start justify-between text-left"
          >
            <div>
              <h2 className="text-lg font-semibold text-rose-200">Supprimer mon compte</h2>
              <p className="text-sm text-white/50 mt-1">
                Anonymisation RGPD définitive. Action irréversible.
              </p>
            </div>
            <span className="text-white/40 text-xl ml-4 shrink-0">
              {deleteOpen ? '−' : '+'}
            </span>
          </button>

          {deleteOpen && (
            <motion.form
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              onSubmit={submitDelete}
              className="mt-5 pt-5 border-t border-white/10 space-y-3"
            >
              <p className="text-sm text-white/70">
                Ton compte sera anonymisé immédiatement. Tu ne pourras plus te connecter.
                Les trades historiques sont conservés pour l'intégrité comptable mais
                désassociés de ton identité (email anonymisé).
              </p>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Mot de passe actuel
                </label>
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={deletePw}
                  onChange={(e) => setDeletePw(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:outline-none font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Tape <code className="text-amber-300">SUPPRIMER</code> pour confirmer
                </label>
                <input
                  type="text"
                  required
                  value={deleteConfirm}
                  onChange={(e) => setDeleteConfirm(e.target.value)}
                  placeholder="SUPPRIMER"
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-rose-400/30 focus:outline-none font-mono text-sm"
                />
              </div>
              {deleteError && <p className="text-xs text-rose-400">{deleteError}</p>}
              <button
                type="submit"
                disabled={deleteMut.isPending || !deletePw || deleteConfirm !== 'SUPPRIMER'}
                className="w-full py-2.5 rounded-xl bg-rose-500/20 border border-rose-400/40 text-rose-200 text-sm font-semibold disabled:opacity-40 hover:bg-rose-500/30"
              >
                {deleteMut.isPending ? 'Suppression…' : 'Supprimer définitivement mon compte'}
              </button>
            </motion.form>
          )}
        </GlassCard>

        {/* Footer links */}
        <div className="flex items-center justify-center gap-3 text-xs text-white/40 pt-2">
          <a href="/docs/cgu.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">CGU</a>
          <span>·</span>
          <a href="/docs/cgv.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">CGV</a>
          <span>·</span>
          <a href="/docs/privacy.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">Confidentialité</a>
        </div>

        <p className="text-center text-xs text-white/30 pt-4">
          Scalping Radar v2 · 2026.04
        </p>
      </motion.div>
    </div>
  );
}
