import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';

/**
 * Onboarding signal-only (2026-04-23 pivot) :
 *  1) Welcome + explication du produit (radar + alertes, pas de bridge)
 *  2) Sélection des paires surveillées (cap par tier)
 *  3) Done → dashboard
 *
 * Le bridge MT5 (auto-exec) n'est plus requis ici. Il est accessible depuis
 * Settings en option Premium pour les traders avancés qui veulent
 * auto-exécuter directement sur leur MT5.
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
      qc.invalidateQueries({ queryKey: ['user', 'watched-pairs'] });
      setStep(3);
    },
  });

  const goDashboard = () => navigate('/dashboard', { replace: true });

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
            <GradientText>Bienvenue sur Scalping Radar</GradientText>
          </h1>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40 text-center mb-6">
            Étape {step} / 3
          </p>

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
                <h2 className="text-lg font-semibold mb-3">Comment ça marche</h2>
                <ul className="space-y-3 mb-6 text-sm text-white/70">
                  <li className="flex gap-2">
                    <span className="text-cyan-400 mt-0.5">◎</span>
                    <span>
                      <strong className="text-white">Un radar qui tourne 24/5</strong> sur 16 paires
                      (forex, métaux, crypto, indices, énergie) et détecte les setups en temps réel.
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-cyan-400 mt-0.5">🔔</span>
                    <span>
                      <strong className="text-white">Alertes Telegram instantanées</strong> sur les
                      setups haute conviction. Tu décides si tu trades.
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-cyan-400 mt-0.5">📊</span>
                    <span>
                      <strong className="text-white">Analytics détaillée</strong> par paire, heure,
                      pattern, régime macro — pour comprendre ce qui gagne.
                    </span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-cyan-400 mt-0.5">💼</span>
                    <span>
                      Tu trades au broker de ton choix, <strong className="text-white">on ne touche
                      jamais à tes fonds</strong>.
                    </span>
                  </li>
                </ul>
                <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-xs text-white/60 mb-6">
                  💡 Si tu veux auto-exécuter les setups sur ton MT5 (plan Premium), tu pourras
                  configurer ton bridge depuis <strong>Paramètres</strong> après l'onboarding.
                </div>
                <button
                  onClick={() => setStep(2)}
                  className="w-full py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
                >
                  Suivant — Choisir mes paires →
                </button>
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
                  <GradientText>Tout est prêt</GradientText>
                </h2>
                <p className="text-sm text-white/60 mb-6">
                  Le radar est en train de scanner tes paires. Les premiers setups et alertes
                  apparaîtront dans le dashboard d'ici quelques minutes.
                </p>
                <button
                  onClick={goDashboard}
                  className="px-8 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
                >
                  Voir mon dashboard →
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </GlassCard>
      </motion.div>
    </div>
  );
}
