import type { Cockpit } from "@/api/types";
import { fmtDuration, fmtMoney, fmtPips, fmtPct, pnlColor } from "@/lib/format";

type Props = { data: Cockpit["active_trades"] };

export function ActiveTradesPanel({ data }: Props) {
  return (
    <section className="panel p-4">
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Trades actifs · {data.count}
        </h2>
        <div className="flex items-center gap-4">
          <div className="text-xs text-slate-400">
            Exposure {data.total_exposure_lots.toFixed(2)} lots
          </div>
          <div className={`font-mono text-sm ${pnlColor(data.unrealized_pnl)}`}>
            {fmtMoney(data.unrealized_pnl)} $
          </div>
        </div>
      </header>

      {data.items.length === 0 ? (
        <div className="text-slate-500 text-sm py-6 text-center">
          Aucune position ouverte.
        </div>
      ) : (
        <ul className="divide-y divide-border/50">
          {data.items.map((t) => (
            <li key={t.id} className="py-3 flex items-center gap-3">
              <span
                className={`pill ${
                  t.direction === "buy"
                    ? "bg-success/20 text-success"
                    : "bg-danger/20 text-danger"
                }`}
              >
                {t.direction.toUpperCase()}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold">{t.pair}</span>
                  <span className="text-xs text-slate-400 font-mono">
                    {t.entry_price} → {t.current_price ?? "—"}
                  </span>
                  {t.is_auto && (
                    <span className="pill bg-accent/15 text-accent">auto</span>
                  )}
                </div>
                <div className="text-xs text-slate-500">
                  {fmtDuration(t.duration_min)} · {t.size_lot} lots
                  {t.near_sl && (
                    <span className="ml-2 text-danger">⚠ proche SL</span>
                  )}
                </div>
              </div>
              <div className="text-right font-mono">
                <div className={pnlColor(t.pnl_unrealized)}>
                  {fmtMoney(t.pnl_unrealized)} $
                </div>
                <div className="text-xs text-slate-500">
                  {fmtPips(t.pnl_pips)} · SL {fmtPct(t.distance_to_sl_pct)}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
