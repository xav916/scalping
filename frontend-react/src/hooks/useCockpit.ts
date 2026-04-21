import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';

/** Drift scan (poll toutes les 5 min, endpoint plus lourd). */
export function useDrift() {
  return useQuery({
    queryKey: ['drift'],
    queryFn: api.drift,
    refetchInterval: 300_000,
    staleTime: 120_000,
  });
}

/** Analytics (breakdowns complet) : fetch-on-demand, pas de poll (données
 *  qui bougent lentement, la page /v2/analytics n'est pas une surface live). */
export function useAnalytics() {
  return useQuery({
    queryKey: ['analytics'],
    queryFn: api.analytics,
    staleTime: 60_000,
  });
}

/** Period stats (PnL/win rate/profit factor par période). Poll 30s pour que
 *  le "Jour" se rafraîchisse pendant que des trades se ferment. */
export function usePeriodStats(period: import('@/types/domain').PeriodKey) {
  return useQuery({
    queryKey: ['period-stats', period],
    queryFn: () => api.periodStats(period),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/** Détecteur d'erreurs (trades sans checklist / SL / TP + avg PnL). Fetch on
 *  demand uniquement, pas de poll — les données évoluent lentement. */
export function useMistakes() {
  return useQuery({
    queryKey: ['mistakes'],
    queryFn: api.mistakes,
    staleTime: 60_000,
  });
}

/** Combos pattern × pair. Même logique que mistakes. */
export function useCombos() {
  return useQuery({
    queryKey: ['combos'],
    queryFn: api.combos,
    staleTime: 60_000,
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
  const toast = useToast();
  const query = useQuery({
    queryKey: ['kill-switch'],
    queryFn: api.killSwitchStatus,
    staleTime: 5_000,
  });
  const mutation = useMutation({
    mutationFn: ({ enabled, reason }: { enabled: boolean; reason?: string }) =>
      api.killSwitchSet(enabled, reason),
    onSuccess: (_, variables) => {
      qc.invalidateQueries({ queryKey: ['kill-switch'] });
      qc.invalidateQueries({ queryKey: ['cockpit'] });
      if (variables.enabled) {
        toast.warning(
          'Kill switch activé',
          `Auto-exec gelé${variables.reason ? ` · ${variables.reason}` : ''}`
        );
      } else {
        toast.success('Kill switch désactivé', 'Auto-exec opérationnel');
      }
    },
    onError: (err) => {
      toast.error('Kill switch — erreur', String(err).slice(0, 120));
    },
  });
  return { query, mutation };
}
