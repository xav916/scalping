import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { swrFetcher } from "@/api/client";
import type { Cockpit, WSMessage } from "@/api/types";

/**
 * Récupère le snapshot cockpit.
 *
 * Stratégie :
 * 1. Fetch initial via REST pour avoir un rendu immediat.
 * 2. Abonne-toi au WebSocket /ws qui pousse des type="cockpit" toutes
 *    les 5s et a chaque fin de cycle d'analyse.
 * 3. Chaque message WS remplace le cache SWR.
 * 4. Si le WS tombe, SWR garde le fetch initial et refetchera
 *    toutes les 15s (fallback polling).
 * 5. Reconnexion WS automatique avec backoff (max 30s).
 */
export function useCockpit() {
  const { data, error, isLoading, mutate } = useSWR<Cockpit>(
    "/api/cockpit",
    swrFetcher,
    {
      refreshInterval: 15000, // fallback si le WS ne pousse pas
      revalidateOnFocus: false,
    }
  );

  const [wsConnected, setWsConnected] = useState(false);
  const retryRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let pingInterval: ReturnType<typeof setInterval> | null = null;

    const connect = () => {
      if (stopped) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        retryRef.current = 0;
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30000);
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as WSMessage;
          if (msg.type === "cockpit") {
            // Remplace le cache SWR sans refetcher (on a la source fraiche).
            mutate(msg.data, { revalidate: false });
          }
        } catch {
          // payloads non-JSON ignores.
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        if (pingInterval) clearInterval(pingInterval);
        if (stopped) return;
        retryRef.current = Math.min(retryRef.current + 1, 6);
        const backoff = Math.min(1000 * 2 ** retryRef.current, 30000);
        setTimeout(connect, backoff);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (pingInterval) clearInterval(pingInterval);
      wsRef.current?.close();
    };
  }, [mutate]);

  return { cockpit: data, loading: isLoading, error, wsConnected };
}
