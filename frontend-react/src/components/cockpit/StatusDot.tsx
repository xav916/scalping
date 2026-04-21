import clsx from 'clsx';
import { motion } from 'motion/react';

/** Dot pulsant : rouge si `active=true` (alerte), vert sinon (OK).
 *  Utilisé dans plusieurs cartes du cockpit (kill switch, santé système). */
export function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={clsx(
        'relative inline-block w-2 h-2 rounded-full',
        active ? 'bg-rose-400' : 'bg-emerald-400'
      )}
    >
      <motion.span
        aria-hidden
        className={clsx(
          'absolute inset-0 rounded-full',
          active ? 'bg-rose-400' : 'bg-emerald-400'
        )}
        animate={{ scale: [1, 2.2], opacity: [0.6, 0] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
      />
    </span>
  );
}
