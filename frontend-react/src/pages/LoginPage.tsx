import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

export function LoginPage() {
  const { login, config } = useAuth();
  const signupEnabled = config.data?.signup_enabled ?? false;
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    login.mutate(
      { username, password },
      {
        onSuccess: () => navigate('/dashboard', { replace: true }),
        onError: () => setError('Identifiants invalides'),
      }
    );
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
          {/* Signature radar */}
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="flex justify-center mb-5"
          >
            <RadarPulse size={64} />
          </motion.div>

          {/* Titre */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.2 }}
          >
            <h1 className="text-3xl font-bold text-center mb-1 tracking-tight">
              <GradientText>Scalping Radar</GradientText>
            </h1>
            <p className="text-xs text-white/40 text-center mb-8 uppercase tracking-[0.3em]">
              Connexion requise
            </p>
          </motion.div>

          {/* Formulaire */}
          <motion.form
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            onSubmit={submit}
            className="space-y-4"
          >
            <div>
              <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                Email ou utilisateur
              </label>
              <input
                type="text"
                autoComplete="username"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-cyan-400/20 transition-all font-mono text-sm"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                Mot de passe
              </label>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-pink-400/20 transition-all font-mono text-sm"
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
            <motion.button
              type="submit"
              disabled={login.isPending}
              whileHover={{ scale: login.isPending ? 1 : 1.02 }}
              whileTap={{ scale: login.isPending ? 1 : 0.98 }}
              className="relative w-full py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50 transition-opacity overflow-hidden group"
            >
              <span className="relative z-10">
                {login.isPending ? 'Connexion…' : 'Se connecter'}
              </span>
              {/* Glow sweep au hover */}
              <span
                aria-hidden
                className="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform duration-700 bg-gradient-to-r from-transparent via-white/30 to-transparent"
              />
            </motion.button>
          </motion.form>

          {signupEnabled && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.45 }}
              className="mt-6 text-center"
            >
              <Link
                to="/signup"
                className="text-xs uppercase tracking-wider text-white/50 hover:text-cyan-300 transition-colors"
              >
                Pas de compte ? Créer un compte →
              </Link>
            </motion.div>
          )}

          {/* Trust indicators */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.5 }}
            className="mt-8 pt-5 border-t border-glass-soft flex items-center justify-between text-[10px] uppercase tracking-wider text-white/40"
          >
            <span className="flex items-center gap-1.5">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" className="text-emerald-400/80">
                <path
                  d="M12 2L4 6v6c0 5.5 3.8 10.7 8 12 4.2-1.3 8-6.5 8-12V6l-8-4z"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              </svg>
              Session chiffrée
            </span>
            <span className="font-mono">v2 · 2026.04</span>
          </motion.div>
        </GlassCard>
      </motion.div>
    </div>
  );
}
