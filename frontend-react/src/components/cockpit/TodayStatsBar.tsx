import type { Cockpit } from "@/api/types";
import { fmtMoney, fmtPct, pnlColor } from "@/lib/format";

export function TodayStatsBar({ today }: { today: Cockpit["today_stats"] }) {
  return (
    <section className="panel p-4 flex flex-wrap items-center gap-6 justify-around">
      <Metric label="PnL du jour">
        <span className={`stat-value ${pnlColor(today.pnl)}`}>
          {fmtMoney(today.pnl)} $
        </span>
        <span className={`text-xs ${pnlColor(today.pnl_pct)}`}>
          {fmtPct(today.pnl_pct)}
        </span>
      </Metric>
      <Metric label="Trades">
        <span className="stat-value">
          {today.n_trades}{" "}
          <span className="text-xs text-slate-400">
            · {today.n_open} ouverts
          </span>
        </span>
      </Metric>
      <Metric label="Capital">
        <span className="stat-value font-mono">
          {fmtMoney(today.capital, 0)} $
        </span>
      </Metric>
      {today.loss_alert && (
        <span className="pill bg-danger/20 text-danger">Loss limit atteint</span>
      )}
      {today.silent_mode && (
        <span className="pill bg-warning/20 text-warning">Silent mode</span>
      )}
    </section>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start">
      <span className="stat-label">{label}</span>
      <div className="flex items-baseline gap-2">{children}</div>
    </div>
  );
}
