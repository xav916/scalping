import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

/** Récupère toutes les candles par pair en un seul appel.
 *  Cache 60s puis refetch — consommable par plusieurs SetupCards simultanément. */
export function useAllCandles() {
  return useQuery({
    queryKey: ['candles', 'all'],
    queryFn: api.allCandles,
    staleTime: 60_000,
    refetchInterval: 90_000,
  });
}
