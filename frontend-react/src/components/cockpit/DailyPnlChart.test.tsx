import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DailyPnlChart } from './DailyPnlChart';
import type { PnlBucket } from '@/types/domain';

function mkBucket(overrides: Partial<PnlBucket>): PnlBucket {
  return {
    bucket_start: '2026-04-22T00:00:00+00:00',
    bucket_end: '2026-04-22T23:59:59+00:00',
    pnl: 0,
    cumulative_pnl: 0,
    n_trades: 0,
    ...overrides,
  };
}

describe('DailyPnlChart', () => {
  it('renders empty state when buckets is empty', () => {
    render(<DailyPnlChart buckets={[]} granularity="day" />);
    expect(screen.getByText(/Aucun bucket/i)).toBeInTheDocument();
  });

  it('renders one bar per bucket', () => {
    const buckets = [
      mkBucket({ bucket_start: '2026-04-20T00:00:00Z', pnl: 10, cumulative_pnl: 10, n_trades: 2 }),
      mkBucket({ bucket_start: '2026-04-21T00:00:00Z', pnl: -5, cumulative_pnl: 5, n_trades: 1 }),
      mkBucket({ bucket_start: '2026-04-22T00:00:00Z', pnl: 7, cumulative_pnl: 12, n_trades: 3 }),
    ];
    const { container } = render(<DailyPnlChart buckets={buckets} granularity="day" />);
    // 3 rects "visible" (bars) + 3 rects "hover zone" invisibles = 6 au total
    const rects = container.querySelectorAll('svg rect');
    expect(rects.length).toBe(6);
  });

  it('calls onBarClick when a bar is clicked on a drillable granularity', () => {
    const onBarClick = vi.fn();
    const buckets = [
      mkBucket({ bucket_start: '2026-04-20T00:00:00Z', pnl: 10, cumulative_pnl: 10, n_trades: 2 }),
    ];
    const { container } = render(
      <DailyPnlChart buckets={buckets} granularity="day" onBarClick={onBarClick} />
    );
    // Hover zone (second rect) → clickable
    const rects = container.querySelectorAll('svg rect');
    fireEvent.click(rects[1]);
    expect(onBarClick).toHaveBeenCalledTimes(1);
    expect(onBarClick).toHaveBeenCalledWith(
      expect.objectContaining({
        start: '2026-04-20T00:00:00Z',
        granularity: 'hour',
      })
    );
  });

  it('does NOT call onBarClick at the deepest granularity (5min)', () => {
    const onBarClick = vi.fn();
    const buckets = [
      mkBucket({ bucket_start: '2026-04-20T14:00:00Z', pnl: 3, cumulative_pnl: 3, n_trades: 1 }),
    ];
    const { container } = render(
      <DailyPnlChart buckets={buckets} granularity="5min" onBarClick={onBarClick} />
    );
    const rects = container.querySelectorAll('svg rect');
    fireEvent.click(rects[1]);
    expect(onBarClick).not.toHaveBeenCalled();
  });

  it('shows tooltip on hover with trade count and pnl', async () => {
    const buckets = [
      mkBucket({
        bucket_start: '2026-04-20T00:00:00Z',
        pnl: 42.1,
        cumulative_pnl: 42.1,
        n_trades: 3,
      }),
    ];
    const { container } = render(<DailyPnlChart buckets={buckets} granularity="day" />);
    const hoverZone = container.querySelectorAll('svg rect')[1];
    fireEvent.mouseEnter(hoverZone);
    expect(screen.getByText(/3 trades/i)).toBeInTheDocument();
  });

  it('renders the last bar with live stroke when live=true', () => {
    const buckets = [
      mkBucket({ bucket_start: '2026-04-22T00:00:00Z', pnl: 10, cumulative_pnl: 10, n_trades: 2 }),
    ];
    const { container } = render(<DailyPnlChart buckets={buckets} granularity="day" live />);
    const bar = container.querySelectorAll('svg rect')[0];
    // Stroke width 2 + non-transparent stroke sur la dernière barre si live
    expect(bar.getAttribute('stroke-width')).toBe('2');
  });
});
