import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

/**
 * Page marketing publique : pitch, features, pricing CTA.
 * Affichée à `/` quand l'utilisateur n'est pas authentifié.
 */

const FEATURES = [
  {
    title: 'Radar 16 paires en temps réel',
    desc: 'Forex, métaux, crypto, indices et énergie. Scoring 0-100 par setup, cycles 20s.',
    icon: '◎',
  },
  {
    title: 'Auto-exécution MT5',
    desc: 'Chaque signal > seuil de confiance est poussé à ton bridge MT5 local via Tailscale. Rien ne transite par nos serveurs.',
    icon: '⚡',
  },
  {
    title: 'Data isolation stricte',
    desc: 'Tes trades, tes stats, tes rejections — zéro croisement entre utilisateurs. Bridge sur ton PC, API key à toi.',
    icon: '🔒',
  },
  {
    title: 'Analytics multi-dimension',
    desc: 'Win rate par paire, heure, pattern, asset class, régime macro. Comprendre pourquoi ça gagne ou perd.',
    icon: '📊',
  },
  {
    title: 'Alertes Telegram',
    desc: 'Notifs push instantanées sur les setups haute conviction. Tu décides si tu valides.',
    icon: '🔔',
  },
  {
    title: 'Journal ML-ready',
    desc: "Chaque trade est loggé avec son contexte complet (macro, slippage, close reason). Base d'entraînement pour future optimisation.",
    icon: '⋯',
  },
];

const PRICING_PREVIEW = [
  {
    name: 'Free',
    price: '0€',
    yearly: null,
    tagline: '1 paire, 7j d\'historique',
  },
  {
    name: 'Pro',
    price: '19€',
    yearly: '190€/an (-17%)',
    tagline: '5 paires + alertes + illimité',
    highlight: true,
  },
  {
    name: 'Premium',
    price: '39€',
    yearly: '390€/an (-17%)',
    tagline: 'Tout + backtest + multi-broker',
  },
];

