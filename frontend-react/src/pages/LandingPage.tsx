import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';
import { api } from '@/lib/api';
import { captureRefCodeFromUrl, getStoredRefCode } from '@/lib/referralCode';

/**
 * Page marketing publique : pitch, features, pricing CTA.
 * Affichée à `/` quand l'utilisateur n'est pas authentifié.
 */

const FEATURES = [
  {
    title: '6 setups, pas 600',
    desc: 'Or, argent, pétrole, ETH, XLI (industrial US), XLK (tech US). Tous validés sur 20 ans de data cross-régime — pas des setups au feeling.',
    icon: '◎',
  },
  {
    title: 'Recherche transparente',
    desc: '36 expériences publiées dans notre journal. Tu vois nos rejets autant que nos winners. Méthodologie ouverte, pas de boîte noire.',
    icon: '📓',
  },
  {
    title: 'Profit Factor mesuré',
    desc: 'PF 1.19-1.42 sur 20 ans. Sharpe annualisé 0.30-0.50. Pas de promesse miracle. Diversification multi-asset = chaque régime a sa star.',
    icon: '📊',
  },
  {
    title: 'Alertes Telegram instantanées',
    desc: 'Setup détecté → ping Telegram → tu décides. Pas de spam, juste les setups qui matchent les filtres validés.',
    icon: '🔔',
  },
  {
    title: 'Tu gardes le contrôle',
    desc: 'On ne touche jamais à ton capital. Trade chez ton broker, ton compte, ton risque. Notifications + analytics, exécution chez toi.',
    icon: '🔐',
  },
  {
    title: 'Auto-exec MT5 (Premium)',
    desc: 'Optionnel : connecte ton bridge MT5 local pour auto-exécuter les setups sur démo Pepperstone ou autre. Pour les traders avancés.',
    icon: '⚡',
  },
];

const PRICING_PREVIEW = [
  {
    name: 'Free',
    price: '0€',
    yearly: null,
    tagline: 'Pour découvrir',
  },
  {
    name: 'Pro',
    price: '49€',
    yearly: '490€/an (-17%)',
    tagline: '6 setups + alertes Telegram + analytics',
    highlight: true,
  },
  {
    name: 'Premium',
    price: '99€',
    yearly: '990€/an (-17%)',
    tagline: 'Pro + auto-exec MT5 + Discord VIP',
  },
];

