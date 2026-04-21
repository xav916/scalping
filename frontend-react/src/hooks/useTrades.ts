import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useTrades(params: { status?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: ['trades', params],
    queryFn: () => api.trades(params),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
