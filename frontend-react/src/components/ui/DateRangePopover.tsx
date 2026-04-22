import { useEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import { DayPicker, type DateRange } from 'react-day-picker';
import { fr } from 'react-day-picker/locale';
import 'react-day-picker/dist/style.css';
import clsx from 'clsx';

interface Props {
  /** ISO UTC date — borne inférieure actuelle */
  startIso: string;
  /** ISO UTC date — borne supérieure actuelle */
  endIso: string;
  /** Appelé quand l'user applique un nouveau range */
  onApply: (startIso: string, endIso: string) => void;
  /** L'enfant (clickable) qui déclenche l'ouverture. Reçoit une ref. */
  children: React.ReactElement;
}

/** Popover calendrier range avec react-day-picker. Rendu via createPortal
 *  pour échapper aux clippings GlassCard (backdrop-blur). Styles custom
 *  Tailwind pour matcher le look glass/cyan. */
export function DateRangePopover({ startIso, endIso, onApply, children }: Props) {
  const triggerRef = useRef<HTMLElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const [range, setRange] = useState<DateRange | undefined>(() => ({
    from: new Date(startIso),
    to: new Date(endIso),
  }));

  // Synchronise le state interne quand les props changent
  useEffect(() => {
    setRange({ from: new Date(startIso), to: new Date(endIso) });
  }, [startIso, endIso]);

  // Ferme au clic extérieur et à Esc
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        triggerRef.current?.contains(t) ||
        popoverRef.current?.contains(t)
      ) {
        return;
      }
      setOpen(false);
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('mousedown', handleClickOutside);
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('mousedown', handleClickOutside);
      window.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const openPopover = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const width = 320;
    let left = rect.left;
    if (left + width > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - width - 8);
    }
    const top = rect.bottom + 8;
    setCoords({ top, left });
    setOpen(true);
  }, []);

  const apply = useCallback(() => {
    if (!range?.from || !range?.to) return;
    // Normalise to UTC day boundaries (start = 00:00:00, end = 23:59:59)
    const s = new Date(
      Date.UTC(range.from.getUTCFullYear(), range.from.getUTCMonth(), range.from.getUTCDate(), 0, 0, 0)
    );
    const e = new Date(
      Date.UTC(range.to.getUTCFullYear(), range.to.getUTCMonth(), range.to.getUTCDate(), 23, 59, 59)
    );
    onApply(s.toISOString(), e.toISOString());
    setOpen(false);
  }, [range, onApply]);

  // Clone le child pour lui injecter la ref + onClick
  const trigger = typeof children === 'object' && children !== null
    ? {
        ...children,
        props: {
          ...(children.props as Record<string, unknown>),
          ref: triggerRef,
          onClick: (e: React.MouseEvent) => {
            (children.props as { onClick?: (ev: React.MouseEvent) => void }).onClick?.(e);
            openPopover();
          },
        },
      }
    : children;

  const popover =
    open && coords ? (
      <AnimatePresence>
        <motion.div
          ref={popoverRef}
          initial={{ opacity: 0, y: -4, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.98 }}
          transition={{ duration: 0.15 }}
          style={{
            position: 'fixed',
            top: coords.top,
            left: coords.left,
            zIndex: 9999,
          }}
          className="rounded-xl border border-cyan-400/30 bg-[#0d111a] p-3 shadow-[0_12px_40px_rgba(0,0,0,0.7)]"
        >
          <style>{dayPickerStyles}</style>
          <DayPicker
            mode="range"
            locale={fr}
            selected={range}
            onSelect={setRange}
            numberOfMonths={1}
            className="dp-custom"
          />
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/5 mt-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-xs px-3 py-1.5 rounded-lg border border-white/10 text-white/60 hover:text-white hover:bg-white/5 transition-colors"
            >
              Annuler
            </button>
            <button
              type="button"
              onClick={apply}
              disabled={!range?.from || !range?.to}
              className={clsx(
                'text-xs px-3 py-1.5 rounded-lg border font-semibold transition-all',
                range?.from && range?.to
                  ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-300 hover:bg-cyan-400/20 shadow-[0_0_12px_rgba(34,211,238,0.15)]'
                  : 'border-white/10 text-white/30 cursor-not-allowed'
              )}
            >
              Appliquer
            </button>
          </div>
        </motion.div>
      </AnimatePresence>
    ) : null;

  return (
    <>
      {trigger}
      {typeof document !== 'undefined' && popover
        ? createPortal(popover, document.body)
        : null}
    </>
  );
}

// Styles custom pour react-day-picker v9 en glass/cyan
const dayPickerStyles = `
  .dp-custom { --rdp-accent-color: #22d3ee; --rdp-background-color: rgba(34,211,238,0.1); color: rgba(255,255,255,0.85); font-size: 12px; }
  .dp-custom .rdp-months { display: flex; justify-content: center; }
  .dp-custom .rdp-month { margin: 0; }
  .dp-custom .rdp-caption_label { font-weight: 600; color: #67e8f9; font-size: 13px; }
  .dp-custom .rdp-nav_button { color: rgba(255,255,255,0.6); }
  .dp-custom .rdp-nav_button:hover { color: #22d3ee; background: rgba(34,211,238,0.08); }
  .dp-custom .rdp-head_cell { color: rgba(255,255,255,0.35); font-weight: 500; font-size: 10px; text-transform: uppercase; }
  .dp-custom .rdp-day { color: rgba(255,255,255,0.7); border-radius: 6px; width: 32px; height: 32px; font-size: 12px; }
  .dp-custom .rdp-day:not(.rdp-day_disabled):hover { background: rgba(255,255,255,0.05); color: #fff; }
  .dp-custom .rdp-day_outside { color: rgba(255,255,255,0.2); }
  .dp-custom .rdp-day_selected,
  .dp-custom .rdp-day_range_start,
  .dp-custom .rdp-day_range_end { background: #22d3ee !important; color: #020617 !important; font-weight: 700; }
  .dp-custom .rdp-day_range_middle { background: rgba(34,211,238,0.15) !important; color: #67e8f9 !important; }
  .dp-custom .rdp-day_today:not(.rdp-day_selected) { color: #22d3ee; font-weight: 700; }
`;
