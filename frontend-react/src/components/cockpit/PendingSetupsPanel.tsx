import type { Cockpit } from "@/api/types";

type Props = { data: Cockpit["pending_setups"] };

export function PendingSetupsPanel({ data }: Props) {
  return (
    <section className="panel p-4">
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Setups TAKE · {data.count}
        </h2>
        <span className="text-xs text-slate-500">
          {data.total_count} setup{data.total_count > 1 ? "s" : ""} au total
        </span>
      </header>

      {data.items.length === 0 ? (
        <div className="text-slate-500 text-sm py-6 text-center">
          Aucun setup haute conviction pour le moment.
        </div>
      ) : (
        <ul className="divide-y divide-border/50">
          {data.items.map((s, i) => (
            <li key={`${s.pair}-${s.timestamp}-${i}`} className="py-3 flex items-center gap-3">
              <span
                className={`pill ${
                  s.direction === "buy"
                    ? "bg-success/20 text-success"
                    : "bg-danger/20 text-danger"
                }`}
              >
                {s.direction.toUpperCase()}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold">{s.pair}</span>
                  <span className="text-xs text-slate-400 font-mono">
                    @{s.entry_price}
                  </span>
                  <span className="pill bg-slate-700/40 text-slate-400 text-[10px]">
                    {s.asset_class}
                  </span>
                </div>
                <div className="text-xs text-slate-500 truncate">
                  {s.pattern ?? "—"} · SL {s.stop_loss} · TP {s.take_profit_1}
                </div>
              </div>
              <div className="text-right">
                <div className="font-mono text-sm">
                  {s.confidence_score.toFixed(0)}
                </div>
                <div className="text-[10px] text-slate-500 uppercase">
                  {s.verdict_action}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
