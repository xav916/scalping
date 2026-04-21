import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useSetups() {
  return useQuery({
    queryKey: ['setups'],
    queryFn: api.setups,
    staleTime: 60_000,
    refetchInterval: 90_000,
  });
}
