import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { motion } from 'motion/react';
import { Header } from '@/components/layout/Header';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { ApiError } from '@/lib/api';

type Confirmed = 'UP' | 'DOWN' | 'UNKNOWN';

interface ProbeBase {
  name: string;
  kind: 'bridge' | 'systemd' | 'data' | 'disk' | 'tailscale';
  ok?: boolean;
  error?: string;
}

interface BridgeProbe extends ProbeBase {
  kind: 'bridge';
  health_ms?: number;
  health_error?: string;
  health?: { ok?: boolean };
  account?: {
    login?: number;
    currency?: string;
    balance?: number;
    equity?: number;
    margin?: number;
    margin_free?: number;
    profit?: number;
    positions_count?: number;
  };
}

interface SystemdProbe extends ProbeBase {
  kind: 'systemd';
  active?: string;
}

interface DataProbe extends ProbeBase {
  kind: 'data';
  age_sec?: number;
  last_event_iso?: string;
}

interface DiskProbe extends ProbeBase {
  kind: 'disk';
  used_pct?: number;
  free_gb?: number;
  total_gb?: number;
}

interface TailscaleProbe extends ProbeBase {
  kind: 'tailscale';
  nodes?: { host: string; online: boolean }[];
}

type Probe = BridgeProbe | SystemdProbe | DataProbe | DiskProbe | TailscaleProbe;

interface ServiceState {
  confirmed: Confirmed;
  last_change_ts: number;
  last_probe: Probe;
  last_recovery: RecoveryEntry | null;
}

interface RecoveryEntry {
  name?: string;
  ts?: string;
  action?: string;
  ok?: boolean;
  detail?: string;
  cmd?: string;
  would_run?: string;
}

interface ControlTowerStatus {
  ts: string;
  services: Record<string, ServiceState>;
  recoveries: RecoveryEntry[];
  auto_recovery_enabled: boolean;
  actions_enabled: string[];
}

async function fetchControlTower(): Promise<ControlTowerStatus> {
  const res = await fetch('/api/admin/control-tower', { credentials: 'include' });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(res.status, body || res.statusText);
  }
  return res.json();
}

const ORDER = [
  'bridge_vps',
  'bridge_local',
  'radar_cycle',
  'scalping.service',
  'scalping-bridge-monitor.service',
  'nginx.service',
  'tailscale',
  'disk_root',
];

