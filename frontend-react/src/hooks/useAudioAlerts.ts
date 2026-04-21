import { useEffect, useRef, useState, useCallback } from 'react';
import { useSetups } from '@/hooks/useSetups';
import { playTakeAlert, unlockAudio } from '@/lib/audioAlerts';
import type { TradeSetup } from '@/types/domain';

const STORAGE_KEY = 'scalping:audio-alerts';

function readPref(): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(STORAGE_KEY) === '1';
}

function writePref(enabled: boolean): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
}

function takeKey(s: TradeSetup): string {
  return `${s.pair}|${s.direction}|${s.entry_price.toFixed(5)}`;
}

/** Hook qui joue un bip quand un NOUVEAU setup TAKE apparaît dans la liste.
 *  - persiste la préférence dans localStorage (défaut OFF)
 *  - diff entre le set précédent et actuel pour détecter les nouveaux TAKE
 *  - n'émet PAS de son sur le premier render (sinon tous les setups existants
 *    bippent au chargement de la page)
 */
export function useAudioAlerts(): { enabled: boolean; toggle: () => void } {
  const [enabled, setEnabled] = useState<boolean>(() => readPref());
  const { data } = useSetups();
  const previousKeysRef = useRef<Set<string> | null>(null);

  useEffect(() => {
    if (!data) return;
    const takeSetups = data.filter((s) => s.verdict_action === 'TAKE');
    const currentKeys = new Set(takeSetups.map(takeKey));
    const previous = previousKeysRef.current;
    // Premier render : on enregistre l'état initial sans bip.
    if (previous === null) {
      previousKeysRef.current = currentKeys;
      return;
    }
    if (enabled) {
      for (const key of currentKeys) {
        if (!previous.has(key)) {
          playTakeAlert();
          break; // un seul bip même si plusieurs nouveaux TAKE arrivent en même temps
        }
      }
    }
    previousKeysRef.current = currentKeys;
  }, [data, enabled]);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      writePref(next);
      if (next) {
        // unlock + bip de confirmation pour que l'user entende que c'est ON
        unlockAudio();
        playTakeAlert();
      }
      return next;
    });
  }, []);

  return { enabled, toggle };
}