export function LandingPage() {
  // Capture le code de parrainage depuis ?ref=CODE et store 30j
  useEffect(() => {
    captureRefCodeFromUrl();
  }, []);
  const refCode = getStoredRefCode();

  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      {/* Header minimal */}
      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </div>
        <nav className="flex items-center gap-4 sm:gap-5">
          <Link
            to="/live"
            className="text-sm text-white/60 hover:text-white transition-colors hidden sm:inline"
          >
            Live
          </Link>
          <Link
            to="/research"
            className="text-sm text-white/60 hover:text-white transition-colors hidden sm:inline"
          >
            Recherche
          </Link>
          <Link
            to="/pricing"
            className="text-sm text-white/60 hover:text-white transition-colors"
          >
            Tarifs
          </Link>
          <Link
            to="/login"
            className="text-sm text-white/60 hover:text-white transition-colors"
          >
            Connexion
          </Link>
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
              6 setups · validés sur 20 ans
            </span>
          </div>
          {refCode && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-emerald-400/10 border border-emerald-400/30"
            >
              <span className="text-xs text-emerald-300">
                ✓ Code parrainage <strong className="font-mono">{refCode}</strong> · early-bird -20% sur 6 mois Pro
              </span>
            </motion.div>
          )}
          <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-5 leading-tight">
            <GradientText>Trade comme un quant.</GradientText>
            <br />
            <span className="text-white/90">Sans coder.</span>
          </h1>
          <p className="text-lg text-white/70 max-w-2xl mx-auto mb-8 leading-relaxed">
            6 setups validés sur <strong className="text-white/90">20 ans de data</strong> cross-régime.
            Or, argent, pétrole, ETH, XLI, XLK. Profit Factor moyen <strong className="text-white/90">1.31</strong>.
            Alertes Telegram en temps réel.{' '}
            <strong className="text-white/90">Tu trades chez ton broker, on ne touche jamais à tes fonds.</strong>
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <Link
              to="/live"
              className="px-6 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold shadow-lg shadow-cyan-500/20 hover:scale-105 transition-transform"
            >
              Voir les setups en direct →
            </Link>
            <Link
              to="/track-record"
              className="px-6 py-3 rounded-xl border border-white/15 text-white/80 text-sm font-medium hover:bg-white/5"
            >
              Track record public
            </Link>
            <Link
              to="/pricing"
              className="px-6 py-3 rounded-xl border border-white/15 text-white/80 text-sm font-medium hover:bg-white/5"
            >
              Tarifs
            </Link>
          </div>
          <p className="text-xs text-white/40 mt-4">
            Aucune carte requise pour visualiser le live et le track record.
          </p>
        </motion.div>
      </section>

      {/* Dashboard mockup preview */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 pb-16">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
        >
          <GlassCard variant="elevated" className="p-1 overflow-hidden">
            <div className="rounded-xl bg-slate-950/60 border border-white/5 overflow-hidden">
              {/* Mock browser chrome */}
              <div className="px-4 py-2.5 border-b border-white/5 flex items-center gap-2 bg-white/[0.02]">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-rose-500/60" />
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/60" />
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/60" />
                </div>
                <div className="flex-1 text-center">
                  <span className="text-[10px] font-mono text-white/40">scalping-radar.online/v2/shadow-log</span>
                </div>
              </div>
              {/* Mock dashboard content */}
              <div className="p-5 space-y-4">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Setups 30j', value: '47', color: 'text-cyan-300' },
                    { label: 'WR', value: '54.2%', color: 'text-emerald-400' },
                    { label: 'PF live', value: '1.42', color: 'text-emerald-400' },
                    { label: 'Sharpe', value: '1.18', color: 'text-cyan-300' },
                  ].map((kpi) => (
                    <div key={kpi.label} className="rounded-lg bg-white/[0.03] border border-white/5 px-3 py-2.5">
                      <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">{kpi.label}</div>
                      <div className={`text-2xl font-bold font-mono ${kpi.color}`}>{kpi.value}</div>
                    </div>
                  ))}
                </div>
                <div className="rounded-lg bg-white/[0.03] border border-white/5 overflow-hidden">
                  <div className="px-4 py-2 border-b border-white/5 flex items-center justify-between">
                    <span className="text-xs font-medium text-white/70">Setups récents (6 stars)</span>
                    <span className="text-[10px] text-emerald-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      live
                    </span>
                  </div>
                  <div className="text-xs font-mono divide-y divide-white/[0.03]">
                    {[
                      { pair: 'XAU/USD', tf: '4H', pattern: 'momentum_up', entry: '2087.42', outcome: 'TP1', pnl: '+1.84%', pnl_color: 'text-emerald-400' },
                      { pair: 'XAG/USD', tf: '4H', pattern: 'engulfing_bullish', entry: '24.61', outcome: 'TP1', pnl: '+2.31%', pnl_color: 'text-emerald-400' },
                      { pair: 'XLK', tf: '1D', pattern: 'momentum_up', entry: '215.84', outcome: 'pending', pnl: '—', pnl_color: 'text-white/40' },
                      { pair: 'WTI/USD', tf: '4H', pattern: 'range_bounce_up', entry: '78.92', outcome: 'SL', pnl: '-0.95%', pnl_color: 'text-rose-400' },
                      { pair: 'ETH/USD', tf: '1D', pattern: 'breakout_up', entry: '3421', outcome: 'pending', pnl: '—', pnl_color: 'text-white/40' },
                    ].map((row, i) => (
                      <div key={i} className="px-4 py-2 grid grid-cols-6 gap-2 items-center">
                        <span className="text-cyan-300 font-semibold">{row.pair}</span>
                        <span className="text-white/50">{row.tf}</span>
                        <span className="text-white/70 col-span-2">{row.pattern}</span>
                        <span className={`font-semibold ${row.pnl_color}`}>{row.outcome}</span>
                        <span className={`text-right ${row.pnl_color}`}>{row.pnl}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="text-[10px] text-white/30 text-center">
                  Données illustratives — voir le vrai live sur /live
                </div>
              </div>
            </div>
          </GlassCard>
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
              title: 'Crée ton compte en 30 secondes',
              desc: '14 jours d\'essai Pro gratuit, sans carte bancaire. Accès immédiat aux 6 setups en temps réel.',
            },
            {
              n: '02',
              title: 'Active les 6 setups validés',
              desc: 'XAU H4, XAG H4, WTI H4, ETH 1d, XLI 1d, XLK 1d. Filtres V2_CORE_LONG / V2_WTI_OPTIMAL / V2_TIGHT_LONG dérivés de 36 expériences publiées.',
            },
            {
              n: '03',
              title: 'Reçois les alertes en temps réel',
              desc: "Dès qu'un setup matche les filtres validés, ping Telegram + ligne dans le dashboard avec entry/SL/TP, contexte macro et lien vers le journal.",
            },
            {
              n: '04',
              title: 'Trades chez ton broker',
              desc: 'Tu décides quoi faire de chaque setup. Ton broker, ton compte, ton argent — nous ne touchons jamais à tes fonds. Optionnel : connecte ton bridge MT5 pour auto-exec démo (Premium).',
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

      {/* Comparatif vs concurrents */}
      <section className="relative z-10 max-w-5xl mx-auto px-6 py-16">
        <motion.h2
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
          className="text-3xl font-bold text-center mb-3"
        >
          <GradientText>Pourquoi pas un autre outil ?</GradientText>
        </motion.h2>
        <p className="text-center text-white/60 mb-10 text-sm max-w-2xl mx-auto">
          On ne fait pas le même travail. Voici ce qui nous distingue.
        </p>
        <GlassCard className="p-0 overflow-hidden">
          <div className="grid grid-cols-5 gap-0 text-sm">
            {/* Header */}
            <div className="px-4 py-3 bg-white/[0.02] border-b border-white/5 col-span-1"></div>
            <div className="px-3 py-3 bg-white/[0.02] border-b border-white/5 text-center text-xs font-semibold">
              <span className="text-cyan-300">Scalping Radar</span>
            </div>
            <div className="px-3 py-3 bg-white/[0.02] border-b border-white/5 text-center text-xs text-white/50">
              TradingView
            </div>
            <div className="px-3 py-3 bg-white/[0.02] border-b border-white/5 text-center text-xs text-white/50">
              Discord bots
            </div>
            <div className="px-3 py-3 bg-white/[0.02] border-b border-white/5 text-center text-xs text-white/50">
              MetaSignals
            </div>
            {[
              {
                feature: 'Setups validés long terme',
                us: 'Oui — 20 ans backtest',
                tv: 'Indicateurs purs',
                dc: 'Variable / opaque',
                ms: 'Variable',
              },
              {
                feature: 'Méthodologie publique',
                us: 'Journal 36 expériences',
                tv: 'N/A',
                dc: 'Souvent boîte noire',
                ms: 'Peu détaillée',
              },
              {
                feature: 'Profit Factor mesuré',
                us: '1.19-1.42 sur 20y',
                tv: 'À mesurer toi-même',
                dc: 'Claims marketing',
                ms: 'Claims marketing',
              },
              {
                feature: 'Track record public',
                us: 'Oui — page /track-record',
                tv: 'N/A',
                dc: 'Capture cherry-picked',
                ms: 'Variable',
              },
              {
                feature: 'Diversification multi-asset',
                us: '6 stars décorrélées',
                tv: 'À toi de configurer',
                dc: '1-2 paires souvent',
                ms: 'Souvent forex only',
              },
              {
                feature: 'Auto-exec démo (optionnel)',
                us: 'Bridge MT5 self-hosted',
                tv: 'Webhook DIY',
                dc: 'Variable',
                ms: 'Souvent inclus',
              },
              {
                feature: 'Tu gardes ton capital',
                us: 'Toujours, on touche pas',
                tv: 'Oui',
                dc: 'Oui',
                ms: 'Variable',
              },
              {
                feature: 'Prix mensuel',
                us: '49€ (Pro) / 99€ (Premium)',
                tv: '15-60€',
                dc: '20-200€',
                ms: '50-150€',
              },
            ].map((row, i) => (
              <div key={row.feature} className="contents">
                <div className={`px-4 py-3 ${i % 2 === 0 ? 'bg-white/[0.01]' : ''} border-b border-white/[0.03] text-white/70 text-xs sm:text-sm`}>
                  {row.feature}
                </div>
                <div className={`px-3 py-3 ${i % 2 === 0 ? 'bg-white/[0.02]' : 'bg-white/[0.01]'} border-b border-white/[0.03] text-center text-xs text-cyan-200 font-medium`}>
                  {row.us}
                </div>
                <div className={`px-3 py-3 ${i % 2 === 0 ? 'bg-white/[0.01]' : ''} border-b border-white/[0.03] text-center text-xs text-white/50`}>
                  {row.tv}
                </div>
                <div className={`px-3 py-3 ${i % 2 === 0 ? 'bg-white/[0.01]' : ''} border-b border-white/[0.03] text-center text-xs text-white/50`}>
                  {row.dc}
                </div>
                <div className={`px-3 py-3 ${i % 2 === 0 ? 'bg-white/[0.01]' : ''} border-b border-white/[0.03] text-center text-xs text-white/50`}>
                  {row.ms}
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </section>

      {/* FAQ */}
      <section className="relative z-10 max-w-3xl mx-auto px-6 py-16">
        <motion.h2
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.4 }}
          className="text-3xl font-bold text-center mb-10"
        >
          <GradientText>Questions fréquentes</GradientText>
        </motion.h2>
        <div className="space-y-3">
          {[
            {
              q: 'Combien je peux gagner avec ce système ?',
              a: 'Honnêtement : sur 20 ans, le Profit Factor moyen est 1.19-1.42 selon la star. À sizing prudent (0.25-0.5%), l\'attente raisonnable est ~10-15%/an cumulé sur le capital alloué. Pas un système miracle, mais un edge méthodologique réel et documenté.',
            },
            {
              q: 'Pourquoi 6 setups et pas 60 ?',
              a: 'Parce qu\'on a testé 454 combinaisons (57 instruments × 2 timeframes × 4 filtres) et que seulement ces 6 passent un FDR strict cross-régime. Plus de signaux ≠ plus de gains, c\'est généralement plus de bruit.',
            },
            {
              q: 'C\'est différent de TradingView ?',
              a: 'TradingView te donne des outils pour analyser. On te donne 6 setups validés à exploiter. C\'est complémentaire — beaucoup d\'utilisateurs gardent TradingView pour le chart et utilisent Scalping Radar pour les signaux exploitables.',
            },
            {
              q: 'Vous touchez à mes fonds ?',
              a: 'Jamais. Tu trades chez ton broker (Pepperstone, IC Markets, Saxo, etc.). On envoie les setups en notification (Telegram + dashboard), tu décides. En option Premium, tu peux connecter un bridge MT5 self-hosted qui exécute automatiquement chez toi.',
            },
            {
              q: 'Garantie de remboursement ?',
              a: 'Pas formelle. Mais l\'essai Pro 14 jours sans carte te permet de tester avant de payer quoi que ce soit. Si tu paies puis annules au mois N, l\'abonnement reste actif jusqu\'à fin du cycle déjà payé, puis stoppe.',
            },
            {
              q: 'C\'est légal en France ?',
              a: 'Oui. C\'est un outil de signaux + dashboard analytics, pas un service de conseil en investissement (CIF). Aucune recommandation personnalisée. Tu décides 100% de tes trades. Disclaimer en footer.',
            },
            {
              q: 'Quelle différence Pro vs Premium ?',
              a: 'Pro (49€) = les 6 setups en temps réel, alertes Telegram, analytics, journal. Premium (99€) ajoute l\'auto-exec MT5 (bridge self-hosted), Discord VIP, onboarding 1:1 mensuel. Pro suffit pour 90% des traders.',
            },
            {
              q: 'Et si une star casse pendant 6 mois ?',
              a: 'Ça arrive. Sur 20 ans, chaque star a au moins une fenêtre de 1-3 ans avec PF<1. C\'est exactement pourquoi on a 6 stars décorrélées : quand XAU casse, XLI/XLK compensent (et inversement). On est transparents sur les drawdowns.',
            },
            {
              q: 'Je suis débutant, c\'est fait pour moi ?',
              a: 'Pas vraiment. Les setups sont validés mais l\'exécution demande de comprendre stop-loss, take-profit, sizing. Si tu débutes, commence par lire les docs (gratuites) et trade en démo avant Pro.',
            },
            {
              q: 'Pourquoi le signup est fermé en avril 2026 ?',
              a: 'On finit la phase d\'observation publique du shadow log (jusqu\'au 6 juin 2026) pour avoir 6 semaines de données live à montrer. Ouverture officielle ensuite. Tu peux suivre le track record en temps réel sur /live.',
            },
          ].map((item, i) => (
            <motion.details
              key={i}
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: i * 0.03 }}
              className="group"
            >
              <summary className="cursor-pointer list-none">
                <GlassCard className="p-4 hover:bg-white/[0.04] transition-colors">
                  <div className="flex items-start gap-3">
                    <span className="text-cyan-300 text-lg leading-none mt-0.5 group-open:rotate-45 transition-transform">+</span>
                    <h3 className="font-medium text-sm flex-1">{item.q}</h3>
                  </div>
                </GlassCard>
              </summary>
              <div className="px-4 py-3 text-sm text-white/60 leading-relaxed">
                {item.a}
              </div>
            </motion.details>
          ))}
        </div>
      </section>

      {/* Email capture beta closed */}
      <BetaSignupSection />

      {/* Final CTA */}
      <section className="relative z-10 max-w-3xl mx-auto px-6 py-20 text-center">
        <GlassCard variant="elevated" className="p-10">
          <h2 className="text-3xl font-bold mb-3">
            <GradientText>Prêt à tester ?</GradientText>
          </h2>
          <p className="text-white/70 mb-6">
            14 jours d'essai Pro gratuit, sans carte. Ouverture officielle après le 6 juin 2026.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <Link
              to="/live"
              className="px-8 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
            >
              Voir le live →
            </Link>
            <Link
              to="/track-record"
              className="px-8 py-3 rounded-xl border border-white/15 text-white/80 text-sm font-medium hover:bg-white/5"
            >
              Track record public
            </Link>
          </div>
        </GlassCard>
      </section>

      {/* Footer */}
      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40 space-y-3">
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <Link to="/live" className="hover:text-white/70">Live</Link>
          <span>·</span>
          <Link to="/track-record" className="hover:text-white/70">Track record</Link>
          <span>·</span>
          <Link to="/research" className="hover:text-white/70">Recherche</Link>
          <span>·</span>
          <Link to="/changelog" className="hover:text-white/70">Changelog</Link>
          <span>·</span>
          <Link to="/about" className="hover:text-white/70">À propos</Link>
          <span>·</span>
          <Link to="/pricing" className="hover:text-white/70">Tarifs</Link>
        </div>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <a href="/docs/cgu.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">CGU</a>
          <span>·</span>
          <a href="/docs/cgv.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">CGV</a>
          <span>·</span>
          <a href="/docs/privacy.html" target="_blank" rel="noopener noreferrer" className="hover:text-white/70">Confidentialité</a>
          <span>·</span>
          <a href="mailto:support@scalping-radar.com" className="hover:text-white/70">Contact</a>
        </div>
        <p>
          © 2026 Scalping Radar · Les performances passées ne préjugent pas des
          performances futures · Pas un conseil d'investissement.
        </p>
      </footer>
    </div>
  );
}

