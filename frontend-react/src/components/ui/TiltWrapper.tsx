import { type ReactNode, type MouseEvent, useEffect, useState } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react';

interface Props {
  children: ReactNode;
  maxTilt?: number;      // degrés max de rotation
  perspective?: number;  // distance de perspective
}

/** true si l'appareil n'a pas de souris fine (touch / mobile). */
function useIsCoarsePointer(): boolean {
  const [isCoarse, setIsCoarse] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(pointer: coarse)');
    setIsCoarse(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsCoarse(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return isCoarse;
}

/** Wrapper qui applique un tilt 3D subtil sur mouse move.
 *  Utilisé autour des SetupCard pour un effet tactile.
 *  IMPORTANT : tous les hooks sont appelés AVANT le early return pour
 *  respecter les Rules of Hooks — sinon crash React sur mobile quand
 *  isCoarse passe de false à true après mount. */
export function TiltWrapper({ children, maxTilt = 6, perspective = 900 }: Props) {
  const isCoarse = useIsCoarsePointer();
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const springConfig = { stiffness: 200, damping: 20, mass: 0.5 };
  const xSpring = useSpring(x, springConfig);
  const ySpring = useSpring(y, springConfig);

  const rotateX = useTransform(ySpring, [-0.5, 0.5], [maxTilt, -maxTilt]);
  const rotateY = useTransform(xSpring, [-0.5, 0.5], [-maxTilt, maxTilt]);

  const handleMove = (e: MouseEvent<HTMLDivElement>) => {
    if (isCoarse) return;
    const rect = e.currentTarget.getBoundingClientRect();
    x.set((e.clientX - rect.left) / rect.width - 0.5);
    y.set((e.clientY - rect.top) / rect.height - 0.5);
  };

  const handleLeave = () => {
    x.set(0);
    y.set(0);
  };

  if (isCoarse) {
    // Rendu sans tilt sur mobile/tablette tactile — tous les hooks ci-dessus
    // sont quand même exécutés (ordre stable = OK React), mais on n'attache
    // pas les handlers et on ne wrap pas en motion.div 3D.
    return <>{children}</>;
  }

  return (
    <div
      style={{ perspective }}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
    >
      <motion.div
        style={{
          rotateX,
          rotateY,
          transformStyle: 'preserve-3d',
        }}
      >
        {children}
      </motion.div>
    </div>
  );
}
