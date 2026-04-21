import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';

interface Props {
  open: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

/** Modal de confirmation pour activer le kill switch manuel.
 *  - Esc ferme, focus trap sur l'input, backdrop-blur + glass
 *  - Demande une raison courte (maintenance, doute, événement macro, etc.) */
export function KillSwitchModal({ open, onConfirm, onCancel }: Props) {
  const [reason, setReason] = useState('maintenance');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setReason('maintenance');
    // focus sur l'input à l'ouverture
    const t = setTimeout(() => inputRef.current?.select(), 50);
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handler);
    return () => {
      clearTimeout(t);
      window.removeEventListener('keydown', handler);
    };
  }, [open, onCancel]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-xl bg-radar-deep/70"
          onClick={onCancel}
        >
          <motion.div
            onClick={(e) => e.stopPropagation()}
            initial={{ scale: 0.95, opacity: 0, y: 10 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 10 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="w-full max-w-md rounded-2xl border border-rose-400/30 bg-white/[0.04] backdrop-blur-glass shadow-[0_0_40px_rgba(244,63,94,0.25)] p-6"
          >
            <h3 className="text-lg font-semibold tracking-tight mb-1">
              Geler l'auto-exec
            </h3>
            <p className="text-xs text-white/50 mb-5">
              Les nouveaux ordres seront bloqués côté bridge. Les trades déjà
              ouverts continuent jusqu'à leur SL/TP.
            </p>
            <label className="block text-[10px] uppercase tracking-[0.2em] text-white/40 mb-2">
              Raison
            </label>
            <input
              ref={inputRef}
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && reason.trim()) {
                  onConfirm(reason.trim());
                }
              }}
              placeholder="ex: maintenance broker"
              className="w-full rounded-lg border border-glass-soft bg-white/[0.03] px-3 py-2 text-sm font-mono focus:border-rose-400/40 focus:bg-white/[0.06] focus:outline-none transition-colors"
              autoFocus
            />
            <div className="flex items-center justify-end gap-2 mt-6">
              <button
                type="button"
                onClick={onCancel}
                className="text-xs px-4 py-2 rounded-lg border border-glass-soft text-white/60 hover:text-white/90 hover:bg-white/5 transition-all uppercase tracking-wider font-semibold"
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => reason.trim() && onConfirm(reason.trim())}
                disabled={!reason.trim()}
                className={clsx(
                  'text-xs px-4 py-2 rounded-lg border transition-all uppercase tracking-wider font-semibold',
                  reason.trim()
                    ? 'border-rose-400/40 bg-rose-400/10 text-rose-300 hover:bg-rose-400/20'
                    : 'border-glass-soft text-white/30 cursor-not-allowed'
                )}
              >
                Geler l'auto-exec
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
