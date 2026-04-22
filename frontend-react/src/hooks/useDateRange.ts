import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode, createElement } from 'react';
import type { Granularity, Preset, DrillSegment } from '@/types/domain';

export interface DateRangeState {
  preset: Preset;
  start: string;
  end: string;
  granularity: Granularity;
  drillPath: DrillSegment[];
}

export interface UseDateRangeApi extends DateRangeState {
  setPreset(p: Exclude<Preset, 'custom'>): void;
  setCustomRange(start: string, end: string): void;
  shiftRange(dir: -1 | 1): void;
  drillInto(seg: DrillSegment): void;
  drillBack(levels?: number): void;
  reset(): void;
}

const LS_KEY = 'scalping_period_range';
const POST_FIX_CUTOFF_ISO = '2026-04-20T21:14:00+00:00';
const DEFAULT_PRESET: Exclude<Preset, 'custom'> = 'week';

function nowUtc(): Date {
  return new Date();
}

function toIso(d: Date): string {
  return d.toISOString();
}

function startOfDayUtc(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 0, 0));
}

function startOfWeekUtc(d: Date): Date {
  const day = d.getUTCDay(); // 0 dim ... 6 sam
  const daysSinceMonday = (day + 6) % 7;
  const anchor = startOfDayUtc(d);
  anchor.setUTCDate(anchor.getUTCDate() - daysSinceMonday);
  return anchor;
}

function startOfMonthUtc(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1, 0, 0, 0, 0));
}

function startOfYearUtc(d: Date): Date {
  return new Date(Date.UTC(d.getUTCFullYear(), 0, 1, 0, 0, 0, 0));
}

/** Calcule les bornes ISO d'un preset à partir de l'instant `now` (UTC). */
export function boundsForPreset(
  preset: Exclude<Preset, 'custom'>,
  now: Date = nowUtc()
): { start: string; end: string } {
  const end = toIso(now);
  if (preset === 'day') return { start: toIso(startOfDayUtc(now)), end };
  if (preset === 'week') return { start: toIso(startOfWeekUtc(now)), end };
  if (preset === 'month') return { start: toIso(startOfMonthUtc(now)), end };
  if (preset === 'year') return { start: toIso(startOfYearUtc(now)), end };
  // all
  return { start: POST_FIX_CUTOFF_ISO, end };
}

/** Granularité de base par preset (table du spec). */
export function granularityForPreset(preset: Exclude<Preset, 'custom'>): Granularity {
  if (preset === 'day') return 'hour';
  if (preset === 'year' || preset === 'all') return 'month';
  return 'day'; // week | month → day bars
}

/** Résolution auto pour custom range — règles identiques au backend. */
export function resolveAutoGranularity(startIso: string, endIso: string): Granularity {
  const spanMs = new Date(endIso).getTime() - new Date(startIso).getTime();
  const spanHours = spanMs / 36e5;
  if (spanHours <= 36) return 'hour';
  const spanDays = spanHours / 24;
  if (spanDays <= 93) return 'day';
  return 'month';
}

/** Décale la range d'une période (preset pilote la direction). Désactivé pour
 *  'all' et 'custom'. */
export function shiftPresetRange(
  state: DateRangeState,
  dir: -1 | 1
): { start: string; end: string } {
  const start = new Date(state.start);
  const end = new Date(state.end);
  if (state.preset === 'day') {
    start.setUTCDate(start.getUTCDate() + dir);
    end.setUTCDate(end.getUTCDate() + dir);
  } else if (state.preset === 'week') {
    start.setUTCDate(start.getUTCDate() + dir * 7);
    end.setUTCDate(end.getUTCDate() + dir * 7);
  } else if (state.preset === 'month') {
    start.setUTCMonth(start.getUTCMonth() + dir);
    end.setUTCMonth(end.getUTCMonth() + dir);
  } else if (state.preset === 'year') {
    start.setUTCFullYear(start.getUTCFullYear() + dir);
    end.setUTCFullYear(end.getUTCFullYear() + dir);
  } else {
    // 'all' et 'custom' : no-op
    return { start: state.start, end: state.end };
  }
  return { start: toIso(start), end: toIso(end) };
}

function initialFromPreset(preset: Exclude<Preset, 'custom'>): DateRangeState {
  const { start, end } = boundsForPreset(preset);
  return {
    preset,
    start,
    end,
    granularity: granularityForPreset(preset),
    drillPath: [],
  };
}

