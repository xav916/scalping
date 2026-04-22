import { useCallback, useEffect, useState } from 'react';

const LS_KEY = 'scalping_cockpit_order_v1';

type OrderMap = Record<string, string[]>;

function loadAll(): OrderMap {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as OrderMap) : {};
  } catch {
    return {};
  }
}

function saveAll(map: OrderMap): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(map));
  } catch {
    /* quota ou dispo */
  }
}

/** Maintient l'ordre des cards dans une section du cockpit. Persisté en
 *  localStorage par section. Si le stockage contient des cards qui
 *  n'existent plus dans `defaultIds`, elles sont ignorées. Nouvelles cards
 *  ajoutées à la fin. */
export function useCardOrder(sectionId: string, defaultIds: readonly string[]) {
  const [order, setOrder] = useState<string[]>(() => {
    const all = loadAll();
    const saved = all[sectionId];
    if (!saved) return [...defaultIds];
    // Merge : on garde l'ordre sauvé pour les ids valides, et on append
    // les nouvelles ids qui ont été ajoutées au code depuis
    const validSaved = saved.filter((id) => defaultIds.includes(id));
    const missing = defaultIds.filter((id) => !validSaved.includes(id));
    return [...validSaved, ...missing];
  });

  // Persist à chaque changement (merge dans la map globale)
  useEffect(() => {
    const all = loadAll();
    all[sectionId] = order;
    saveAll(all);
  }, [sectionId, order]);

  const reorder = useCallback((newOrder: string[]) => {
    setOrder(newOrder);
  }, []);

  const reset = useCallback(() => {
    setOrder([...defaultIds]);
  }, [defaultIds]);

  return { order, reorder, reset };
}

/** Reset tous les layouts du cockpit (toutes sections). Appelé par le
 *  bouton "Reset layout" dans la nav. */
export function resetAllCardOrders(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(LS_KEY);
  } catch {
    /* ignore */
  }
}
