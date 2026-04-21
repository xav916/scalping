import useSWR from "swr";
import { swrFetcher } from "@/api/client";
import type { PersonalTrade } from "@/api/types";
import { fmtMoney, fmtPips, pnlColor } from "@/lib/format";

export function TradesPage() {
  const { data, error } = useSWR<PersonalTrade[]>(
    "/api/trades?limit=200",
    swrFetcher
  );

  if (error) {
    return (
      <div className="text-danger p-4 text-sm">
        Erreur : {(error as Error).message}
      </div>
    );
  }
  if (!data) {
    return <div className="text-slate-500 p-4 text-sm">Chargement trades…</div>;
  }

  return (
    <div className="panel p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-3">
        Journal des trades ({data.length})
      </h2>
      {data.length === 0 ? (
        <div className="text-slate-500 text-sm py-6 text-center">
          Aucun trade enregistré pour l'instant.
        </div>
      ) : (
        <div className="overflow-x-auto text-sm">
          <table className="w-full">
            <thead className="text-slate-500 text-[11px] uppercase tracking-wider">
              <tr>
                <Th>Ouvert</Th>
                <Th>Pair</Th>
                <Th>Sens</Th>
                <Th>Entry</Th>
                <Th>Exit</Th>
                <Th>Slip</Th>
                <Th>Clôture</Th>
                <Th>PnL</Th>
                <Th>Statut</Th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {data.map((t) => (
                <tr key={t.id} className="border-t border-border/40">
                  <Td>{t.created_at.slice(0, 16).replace("T", " ")}</Td>
                  <Td>{t.pair}</Td>
                  <Td>
                    <span
                      className={`pill text-[10px] ${
                        t.direction === "buy"
                          ? "bg-success/20 text-success"
                          : "bg-danger/20 text-danger"
                      }`}
                    >
                      {t.direction.toUpperCase()}
                    </span>
                  </Td>
                  <Td>{t.entry_price}</Td>
                  <Td>{t.exit_price ?? "—"}</Td>
                  <Td>{fmtPips(t.slippage_pips)}</Td>
                  <Td>{t.close_reason ?? "—"}</Td>
                  <Td className={pnlColor(t.pnl)}>{fmtMoney(t.pnl)}</Td>
                  <Td>
                    <span
                      className={`pill text-[10px] ${
                        t.status === "OPEN"
                          ? "bg-accent/20 text-accent"
                          : "bg-slate-700/40 text-slate-400"
                      }`}
                    >
                      {t.status}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="text-left py-1 pr-4 font-normal">{children}</th>;
}
function Td({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`py-1.5 pr-4 ${className}`}>{children}</td>;
}
