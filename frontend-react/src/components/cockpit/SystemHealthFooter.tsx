import type { Cockpit } from "@/api/types";

type Props = { health: Cockpit["system_health"]; wsConnected: boolean };

export function SystemHealthFooter({ health, wsConnected }: Props) {
  const cycleAgo =
    health.seconds_since_last_cycle !== null
      ? `${Math.round(health.seconds_since_last_cycle)}s`
      : "—";
  const bridgeStatus = !health.bridge.configured
    ? "non configuré"
    : health.bridge.reachable
    ? `OK · ${health.bridge.mode ?? "?"}`
    : "injoignable";
  return (
    <footer className="panel px-4 py-2 flex flex-wrap items-center gap-4 text-xs text-slate-400">
      <Dot ok={health.healthy} label={`cycle ${cycleAgo}`} />
      <Dot
        ok={health.bridge.reachable || !health.bridge.configured}
        label={`bridge ${bridgeStatus}`}
      />
      <Dot ok={wsConnected} label={wsConnected ? "WS live" : "WS polling"} />
      <span>{health.ws_clients} client{health.ws_clients > 1 ? "s" : ""}</span>
      <span>{health.watched_pairs} pairs surveillées</span>
    </footer>
  );
}

function Dot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`inline-block w-2 h-2 rounded-full ${
          ok ? "bg-success" : "bg-danger"
        }`}
      />
      {label}
    </span>
  );
}
