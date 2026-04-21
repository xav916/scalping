import useSWR from "swr";
import { swrFetcher } from "@/api/client";
import type { Analytics, AnalyticsBucket, DriftResult } from "@/api/types";

export function AnalyticsPage() {
  const { data: a } = useSWR<Analytics>("/api/analytics", swrFetcher);
  const { data: d } = useSWR<DriftResult>("/api/drift", swrFetcher);

  if (!a) {
    return (
      <div className="text-slate-500 text-sm p-4">Chargement analytics…</div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <BucketTable title="Par paire" rows={a.by_pair} />
        <BucketTable title="Par pattern" rows={a.by_pattern} />
        <BucketTable title="Par heure UTC" rows={a.by_hour_utc} />
        <BucketTable
          title="Par bucket de confiance"
          rows={a.by_confidence_bucket}
        />
        <BucketTable title="Par classe d'actif" rows={a.by_asset_class} />
        <BucketTable title="Par régime macro" rows={a.by_risk_regime} />
      </div>

      <section className="panel p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-3">
          Qualité d'exécution ·{" "}
          {a.execution_quality.total_closed_trades} trades fermés
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="stat-label mb-2">Slippage par paire</h3>
            <SimpleTable
              columns={["Pair", "N", "Moy", "Min", "Max"]}
              rows={a.execution_quality.slippage_by_pair.map((s) => [
                s.pair,
                s.n,
                `${s.avg_pips}p`,
                `${s.min_pips}p`,
                `${s.max_pips}p`,
              ])}
            />
          </div>
          <div>
            <h3 className="stat-label mb-2">Distribution des clôtures</h3>
            <SimpleTable
              columns={["Raison", "N", "%", "PnL moy"]}
              rows={a.execution_quality.close_reason_distribution.map((r) => [
                r.reason,
                r.count,
                `${r.pct}%`,
                `${r.avg_pnl} $`,
              ])}
            />
          </div>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-3">
          Volume de signaux
        </h2>
        <div className="flex flex-wrap gap-6 text-sm">
          <Stat label="Total" value={a.signal_volume.total_signals} />
          <Stat label="TAKE" value={a.signal_volume.verdict_take} />
          <Stat label="SKIP" value={a.signal_volume.verdict_skip} />
          <Stat
            label="Ratio TAKE"
            value={`${a.signal_volume.take_ratio_pct}%`}
          />
        </div>
      </section>

      {d && (d.by_pair.length > 0 || d.by_pattern.length > 0) && (
        <section className="panel p-4 border-warning/50">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-warning mb-3">
            ⚠ Drift détecté (fenêtre {d.window_days}j, seuil {d.threshold_pct}pts)
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            <DriftTable title="Par paire" rows={d.by_pair} />
            <DriftTable title="Par pattern" rows={d.by_pattern} />
          </div>
        </section>
      )}
    </div>
  );
}

function BucketTable({
  title,
  rows,
}: {
  title: string;
  rows: AnalyticsBucket[];
}) {
  return (
    <div className="panel p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-3">
        {title}
      </h3>
      {rows.length === 0 ? (
        <div className="text-slate-500 text-sm">Pas encore de données.</div>
      ) : (
        <SimpleTable
          columns={["Clé", "Wins", "Losses", "Total", "Win %"]}
          rows={rows.map((b) => [
            b.key,
            b.wins,
            b.losses,
            b.total,
            `${b.win_rate_pct}%`,
          ])}
        />
      )}
    </div>
  );
}

function DriftTable({
  title,
  rows,
}: {
  title: string;
  rows: DriftResult["by_pair"];
}) {
  return (
    <div>
      <h3 className="stat-label mb-2">{title}</h3>
      {rows.length === 0 ? (
        <div className="text-slate-500 text-sm">Rien à signaler.</div>
      ) : (
        <SimpleTable
          columns={["Clé", "Récent", "Baseline", "Δ"]}
          rows={rows.map((r) => [
            r.key,
            `${r.recent_win_rate_pct}% (${r.recent_n})`,
            `${r.baseline_win_rate_pct}% (${r.baseline_n})`,
            `${r.delta_pct}pts`,
          ])}
        />
      )}
    </div>
  );
}

function SimpleTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <div className="overflow-x-auto text-sm">
      <table className="w-full">
        <thead>
          <tr className="text-left text-slate-500 text-[11px] uppercase tracking-wider">
            {columns.map((c) => (
              <th key={c} className="py-1 pr-4 font-normal">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border/40">
              {r.map((cell, j) => (
                <td key={j} className="py-1.5 pr-4">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex flex-col">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}