export function LandingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      {/* Header minimal */}
      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </div>
        <nav className="flex items-center gap-5">
          <Link
            to="/pricing"
            className="text-sm text-white/60 hover:text-white transition-colors"
          >
            Pricing
          </Link>
          <Link
            to="/login"
            className="text-sm text-white/60 hover:text-white transition-colors"
          >
            Connexion
          </Link>
          <button
            onClick={() => navigate('/signup')}
            className="px-4 py-2 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
          >
            Démarrer
          </button>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 py-20 text-center">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 mb-6">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs uppercase tracking-wider text-white/60">
              16 paires · 24/5 en live
            </span>
          </div>
          <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-5 leading-tight">
            <GradientText>Le radar de scalping</GradientText>
            <br />
            <span className="text-white/90">qui tourne sur ton PC.</span>
          </h1>
          <p className="text-lg text-white/70 max-w-2xl mx-auto mb-8 leading-relaxed">
            Détection automatisée de setups sur 16 instruments. Scoring macro + technique
            en continu. Auto-exécution directe sur ton compte MT5 via bridge local.
            Aucun fonds chez nous, ton broker à toi.
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => navigate('/signup')}
              className="px-6 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold shadow-lg shadow-cyan-500/20"
            >
              Créer un compte gratuit
            </button>
            <Link
              to="/pricing"
              className="px-6 py-3 rounded-xl border border-white/15 text-white/80 text-sm font-medium hover:bg-white/5"
            >
              Voir les plans →
            </Link>
          </div>
          <p className="text-xs text-white/40 mt-4">
            Sans carte. 14 jours d'essai Pro inclus.
          </p>
        </motion.div>
      </section>

      {/* Features grid */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 py-12">
        <motion.h2
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
          className="text-3xl font-bold text-center mb-12"
        >
          <GradientText>Ce que tu obtiens</GradientText>
        </motion.h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.35, delay: i * 0.05 }}
            >
              <GlassCard className="p-5 h-full">
                <div className="text-2xl mb-2 text-cyan-300">{f.icon}</div>
                <h3 className="font-semibold mb-1.5">{f.title}</h3>
                <p className="text-sm text-white/60 leading-relaxed">{f.desc}</p>
              </GlassCard>
            </motion.div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="relative z-10 max-w-4xl mx-auto px-6 py-16">
        <motion.h2
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
          className="text-3xl font-bold text-center mb-12"
        >
          <GradientText>Comment ça marche</GradientText>
        </motion.h2>
        <div className="space-y-6">
          {[
            {
              n: '01',
              title: 'Installe le bridge sur ton PC Windows',
              desc: 'Petit serveur local qui relaie les ordres au terminal MT5. 10 minutes à configurer avec notre guide + Tailscale gratuit.',
            },
            {
              n: '02',
              title: 'Connecte-toi à Scalping Radar',
              desc: "Saisie l'URL Tailscale du bridge + l'API key dans l'app. On test la connexion en un clic.",
            },
            {
              n: '03',
              title: 'Choisis tes paires et active',
              desc: 'Sélectionne jusqu\'à 16 paires à surveiller. Active le mode auto-exec. Le radar pousse les ordres dès qu\'un setup haute confiance apparaît.',
            },
            {
              n: '04',
              title: 'Supervise depuis le cockpit',
              desc: 'PnL temps réel, exposure, rejections, analytics multi-dimension. Tu coupes le kill-switch quand tu veux, tu reprends quand tu veux.',
            },
          ].map((step, i) => (
            <motion.div
              key={step.n}
              initial={{ opacity: 0, x: -10 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.35, delay: i * 0.06 }}
              className="flex gap-4"
            >
              <div className="text-3xl font-bold text-cyan-300 font-mono min-w-[60px]">
                {step.n}
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-1">{step.title}</h3>
                <p className="text-sm text-white/60 leading-relaxed">{step.desc}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Pricing preview */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 py-16">
        <motion.h2
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          className="text-3xl font-bold text-center mb-4"
        >
          <GradientText>Tarifs simples</GradientText>
        </motion.h2>
        <p className="text-center text-white/60 mb-10 text-sm">
          Sans engagement. Annulable depuis ton espace en un clic.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PRICING_PREVIEW.map((p) => (
            <GlassCard
              key={p.name}
              variant={p.highlight ? 'elevated' : 'default'}
              className={`p-6 ${p.highlight ? 'ring-1 ring-cyan-400/40' : ''}`}
            >
              <h3 className="text-xl font-bold mb-1">{p.name}</h3>
              <p className="text-xs uppercase tracking-wider text-white/40 mb-3">
                {p.tagline}
              </p>
              <div>
                <span className="text-3xl font-bold">{p.price}</span>
                {p.name !== 'Free' && (
                  <span className="text-white/50 text-sm">/mois</span>
                )}
              </div>
              {p.yearly && (
                <div className="mt-2 text-xs text-emerald-300/80">
                  ou {p.yearly}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
        <div className="text-center mt-8">
          <Link
            to="/pricing"
            className="text-cyan-300 hover:text-cyan-200 text-sm font-medium"
          >
            Voir tous les détails →
          </Link>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative z-10 max-w-3xl mx-auto px-6 py-20 text-center">
        <GlassCard variant="elevated" className="p-10">
          <h2 className="text-3xl font-bold mb-3">
            <GradientText>Prêt à tester ?</GradientText>
          </h2>
          <p className="text-white/70 mb-6">
            14 jours d'essai Pro gratuit, sans carte.
          </p>
          <button
            onClick={() => navigate('/signup')}
            className="px-8 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
          >
            Créer mon compte →
          </button>
        </GlassCard>
      </section>

      {/* Footer */}
      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>
          © 2026 Scalping Radar · Les performances passées ne préjugent pas des
          performances futures · Pas un conseil d'investissement.
        </p>
      </footer>
    </div>
  );
}
