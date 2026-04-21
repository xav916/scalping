// Helpers de formattage reutilisables dans toute l'app.

export function fmtMoney(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined) return "—";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value).toLocaleString("fr-FR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${sign}${abs}`;
}

export function pnlColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-slate-300";
  return value > 0 ? "text-success" : "text-danger";
}

export function fmtPips(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}p`;
}

export function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(decimals)}%`;
}

export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h}h${m}` : `${h}h`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("fr-FR", {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function sessionBadge(label: string): { text: string; className: string } {
  const map: Record<string, { text: string; className: string }> = {
    london_ny_overlap: { text: "London/NY", className: "bg-success/20 text-success" },
    london: { text: "London", className: "bg-accent/20 text-accent" },
    new_york: { text: "New York", className: "bg-accent/20 text-accent" },
    asian: { text: "Asian", className: "bg-slate-600/30 text-slate-300" },
    sydney: { text: "Sydney", className: "bg-slate-600/30 text-slate-300" },
    off_hours: { text: "Off hours", className: "bg-slate-700/40 text-slate-400" },
    weekend: { text: "Weekend", className: "bg-warning/20 text-warning" },
  };
  return map[label] ?? { text: label, className: "bg-slate-700/40 text-slate-400" };
}
