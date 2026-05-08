import { useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Tooltip, LabelWithInfo } from '@/components/ui/Tooltip';
import type { PolymarketSnapshot, PolymarketReading } from '@/types/domain';

const THEME_LABELS: Record<string, string> = {
  monetary: 'Fed / Taux',
  geopolitical: 'Géopolitique',
  economy: 'Économie',
  crypto: 'Crypto',
  politics: 'Politique',
};

const THEME_TIPS: Record<string, string> = {
  monetary: 'Marchés Polymarket sur les décisions Fed/BCE/taux directeurs',
  geopolitical: 'Marchés sur les conflits, peace deals, sanctions, Hormuz',
  economy: 'Marchés sur récession, GDP, unemployment, inflation',
  crypto: 'Marchés sur prix BTC/ETH/altcoins',
  politics: 'Marchés sur élections, impeachment, événements politiques',
};

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
}

function probColor(p: number): string {
  if (p >= 0.7) return 'from-emerald-500 to-emerald-300';
  if (p >= 0.4) return 'from-amber-400 to-amber-300';
  if (p >= 0.15) return 'from-rose-400 to-pink-400';
  return 'from-rose-600 to-rose-500';
}

function MarketRow({ m }: { m: PolymarketReading }) {
  const pct = Math.round(m.yes_prob * 100);
  // Polymarket /event/<slug> attend le slug de l'event parent (groupe les
  // markets par maturité). Le slug du market seul renvoie 404. Fallback sur
  // le market slug pour les anciens snapshots persistés sans event_slug.
  const linkSlug = m.event_slug ?? m.slug;
  const url = linkSlug ? `https://polymarket.com/event/${linkSlug}` : null;
  const inner = (
    <div className="py-2 border-b border-white/5 last:border-b-0 hover:bg-white/[0.02] transition px-1 -mx-1 rounded">
      <div className="flex items-baseline justify-between gap-2 mb-1.5">
        <span className="text-[11px] leading-snug text-white/80 line-clamp-2 flex-1">
          {m.question}
        </span>
        <span className="text-sm font-mono font-bold tabular-nums shrink-0">
          {pct}%
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
          <motion.div
            className={clsx('h-full rounded-full bg-gradient-to-r', probColor(m.yes_prob))}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
        <span className="text-[9px] font-mono text-white/40 shrink-0 tabular-nums">
          {formatVolume(m.volume_24h)}
        </span>
        {m.end_date && (
          <span className="text-[9px] font-mono text-white/30 shrink-0">
            {m.end_date.slice(5)}
          </span>
        )}
      </div>
    </div>
  );
  if (url) {
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className="block">
        {inner}
      </a>
    );
  }
  return inner;
}

/** Polymarket prediction markets : probabilités chiffrées sur évents
 * géopolitiques/macro. Shadow only — observation, pas branché au scoring. */
export function PolymarketCard({ snapshot }: { snapshot: PolymarketSnapshot | null }) {
  const themeKeys = ['geopolitical', 'monetary', 'crypto', 'economy', 'politics'];
  const [activeTab, setActiveTab] = useState<string>('top');

  if (!snapshot) {
    return (
      <GlassCard className="p-5 h-full">
        <h3 className="text-sm font-semibold tracking-tight mb-2">Probabilités événements</h3>
        <p className="text-xs text-white/40">Pas de données — refresh 5min Polymarket.</p>
      </GlassCard>
    );
  }

  const tabs = ['top', ...themeKeys.filter((k) => (snapshot.themes[k] ?? []).length > 0)];
  const items: PolymarketReading[] =
    activeTab === 'top' ? snapshot.top_volume : snapshot.themes[activeTab] ?? [];

  return (
    <GlassCard className="p-5 h-full">
      <div className="flex items-center justify-between mb-3">
        <LabelWithInfo
          label={
            <h3 className="text-sm font-semibold tracking-tight">Probabilités événements</h3>
          }
          tip="Marchés de prédiction Polymarket — probabilités chiffrées (skin in the game) sur les événements géopolitiques/macro à venir. Cliquer sur une ligne ouvre Polymarket. Refresh 5 min. Shadow only."
        />
        <span className="text-[9px] text-white/40 font-mono uppercase tracking-wider">
          POLYMARKET
        </span>
      </div>

      <div className="flex gap-1 mb-3 overflow-x-auto -mx-1 px-1 pb-1">
        {tabs.map((t) => {
          const isActive = activeTab === t;
          const label =
            t === 'top' ? `Top vol (${snapshot.top_volume.length})` : THEME_LABELS[t] ?? t;
          const tip = t === 'top' ? 'Top 5 marchés tous thèmes confondus par volume 24h' : THEME_TIPS[t];
          return (
            <Tooltip key={t} content={tip ?? label}>
              <button
                type="button"
                onClick={() => setActiveTab(t)}
                className={clsx(
                  'text-[10px] uppercase tracking-wider font-semibold px-2 py-1 rounded-md whitespace-nowrap transition',
                  isActive
                    ? 'bg-cyan-400/15 text-cyan-300 border border-cyan-400/30'
                    : 'text-white/40 hover:text-white/70 border border-transparent'
                )}
              >
                {label}
              </button>
            </Tooltip>
          );
        })}
      </div>

      {items.length === 0 ? (
        <p className="text-[11px] text-white/40">Aucun marché matchant ce thème actuellement.</p>
      ) : (
        <div className="space-y-0">
          {items.map((m) => (
            <MarketRow key={m.slug || m.question} m={m} />
          ))}
        </div>
      )}

      <div className="mt-3 pt-3 border-t border-white/5 text-[9px] text-white/30 font-mono">
        {snapshot.n_matched} markets matched / {snapshot.n_total_fetched} fetched
      </div>
    </GlassCard>
  );
}
