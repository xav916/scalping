import type { Cockpit } from "@/api/types";
import { sessionBadge } from "@/lib/format";

type Props = {
  macro: Cockpit["macro"];
  session: Cockpit["session"];
  fearGreed: Cockpit["fear_greed"];
};

const regimeClass: Record<string, string> = {
  risk_on: "bg-success/10 border-success/40 text-success",
  risk_off: "bg-danger/10 border-danger/40 text-danger",
  neutral: "bg-slate-700/30 border-border text-slate-200",
};

const fgClass: Record<string, string> = {
  extreme_fear: "bg-success/20 text-success",
  fear: "bg-success/10 text-success",
  neutral: "bg-slate-700/40 text-slate-300",
  greed: "bg-warning/10 text-warning",
  extreme_greed: "bg-danger/20 text-danger",
};

export function MacroBanner({ macro, session, fearGreed }: Props) {
  const sess = sessionBadge(session.label);
  const regime = macro?.risk_regime ?? "neutral";
  return (
    <div
      className={`panel px-4 py-3 border ${regimeClass[regime]} flex flex-wrap items-center gap-4 text-sm`}
    >
      <div className="font-semibold tracking-wide uppercase text-xs">
        {regime.replace("_", " ")}
      </div>
      {macro && (
        <>
          <Stat label="DXY" value={macro.dxy} />
          <Stat label="SPX" value={macro.spx} />
          <Stat
            label="VIX"
            value={`${macro.vix_level} (${macro.vix_value.toFixed(1)})`}
          />
        </>
      )}
      <span className={`pill ${sess.className}`}>{sess.text}</span>
      <span className="text-slate-400 text-xs">
        ×{session.activity_multiplier.toFixed(1)} sizing
      </span>
      {fearGreed && (
        <span className={`pill ${fgClass[fearGreed.classification] ?? ""}`}>
          F&G {fearGreed.value.toFixed(0)} · {fearGreed.classification}
        </span>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-[11px] text-slate-400 uppercase">{label}</span>
      <span className="font-mono text-sm">{value}</span>
    </div>
  );
}
