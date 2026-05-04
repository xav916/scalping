import { useState, useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'motion/react';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';
import { ApiError } from '@/lib/api';
import { captureRefCodeFromUrl, getStoredRefCode } from '@/lib/referralCode';

const PASSWORD_MIN = 8;

export function SignupPage() {
  const { signup, login, config } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Beta fermée : le flag serveur bloque le signup public, mais la query
  // `?preview=1` affiche quand même le form pour tester le funnel end-to-end
  // depuis une whitelist d'emails (vérifiée côté backend par SIGNUP_WHITELIST).
  const previewMode = searchParams.get('preview') === '1';
  const signupEnabled = config.data?.signup_enabled ?? false;

  // Capture le code de parrainage depuis URL ou localStorage
  useEffect(() => {
    captureRefCodeFromUrl();
  }, []);
  const refCode = getStoredRefCode();
  if (config.isFetched && !signupEnabled && !previewMode) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <AnimatedMeshGradient />
        <GlassCard variant="elevated" className="p-8 max-w-sm text-center">
          <p className="text-white/70 text-sm mb-4">
            Les inscriptions ne sont pas encore ouvertes.
          </p>
          <Link
            to="/login"
            className="text-cyan-400 hover:text-cyan-300 text-sm uppercase tracking-wider"
          >
            Aller au login →
          </Link>
        </GlassCard>
      </div>
    );
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.includes('@')) {
      setError('Email invalide');
      return;
    }
    if (password.length < PASSWORD_MIN) {
      setError(`Password trop court (${PASSWORD_MIN} caractères min)`);
      return;
    }
    if (password !== confirm) {
      setError('Les passwords ne correspondent pas');
      return;
    }
    if (!acceptedTerms) {
      setError('Vous devez accepter les CGU, CGV et la politique de confidentialité');
      return;
    }
    signup.mutate(
      { email, password, accepted_terms: true, referral_code: refCode || undefined },
      {
        onSuccess: () => {
          // Auto-login après signup réussi.
          login.mutate(
            { username: email, password },
            {
              onSuccess: () => navigate('/dashboard', { replace: true }),
              onError: () => navigate('/login', { replace: true }),
            }
          );
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setError('Un compte existe déjà pour cet email');
          } else if (err instanceof ApiError && err.status === 400) {
            setError(err.message || 'Requête invalide');
          } else {
            setError('Erreur serveur, réessayer');
          }
        },
      }
    );
  };

  const busy = signup.isPending || login.isPending;

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
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="flex justify-center mb-5"
          >
            <RadarPulse size={64} />
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.2 }}
          >
            <h1 className="text-3xl font-bold text-center mb-1 tracking-tight">
              <GradientText>Scalping Radar</GradientText>
            </h1>
            <p className="text-xs text-white/40 text-center mb-8 uppercase tracking-[0.3em]">
              Créer un compte
            </p>
          </motion.div>

          {refCode && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="mb-4 px-3 py-2 rounded-lg bg-emerald-400/10 border border-emerald-400/30 text-xs text-emerald-300 text-center"
            >
              ✓ Code parrainage <strong className="font-mono">{refCode}</strong> appliqué — early-bird -20% sur 6 mois
            </motion.div>
          )}

          <motion.form
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.3 }}
            onSubmit={submit}
            className="space-y-4"
          >
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
                className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-cyan-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-cyan-400/20 transition-all font-mono text-sm"
              />
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                Mot de passe
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  minLength={PASSWORD_MIN}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-2.5 pr-11 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-pink-400/20 transition-all font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
                  aria-pressed={showPassword}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-white/40 hover:text-pink-300 hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-pink-400/30 transition-colors"
                >
                  {showPassword ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                      <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                      <line x1="2" y1="2" x2="22" y2="22" />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
                Confirmer le mot de passe
              </label>
              <div className="relative">
                <input
                  type={showConfirm ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full px-4 py-2.5 pr-11 rounded-xl bg-white/5 border border-glass-soft focus:border-pink-400/50 focus:bg-white/[0.07] focus:outline-none focus:ring-2 focus:ring-pink-400/20 transition-all font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm((v) => !v)}
                  aria-label={showConfirm ? 'Masquer la confirmation' : 'Afficher la confirmation'}
                  aria-pressed={showConfirm}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-white/40 hover:text-pink-300 hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-pink-400/30 transition-colors"
                >
                  {showConfirm ? (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                      <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                      <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                      <line x1="2" y1="2" x2="22" y2="22" />
                    </svg>
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <label className="flex items-start gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border border-glass-soft bg-white/5 text-cyan-400 focus:ring-2 focus:ring-cyan-400/30 focus:ring-offset-0 accent-cyan-400 cursor-pointer"
              />
              <span className="text-xs text-white/60 leading-relaxed">
                J'accepte les{' '}
                <a
                  href="/docs/cgu.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
                >
                  CGU
                </a>
                , les{' '}
                <a
                  href="/docs/cgv.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
                >
                  CGV
                </a>{' '}
                et la{' '}
                <a
                  href="/docs/privacy.html"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
                >
                  politique de confidentialité
                </a>
                .
              </span>
            </label>
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
              disabled={busy || !acceptedTerms}
              whileHover={{ scale: busy || !acceptedTerms ? 1 : 1.02 }}
              whileTap={{ scale: busy || !acceptedTerms ? 1 : 0.98 }}
              className="relative w-full py-3 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-opacity overflow-hidden group"
            >
              <span className="relative z-10">
                {busy ? 'Création…' : 'Créer mon compte'}
              </span>
              <span
                aria-hidden
                className="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform duration-700 bg-gradient-to-r from-transparent via-white/30 to-transparent"
              />
            </motion.button>
          </motion.form>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.5 }}
            className="mt-6 text-center"
          >
            <Link
              to="/login"
              className="text-xs uppercase tracking-wider text-white/50 hover:text-cyan-300 transition-colors"
            >
              Déjà inscrit ? Se connecter →
            </Link>
          </motion.div>
        </GlassCard>
      </motion.div>
    </div>
  );
}
