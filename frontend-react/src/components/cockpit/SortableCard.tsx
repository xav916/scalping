import { type ReactNode } from 'react';
import clsx from 'clsx';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

interface Props {
  id: string;
  children: ReactNode;
  /** Désactive le drag (ex : mobile, ou URGENT cards pinned) */
  disabled?: boolean;
}

/** Wrapper qui rend n'importe quelle carte draggable via @dnd-kit. Expose
 *  un grip handle en top-right, visible uniquement au hover (desktop). */
export function SortableCard({ id, children, disabled = false }: Props) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 40 : 'auto',
  };

  return (
    <div ref={setNodeRef} style={style} className="relative group">
      {!disabled && (
        <button
          {...attributes}
          {...listeners}
          type="button"
          aria-label="Déplacer cette carte"
          className={clsx(
            'absolute top-3 right-3 z-20 w-8 h-8 flex items-center justify-center rounded-md',
            'border border-white/10 text-white/30 bg-[#0a0f1a]/80 backdrop-blur-sm',
            'cursor-grab active:cursor-grabbing',
            'opacity-0 group-hover:opacity-100 transition-opacity',
            'hover:text-cyan-300 hover:border-cyan-400/30 hover:bg-cyan-400/5',
            isDragging && 'opacity-100 text-cyan-300 border-cyan-400/40'
          )}
        >
          {/* Grip icon — 2 colonnes de 3 points */}
          <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
            <circle cx="3" cy="3" r="1.2" />
            <circle cx="9" cy="3" r="1.2" />
            <circle cx="3" cy="7" r="1.2" />
            <circle cx="9" cy="7" r="1.2" />
            <circle cx="3" cy="11" r="1.2" />
            <circle cx="9" cy="11" r="1.2" />
          </svg>
        </button>
      )}
      {children}
    </div>
  );
}
