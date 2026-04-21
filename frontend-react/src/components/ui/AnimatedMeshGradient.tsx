import { motion } from 'motion/react';

/** Mesh gradient avec drift lent des 3 radial-gradients.
 *  Utilisé sur la LoginPage pour un wow factor à l'entrée.
 *  Respecte prefers-reduced-motion via reset des transforms. */
export function AnimatedMeshGradient() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <motion.div
        className="absolute inset-0"
        animate={{
          background: [
            'radial-gradient(ellipse 600px 300px at 15% 10%, rgba(139,92,246,0.22), transparent 60%), radial-gradient(ellipse 500px 300px at 85% 90%, rgba(236,72,153,0.16), transparent 60%), radial-gradient(ellipse 500px 200px at 50% 50%, rgba(34,211,238,0.10), transparent 60%)',
            'radial-gradient(ellipse 600px 300px at 70% 20%, rgba(139,92,246,0.20), transparent 60%), radial-gradient(ellipse 500px 300px at 20% 80%, rgba(236,72,153,0.18), transparent 60%), radial-gradient(ellipse 500px 200px at 60% 40%, rgba(34,211,238,0.12), transparent 60%)',
            'radial-gradient(ellipse 600px 300px at 40% 80%, rgba(139,92,246,0.18), transparent 60%), radial-gradient(ellipse 500px 300px at 60% 20%, rgba(236,72,153,0.14), transparent 60%), radial-gradient(ellipse 500px 200px at 30% 70%, rgba(34,211,238,0.14), transparent 60%)',
            'radial-gradient(ellipse 600px 300px at 15% 10%, rgba(139,92,246,0.22), transparent 60%), radial-gradient(ellipse 500px 300px at 85% 90%, rgba(236,72,153,0.16), transparent 60%), radial-gradient(ellipse 500px 200px at 50% 50%, rgba(34,211,238,0.10), transparent 60%)',
          ],
        }}
        transition={{
          duration: 24,
          repeat: Infinity,
          ease: 'linear',
        }}
      />
    </div>
  );
}
