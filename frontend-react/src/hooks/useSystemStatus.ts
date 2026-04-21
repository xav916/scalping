import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';

/** Statut affiché dans le Header — reflète la santé RÉELLE du pipeline
 *  de données, pas juste l'état du WebSocket.
 *
 *  - LIVE  : cycles d'analyse < 10 min (pipeline vivant). On reçoit les
 *            données récentes, soit par push WS soit par poll.
 *  - POLL  : pipeline vivant mais WebSocket fermé. Les données sont fraîches
 *            (polling React Query 10-60s) mais pas en temps réel strict.
 *  - SYNC  : connexion WebSocket en cours d'établissement (phase transitoire
 *            au chargement de la page ou à la reconnexion).
 *  - DOWN  : pipeline mort — dernier cycle d'analyse > 10 min. Le scheduler
 *            backend ne tourne pas, ou source de données KO. Vraie alerte.
 *  - UNKNOWN : on n'a pas encore la réponse de /api/health. État initial fugace.
 */
export type SystemStatus = 'LIVE' | 'POLL' | 'SYNC' | 'DOWN' | 'UNKNOWN';

export interface SystemStatusInfo {
  status: SystemStatus;
  healthy: boolean;
  secondsSinceLastCycle: number | null;
  wsOpen: boolean;
}

/** /api/health poll 30s — léger endpoint qui indique juste si le scheduler
 *  a tourné récemment. Combiné avec l'état du WebSocket pour déduire l'état
 *  global du pipeline. */
export function useSystemStatus(): SystemStatusInfo {
  const { status: wsStatus } = useWebSocket();
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
    staleTime: 15_000,
    // En cas d'erreur (401, réseau), on ne retente pas en boucle infinie
    retry: 1,
  });

  const secondsSince = health.data?.seconds_since_last_cycle ?? null;
  const healthy = health.data?.healthy ?? false;
  const wsOpen = wsStatus === 'open';

  let status: SystemStatus;
  if (health.isLoading || !health.data) {
    // Pendant le premier fetch on regarde juste le WS pour ne pas afficher DOWN à tort
    status = wsStatus === 'connecting' ? 'SYNC' : 'UNKNOWN';
  } else if (!healthy) {
    // Dernier cycle > 10 min → problème réel
    status = 'DOWN';
  } else if (wsOpen) {
    status = 'LIVE';
  } else if (wsStatus === 'connecting') {
    status = 'SYNC';
  } else {
    status = 'POLL';
  }

  return {
    status,
    healthy,
    secondsSinceLastCycle: secondsSince,
    wsOpen,
  };
}
