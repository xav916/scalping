import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { motion } from 'motion/react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useWebSocket, type WSStatus } from '@/hooks/useWebSocket';
import { useAudioAlerts } from '@/hooks/useAudioAlerts';
import { Tooltip } from '@/components/ui/Tooltip';
import { formatParisTime } from '@/lib/format';
import { TIPS } from '@/lib/metricTips';

function StatusDot({ status }: { status: WSStatus }) {
  const base = 'relative inline-block w-2 h-2 rounded-full';
  if (status === 'open') {
    return (
      <span className={clsx(base, 'bg-emerald-400')}>
        {/* Pulse ring animé pour signaler la connexion vivante */}
        <motion.span
          aria-hidden
          className="absolute inset-0 rounded-full bg-emerald-400"
          animate={{ scale: [1, 2.2], opacity: [0.6, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
        />
      </span>
    );
  }
  if (status === 'connecting') {
    return (
      <motion.span
        className={clsx(base, 'bg-amber-400')}
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
      />
    );
  }
  return <span className={clsx(base, 'bg-rose-400')} />;
}

function statusLabel(s: WSStatus): string {
  if (s === 'open') return 'LIVE';
  if (s === 'connecting') return 'SYNC';
  return 'OFFLINE';
}

const NAV_LINKS = [
  { to: '/', label: 'Dashboard' },
  { to: '/cockpit', label: 'Cockpit' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/trades', label: 'Trades' },
];

export function Header() {
  const { whoami, logout } = useAuth();
  const { status } = useWebSocket();
  const { enabled: audioEnabled, toggle: toggleAudio } = useAudioAlerts();
  const location = useLocation();
  const [now, setNow] = useState(() => formatParisTime());

  useEffect(() => {
    const id = setInterval(() => setNow(formatParisTime()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="sticky top-0 z-20 px-4 sm:px-6 py-3 sm:py-4 flex items-center justify-between gap-2 border-b border-glass-soft backdrop-blur-glass bg-radar-deep/60">
      <div className="flex items-center gap-2 sm:gap-4 min-w-0">
        <span className="text-base sm:text-xl font-semibold tracking-tight whitespace-nowrap">
          <span className="hidden xs:inline">📡 </span>Scalping Radar
        </span>
        <Tooltip content={TIPS.header.v2Badge}>
          <span className="text-[10px] font-mono font-semibold text-cyan-300/80 px-2 py-0.5 rounded-md bg-cyan-400/10 border border-cyan-400/20 shadow-[0_0_12px_rgba(34,211,238,0.15)]">
            V2
          </span>
        </Tooltip>
        <nav className="hidden sm:flex items-center gap-1 ml-2">
          {NAV_LINKS.map((l) => {
            const active = location.pathname === l.to;
            return (
              <Link
                key={l.to}
                to={l.to}
                className={clsx(
                  'text-xs px-2.5 py-1 rounded-md transition-colors',
                  active
                    ? 'bg-white/10 text-white'
                    : 'text-white/50 hover:text-white/90 hover:bg-white/5'
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-2 sm:gap-5 text-sm text-white/70">
        {/* Heure Paris — masquée sur très petit écran */}
        <div className="hidden md:flex items-baseline gap-2">
          <span className="font-mono tabular-nums text-base text-white/90">{now}</span>
          <span className="text-[9px] uppercase tracking-[0.2em] text-white/40">Paris</span>
        </div>
        {/* Status LIVE/SYNC/OFFLINE */}
        <Tooltip content={
          status === 'open' ? TIPS.header.statusLive
          : status === 'connecting' ? TIPS.header.statusSync
          : TIPS.header.statusOffline
        }>
          <div
            className={clsx(
              'flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg border',
              status === 'open' && 'bg-emerald-400/10 border-emerald-400/30',
              status === 'connecting' && 'bg-amber-400/10 border-amber-400/30',
              status === 'closed' && 'bg-rose-400/10 border-rose-400/30'
            )}
          >
            <StatusDot status={status} />
            <span
              className={clsx(
                'text-[9px] sm:text-[10px] font-bold uppercase tracking-[0.15em] sm:tracking-[0.2em]',
                status === 'open' && 'text-emerald-300',
                status === 'connecting' && 'text-amber-300',
                status === 'closed' && 'text-rose-300'
              )}
            >
              {statusLabel(status)}
            </span>
          </div>
        </Tooltip>
        {/* Son ON/OFF — bip discret sur nouveau setup TAKE */}
        <Tooltip content={audioEnabled ? TIPS.header.soundOn : TIPS.header.soundOff}>
        <button
          type="button"
          onClick={toggleAudio}
          aria-pressed={audioEnabled}
          aria-label={audioEnabled ? 'Désactiver les alertes audio' : 'Activer les alertes audio'}
          className={clsx(
            'flex items-center justify-center w-8 h-8 sm:w-9 sm:h-9 rounded-lg border transition-all',
            audioEnabled
              ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-300 shadow-[0_0_12px_rgba(34,211,238,0.15)]'
              : 'border-glass-soft text-white/40 hover:text-white/70 hover:bg-white/5'
          )}
        >
          {audioEnabled ? (
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
              <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
              <line x1="22" y1="9" x2="16" y2="15"/>
              <line x1="16" y1="9" x2="22" y2="15"/>
            </svg>
          )}
        </button>
        </Tooltip>
        {/* Logout */}
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
            className="text-xs px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg border border-glass-soft hover:border-glass-strong hover:bg-white/5 transition-all"
            title={`Logout ${whoami.data.username}`}
          >
            <span className="opacity-60 sm:mr-1.5">⎋</span>
            <span className="font-mono hidden sm:inline">{whoami.data.username}</span>
          </button>
        )}
      </div>
    </header>
  );
}
