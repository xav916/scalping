import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui/GlassCard';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GradientText } from '@/components/ui/GradientText';

export function LoginPage() {
  const { login } = useAuth();
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
        onSuccess: () => navigate('/', { replace: true }),
        onError: () => setError('Identifiants invalides'),
      }
    );
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <MeshGradient />
      <GlassCard variant="elevated" className="w-full max-w-sm p-8">
        <h1 className="text-2xl font-semibold mb-1">
          <GradientText>Scalping Radar</GradientText>
        </h1>
        <p className="text-sm text-white/50 mb-8">Connexion requise</p>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
              Utilisateur
            </label>
            <input
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-glass-strong focus:outline-none transition-colors font-mono text-sm"
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
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-glass-strong focus:outline-none transition-colors font-mono text-sm"
            />
          </div>
          {error && <p className="text-xs text-rose-400">{error}</p>}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50 transition-opacity"
          >
            {login.isPending ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </GlassCard>
    </div>
  );
}
