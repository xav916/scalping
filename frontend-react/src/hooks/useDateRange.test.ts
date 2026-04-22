/** Tests unitaires des calculs purs de useDateRange. Les fonctions exposées
 *  (boundsForPreset, granularityForPreset, resolveAutoGranularity,
 *  shiftPresetRange) n'ont pas de dépendance React → testables sans renderer. */
import { describe, expect, it } from 'vitest';
import {
  boundsForPreset,
  granularityForPreset,
  resolveAutoGranularity,
  shiftPresetRange,
} from './useDateRange';
import type { DateRangeState } from './useDateRange';

describe('boundsForPreset', () => {
  // Mercredi 22 avril 2026 10:00 UTC
  const now = new Date('2026-04-22T10:00:00Z');

  it('day starts at 00:00 UTC', () => {
    const { start, end } = boundsForPreset('day', now);
    expect(start).toBe('2026-04-22T00:00:00.000Z');
    expect(end).toBe('2026-04-22T10:00:00.000Z');
  });

  it('week starts at Monday 00:00 UTC', () => {
    const { start } = boundsForPreset('week', now);
    expect(start).toBe('2026-04-20T00:00:00.000Z'); // lundi
  });

  it('month starts at 1st of month 00:00', () => {
    const { start } = boundsForPreset('month', now);
    expect(start).toBe('2026-04-01T00:00:00.000Z');
  });

  it('year starts at Jan 1st 00:00', () => {
    const { start } = boundsForPreset('year', now);
    expect(start).toBe('2026-01-01T00:00:00.000Z');
  });

  it('all starts at POST_FIX_CUTOFF', () => {
    const { start } = boundsForPreset('all', now);
    expect(start).toBe('2026-04-20T21:14:00+00:00');
  });

  it('week on Monday treats it as start of the same week', () => {
    const monday = new Date('2026-04-20T10:00:00Z');
    const { start } = boundsForPreset('week', monday);
    expect(start).toBe('2026-04-20T00:00:00.000Z');
  });

  it('week on Sunday goes back 6 days to Monday', () => {
    const sunday = new Date('2026-04-26T10:00:00Z');
    const { start } = boundsForPreset('week', sunday);
    expect(start).toBe('2026-04-20T00:00:00.000Z');
  });
});

describe('granularityForPreset', () => {
  it('day → hour', () => {
    expect(granularityForPreset('day')).toBe('hour');
  });

  it('week → day', () => {
    expect(granularityForPreset('week')).toBe('day');
  });

  it('month → day', () => {
    expect(granularityForPreset('month')).toBe('day');
  });

  it('year → month', () => {
    expect(granularityForPreset('year')).toBe('month');
  });

  it('all → month', () => {
    expect(granularityForPreset('all')).toBe('month');
  });
});

describe('resolveAutoGranularity', () => {
  it('span ≤ 36h → hour', () => {
    expect(
      resolveAutoGranularity('2026-04-22T00:00:00Z', '2026-04-23T00:00:00Z')
    ).toBe('hour');
    expect(
      resolveAutoGranularity('2026-04-22T00:00:00Z', '2026-04-23T11:59:59Z')
    ).toBe('hour'); // 35h59
  });

  it('36h < span ≤ 93j → day', () => {
    expect(
      resolveAutoGranularity('2026-04-22T00:00:00Z', '2026-04-25T00:00:00Z')
    ).toBe('day');
    expect(
      resolveAutoGranularity('2026-01-01T00:00:00Z', '2026-04-03T00:00:00Z')
    ).toBe('day'); // 92 jours
  });

  it('span > 93j → month', () => {
    expect(
      resolveAutoGranularity('2026-01-01T00:00:00Z', '2026-06-01T00:00:00Z')
    ).toBe('month');
  });
});

describe('shiftPresetRange', () => {
  function mkState(
    preset: DateRangeState['preset'],
    start: string,
    end: string
  ): DateRangeState {
    return { preset, start, end, granularity: 'day', drillPath: [] };
  }

  it('day shifts by 1 day', () => {
    const r = shiftPresetRange(
      mkState('day', '2026-04-22T00:00:00Z', '2026-04-22T23:59:59Z'),
      1
    );
    expect(r.start.startsWith('2026-04-23')).toBe(true);
    expect(r.end.startsWith('2026-04-23')).toBe(true);
  });

  it('week shifts by 7 days', () => {
    const r = shiftPresetRange(
      mkState('week', '2026-04-20T00:00:00Z', '2026-04-26T23:59:59Z'),
      -1
    );
    expect(r.start.startsWith('2026-04-13')).toBe(true);
  });

  it('month handles year rollover', () => {
    const r = shiftPresetRange(
      mkState('month', '2025-12-01T00:00:00Z', '2025-12-31T23:59:59Z'),
      1
    );
    expect(r.start.startsWith('2026-01')).toBe(true);
  });

  it('year increments', () => {
    const r = shiftPresetRange(
      mkState('year', '2026-01-01T00:00:00Z', '2026-12-31T23:59:59Z'),
      -1
    );
    expect(r.start.startsWith('2025')).toBe(true);
  });

  it('all is a no-op', () => {
    const original = mkState('all', '2026-04-20T21:14:00Z', '2026-04-22T10:00:00Z');
    const r = shiftPresetRange(original, 1);
    expect(r.start).toBe(original.start);
    expect(r.end).toBe(original.end);
  });

  it('custom is a no-op', () => {
    const original = mkState('custom', '2026-04-10T00:00:00Z', '2026-04-15T23:59:59Z');
    const r = shiftPresetRange(original, -1);
    expect(r.start).toBe(original.start);
    expect(r.end).toBe(original.end);
  });
});
