import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POST_FIX_CUTOFF } from '@/lib/constants';

export function useEquityCurve(since: string = POST_FIX_CUTOFF) {
  return useQuery({
    queryKey: ['equity-curve', since],
    queryFn: () => api.equityCurve(since),
    staleTime: 60_000,
    refetchInterval: 2 * 60_000,
  });
}
