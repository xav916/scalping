import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

/** Drift scan (poll toutes les 5 min, endpoint plus lourd). */
export function useDrift() {
  return useQuery({
    queryKey: ['drift'],
    queryFn: api.drift,
    refetchInterval: 300_000,
    staleTime: 120_000,
  });
}

/** Snapshot cockpit. Le backend push via WebSocket (type: 'cockpit') et
 *  setQueryData dans useWebSocket alimente la cache directement. On garde
 *  un refetchInterval long (60s) comme filet de sécurité si le WS tombe. */
export function useCockpit() {
  return useQuery({
    queryKey: ['cockpit'],
    queryFn: api.cockpit,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useKillSwitch() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['kill-switch'],
    queryFn: api.killSwitchStatus,
    staleTime: 5_000,
  });
  const mutation = useMutation({
    mutationFn: ({ enabled, reason }: { enabled: boolean; reason?: string }) =>
      api.killSwitchSet(enabled, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kill-switch'] });
      qc.invalidateQueries({ queryKey: ['cockpit'] });
    },
  });
  return { query, mutation };
}
