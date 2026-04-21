import { useState } from "react";
import { mutate } from "swr";
import { apiPost } from "@/api/client";
import type { KillSwitchStatus } from "@/api/types";

export function KillSwitchToggle({ status }: { status: KillSwitchStatus }) {
  const [pending, setPending] = useState(false);
  const active = status.manual_enabled;

  const toggle = async () => {
    if (pending) return;
    let reason: string | null = null;
    if (!active) {
      reason = window.prompt(
        "Raison de l'activation du kill switch ?",
        "Pause manuelle"
      );
      if (reason === null) return;
    }
    setPending(true);
    try {
      await apiPost("/api/kill-switch", {
        enabled: !active,
        reason,
      });
      await mutate("/api/cockpit");
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      onClick={toggle}
      disabled={pending}
      className={`px-3 py-1.5 rounded text-xs font-semibold uppercase tracking-wider transition
        ${
          active || status.active
            ? "bg-danger/20 text-danger hover:bg-danger/30 border border-danger/40"
            : "bg-slate-700/40 text-slate-300 hover:bg-slate-700 border border-border"
        }
        ${pending ? "opacity-50 cursor-wait" : ""}`}
      title={status.reason ?? "Kill switch"}
    >
      {active || status.active ? "KILL SWITCH ON" : "Kill switch"}
    </button>
  );
}
