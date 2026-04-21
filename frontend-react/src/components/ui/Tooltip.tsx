import { type ReactNode, useRef, useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  /** px de décalage vertical du tooltip depuis l'enfant (default: 8) */
  offset?: number;
  /** placement préféré — "top" par défaut, flip auto sur "bottom" si près du bord haut */
  placement?: 'top' | 'bottom';
  /** délai d'apparition en ms (default: 300) */
  delay?: number;
  /** largeur max du texte (default: 240px) */
  maxWidth?: number;
  /** désactive complètement le tooltip si true */
  disabled?: boolean;
  className?: string;
}

/** Tooltip léger sans lib. Hover/focus sur l'enfant → fade-in glass bubble.
 *  Positionnement fixed calculé depuis le rect de l'enfant — échappe aux
 *  overflow:hidden parents (GlassCard, modals, etc.). */
export function Tooltip({
  content,
  children,
  offset = 8,
  placement = 'top',
  delay = 300,
  maxWidth = 240,
  disabled = false,
  className,
}: TooltipProps) {
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const [visible, setVisible] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number; flip: boolean } | null>(null);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  const computePosition = () => {
    if (!wrapperRef.current) return;
    const rect = wrapperRef.current.getBoundingClientRect();
    const wantFlip = placement === 'top' && rect.top < 80;
    let top = wantFlip ? rect.bottom + offset : rect.top - offset;
    let left = rect.left + rect.width / 2;
    // Clamp horizontal : ne jamais déborder du viewport, en tenant compte
    // du maxWidth (le tooltip est centré sur left).
    const half = maxWidth / 2;
    const minLeft = half + 8;
    const maxLeft = window.innerWidth - half - 8;
    if (left < minLeft) left = minLeft;
    if (left > maxLeft) left = maxLeft;
    // Clamp vertical : si le tooltip dépasse en bas (flip), le bloquer
    if (wantFlip && top + 60 > window.innerHeight) {
      top = window.innerHeight - 60;
    }
    setCoords({ top, left, flip: wantFlip });
  };

  const show = () => {
    if (disabled || !content) return;
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => {
      computePosition();
      setVisible(true);
    }, delay);
  };

  const hide = () => {
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    setVisible(false);
  };

  const tooltipNode =
    visible && coords && content ? (
      <AnimatePresence>
        <motion.div
          role="tooltip"
          initial={{ opacity: 0, y: coords.flip ? -4 : 4, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: coords.flip ? -4 : 4, scale: 0.97 }}
          transition={{ duration: 0.15, ease: 'easeOut' }}
          style={{
            position: 'fixed',
            top: coords.top,
            left: coords.left,
            transform: coords.flip
              ? 'translate(-50%, 0%)'
              : 'translate(-50%, -100%)',
            maxWidth,
            zIndex: 9999,
            pointerEvents: 'none',
          }}
          // Pas de backdrop-blur ici — aucun filter sur le tooltip pour
          // éviter qu'un parent transformed/filtered puisse le trapper.
          className="rounded-lg border border-cyan-400/30 bg-[#0d111a] px-3 py-2 shadow-[0_8px_24px_rgba(0,0,0,0.6)]"
        >
          <div className="text-[11px] leading-relaxed text-white/85">{content}</div>
        </motion.div>
      </AnimatePresence>
    ) : null;

  return (
    <>
      <span
        ref={wrapperRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className={clsx('inline-flex items-center', className)}
      >
        {children}
      </span>
      {typeof document !== 'undefined' && tooltipNode
        ? createPortal(tooltipNode, document.body)
        : null}
    </>
  );
}

/** Icône "i" hoverable qui affiche un tooltip. À placer à côté d'un label. */
export function InfoDot({ tip, className }: { tip: ReactNode; className?: string }) {
  return (
    <Tooltip content={tip}>
      <span
        className={clsx(
          'inline-flex items-center justify-center w-3.5 h-3.5 rounded-full',
          'border border-white/20 text-white/40 hover:text-cyan-300 hover:border-cyan-300/40',
          'text-[8px] font-semibold font-mono transition-colors',
          className
        )}
        aria-label="Plus d'informations"
      >
        i
      </span>
    </Tooltip>
  );
}

/** Raccourci : label + InfoDot. Utilisé partout pour uniformiser les Kpi. */
export function LabelWithInfo({
  label,
  tip,
  className,
}: {
  label: ReactNode;
  tip: ReactNode;
  className?: string;
}) {
  return (
    <span className={clsx('inline-flex items-center gap-1.5', className)}>
      <span>{label}</span>
      <InfoDot tip={tip} />
    </span>
  );
}
