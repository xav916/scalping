import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

/**
 * Page publique /v2/about — méthodologie + éthique + contact.
 * Signal de crédibilité pour les visiteurs sceptiques.
 */
export function AboutPage() {
  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <Link to="/" className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </Link>
        <nav className="flex items-center gap-5">
          <Link to="/live" className="text-sm text-white/60 hover:text-white transition-colors">Live</Link>
          <Link to="/research" className="text-sm text-white/60 hover:text-white transition-colors">Recherche</Link>
          <Link to="/pricing" className="text-sm text-white/60 hover:text-white transition-colors">Tarifs</Link>
        </nav>
      </header>

      <section className="relative z-10 max-w-3xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3">
            <GradientText>À propos</GradientText>
          </h1>
          <p className="text-white/60 text-sm max-w-2xl mx-auto">
            Pourquoi ce projet existe, comment on travaille, ce qu'on n'est pas.
          </p>
        </motion.div>

        <div className="space-y-6">
          <GlassCard className="p-6 sm:p-7">
            <h2 className="text-xl font-bold mb-3">
              <GradientText>L'origine</GradientText>
            </h2>
            <p className="text-sm text-white/70 leading-relaxed">
              Scalping Radar est né d'un constat : la majorité des outils de signaux retail
              promettent des PF de 3+ et des win rates de 80%, sans jamais publier leur méthodologie
              ni un track record vérifiable. C'est du marketing, pas de la recherche.
            </p>
            <p className="text-sm text-white/70 leading-relaxed mt-3">
              On a pris l'approche inverse : tester systématiquement 60+ combinaisons
              (instrument × timeframe × filter), publier les rejets autant que les survivants,
              valider sur 20 ans cross-régime, et exposer le track record live publiquement.
            </p>
          </GlassCard>

          <GlassCard className="p-6 sm:p-7">
            <h2 className="text-xl font-bold mb-3">
              <GradientText>La méthodologie</GradientText>
            </h2>
            <ol className="text-sm text-white/70 space-y-3 list-decimal list-inside leading-relaxed">
              <li>
                <strong className="text-white/90">Hypothèse claire</strong> avant chaque test (PF cible, sample min, fenêtres de validation)
              </li>
              <li>
                <strong className="text-white/90">Pre-screening</strong> sur 12M no-costs pour éliminer 90% des candidats
              </li>
              <li>
                <strong className="text-white/90">Deep dive cross-régime</strong> sur 4 fenêtres (12M, 24M, 3y, pré-bull) avec coûts standard 0.02%
              </li>
              <li>
                <strong className="text-white/90">FDR Bonferroni</strong> pour ajuster le seuil PF en fonction du nombre de tests (anti-cherry-picking)
              </li>
              <li>
                <strong className="text-white/90">Validation profondeur</strong> jusqu'à 20 ans quand data disponible (Daily TD)
              </li>
              <li>
                <strong className="text-white/90">Shadow log live</strong> : on observe sans exécuter pendant 6 semaines pour valider que le live = backtest
              </li>
            </ol>
          </GlassCard>

          <GlassCard className="p-6 sm:p-7">
            <h2 className="text-xl font-bold mb-3">
              <GradientText>Ce qu'on n'est pas</GradientText>
            </h2>
            <ul className="text-sm text-white/70 space-y-2 leading-relaxed">
              <li className="flex items-start gap-2">
                <span className="text-rose-400 mt-0.5">✗</span>
                <span>Un service de "signaux miracles" avec PF 5.0 et WR 90%. Notre PF moyen 20 ans est <strong className="text-white/90">1.20-1.40</strong> selon la star. Edge réel mais modeste.</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-rose-400 mt-0.5">✗</span>
                <span>Un conseil en investissement (CIF). Aucune recommandation personnalisée. Tu décides 100% de tes trades.</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-rose-400 mt-0.5">✗</span>
                <span>Un broker. On ne touche jamais à ton capital. Tu trades chez Pepperstone, IC Markets, Saxo, ce que tu veux.</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-rose-400 mt-0.5">✗</span>
                <span>Un système qui te rendra riche en 6 mois. Si tu cherches ça, tu vas être déçu — l'attente raisonnable est ~10-15%/an cumulé long terme.</span>
              </li>
            </ul>
          </GlassCard>

          <GlassCard className="p-6 sm:p-7">
            <h2 className="text-xl font-bold mb-3">
              <GradientText>Pour qui c'est fait</GradientText>
            </h2>
            <p className="text-sm text-white/70 leading-relaxed">
              Pour les traders qui veulent <strong className="text-white/90">un edge méthodologique validé sans coder</strong> :
            </p>
            <ul className="text-sm text-white/70 space-y-1.5 mt-3 leading-relaxed list-disc list-inside">
              <li>Tu connais la base (stop-loss, take-profit, sizing, R:R)</li>
              <li>Tu as un broker MT5 (Pepperstone, IC Markets, etc.) ou tu trades manuellement</li>
              <li>Tu acceptes des drawdowns 15-25% en échange d'un edge mesurable long terme</li>
              <li>Tu veux apprendre par la pratique avec un journal de tes trades</li>
            </ul>
            <p className="text-sm text-white/70 leading-relaxed mt-4">
              Pour qui c'est <strong className="text-rose-300">pas</strong> fait : débutants complets, traders cherchant
              du gambling rapide, ou ceux qui veulent un PF 5.0 garanti.
            </p>
          </GlassCard>

          <GlassCard className="p-6 sm:p-7">
            <h2 className="text-xl font-bold mb-3">
              <GradientText>Contact</GradientText>
            </h2>
            <p className="text-sm text-white/70 leading-relaxed">
              Pour toute question, retour, ou demande de partenariat :
            </p>
            <div className="mt-3 space-y-2 text-sm">
              <a
                href="mailto:support@scalping-radar.com"
                className="block text-cyan-300 hover:text-cyan-200 transition-colors"
              >
                support@scalping-radar.com
              </a>
            </div>
          </GlassCard>
        </div>

        <div className="mt-12 text-center">
          <Link
            to="/"
            className="text-sm text-cyan-300 hover:text-cyan-200 font-medium"
          >
            ← Retour landing
          </Link>
        </div>
      </section>

      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>© 2026 Scalping Radar · Pas un conseil d'investissement · Performances passées ≠ futures</p>
      </footer>
    </div>
  );
}