/**
 * Email capture pendant la phase beta closed (avant ouverture signup
 * 2026-06-07). Capture les emails intéressés pour notification d'ouverture.
 * POST /api/public/leads/subscribe — idempotent.
 */
function BetaSignupSection() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes('@')) {
      setStatus('error');
      setMessage('Email invalide');
      return;
    }
    setStatus('loading');
    try {
      const res = await api.publicLeadSubscribe(email, 'landing');
      if (res.ok) {
        setStatus('success');
        setMessage(res.message || 'Tu es sur la liste.');
        setEmail('');
      } else {
        setStatus('error');
        setMessage(res.message || 'Erreur, réessaie');
      }
    } catch {
      setStatus('error');
      setMessage('Erreur réseau, réessaie');
    }
  };

  return (
    <section className="relative z-10 max-w-3xl mx-auto px-6 py-16">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5 }}
      >
        <GlassCard variant="elevated" className="p-8 sm:p-10 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-400/10 border border-amber-400/30 mb-5">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="text-xs uppercase tracking-wider text-amber-300">
              Beta fermée jusqu'au 2026-06-07
            </span>
          </div>
          <h2 className="text-2xl sm:text-3xl font-bold mb-3">
            <GradientText>Sois prévenu à l'ouverture</GradientText>
          </h2>
          <p className="text-white/70 mb-6 max-w-xl mx-auto">
            Le signup ouvre après le gate Phase 4 (6 juin 2026). Laisse ton email,
            on te prévient avec un code <strong className="text-white/90">early-bird -20%</strong>{' '}
            sur les 6 premiers mois Pro.
          </p>
          <form
            onSubmit={submit}
            className="flex flex-col sm:flex-row gap-2 max-w-md mx-auto"
          >
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ton@email.com"
              className="flex-1 px-4 py-3 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-cyan-400/20 transition-all font-mono text-sm"
              disabled={status === 'loading' || status === 'success'}
            />
            <button
              type="submit"
              disabled={status === 'loading' || status === 'success'}
              className="px-6 py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {status === 'loading' ? 'Envoi…' : status === 'success' ? '✓ Ajouté' : "M'inscrire"}
            </button>
          </form>
          {message && (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className={`text-xs mt-3 ${status === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}
            >
              {message}
            </motion.p>
          )}
          <p className="text-xs text-white/40 mt-5">
            Pas de spam. Pas de revente d'email. Juste un mail à l'ouverture + une éventuelle relance
            au moment du gate Phase 5 (octobre 2026).
          </p>
        </GlassCard>
      </motion.div>
    </section>
  );
}
