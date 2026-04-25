import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useShadowSetups(params: { system_id?: string; outcome?: string; limit?: number } = {}) {
  return useQuery({
    queryKey: ['shadow', 'setups', params],
    queryFn: () => api.shadowSetups(params),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

export function useShadowSummary() {
  return useQuery({
    queryKey: ['shadow', 'summary'],
    queryFn: () => api.shadowSummary(),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}
