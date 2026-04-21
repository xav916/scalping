import { motion } from 'motion/react';

interface Props {
  values: number[];
  width?: number;
  height?: number;
  variant?: 'buy' | 'sell' | 'neutral';
  showEntry?: number;
  showSL?: number;
  showTP?: number;
  responsive?: boolean;        // true = svg width 100% du parent via viewBox
}

/** Mini sparkline SVG pour afficher une série de close prices dans une carte.
 *  Auto-scale sur min/max + padding 5%. Ligne animée au mount. */
export function Sparkline({
  values,
  width = 200,
  height = 36,
  variant = 'neutral',
  showEntry,
  showSL,
  showTP,
  responsive = true,
}: Props) {
  if (values.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[9px] text-white/25 font-mono"
        style={{ width, height }}
      >
        chargement…
      </div>
    );
  }

  const min = Math.min(...values, ...(showSL !== undefined ? [showSL] : []));
  const max = Math.max(...values, ...(showTP !== undefined ? [showTP] : []));
  const range = max - min || 1;
  const padY = 2;

  const scaleX = (i: number) => (i / (values.length - 1)) * width;
  const scaleY = (v: number) =>
    padY + ((max - v) / range) * (height - 2 * padY);

  const pathD = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(2)},${scaleY(v).toFixed(2)}`)
    .join(' ');

  // Fill area sous la courbe pour effet gradient
  const fillD = `${pathD} L ${scaleX(values.length - 1).toFixed(2)},${height} L 0,${height} Z`;

  const stops =
    variant === 'buy'
      ? { line: '#22d3ee', fillTop: 'rgba(34,211,238,0.25)', fillBot: 'rgba(34,211,238,0)' }
      : variant === 'sell'
      ? { line: '#ec4899', fillTop: 'rgba(236,72,153,0.25)', fillBot: 'rgba(236,72,153,0)' }
      : { line: 'rgba(255,255,255,0.6)', fillTop: 'rgba(255,255,255,0.12)', fillBot: 'rgba(255,255,255,0)' };

  const gradientId = `spark-${variant}-${Math.random().toString(36).slice(2, 8)}`;

  const svgProps = responsive
    ? { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none' as const, style: { width: '100%', height, display: 'block' as const } }
    : { width, height, className: 'block' };

  return (
    <svg {...svgProps}>
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={stops.fillTop} />
          <stop offset="100%" stopColor={stops.fillBot} />
        </linearGradient>
      </defs>

      {/* Ligne SL (rouge, pointillée) */}
      {showSL !== undefined && showSL >= min && showSL <= max && (
        <line
          x1={0}
          y1={scaleY(showSL)}
          x2={width}
          y2={scaleY(showSL)}
          stroke="rgba(244,63,94,0.35)"
          strokeWidth={1}
          strokeDasharray="2,3"
        />
      )}
      {/* Ligne TP (vert, pointillée) */}
      {showTP !== undefined && showTP >= min && showTP <= max && (
        <line
          x1={0}
          y1={scaleY(showTP)}
          x2={width}
          y2={scaleY(showTP)}
          stroke="rgba(52,211,153,0.35)"
          strokeWidth={1}
          strokeDasharray="2,3"
        />
      )}
      {/* Ligne entry (blanc, pointillée) */}
      {showEntry !== undefined && showEntry >= min && showEntry <= max && (
        <line
          x1={0}
          y1={scaleY(showEntry)}
          x2={width}
          y2={scaleY(showEntry)}
          stroke="rgba(255,255,255,0.35)"
          strokeWidth={1}
          strokeDasharray="1,2"
        />
      )}

      {/* Fill gradient sous la courbe */}
      <motion.path
        d={fillD}
        fill={`url(#${gradientId})`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4 }}
      />

      {/* Courbe */}
      <motion.path
        d={pathD}
        stroke={stops.line}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        fill="none"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
      />

      {/* Point final en surbrillance */}
      <motion.circle
        cx={scaleX(values.length - 1)}
        cy={scaleY(values[values.length - 1])}
        r={2.5}
        fill={stops.line}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ duration: 0.3, delay: 0.7 }}
      />
    </svg>
  );
}
