import { useEffect } from 'react';
import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useSpring,
  useTransform,
} from 'motion/react';

/** MeshGradient qui réagit à la position de la souris.
 *  Les 3 radial-gradients dérivent leur centre d'une interpolation avec
 *  la souris, donnant une impression de profondeur à tout le dashboard. */
export function ReactiveMeshGradient() {
  const mx = useMotionValue(0.5);
  const my = useMotionValue(0.5);

  const springConfig = { stiffness: 80, damping: 30, mass: 0.8 };
  const mxSpring = useSpring(mx, springConfig);
  const mySpring = useSpring(my, springConfig);

  useEffect(() => {
    const handleMove = (e: MouseEvent) => {
      mx.set(e.clientX / window.innerWidth);
      my.set(e.clientY / window.innerHeight);
    };
    window.addEventListener('mousemove', handleMove, { passive: true });
    return () => window.removeEventListener('mousemove', handleMove);
  }, [mx, my]);

  // Violet tache : suit légèrement la souris (amplitude 15%)
  const violetX = useTransform(mxSpring, (v) => `${10 + v * 15}%`);
  const violetY = useTransform(mySpring, (v) => `${5 + v * 10}%`);
  // Pink tache : inverse de la souris (parallaxe opposée)
  const pinkX = useTransform(mxSpring, (v) => `${85 - v * 15}%`);
  const pinkY = useTransform(mySpring, (v) => `${95 - v * 15}%`);
  // Cyan tache : centre ajustable
  const cyanX = useTransform(mxSpring, (v) => `${50 + v * 10}%`);
  const cyanY = useTransform(mySpring, (v) => `${50 - v * 5}%`);

  const bg = useMotionTemplate`
    radial-gradient(ellipse 600px 300px at ${violetX} ${violetY}, rgba(139,92,246,0.18), transparent 60%),
    radial-gradient(ellipse 500px 300px at ${pinkX} ${pinkY}, rgba(236,72,153,0.12), transparent 60%),
    radial-gradient(ellipse 500px 200px at ${cyanX} ${cyanY}, rgba(34,211,238,0.08), transparent 60%)
  `;

  return (
    <motion.div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10"
      style={{ background: bg }}
    />
  );
}
