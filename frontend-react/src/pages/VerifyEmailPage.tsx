import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { motion } from 'motion/react';
import { useMutation } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const [state, setState] = useState<'verifying' | 'success' | 'error'>('verifying');
  const [errorMsg, setErrorMsg] = useState('');

  const verify = useMutation({
    mutationFn: () => api.verifyEmail(token),
    onSuccess: () => setState('success'),
    onError: (err) => {
      setState('error');
      setErrorMsg(
        err instanceof ApiError ? err.message || 'Lien invalide' : 'Erreur serveur'
      );
    },
  });

  useEffect(() => {
    if (token) {
      verify.mutate();
    } else {
      setState('error');
      setErrorMsg('Token manquant dans le lien');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <AnimatedMeshGradient />
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-sm"
      >
        <GlassCard variant="elevated" className="p-8 text-center">
          <h1 className="text-2xl font-bold mb-2">
            <GradientText>Vérification de ton email</GradientText>
          </h1>

          {state === 'verifying' && (
            <p className="text-sm text-white/60 mt-4">En cours de vérification…</p>
          )}

          {state === 'success' && (
            <>
              <div className="text-5xl mt-4 mb-3">✓</div>
              <p className="text-sm text-emerald-300 mb-4">
                Ton email est vérifié. Tu as accès à toutes les fonctionnalités.
              </p>
              <Link
                to="/dashboard"
                className="inline-block px-5 py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold"
              >
                Aller au dashboard →
              </Link>
            </>
          )}

          {state === 'error' && (
            <>
              <div className="text-5xl mt-4 mb-3">✗</div>
              <p className="text-sm text-rose-400 mb-4">{errorMsg}</p>
              <Link
                to="/login"
                className="inline-block text-xs uppercase tracking-wider text-white/50 hover:text-cyan-300"
              >
                Retour à la connexion
              </Link>
            </>
          )}
        </GlassCard>
      </motion.div>
    </div>
  );
}
