import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';

/**
 * Bannière persistante "vérifie ton email" affichée sur les routes
 * authentifiées quand email_verified=false. Bouton "Renvoyer" déclenche
 * l'email de vérif. Dismiss en sessionStorage (réapparaît au prochain
 * onglet).
 */
const DISMISS_KEY = 'verify-email-banner-dismissed-at';

export function VerifyEmailBanner() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(DISMISS_KEY) !== null;
    } catch {
      return false;
    }
  });
  const [resentOk, setResentOk] = useState(false);

  const tier = useQuery({
    queryKey: ['user', 'tier'],
    queryFn: api.userTier,
    retry: 0,
    staleTime: 5 * 60_000,
  });

  const resend = useMutation({
    mutationFn: () => api.resendVerification(),
    onSuccess: () => setResentOk(true),
  });

  const verified = tier.data?.email_verified ?? true;  // default true pour ne pas blinker
  if (verified || dismissed) return null;

  const handleDismiss = () => {
    try {
      sessionStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* ignore */
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
        className="relative z-40 w-full px-4 py-2 border-b bg-amber-400/10 border-amber-400/30 text-amber-100"
      >
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-sm">
            <span className="w-2 h-2 rounded-full animate-pulse bg-amber-400" />
            <span>
              📧 Vérifie ton email pour débloquer toutes les fonctionnalités
              (upgrade payant, rappels).
            </span>
          </div>
          <div className="flex items-center gap-3">
            {resentOk ? (
              <span className="text-xs text-emerald-300">Email renvoyé ✓</span>
            ) : (
              <button
                onClick={() => resend.mutate()}
                disabled={resend.isPending}
                className="text-xs uppercase tracking-wider font-semibold text-amber-200 hover:text-amber-100 disabled:opacity-50"
              >
                {resend.isPending ? 'Envoi…' : 'Renvoyer le lien →'}
              </button>
            )}
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
