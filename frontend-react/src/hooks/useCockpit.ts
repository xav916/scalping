import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

/** Snapshot cockpit : poll toutes les 10s + invalidé par WS setups_update.
 *  Reste simple : pas de WS dédié cockpit (le push WS existe mais on peut
 *  l'intégrer dans une session future). */
export function useCockpit() {
  return useQuery({
    queryKey: ['cockpit'],
    queryFn: api.cockpit,
    refetchInterval: 10_000,
    staleTime: 5_000,
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
