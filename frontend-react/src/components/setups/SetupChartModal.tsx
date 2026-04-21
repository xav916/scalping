import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';
import {
  createChart,
  CandlestickSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
} from 'lightweight-charts';
import type { TradeSetup } from '@/types/domain';
import { useAllCandles } from '@/hooks/useCandles';
import { GradientText } from '@/components/ui/GradientText';
import { formatPrice } from '@/lib/format';

interface Props {
  setup: TradeSetup | null;
  onClose: () => void;
}

/** Modal fullscreen avec chart candlestick complet du prix autour d'un setup.
 *  SL / Entry / TP matérialisés par des priceLines sur la série. */
export function SetupChartModal({ setup, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const { data: allCandles } = useAllCandles();

  useEffect(() => {
    if (!setup || !containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#8b94a8',
        fontFamily: 'JetBrains Mono, ui-monospace, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.08)',
      },
      crosshair: {
        mode: 1,
      },
      autoSize: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22d3ee',
      downColor: '#ec4899',
      borderUpColor: '#22d3ee',
      borderDownColor: '#ec4899',
      wickUpColor: '#22d3ee',
      wickDownColor: '#ec4899',
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => chart.applyOptions({});
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [setup]);

  useEffect(() => {
    if (!setup || !seriesRef.current) return;
    const candles = allCandles?.[setup.pair] ?? [];
    if (candles.length === 0) return;

    const data: CandlestickData[] = candles.map((c) => ({
      time: (Math.floor(new Date(c.timestamp).getTime() / 1000) as unknown) as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    seriesRef.current.setData(data);

    // PriceLines SL / Entry / TP
    const series = seriesRef.current;
    // Clear any existing price lines
    // Note: lightweight-charts v5 ne fournit pas d'API pour lister les priceLines,
    // donc on recrée à chaque update (acceptable au changement de setup).
    const lines: Array<ReturnType<typeof series.createPriceLine>> = [];
    lines.push(
      series.createPriceLine({
        price: setup.entry_price,
        color: 'rgba(255,255,255,0.6)',
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Entry',
      })
    );
    lines.push(
      series.createPriceLine({
        price: setup.stop_loss,
        color: 'rgba(244,63,94,0.7)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL',
      })
    );
    lines.push(
      series.createPriceLine({
        price: setup.take_profit_1,
        color: 'rgba(52,211,153,0.7)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'TP1',
      })
    );

    chartRef.current?.timeScale().fitContent();

    return () => {
      lines.forEach((l) => {
        try {
          series.removePriceLine(l);
        } catch {
          /* already removed */
        }
      });
    };
  }, [setup, allCandles]);

  // ESC pour fermer
  useEffect(() => {
    if (!setup) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setup, onClose]);

  return (
    <AnimatePresence>
      {setup && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-6 backdrop-blur-xl bg-radar-deep/70"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.94 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-5xl max-h-[90vh] rounded-2xl border border-glass-strong bg-radar-deep/95 shadow-glass-elevated flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between gap-4 px-5 py-3 border-b border-glass-soft">
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-mono text-xl font-bold tracking-tight">{setup.pair}</span>
                <span
                  className={clsx(
                    'text-[10px] font-semibold uppercase tracking-widest px-2 py-0.5 rounded-md',
                    setup.direction === 'buy'
                      ? 'bg-cyan-400/10 text-cyan-300 border border-cyan-400/20'
                      : 'bg-pink-400/10 text-pink-300 border border-pink-400/20'
                  )}
                >
                  {setup.direction}
                </span>
                <GradientText
                  variant={setup.direction === 'buy' ? 'buy' : 'sell'}
                  className="text-xl"
                >
                  {setup.confidence_score.toFixed(0)}
                </GradientText>
              </div>
              <div className="flex items-center gap-4 text-xs text-white/60 font-mono tabular-nums">
                <span className="hidden sm:inline">
                  SL <span className="text-rose-300">{formatPrice(setup.stop_loss)}</span>
                </span>
                <span className="hidden sm:inline">
                  Entry <span className="text-white">{formatPrice(setup.entry_price)}</span>
                </span>
                <span className="hidden sm:inline">
                  TP <span className="text-emerald-300">{formatPrice(setup.take_profit_1)}</span>
                </span>
                <button
                  type="button"
                  onClick={onClose}
                  className="text-lg px-2 leading-none rounded hover:bg-white/5 transition-colors text-white/60 hover:text-white"
                  aria-label="Fermer"
                >
                  ✕
                </button>
              </div>
            </div>
            {/* Chart container */}
            <div ref={containerRef} className="flex-1 min-h-[320px]" />
            {/* Footer avec verdict si présent */}
            {setup.verdict_summary && (
              <div className="px-5 py-3 border-t border-glass-soft text-xs text-white/60 leading-relaxed">
                {setup.verdict_summary}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
