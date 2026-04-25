import { useMemo } from 'react';
import type { ShadowMonthlyReturn } from '@/types/domain';

interface Props {
  monthly: ShadowMonthlyReturn[];
  width?: number;
  height?: number;
}

/**
 * Bar chart des retours mensuels (% du capital initial).
 * Vert si positif, rouge si négatif. Layout horizontal compact.
 */
export function MonthlyReturnsChart({
  monthly,
  width = 600,
  height = 120,
}: Props) {
  const { bars, maxAbs, hasData } = useMemo(() => {
    if (monthly.length === 0) {
      return { bars: [], maxAbs: 1, hasData: false };
    }
    const maxAbs = Math.max(
      ...monthly.map((m) => Math.abs(m.return_pct)),
      0.5,
    );
    return {
      bars: monthly.map((m) => ({
        ...m,
        height: (Math.abs(m.return_pct) / maxAbs),
      })),
      maxAbs,
      hasData: true,
    };
  }, [monthly]);

  if (!hasData) {
    return (
      <div className="text-xs text-white/40 text-center py-6">
        Pas encore de mois résolus
      </div>
    );
  }

  const padding = 18;
  const w = width - padding * 2;
  const h = height - padding * 2;
  const midY = padding + h / 2;
  const barGap = 4;
  const barWidth = Math.max((w - barGap * (bars.length - 1)) / bars.length, 4);

  return (
    <div className="relative">
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {/* axe zéro */}
        <line
          x1={padding}
          x2={width - padding}
          y1={midY}
          y2={midY}
          stroke="rgba(255,255,255,0.2)"
          strokeWidth={1}
        />
        {bars.map((b, i) => {
          const x = padding + i * (barWidth + barGap);
          const barH = (b.height * h) / 2;
          const isPositive = b.return_pct >= 0;
          const y = isPositive ? midY - barH : midY;
          return (
            <g key={b.month}>
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={barH}
                fill={isPositive ? 'rgba(16, 185, 129, 0.7)' : 'rgba(244, 63, 94, 0.7)'}
                rx={1}
              >
                <title>{`${b.month}: ${b.return_pct >= 0 ? '+' : ''}${b.return_pct.toFixed(2)}% (${b.pnl_eur >= 0 ? '+' : ''}${b.pnl_eur.toFixed(0)}€)`}</title>
              </rect>
              {/* label mois si peu de bars */}
              {bars.length <= 18 && (
                <text
                  x={x + barWidth / 2}
                  y={height - 4}
                  textAnchor="middle"
                  className="fill-white/40"
                  fontSize="9"
                >
                  {b.month.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex items-center justify-between mt-1 text-xs text-white/40">
        <span>
          {bars.filter((b) => b.return_pct > 0).length} mois positifs / {bars.filter((b) => b.return_pct < 0).length} négatifs
        </span>
        <span>amplitude max ±{maxAbs.toFixed(1)}%</span>
      </div>
    </div>
  );
}
