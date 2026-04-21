import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POST_FIX_CUTOFF } from '@/lib/constants';

export function usePerformance(since: string = POST_FIX_CUTOFF) {
  return useQuery({
    queryKey: ['performance', since],
    queryFn: () => api.performance(since),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}
