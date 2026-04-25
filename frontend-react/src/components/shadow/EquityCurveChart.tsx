import { useMemo } from 'react';
import type { ShadowEquityPoint } from '@/types/domain';

interface Props {
  curve: ShadowEquityPoint[];
  width?: number;
  height?: number;
  capital?: number;
}

/**
 * Equity curve SVG inline, design minimal.
 * Affiche la valeur du capital virtuel au fil des setups, avec line smooth.
 * Au-dessus du capital initial = vert, en dessous = rouge.
 */
export function EquityCurveChart({
  curve,
  width = 600,
  height = 140,
  capital = 10_000,
}: Props) {
  const { path, fillPath, lastEquity, minEq, maxEq } = useMemo(() => {
    if (curve.length === 0) {
      return { path: '', fillPath: '', lastEquity: capital, minEq: capital, maxEq: capital };
    }
    const padding = 8;
    const w = width - padding * 2;
    const h = height - padding * 2;

    const eqs = curve.map((p) => p.equity_eur);
    const min = Math.min(...eqs, capital);
    const max = Math.max(...eqs, capital);
    const range = Math.max(max - min, 1);

    const xStep = curve.length > 1 ? w / (curve.length - 1) : 0;

    const points = curve.map((p, i) => {
      const x = padding + i * xStep;
      const y = padding + h - ((p.equity_eur - min) / range) * h;
      return [x, y] as const;
    });

    const path = points
      .map(([x, y], i) => (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : `L ${x.toFixed(1)} ${y.toFixed(1)}`))
      .join(' ');

    // Fill area sous la courbe (alpha)
    const fillPath = `${path} L ${(padding + (curve.length - 1) * xStep).toFixed(1)} ${(padding + h).toFixed(1)} L ${padding} ${(padding + h).toFixed(1)} Z`;

    return {
      path,
      fillPath,
      lastEquity: curve[curve.length - 1].equity_eur,
      minEq: min,
      maxEq: max,
    };
  }, [curve, width, height, capital]);

  if (curve.length === 0) {
    return (
      <div className="text-xs text-white/40 text-center py-8">
        Pas encore de setup résolu pour tracer l'équity curve
      </div>
    );
  }

  // Position du baseline capital sur l'axe Y
  const padding = 8;
  const h = height - padding * 2;
  const range = Math.max(maxEq - minEq, 1);
  const baselineY = padding + h - ((capital - minEq) / range) * h;

  const isProfit = lastEquity >= capital;
  const strokeColor = isProfit ? '#10b981' : '#f43f5e'; // emerald-500 / rose-500
  const fillColor = isProfit ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)';

  return (
    <div className="relative">
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {/* baseline capital initial */}
        <line
          x1={padding}
          x2={width - padding}
          y1={baselineY}
          y2={baselineY}
          stroke="rgba(255,255,255,0.15)"
          strokeWidth={1}
          strokeDasharray="3,3"
        />
        {/* fill */}
        <path d={fillPath} fill={fillColor} />
        {/* line */}
        <path d={path} fill="none" stroke={strokeColor} strokeWidth={1.5} />
      </svg>
      <div className="flex items-center justify-between mt-2 text-xs text-white/40">
        <span>{capital.toLocaleString('fr-FR')} €</span>
        <span className={isProfit ? 'text-emerald-400' : 'text-rose-400'}>
          {lastEquity.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €
          ({((lastEquity / capital - 1) * 100).toFixed(1)}%)
        </span>
        <span>min {minEq.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} / max {maxEq.toLocaleString('fr-FR', { maximumFractionDigits: 0 })}</span>
      </div>
    </div>
  );
}
