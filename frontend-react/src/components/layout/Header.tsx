import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { useWebSocket } from '@/hooks/useWebSocket';
import { formatParisTime } from '@/lib/format';

export function Header() {
  const { whoami, logout } = useAuth();
  const { status } = useWebSocket();
  const [now, setNow] = useState(() => formatParisTime());

  useEffect(() => {
    const id = setInterval(() => setNow(formatParisTime()), 1000);
    return () => clearInterval(id);
  }, []);

  const statusColor =
    status === 'open' ? 'bg-emerald-400' : status === 'connecting' ? 'bg-amber-400' : 'bg-rose-400';

  return (
    <header className="sticky top-0 z-20 px-6 py-4 flex items-center justify-between border-b border-glass-soft backdrop-blur-glass bg-radar-deep/50">
      <div className="flex items-center gap-3">
        <span className="text-xl font-semibold tracking-tight">📡 Scalping Radar</span>
        <span className="text-xs font-mono text-white/40 px-2 py-0.5 rounded bg-white/5 border border-glass-soft">V2</span>
      </div>
      <div className="flex items-center gap-5 text-sm text-white/70">
        <span className="font-mono tabular-nums">{now} Paris</span>
        <span className="flex items-center gap-2">
          <span className={clsx('w-2 h-2 rounded-full', statusColor)} />
          <span className="text-xs uppercase tracking-wider">{status}</span>
        </span>
        {whoami.data && (
          <button
            type="button"
            onClick={() => {
              logout.mutate(undefined, {
                onSuccess: () => {
                  window.location.href = '/v2/login';
                },
              });
            }}
            className="text-xs px-3 py-1.5 rounded-lg border border-glass-soft hover:border-glass-strong transition-colors"
          >
            Logout ({whoami.data.username})
          </button>
        )}
      </div>
    </header>
  );
}
