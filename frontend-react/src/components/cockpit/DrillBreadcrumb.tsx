import { useEffect } from 'react';
import type { DrillSegment } from '@/types/domain';

interface Props {
  drillPath: DrillSegment[];
  onDrillBack(levels: number): void;
}

/** Breadcrumb cliquable du drill-down. Affiché seulement si drillPath.length > 0.
 *  Esc remonte d'un cran. */
export function DrillBreadcrumb({ drillPath, onDrillBack }: Props) {
  useEffect(() => {
    if (drillPath.length === 0) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDrillBack(1);
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [drillPath.length, onDrillBack]);

  if (drillPath.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 text-xs flex-wrap py-2 px-2 rounded-lg bg-white/[0.02] border border-cyan-400/10">
      <button
        type="button"
        onClick={() => onDrillBack(1)}
        className="w-6 h-6 flex items-center justify-center rounded-md text-white/60 hover:text-cyan-300 hover:bg-cyan-400/10 transition-colors"
        aria-label="Retour (Esc)"
        title="Esc"
      >
        ←
      </button>
      {drillPath.map((seg, i) => {
        const last = i === drillPath.length - 1;
        const levelsToGoBack = drillPath.length - 1 - i;
        return (
          <span key={`${seg.start}-${i}`} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-white/20">›</span>}
            {last ? (
              <span className="text-cyan-300 font-semibold">{seg.label}</span>
            ) : (
              <button
                type="button"
                onClick={() => onDrillBack(levelsToGoBack)}
                className="text-white/60 hover:text-cyan-300 transition-colors underline-offset-2 hover:underline"
              >
                {seg.label}
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}
