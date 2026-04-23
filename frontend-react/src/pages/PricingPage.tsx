import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';

type Cycle = 'monthly' | 'yearly';

type Tier = {
  id: 'free' | 'pro' | 'premium';
  name: string;
  /** Prix mensuel effectif (€/mois) dans chaque cycle. */
  price_monthly: number;
  price_yearly_total: number;
  tagline: string;
  features: string[];
  highlight?: boolean;
};

// -17% sur l'annuel = équivalent à 2 mois offerts sur 12.
const TIERS: Tier[] = [
  {
    id: 'free',
    name: 'Free',
    price_monthly: 0,
    price_yearly_total: 0,
    tagline: 'Pour découvrir',
    features: [
      'Dashboard lecture',
      '1 paire surveillée',
      'Historique 7 jours',
      'Pas d\'alertes Telegram',
    ],
  },
  {
    id: 'pro',
    name: 'Pro',
    price_monthly: 19,
    price_yearly_total: 190,
    tagline: 'Pour trader sérieusement',
    highlight: true,
    features: [
      'Dashboard complet',
      '5 paires surveillées',
      'Historique illimité',
      'Alertes Telegram',
      'Rejections log',
    ],
  },
  {
    id: 'premium',
    name: 'Premium',
    price_monthly: 39,
    price_yearly_total: 390,
    tagline: 'Toutes les features',
    features: [
      'Tout Pro +',
      '16 paires surveillées',
      'Backtest illimité',
      'Multi-broker',
      'Support prioritaire',
    ],
  },
];

const TIER_ORDER: Tier['id'][] = ['free', 'pro', 'premium'];

function formatEuro(n: number): string {
  return n % 1 === 0 ? `${n}€` : `${n.toFixed(2).replace('.', ',')}€`;
}

