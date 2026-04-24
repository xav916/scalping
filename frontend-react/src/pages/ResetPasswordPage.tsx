import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'motion/react';
import { useMutation } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

const PASSWORD_MIN = 8;

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const navigate = useNavigate();

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);

  const reset = useMutation({
    mutationFn: () => api.resetPassword(token, password),
    onSuccess: () => {
      setTimeout(() => navigate('/login', { replace: true }), 1500);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.message || 'Lien invalide ou expiré');
      } else {
        setError('Erreur serveur, réessayer');
      }
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < PASSWORD_MIN) {
      setError(`Mot de passe trop court (${PASSWORD_MIN} caractères min)`);
      return;
    }
    if (password !== confirm) {
      setError('Les mots de passe ne correspondent pas');
      return;
    }
    reset.mutate();
  };

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <AnimatedMeshGradient />
        <GlassCard variant="elevated" className="p-8 max-w-sm text-center">
          <p className="text-white/80 mb-4">Lien invalide — token manquant.</p>
          <Link to="/forgot-password" className="text-cyan-400 hover:text-cyan-300 text-sm">
            Demander un nouveau lien →
          </Link>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <AnimatedMeshGradient />

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="w-full max-w-sm"
      >
        <GlassCard variant="elevated" className="p-8">
          <div className="flex justify-center mb-5">
            <RadarPulse size={56} />
          </div>
          <h1 className="text-2xl font-bold text-center mb-1">
            <GradientText>Nouveau mot de passe</GradientText>
          </h1>
          <p className="text-xs text-white/40 text-center mb-6 uppercase tracking-[0.2em]">
            Réinitialisation
          </p>

          {reset.isSuccess ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center"
            >
              <div className="text-5xl mb-3">✓</div>
              <p className="text-sm text-emerald-300 mb-3">
                Mot de passe changé avec succès.
              </p>
              <p className="text-xs text-white/50">Redirection vers login…</p>
            </motion.div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Nouveau mot de passe
                </label>
                <input
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={PASSWORD_MIN}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:outline-none font-mono text-sm"
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
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:outline-none font-mono text-sm"
                />
              </div>
              {error && (
                <motion.p
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="text-xs text-rose-400 text-center"
                >
                  {error}
                </motion.p>
              )}
              <button
                type="submit"
                disabled={reset.isPending || password.length < PASSWORD_MIN}
                className="w-full py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50"
              >
                {reset.isPending ? 'Mise à jour…' : 'Mettre à jour'}
              </button>
            </form>
          )}
        </GlassCard>
      </motion.div>
    </div>
  );
}
