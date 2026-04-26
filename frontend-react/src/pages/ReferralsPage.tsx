import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Header } from '@/components/layout/Header';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/api';

/**
 * Page utilisateur authentifié /v2/referrals — affiche le code de
 * parrainage du user, le lien partageable, et les stats (signups,
 * conversions, commissions).
 */
export function ReferralsPage() {
  const [copied, setCopied] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['referrals', 'me'],
    queryFn: () => api.referralsMe(),
    staleTime: 60_000,
  });

  const copyShareUrl = () => {
    if (!data?.share_url) return;
    navigator.clipboard.writeText(data.share_url).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => alert("Erreur copie — copie manuellement le lien")
    );
  };

  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-3xl mx-auto space-y-4">
        <Link to="/dashboard" className="text-xs text-white/40 hover:text-white/70 inline-flex items-center gap-1 mb-1">
          ← Dashboard
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Programme parrainage</h1>
        <p className="text-sm text-white/60">
          Partage ton code à un trader. Si il devient payant Pro/Premium, tu gagnes
          <strong className="text-emerald-400"> 20% commission</strong> sur ses 6 premiers mois.
        </p>

        {isLoading && <Skeleton className="h-32 w-full mt-4" />}

        {data && (
          <>
            <GlassCard variant="elevated" className="p-6 mt-4">
              <div className="text-xs uppercase tracking-wider text-white/40 mb-2">Ton code</div>
              <div className="text-3xl font-bold font-mono mb-4 text-cyan-300">{data.code}</div>

              <div className="text-xs uppercase tracking-wider text-white/40 mb-2">Ton lien partageable</div>
              <div className="flex gap-2 mb-3 flex-col sm:flex-row">
                <input
                  type="text"
                  readOnly
                  value={data.share_url}
                  onClick={(e) => (e.target as HTMLInputElement).select()}
                  className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm font-mono text-white/80"
                />
                <button
                  onClick={copyShareUrl}
                  className="px-4 py-2 rounded-lg bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 text-sm font-semibold whitespace-nowrap"
                >
                  {copied ? '✓ Copié' : 'Copier'}
                </button>
              </div>
              <p className="text-xs text-white/40">
                Le code est tracké via cookie 30 jours. Si ton filleul s'abonne dans cette
                fenêtre, tu touches la commission.
              </p>
            </GlassCard>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
              {[
                { label: 'Inscriptions', value: data.n_signups.toString(), color: 'text-cyan-300' },
                { label: 'Conversions', value: data.n_converted.toString(), color: 'text-emerald-400' },
                { label: 'Commission acquise', value: `${data.commission_total_eur.toFixed(0)}€`, color: 'text-emerald-400' },
                { label: 'À recevoir', value: `${data.commission_pending_eur.toFixed(0)}€`, color: 'text-amber-300' },
              ].map((kpi) => (
                <GlassCard key={kpi.label} className="p-4">
                  <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">{kpi.label}</div>
                  <div className={`text-2xl font-bold font-mono ${kpi.color}`}>{kpi.value}</div>
                </GlassCard>
              ))}
            </div>

            <GlassCard className="p-5 mt-4">
              <h3 className="font-semibold mb-2">Comment ça marche ?</h3>
              <ol className="text-sm text-white/60 space-y-2 list-decimal list-inside leading-relaxed">
                <li>Tu partages ton lien (Twitter, blog, Discord, WhatsApp, etc.)</li>
                <li>Quand quelqu'un clique, ton code est stocké dans son navigateur 30 jours</li>
                <li>Si il s'abonne Pro ou Premium dans cette fenêtre, on track le parrainage</li>
                <li>Tu gagnes 20% sur ses 6 premiers mois (49€ Pro × 20% × 6 = 58.80€ par filleul Pro)</li>
                <li>Paiement manuel via virement bancaire mensuel (V1 — Stripe Connect en V2)</li>
              </ol>
            </GlassCard>

            <GlassCard className="p-5 mt-4">
              <h3 className="font-semibold mb-2">Idées de partage</h3>
              <ul className="text-sm text-white/60 space-y-1.5 list-disc list-inside leading-relaxed">
                <li>Twitter thread sur ta config trading + lien</li>
                <li>Blog post review du système</li>
                <li>Discord/Telegram trading que tu fréquentes (avec accord modo)</li>
                <li>YouTube vidéo "trade-along" en direct</li>
                <li>Email à ton réseau de traders connus</li>
              </ul>
            </GlassCard>
          </>
        )}
      </main>
    </>
  );
}
