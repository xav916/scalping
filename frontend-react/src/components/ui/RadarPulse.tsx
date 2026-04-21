import { motion } from 'motion/react';

/** Icône radar animée avec pulse concentric rings.
 *  Utilisé comme signature visuelle au-dessus des titres. */
export function RadarPulse({ size = 56 }: { size?: number }) {
  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {/* 3 anneaux qui pulsent de manière décalée */}
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="absolute rounded-full border"
          style={{
            width: size,
            height: size,
            borderColor: 'rgba(34,211,238,0.4)',
          }}
          initial={{ scale: 0.6, opacity: 0.8 }}
          animate={{ scale: 1.8, opacity: 0 }}
          transition={{
            duration: 2.4,
            repeat: Infinity,
            ease: 'easeOut',
            delay: i * 0.8,
          }}
        />
      ))}
      {/* Cœur : disque gradient avec léger halo */}
      <motion.div
        className="relative rounded-full"
        style={{
          width: size * 0.4,
          height: size * 0.4,
          background: 'linear-gradient(135deg, #22d3ee 0%, #ec4899 100%)',
          boxShadow: '0 0 20px rgba(34,211,238,0.5), 0 0 40px rgba(236,72,153,0.3)',
        }}
        animate={{ scale: [1, 1.08, 1] }}
        transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  );
}
