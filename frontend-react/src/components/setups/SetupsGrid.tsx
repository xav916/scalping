import { AnimatePresence } from 'motion/react';
import { useSetups } from '@/hooks/useSetups';
import { SetupCard } from './SetupCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { UI_MIN_CONFIDENCE } from '@/lib/constants';

function setupKey(s: { pair: string; direction: string; entry_price: number }) {
  return `${s.pair}-${s.direction}-${s.entry_price.toFixed(5)}`;
}

export function SetupsGrid() {
  const { data, isLoading } = useSetups();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  const setups = (data ?? [])
    .filter((s) => s.confidence_score >= UI_MIN_CONFIDENCE)
    .sort((a, b) => b.confidence_score - a.confidence_score);

  if (setups.length === 0) {
    return (
      <div className="text-center py-12 text-white/40 text-sm">
        Aucun setup ≥ {UI_MIN_CONFIDENCE} pour l'instant.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <AnimatePresence>
        {setups.map((s) => (
          <SetupCard key={setupKey(s)} setup={s} />
        ))}
      </AnimatePresence>
    </div>
  );
}
