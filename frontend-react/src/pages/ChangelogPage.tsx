import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

/**
 * Page publique /v2/changelog — liste les commits récents.
 * Différenciation par transparence : on montre exactement ce qui change.
 */

const TYPE_COLORS: Record<string, string> = {
  feat: 'bg-emerald-400/15 text-emerald-300 border-emerald-400/30',
  fix: 'bg-amber-400/15 text-amber-300 border-amber-400/30',
  research: 'bg-cyan-400/15 text-cyan-300 border-cyan-400/30',
  docs: 'bg-white/10 text-white/60 border-white/20',
  test: 'bg-violet-400/15 text-violet-300 border-violet-400/30',
  refactor: 'bg-blue-400/15 text-blue-300 border-blue-400/30',
  other: 'bg-white/5 text-white/40 border-white/10',
};

function typeColor(t: string): string {
  return TYPE_COLORS[t] ?? TYPE_COLORS.other;
}

export function ChangelogPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['public', 'changelog'],
    queryFn: () => api.publicChangelog(),
    staleTime: 5 * 60_000,
  });

  const commits = data?.commits ?? [];

  // Group by date
  const byDate: Record<string, typeof commits> = {};
  for (const c of commits) {
    if (!byDate[c.date]) byDate[c.date] = [];
    byDate[c.date].push(c);
  }
  const dates = Object.keys(byDate).sort().reverse();

  return (
    <div className="min-h-screen">
      <AnimatedMeshGradient />

      <header className="relative z-10 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto">
        <Link to="/" className="flex items-center gap-2">
          <RadarPulse size={32} />
          <span className="font-semibold tracking-tight">Scalping Radar</span>
        </Link>
        <nav className="flex items-center gap-5">
          <Link to="/live" className="text-sm text-white/60 hover:text-white transition-colors">Live</Link>
          <Link to="/research" className="text-sm text-white/60 hover:text-white transition-colors">Recherche</Link>
          <Link to="/pricing" className="text-sm text-white/60 hover:text-white transition-colors">Tarifs</Link>
        </nav>
      </header>

      <section className="relative z-10 max-w-4xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3">
            <GradientText>Changelog</GradientText>
          </h1>
          <p className="text-white/60 text-sm max-w-2xl mx-auto">
            Les 50 derniers commits du projet. Aucun produit en SaaS retail
            n'expose son log technique au public — nous oui. Tu vois ce qu'on bouge,
            quand, pourquoi.
          </p>
        </motion.div>

        {isLoading && (
          <p className="text-center text-white/50 py-8">Chargement…</p>
        )}

        <div className="space-y-8">
          {dates.map((date) => (
            <motion.div
              key={date}
              initial={{ opacity: 0, x: -8 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3 }}
            >
              <h3 className="text-xs uppercase tracking-wider text-white/40 mb-3 font-mono">
                {new Date(date).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}
              </h3>
              <div className="space-y-2">
                {byDate[date].map((c) => (
                  <GlassCard key={c.hash} className="p-3 hover:bg-white/[0.03] transition-colors">
                    <div className="flex items-start gap-3 flex-wrap sm:flex-nowrap">
                      <span className={`text-[10px] uppercase px-2 py-0.5 rounded-full border whitespace-nowrap ${typeColor(c.type)}`}>
                        {c.type}{c.scope ? `(${c.scope})` : ''}
                      </span>
                      <p className="text-sm text-white/80 flex-1 leading-relaxed">{c.subject}</p>
                      <span className="text-[10px] font-mono text-white/30 whitespace-nowrap">{c.hash}</span>
                    </div>
                  </GlassCard>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        {commits.length === 0 && !isLoading && (
          <p className="text-center text-white/50 py-8">Pas de commits récents.</p>
        )}

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Convention de commit</h3>
            <p className="text-xs text-white/60 leading-relaxed">
              On suit Conventional Commits : <span className="font-mono text-cyan-300">feat</span>{' '}
              (nouvelle fonctionnalité), <span className="font-mono text-amber-300">fix</span>{' '}
              (correction de bug), <span className="font-mono text-cyan-300">research</span>{' '}
              (expérience), <span className="font-mono text-white/50">docs</span> (documentation),
              etc.
            </p>
          </GlassCard>
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Pourquoi exposer le changelog ?</h3>
            <p className="text-xs text-white/60 leading-relaxed">
              Parce que la transparence opérationnelle est un signal de confiance.
              Tu vois la cadence de développement, les corrections, les nouvelles
              fonctionnalités — pas juste les promesses marketing.
            </p>
          </GlassCard>
        </div>
      </section>

      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>Changelog public · 50 derniers commits · Open source à terme</p>
      </footer>
    </div>
  );
}
