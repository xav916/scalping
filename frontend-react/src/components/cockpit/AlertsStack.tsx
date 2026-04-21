import type { Alert } from "@/api/types";

const levelClass: Record<Alert["level"], string> = {
  critical: "bg-danger/10 border-danger/50 text-danger",
  warning: "bg-warning/10 border-warning/50 text-warning",
  info: "bg-accent/10 border-accent/40 text-accent",
};

export function AlertsStack({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return null;
  return (
    <section className="space-y-1.5">
      {alerts.map((a, i) => (
        <div
          key={`${a.code}-${i}`}
          className={`text-sm px-3 py-2 rounded border ${levelClass[a.level]}`}
        >
          {a.msg}
        </div>
      ))}
    </section>
  );
}