function StatusBadge({ status }: { status: Confirmed }) {
  const cls =
    status === 'UP'
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
      : status === 'DOWN'
      ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
      : 'bg-white/10 text-white/50 border-white/10';
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold tracking-wide ${cls}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          status === 'UP'
            ? 'bg-emerald-400 animate-pulse'
            : status === 'DOWN'
            ? 'bg-rose-400'
            : 'bg-white/40'
        }`}
      />
      {status}
    </span>
  );
}

function formatSince(tsSec: number): string {
  const diff = Math.max(0, Date.now() / 1000 - tsSec);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = Math.floor(diff % 60);
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function ProbeDetail({ probe }: { probe: Probe }) {
  if (probe.kind === 'bridge') {
    const acc = probe.account;
    if (acc) {
      return (
        <div className="space-y-0.5 text-xs text-white/60">
          <div>
            #{acc.login} ·{' '}
            <span className="text-white/80 font-mono">
              {acc.balance?.toFixed(2)} {acc.currency}
            </span>{' '}
            · {acc.positions_count}p
          </div>
          {probe.health_ms !== undefined && (
            <div className="text-white/40">
              latence health {probe.health_ms}ms
            </div>
          )}
        </div>
      );
    }
    if (probe.health_error) {
      return (
        <div className="text-xs text-rose-300/80 font-mono break-words">
          {probe.health_error.slice(0, 120)}
        </div>
      );
    }
    return null;
  }
  if (probe.kind === 'systemd') {
    return (
      <div className="text-xs text-white/60">
        systemctl: <span className="font-mono">{probe.active || '?'}</span>
      </div>
    );
  }
  if (probe.kind === 'data') {
    return (
      <div className="text-xs text-white/60">
        {probe.age_sec !== undefined && (
          <span>
            dernier event il y a{' '}
            <span className="font-mono">{probe.age_sec}s</span>
          </span>
        )}
        {probe.error && (
          <div className="text-rose-300/80 mt-0.5">{probe.error.slice(0, 100)}</div>
        )}
      </div>
    );
  }
  if (probe.kind === 'disk') {
    return (
      <div className="text-xs text-white/60">
        <span className="font-mono">{probe.used_pct}%</span> utilisé · {probe.free_gb} GB libre
      </div>
    );
  }
  if (probe.kind === 'tailscale') {
    return (
      <div className="text-xs text-white/60 flex flex-wrap gap-x-3 gap-y-0.5">
        {(probe.nodes ?? []).map((n) => (
          <span key={n.host} className="font-mono">
            {n.host}{' '}
            <span className={n.online ? 'text-emerald-300' : 'text-rose-300'}>
              {n.online ? 'on' : 'off'}
            </span>
          </span>
        ))}
        {probe.error && (
          <div className="text-rose-300/80 w-full">{probe.error.slice(0, 100)}</div>
        )}
      </div>
    );
  }
  return null;
}

function ProbeCard({
  name,
  state,
}: {
  name: string;
  state: ServiceState;
}) {
  return (
    <GlassCard className="p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white/90 tracking-tight">{name}</div>
          <div className="text-[10px] uppercase tracking-wider text-white/40 mt-0.5">
            {state.last_probe.kind} · since {formatSince(state.last_change_ts)}
          </div>
        </div>
        <StatusBadge status={state.confirmed} />
      </div>
      <ProbeDetail probe={state.last_probe} />
      {state.last_recovery && (
        <div className="text-[11px] mt-1 pt-2 border-t border-white/5">
          <span
            className={
              state.last_recovery.ok
                ? 'text-emerald-300'
                : 'text-amber-300/80'
            }
          >
            {state.last_recovery.ok ? '🔧' : '🛑'} recovery{' '}
            <span className="font-mono">{state.last_recovery.action}</span>
          </span>
          {state.last_recovery.detail && (
            <div className="text-white/50 mt-0.5 break-words">
              {state.last_recovery.detail.slice(0, 130)}
            </div>
          )}
        </div>
      )}
    </GlassCard>
  );
}

function RecoveryHistoryRow({ entry }: { entry: RecoveryEntry }) {
  return (
    <li className="flex items-center gap-3 py-2 border-b border-white/5 last:border-0 text-xs">
      <span className={entry.ok ? 'text-emerald-400' : 'text-amber-400/80'}>
        {entry.ok ? '✓' : '–'}
      </span>
      <span className="font-mono text-white/60 w-36 shrink-0">
        {entry.ts ? entry.ts.slice(11, 19) + 'Z' : '?'}
      </span>
      <span className="font-mono text-white/80 w-44 shrink-0 truncate">
        {entry.name} → {entry.action}
      </span>
      <span className="text-white/50 truncate">{entry.detail}</span>
    </li>
  );
}

export function ControlTowerPage() {
  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ['admin', 'control-tower'],
    queryFn: fetchControlTower,
    refetchInterval: 15_000,
    staleTime: 5_000,
    retry: 1,
  });

  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <GlassCard className="p-8 max-w-sm text-center">
          <p className="text-white/80 mb-4">Accès admin requis.</p>
          <Link to="/dashboard" className="text-cyan-400 hover:text-cyan-300 text-sm">
            ← Retour au dashboard
          </Link>
        </GlassCard>
      </div>
    );
  }

  const services = data?.services ?? {};
  const orderedNames = [
    ...ORDER.filter((n) => services[n]),
    ...Object.keys(services).filter((n) => !ORDER.includes(n)),
  ];

  const downCount = Object.values(services).filter((s) => s.confirmed === 'DOWN').length;
  const upCount = Object.values(services).filter((s) => s.confirmed === 'UP').length;

  const recoveries = data?.recoveries ?? [];
  const recentRecoveries = [...recoveries].reverse().slice(0, 10);

  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-4 sm:px-6 py-6 max-w-[1500px] mx-auto space-y-5">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Link
            to="/dashboard"
            className="text-xs text-white/40 hover:text-white/70 transition-colors inline-flex items-center gap-1 mb-1"
          >
            ← Dashboard
          </Link>
          <div className="flex items-end justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                Tour de contrôle infra
              </h1>
              <p className="text-sm text-white/50 mt-1">
                Sondes live des bridges MT5, services systemd et data flow.
                Polling 15s.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-white/40">
                {dataUpdatedAt
                  ? `mis à jour ${new Date(dataUpdatedAt).toLocaleTimeString('fr-FR', {
                      timeZone: 'Europe/Paris',
                    })}`
                  : '—'}
              </span>
            </div>
          </div>
        </motion.div>

        {error && !(error instanceof ApiError && error.status === 403) && (
          <GlassCard className="p-4 text-xs text-rose-300/80">
            Erreur fetch:{' '}
            <span className="font-mono">{(error as Error).message}</span>
          </GlassCard>
        )}

        {/* Vue synthèse */}
        {data && (
          <GlassCard className="p-4 flex flex-wrap items-center gap-x-6 gap-y-2">
            <div className="text-sm">
              <span className="text-emerald-400 font-semibold">{upCount}</span>{' '}
              <span className="text-white/50">UP</span>
              {downCount > 0 && (
                <>
                  {' · '}
                  <span className="text-rose-400 font-semibold">{downCount}</span>{' '}
                  <span className="text-white/50">DOWN</span>
                </>
              )}
            </div>
            <div className="text-xs text-white/50">
              auto-recovery{' '}
              <span
                className={
                  data.auto_recovery_enabled ? 'text-emerald-300' : 'text-amber-300'
                }
              >
                {data.auto_recovery_enabled ? 'ON' : 'OFF'}
              </span>
              {data.actions_enabled.length > 0 && (
                <>
                  {' · '}
                  actions:{' '}
                  <span className="font-mono text-white/70">
                    {data.actions_enabled.join(', ')}
                  </span>
                </>
              )}
            </div>
          </GlassCard>
        )}

        {/* Grille des sondes */}
        {isLoading && !data ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-2xl" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {orderedNames.map((name) => (
              <ProbeCard key={name} name={name} state={services[name]} />
            ))}
          </div>
        )}

        {/* Historique recovery */}
        <GlassCard className="p-4">
          <h2 className="text-sm font-semibold tracking-tight mb-2">
            Historique auto-recovery
          </h2>
          {recentRecoveries.length === 0 ? (
            <p className="text-xs text-white/40">
              Aucune recovery action récente. Les actions futures
              s'afficheront ici.
            </p>
          ) : (
            <ul className="text-xs">
              {recentRecoveries.map((r, i) => (
                <RecoveryHistoryRow key={i} entry={r} />
              ))}
            </ul>
          )}
        </GlassCard>
      </main>
    </>
  );
}