export function PricingPage() {
  const navigate = useNavigate();

  const tierInfo = useQuery({
    queryKey: ['user', 'tier'],
    queryFn: api.userTier,
    retry: 0,
    staleTime: 60_000,
  });
  const currentTier = tierInfo.data?.tier ?? 'free';
  const currentCycle = tierInfo.data?.billing_cycle ?? null;
  const isAuth = !tierInfo.isError;

  // Le toggle s'initialise sur le cycle actuel du user (ou monthly par défaut).
  const [cycle, setCycle] = useState<Cycle>(currentCycle === 'yearly' ? 'yearly' : 'monthly');

  const checkout = useMutation({
    mutationFn: ({ tier, c }: { tier: 'pro' | 'premium'; c: Cycle }) =>
      api.stripeCheckout(tier, c),
    onSuccess: (data) => {
      if (data.url) {
        window.location.href = data.url;
      }
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 503) {
        alert('Les paiements ne sont pas encore activés. Revenez bientôt !');
      } else if (err instanceof ApiError && err.status === 401) {
        navigate('/login');
      } else {
        alert('Erreur lors de la création du checkout');
      }
    },
  });

  const portal = useMutation({
    mutationFn: () => api.stripePortal(),
    onSuccess: (data) => {
      if (data.url) window.location.href = data.url;
    },
    onError: () => alert('Impossible d\'ouvrir le portail Stripe'),
  });

  const handleAction = (tier: Tier) => {
    if (!isAuth) {
      navigate('/signup');
      return;
    }
    if (tier.id === 'free') return;

    // Même tier : si cycle différent, bascule via portal (Stripe gère le prorata) ;
    // si cycle identique, juste gérer l'abonnement.
    if (tier.id === currentTier) {
      portal.mutate();
      return;
    }
    checkout.mutate({ tier: tier.id, c: cycle });
  };

  /** Libellé du CTA selon l'état user + tier + cycle sélectionné. */
  const ctaLabel = (tier: Tier): string => {
    if (!isAuth) return tier.id === 'free' ? 'Créer un compte' : 'Créer un compte';
    if (tier.id === 'free') {
      return currentTier === 'free' ? 'Gratuit à vie' : 'Downgrade';
    }
    if (tier.id === currentTier) {
      // Même tier — précise si changement de cycle ou pas.
      if (currentCycle && currentCycle !== cycle) {
        return cycle === 'yearly' ? 'Passer en annuel' : 'Passer en mensuel';
      }
      return 'Gérer mon abonnement';
    }
    // Tier différent.
    const isDowngrade =
      TIER_ORDER.indexOf(tier.id) < TIER_ORDER.indexOf(currentTier as Tier['id']);
    if (isDowngrade) return 'Downgrade';
    return `Passer en ${tier.name}`;
  };

  return (
    <div className="min-h-screen py-16 px-4">
      <AnimatedMeshGradient />

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="max-w-5xl mx-auto"
      >
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold mb-2">
            <GradientText>Choisis ton plan</GradientText>
          </h1>
          <p className="text-white/60 text-sm">
            Sans engagement, annulable à tout moment depuis ton espace.
          </p>
          {tierInfo.data?.trial_active && tierInfo.data?.trial_days_left !== null && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-2 mt-4 px-3 py-1.5 rounded-full bg-cyan-400/15 border border-cyan-400/30"
            >
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <span className="text-xs text-cyan-200">
                Trial Pro actif — il te reste{' '}
                <strong>
                  {tierInfo.data.trial_days_left}{' '}
                  jour{(tierInfo.data.trial_days_left ?? 0) > 1 ? 's' : ''}
                </strong>
              </span>
            </motion.div>
          )}
        </div>

        {/* Toggle Mensuel/Annuel */}
        <div className="flex justify-center mb-10">
          <div className="relative inline-flex items-center gap-1 p-1 rounded-xl bg-white/5 border border-white/10">
            <CycleButton
              active={cycle === 'monthly'}
              onClick={() => setCycle('monthly')}
              label="Mensuel"
            />
            <CycleButton
              active={cycle === 'yearly'}
              onClick={() => setCycle('yearly')}
              label="Annuel"
              badge="-17%"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TIERS.map((tier) => {
            const isCurrent = isAuth && tier.id === currentTier;
            const sameCycle = currentCycle === cycle;

            // Prix affiché : toujours "équivalent mensuel" pour comparabilité.
            const monthly_eq =
              cycle === 'yearly'
                ? tier.price_yearly_total / 12
                : tier.price_monthly;
            const showSaving = cycle === 'yearly' && tier.id !== 'free';

            return (
              <motion.div
                key={tier.id}
                whileHover={{ y: -4 }}
                transition={{ duration: 0.2 }}
              >
                <GlassCard
                  variant={tier.highlight ? 'elevated' : 'default'}
                  className={`p-6 h-full flex flex-col ${
                    tier.highlight ? 'ring-1 ring-cyan-400/40' : ''
                  }`}
                >
                  {tier.highlight && (
                    <div className="inline-flex self-start px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider bg-cyan-400/20 text-cyan-300 mb-3">
                      Populaire
                    </div>
                  )}
                  <h2 className="text-2xl font-bold mb-1">{tier.name}</h2>
                  <p className="text-xs uppercase tracking-wider text-white/40 mb-4">
                    {tier.tagline}
                  </p>
                  <div className="mb-2 min-h-[70px]">
                    <span className="text-4xl font-bold">{formatEuro(monthly_eq)}</span>
                    {tier.id !== 'free' && (
                      <span className="text-white/50 text-sm">/mois</span>
                    )}
                    {showSaving && (
                      <div className="mt-1 text-xs text-emerald-400">
                        Facturé {tier.price_yearly_total}€/an
                      </div>
                    )}
                    {!showSaving && tier.id !== 'free' && (
                      <div className="mt-1 text-xs text-white/40">
                        soit {tier.price_yearly_total}€/an en annuel
                      </div>
                    )}
                  </div>

                  <ul className="space-y-2 mb-6 mt-3 flex-1">
                    {tier.features.map((f) => (
                      <li key={f} className="text-sm text-white/70 flex items-start gap-2">
                        <span className="text-cyan-400 mt-0.5">✓</span>
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>

                  <button
                    onClick={() => handleAction(tier)}
                    disabled={tier.id === 'free' && isCurrent}
                    className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-opacity ${
                      isCurrent && sameCycle
                        ? 'bg-white/10 text-white/70'
                        : tier.highlight || (isCurrent && !sameCycle)
                          ? 'bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900'
                          : 'bg-white/10 text-white hover:bg-white/15'
                    } disabled:opacity-50`}
                  >
                    {ctaLabel(tier)}
                  </button>
                </GlassCard>
              </motion.div>
            );
          })}
        </div>

        {isAuth && tierInfo.data?.stripe_customer_set && (
          <div className="text-center mt-8">
            <button
              onClick={() => portal.mutate()}
              disabled={portal.isPending}
              className="text-xs uppercase tracking-wider text-white/50 hover:text-cyan-300"
            >
              Gérer mon abonnement, factures et carte →
            </button>
          </div>
        )}
      </motion.div>
    </div>
  );
}

function CycleButton({
  active,
  onClick,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  badge?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative px-5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active ? 'text-slate-900' : 'text-white/70 hover:text-white'
      }`}
    >
      {active && (
        <motion.span
          layoutId="cycle-pill"
          transition={{ type: 'spring', stiffness: 500, damping: 40 }}
          className="absolute inset-0 rounded-lg bg-gradient-to-br from-cyan-400 to-pink-500"
        />
      )}
      <span className="relative z-10 flex items-center gap-1.5">
        {label}
        {badge && (
          <span
            className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
              active ? 'bg-slate-900/20 text-slate-900' : 'bg-emerald-400/20 text-emerald-300'
            }`}
          >
            {badge}
          </span>
        )}
      </span>
    </button>
  );
}
