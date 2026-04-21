import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { WSMessage } from '@/types/domain';

export type WSStatus = 'connecting' | 'open' | 'closed';

export function useWebSocket(path = '/ws') {
  const [status, setStatus] = useState<WSStatus>('connecting');
  const qc = useQueryClient();
  const reconnectAttemptsRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      setStatus('connecting');
      const url = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${path}`;
      const sock = new WebSocket(url);
      socketRef.current = sock;

      sock.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setStatus('open');
      };

      sock.onmessage = (ev) => {
        try {
          const msg: WSMessage = JSON.parse(ev.data);
          if (msg.type === 'setups_update') {
            qc.invalidateQueries({ queryKey: ['setups'] });
          }
        } catch {
          /* ignore malformed */
        }
      };

      sock.onclose = () => {
        setStatus('closed');
        if (stopped) return;
        const backoff = Math.min(30_000, 1_000 * 2 ** reconnectAttemptsRef.current);
        reconnectAttemptsRef.current += 1;
        setTimeout(connect, backoff);
      };

      sock.onerror = () => {
        sock.close();
      };
    };

    connect();
    return () => {
      stopped = true;
      socketRef.current?.close();
    };
  }, [path, qc]);

  return { status };
}
