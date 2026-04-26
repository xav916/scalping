import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'motion/react';
import { api } from '@/lib/api';
import { GlassCard } from '@/components/ui/GlassCard';
import { AnimatedMeshGradient } from '@/components/ui/AnimatedMeshGradient';
import { GradientText } from '@/components/ui/GradientText';
import { RadarPulse } from '@/components/ui/RadarPulse';

/**
 * Page publique /v2/research — expose le journal de recherche.
 *
 * USP : transparence radicale. Concurrents cachent leurs résultats, on
 * publie les 26 expériences avec verdicts (positifs ET négatifs) et liens
 * vers les détails markdown dans le repo public.
 */

function statusBadge(status: string): { color: string; label: string } {
  if (status.includes('positive')) return { color: 'bg-emerald-400/15 text-emerald-300 border-emerald-400/30', label: 'Positive' };
  if (status.includes('negative')) return { color: 'bg-rose-400/15 text-rose-300 border-rose-400/30', label: 'Négative' };
  if (status.includes('neutral')) return { color: 'bg-amber-400/15 text-amber-300 border-amber-400/30', label: 'Neutre' };
  if (status.includes('mixed')) return { color: 'bg-cyan-400/15 text-cyan-300 border-cyan-400/30', label: 'Mixte' };
  return { color: 'bg-white/10 text-white/60 border-white/20', label: status };
}

export function ResearchPage() {
  const [filter, setFilter] = useState<'all' | 'positive' | 'negative' | 'mixed'>('all');

  const { data, isLoading } = useQuery({
    queryKey: ['public', 'research', 'experiments'],
    queryFn: () => api.publicResearchExperiments(),
    staleTime: 5 * 60_000,
  });

  const experiments = data?.experiments ?? [];
  const filtered = useMemo(() => {
    if (filter === 'all') return experiments;
    return experiments.filter((e) => e.status.includes(filter));
  }, [experiments, filter]);

  const counts = useMemo(() => ({
    total: experiments.length,
    positive: experiments.filter((e) => e.status.includes('positive')).length,
    negative: experiments.filter((e) => e.status.includes('negative')).length,
    mixed: experiments.filter((e) => e.status.includes('mixed') || e.status.includes('neutral')).length,
  }), [experiments]);

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
          <Link to="/track-record" className="text-sm text-white/60 hover:text-white transition-colors">Track record</Link>
          <Link to="/pricing" className="text-sm text-white/60 hover:text-white transition-colors">Tarifs</Link>
        </nav>
      </header>

      <section className="relative z-10 max-w-5xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center mb-10"
        >
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-3">
            <GradientText>Journal de recherche</GradientText>
          </h1>
          <p className="text-white/60 text-sm max-w-2xl mx-auto">
            Toutes les expériences réalisées pour identifier les 6 stars actuelles.
            Tu vois les verdicts <span className="text-emerald-400">positifs</span>,{' '}
            <span className="text-rose-400">négatifs</span> et{' '}
            <span className="text-cyan-400">mixtes</span>. Aucune cherry-picking.
          </p>
        </motion.div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          {[
            { label: 'Total', value: counts.total.toString(), color: 'text-white/90' },
            { label: 'Positives ✓', value: counts.positive.toString(), color: 'text-emerald-400' },
            { label: 'Négatives ✗', value: counts.negative.toString(), color: 'text-rose-400' },
            { label: 'Mixtes / neutres', value: counts.mixed.toString(), color: 'text-cyan-300' },
          ].map((kpi) => (
            <GlassCard key={kpi.label} className="p-4">
              <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">{kpi.label}</div>
              <div className={`text-2xl font-bold font-mono ${kpi.color}`}>{kpi.value}</div>
            </GlassCard>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-6">
          <span className="text-xs uppercase tracking-wider text-white/40 mr-2">Filtre :</span>
          {[
            { id: 'all', label: 'Toutes' },
            { id: 'positive', label: 'Positives' },
            { id: 'negative', label: 'Négatives' },
            { id: 'mixed', label: 'Mixtes' },
          ].map((b) => (
            <button
              key={b.id}
              onClick={() => setFilter(b.id as typeof filter)}
              className={`px-3 py-1 rounded-lg text-xs transition-colors ${
                filter === b.id
                  ? 'bg-cyan-400/20 text-cyan-300 border border-cyan-400/40'
                  : 'bg-white/5 text-white/60 border border-white/10 hover:bg-white/10'
              }`}
            >
              {b.label}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {filtered.map((exp, i) => {
            const badge = statusBadge(exp.status);
            return (
              <motion.div
                key={exp.num}
                initial={{ opacity: 0, x: -8 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.3, delay: Math.min(i * 0.02, 0.4) }}
              >
                <GlassCard className="p-5">
                  <div className="flex items-start gap-4 flex-wrap sm:flex-nowrap">
                    <div className="flex-shrink-0">
                      <div className="text-xs font-mono text-white/40">#{exp.num}</div>
                      <div className="text-[10px] text-white/30 mt-0.5">{exp.date}</div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start gap-2 mb-1.5 flex-wrap">
                        <h3 className="font-semibold text-sm sm:text-base">{exp.title}</h3>
                        <span className={`text-[10px] uppercase px-2 py-0.5 rounded-full border ${badge.color}`}>
                          {badge.label}
                        </span>
                        <span className="text-[10px] uppercase px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/50">
                          {exp.track}
                        </span>
                      </div>
                      <p className="text-xs text-white/60 leading-relaxed">{exp.verdict}</p>
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            );
          })}
          {filtered.length === 0 && !isLoading && (
            <p className="text-center text-white/50 py-12">
              Aucune expérience ne correspond au filtre.
            </p>
          )}
        </div>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Pourquoi exposer les négatifs ?</h3>
            <p className="text-sm text-white/60 leading-relaxed">
              Tester 60 idées et n'en garder que 6 = ratio 10%. C'est normal. La science honnête
              c'est de publier les rejets autant que les survivants. Sinon on tombe dans le biais
              de survie : on croit qu'on a un edge magique alors qu'on a juste oublié 90 ratés.
            </p>
          </GlassCard>
          <GlassCard className="p-5">
            <h3 className="font-semibold mb-2">Aller plus loin</h3>
            <p className="text-sm text-white/60 leading-relaxed">
              Le journal complet (markdown brut) est dans le repo public.
              Chaque entrée pointe vers un fichier détaillé avec hypothèse, protocole,
              résultats chiffrés, verdict, conséquences actées.
              <Link to="/" className="text-cyan-300 hover:text-cyan-200 ml-1">Retour landing →</Link>
            </p>
          </GlassCard>
        </div>
      </section>

      <footer className="relative z-10 max-w-6xl mx-auto px-6 py-10 text-center text-xs text-white/40">
        <p>Journal de recherche public · Méthodologie ouverte · Pas un conseil d'investissement</p>
      </footer>
    </div>
  );
}
