import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';

/**
 * Wizard d'onboarding en 3 étapes :
 *  1) Setup du bridge MT5 (URL + API key) + test de connexion
 *  2) Choix des paires surveillées (limité par le tier)
 *  3) Done → redirect dashboard
 */

const ALL_PAIRS = [
  'EUR/USD', 'GBP/USD', 'USD/JPY', 'EUR/GBP', 'USD/CHF',
  'AUD/USD', 'USD/CAD', 'EUR/JPY', 'GBP/JPY',
  'XAU/USD', 'XAG/USD',
  'BTC/USD', 'ETH/USD',
  'SPX', 'NDX', 'WTI/USD',
];

type Step = 1 | 2 | 3;

export function OnboardingPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>(1);

  // ─── Étape 1 : broker
  const [bridgeUrl, setBridgeUrl] = useState('http://100.');
  const [bridgeApiKey, setBridgeApiKey] = useState('');
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const testMut = useMutation({
    mutationFn: () => api.userBrokerTest(bridgeUrl, bridgeApiKey),
    onSuccess: (data) => {
      if (data.ok && data.reachable) {
        setTestResult({ ok: true, msg: 'Bridge joignable ✓' });
      } else {
        setTestResult({ ok: false, msg: data.error || 'Bridge injoignable' });
      }
    },
    onError: () => setTestResult({ ok: false, msg: 'Erreur de test' }),
  });

  const saveBrokerMut = useMutation({
    mutationFn: () => api.userBrokerPut(bridgeUrl, bridgeApiKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user', 'onboarding'] });
      setStep(2);
    },
  });

  // ─── Étape 2 : pairs
  const pairsInfo = useQuery({
    queryKey: ['user', 'watched-pairs'],
    queryFn: api.userWatchedPairsGet,
    staleTime: 30_000,
    enabled: step === 2,
  });
  const cap = pairsInfo.data?.cap ?? 1;
  const tier = pairsInfo.data?.tier ?? 'free';
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const togglePair = (p: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(p)) {
        next.delete(p);
      } else if (next.size < cap) {
        next.add(p);
      }
      return next;
    });
  };

  const savePairsMut = useMutation({
    mutationFn: () => api.userWatchedPairsPut(Array.from(selected)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user', 'onboarding'] });
      setStep(3);
    },
  });

  // ─── Étape 3 : done
  const goDashboard = () => navigate('/', { replace: true });

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-8">
      <AnimatedMeshGradient />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="w-full max-w-xl"
      >
        <GlassCard variant="elevated" className="p-8">
          <h1 className="text-2xl font-bold text-center mb-1">
            <GradientText>Configuration initiale</GradientText>
          </h1>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40 text-center mb-6">
            Étape {step} / 3
          </p>

          {/* Progress bar */}
          <div className="flex items-center gap-2 mb-8">
            {[1, 2, 3].map((s) => (
              <div
                key={s}
                className={`flex-1 h-1 rounded-full transition-colors ${
                  s <= step ? 'bg-cyan-400' : 'bg-white/10'
                }`}
              />
            ))}
          </div>

          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.div
                key="step-1"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -12 }}
                transition={{ duration: 0.25 }}
              >
                <h2 className="text-lg font-semibold mb-3">Connecter ton bridge MT5</h2>
                <p className="text-sm text-white/60 mb-4 leading-relaxed">
                  Le bridge tourne sur ton PC Windows (app locale) et expose une URL
                  Tailscale. Si tu n'as pas encore installé le bridge, suis le guide{' '}
                  <a
                    href="/docs/bridge-setup.html"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-cyan-400 hover:text-cyan-300 underline"
                  >
                    ici
                  </a>
                  .
                </p>

                <div className="space-y-3">
                  <div>
                    <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                      URL du bridge (Tailscale)
                    </label>
                    <input
                      type="url"
                      value={bridgeUrl}
                      onChange={(e) => {
                        setBridgeUrl(e.target.value);
                        setTestResult(null);
                      }}
                      placeholder="http://100.x.y.z:8787"
                      className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:outline-none font-mono text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                      API key du bridge
                    </label>
                    <input
                      type="password"
                      value={bridgeApiKey}
                      onChange={(e) => {
                        setBridgeApiKey(e.target.value);
                        setTestResult(null);
                      }}
                      placeholder="min 16 caractères"
                      className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:outline-none font-mono text-sm"
                    />
                  </div>

                  {testResult && (
                    <motion.p
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className={`text-sm ${testResult.ok ? 'text-emerald-400' : 'text-rose-400'}`}
                    >
                      {testResult.msg}
                    </motion.p>
                  )}
                </div>

                <div className="flex gap-3 mt-6">
                  <button
                    onClick={() => testMut.mutate()}
                    disabled={testMut.isPending || !bridgeUrl || bridgeApiKey.length < 16}
                    className="flex-1 py-2.5 rounded-xl border border-cyan-400/30 text-cyan-300 text-sm font-medium disabled:opacity-40 hover:bg-cyan-400/10 transition-colors"
                  >
                    {testMut.isPending ? 'Test…' : 'Tester la connexion'}
                  </button>
                  <button
                    onClick={() => saveBrokerMut.mutate()}
                    disabled={saveBrokerMut.isPending || !testResult?.ok}
                    className="flex-1 py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
                  >
                    {saveBrokerMut.isPending ? 'Enregistrement…' : 'Suivant →'}
                  </button>
                </div>
              </motion.div>
            )}

            {step === 2 && (
              <motion.div
                key="step-2"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -12 }}
                transition={{ duration: 0.25 }}
              >
                <h2 className="text-lg font-semibold mb-1">Choisir tes paires</h2>
                <p className="text-sm text-white/60 mb-4">
                  Tier <strong className="capitalize">{tier}</strong> : jusqu'à{' '}
                  <strong>{cap}</strong> paire{cap > 1 ? 's' : ''} surveillée{cap > 1 ? 's' : ''}.
                </p>

                <div className="grid grid-cols-3 gap-2 mb-6">
                  {ALL_PAIRS.map((p) => {
                    const isSelected = selected.has(p);
                    const isDisabled = !isSelected && selected.size >= cap;
                    return (
                      <button
                        key={p}
                        onClick={() => togglePair(p)}
                        disabled={isDisabled}
                        className={`px-3 py-2 rounded-lg text-sm font-mono transition-all ${
                          isSelected
                            ? 'bg-cyan-400/20 border border-cyan-400/50 text-cyan-200'
                            : isDisabled
                              ? 'bg-white/5 border border-white/10 text-white/30 cursor-not-allowed'
                              : 'bg-white/5 border border-white/10 text-white/70 hover:border-white/20 hover:bg-white/[0.07]'
                        }`}
                      >
                        {p}
                      </button>
                    );
                  })}
                </div>

                <p className="text-xs text-white/40 text-center mb-4">
                  {selected.size} / {cap} sélectionnée{selected.size > 1 ? 's' : ''}
                </p>

                <div className="flex gap-3">
                  <button
                    onClick={() => setStep(1)}
                    className="flex-1 py-2.5 rounded-xl border border-white/10 text-white/60 text-sm font-medium hover:bg-white/5"
                  >
                    ← Retour
                  </button>
                  <button
                    onClick={() => savePairsMut.mutate()}
                    disabled={savePairsMut.isPending || selected.size === 0}
                    className="flex-1 py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-40"
                  >
                    {savePairsMut.isPending ? 'Enregistrement…' : 'Terminer'}
                  </button>
                </div>
              </motion.div>
            )}

            {step === 3 && (
              <motion.div
                key="step-3"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3 }}
                className="text-center"
              >
                <div className="text-6xl mb-4">✓</div>
                <h2 className="text-xl font-semibold mb-2">
                  <GradientText>Configuration terminée</GradientText>
                </h2>
                <p className="text-sm text-white/60 mb-6">
                  Ton compte est prêt. Le radar va commencer à surveiller tes paires
                  et t'alerter dès qu'un setup apparaît.
                </p>
                <button
                  onClick={goDashboard}
                  className="px-8 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
                >
                  Aller au dashboard →
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </GlassCard>
      </motion.div>
    </div>
  );
}
