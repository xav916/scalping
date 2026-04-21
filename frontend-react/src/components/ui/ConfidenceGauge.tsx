import { motion } from 'motion/react';

interface Props {
  score: number;            // 0-100
  variant: 'buy' | 'sell';
  size?: number;
}

/** Jauge circulaire du score de confiance, animée au mount.
 *  Arc SVG avec gradient selon direction (buy cyan, sell pink). */
export function ConfidenceGauge({ score, variant, size = 72 }: Props) {
  const stroke = 6;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, score)) / 100;
  const dash = circumference * pct;

  const gradientId = `gauge-${variant}-${size}`;
  const stops =
    variant === 'buy'
      ? ['#22d3ee', '#a3e635']
      : ['#ec4899', '#fb923c'];

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={stops[0]} />
            <stop offset="100%" stopColor={stops[1]} />
          </linearGradient>
        </defs>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={stroke}
          fill="none"
        />
        {/* Progress */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={`url(#${gradientId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference - dash }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span
          className="font-mono font-bold leading-none"
          style={{
            fontSize: size * 0.35,
            background: `linear-gradient(135deg, ${stops[0]} 0%, ${stops[1]} 100%)`,
            WebkitBackgroundClip: 'text',
            backgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            color: 'transparent',
          }}
        >
          {score.toFixed(0)}
        </span>
      </div>
    </div>
  );
}
