import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useMacro() {
  return useQuery({
    queryKey: ['macro'],
    queryFn: api.macro,
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
}