/** Restore depuis URL (searchParams) puis localStorage, fallback default. */
function loadInitialState(): DateRangeState {
  // URL d'abord (shareable links > localStorage)
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    const preset = params.get('preset') as Preset | null;
    const since = params.get('since');
    const until = params.get('until');
    if (preset && ['day', 'week', 'month', 'year', 'all'].includes(preset)) {
      return initialFromPreset(preset as Exclude<Preset, 'custom'>);
    }
    if (preset === 'custom' && since && until) {
      return {
        preset: 'custom',
        start: since,
        end: until,
        granularity: resolveAutoGranularity(since, until),
        drillPath: [],
      };
    }
    // localStorage
    try {
      const raw = window.localStorage.getItem(LS_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as DateRangeState;
        // Si preset != custom, on recalcule les bornes sur now pour rester "live"
        if (saved.preset !== 'custom') {
          return initialFromPreset(saved.preset);
        }
        return { ...saved, drillPath: [] }; // drill jamais restauré
      }
    } catch {
      /* localStorage indisponible ou JSON corrompu */
    }
  }
  return initialFromPreset(DEFAULT_PRESET);
}

/** Hook "standalone" qui gère l'état en local. Utilisé directement si la
 *  carte n'est pas wrappée dans un `DateRangeProvider` ; sinon, le provider
 *  l'utilise une fois au niveau supérieur et partage via contexte. */
function useDateRangeStandalone(): UseDateRangeApi {
  const [state, setState] = useState<DateRangeState>(loadInitialState);

  // Persist dans localStorage à chaque changement (hors drill)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const { preset, start, end, granularity } = state;
      window.localStorage.setItem(
        LS_KEY,
        JSON.stringify({ preset, start, end, granularity, drillPath: [] })
      );
    } catch {
      /* quota ou dispo */
    }
  }, [state.preset, state.start, state.end, state.granularity]);

  const setPreset = useCallback((p: Exclude<Preset, 'custom'>) => {
    setState(initialFromPreset(p));
  }, []);

  const setCustomRange = useCallback((start: string, end: string) => {
    setState({
      preset: 'custom',
      start,
      end,
      granularity: resolveAutoGranularity(start, end),
      drillPath: [],
    });
  }, []);

  const shiftRange = useCallback((dir: -1 | 1) => {
    setState((prev) => {
      if (prev.preset === 'all' || prev.preset === 'custom') return prev;
      const { start, end } = shiftPresetRange(prev, dir);
      return { ...prev, start, end, drillPath: [] };
    });
  }, []);

  const drillInto = useCallback((seg: DrillSegment) => {
    setState((prev) => ({
      ...prev,
      start: seg.start,
      end: seg.end,
      granularity: seg.granularity,
      drillPath: [...prev.drillPath, seg],
    }));
  }, []);

  const drillBack = useCallback((levels: number = 1) => {
    setState((prev) => {
      if (prev.drillPath.length === 0) return prev;
      const newPath = prev.drillPath.slice(0, Math.max(0, prev.drillPath.length - levels));
      if (newPath.length === 0) {
        // Remonte au root du preset
        if (prev.preset === 'custom') {
          return { ...prev, drillPath: [] };
        }
        return initialFromPreset(prev.preset);
      }
      const last = newPath[newPath.length - 1];
      return {
        ...prev,
        start: last.start,
        end: last.end,
        granularity: last.granularity,
        drillPath: newPath,
      };
    });
  }, []);

  const reset = useCallback(() => {
    setState(initialFromPreset(DEFAULT_PRESET));
  }, []);

  return useMemo(
    () => ({ ...state, setPreset, setCustomRange, shiftRange, drillInto, drillBack, reset }),
    [state, setPreset, setCustomRange, shiftRange, drillInto, drillBack, reset]
  );
}

// ─── Contexte pour partager l'état entre cartes du Cockpit ────────────────

const DateRangeContext = createContext<UseDateRangeApi | null>(null);

export function DateRangeProvider({ children }: { children: ReactNode }) {
  const api = useDateRangeStandalone();
  return createElement(DateRangeContext.Provider, { value: api }, children);
}

/** Lit l'état partagé depuis `DateRangeProvider`. Fallback sur une instance
 *  locale si aucun provider n'est détecté (backward compat avec les pages
 *  qui n'ont pas encore adopté le provider). */
export function useDateRange(): UseDateRangeApi {
  const ctx = useContext(DateRangeContext);
  const standalone = useDateRangeStandalone();
  return ctx ?? standalone;
}
