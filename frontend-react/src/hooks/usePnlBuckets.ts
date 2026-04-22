import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Granularity } from '@/types/domain';

interface Args {
  since: string;
  until: string;
  granularity: Granularity;
  /** Si true, la query s'invalide sur push WebSocket cockpit (période live). */
  live: boolean;
}

const STALE_MS: Record<Granularity, number> = {
  '5min': 2_000,
  hour: 5_000,
  day: 10_000,
  month: 60_000,
};

/** Série temporelle bucketisée du PnL. Alimente le graph de la carte
 *  Performance. Invalide au push WS cockpit si la range inclut `now`. */
export function usePnlBuckets({ since, until, granularity, live }: Args) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['pnl-buckets', since, until, granularity],
    queryFn: () => api.pnlBuckets(since, until, granularity),
    staleTime: STALE_MS[granularity],
    refetchInterval: live ? STALE_MS[granularity] * 3 : false,
  });

  // Invalide au push WS cockpit (via le query 'cockpit' déjà cache-setté)
  useEffect(() => {
    if (!live) return;
    const unsub = qc.getQueryCache().subscribe((event) => {
      if (
        event.type === 'updated' &&
        event.query.queryKey[0] === 'cockpit' &&
        event.action.type === 'success'
      ) {
        qc.invalidateQueries({ queryKey: ['pnl-buckets', since, until, granularity] });
      }
    });
    return unsub;
  }, [qc, since, until, granularity, live]);

  return query;
}
