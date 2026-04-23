import { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const forgot = useMutation({
    mutationFn: () => api.forgotPassword(email),
    onSuccess: () => setSubmitted(true),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes('@')) return;
    forgot.mutate();
  };

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
            <GradientText>Mot de passe oublié</GradientText>
          </h1>
          <p className="text-xs text-white/40 text-center mb-6 uppercase tracking-[0.2em]">
            Réinitialisation
          </p>

          {submitted ? (
            <>
              <p className="text-sm text-white/70 text-center mb-6">
                Si un compte existe pour <strong className="font-mono">{email}</strong>, un
                email avec un lien de réinitialisation vient de partir.
              </p>
              <p className="text-xs text-white/40 text-center">
                Le lien est valide pendant 1 heure.
              </p>
              <div className="mt-6 text-center">
                <Link
                  to="/login"
                  className="text-xs uppercase tracking-wider text-white/50 hover:text-cyan-300"
                >
                  ← Retour à la connexion
                </Link>
              </div>
            </>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                  Email
                </label>
                <input
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:outline-none font-mono text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={forgot.isPending || !email.includes('@')}
                className="w-full py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50"
              >
                {forgot.isPending ? 'Envoi…' : 'Envoyer le lien'}
              </button>
              <div className="text-center pt-2">
                <Link
                  to="/login"
                  className="text-xs uppercase tracking-wider text-white/40 hover:text-white/70"
                >
                  ← Retour à la connexion
                </Link>
              </div>
            </form>
          )}
        </GlassCard>
      </motion.div>
    </div>
  );
}
