import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'motion/react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

const DISMISS_KEY = 'trial-banner-dismissed-at';

/**
 * Bannière persistante affichée en haut des pages authentifiées tant qu'un
 * trial Pro est actif. Permet de cliquer pour dismiss (sessionStorage,
 * réapparaît à la prochaine ouverture de navigateur).
 *
 * - Silencieux si trial inactif / user env legacy / pas de trial_days_left.
 * - Affichage plus pressant quand days_left ≤ 3 (ambre).
 */
export function TrialBanner() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(DISMISS_KEY) !== null;
    } catch {
      return false;
    }
  });

  const tier = useQuery({
    queryKey: ['user', 'tier'],
    queryFn: api.userTier,
    retry: 0,
    staleTime: 5 * 60_000,
  });

  const active = tier.data?.trial_active;
  const daysLeft = tier.data?.trial_days_left;

  if (!active || daysLeft === null || daysLeft === undefined || dismissed) {
    return null;
  }

  const pressing = daysLeft <= 3;

  const handleDismiss = () => {
    try {
      sessionStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // sessionStorage disabled (private mode) → on ignore, le banner
      // réapparaitra juste à chaque navigation React, acceptable.
    }
    setDismissed(true);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.3 }}
        className={`relative z-40 w-full px-4 py-2 border-b ${
          pressing
            ? 'bg-amber-400/10 border-amber-400/30 text-amber-100'
            : 'bg-cyan-400/10 border-cyan-400/30 text-cyan-100'
        }`}
      >
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-sm">
            <span
              className={`w-2 h-2 rounded-full animate-pulse ${
                pressing ? 'bg-amber-400' : 'bg-cyan-400'
              }`}
            />
            <span>
              <strong>
                {daysLeft} jour{daysLeft > 1 ? 's' : ''}
              </strong>{' '}
              de Trial Pro restant{daysLeft > 1 ? 's' : ''}
              {pressing ? ' — pense à upgrader avant expiration' : ''}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/pricing"
              className={`text-xs uppercase tracking-wider font-semibold ${
                pressing ? 'text-amber-200 hover:text-amber-100' : 'text-cyan-200 hover:text-cyan-100'
              }`}
            >
              Voir les plans →
            </Link>
            <button
              onClick={handleDismiss}
              aria-label="Masquer"
              className="text-white/40 hover:text-white/70 text-sm leading-none"
            >
              ×
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
