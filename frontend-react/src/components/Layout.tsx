import { NavLink, Outlet } from "react-router-dom";
import useSWR from "swr";
import { swrFetcher } from "@/api/client";
import type { Cockpit } from "@/api/types";
import { KillSwitchToggle } from "@/components/cockpit/KillSwitchToggle";
import { useAuth } from "@/hooks/useAuth";

export function Layout() {
  const { user, logout } = useAuth();
  // On lit la derniere valeur connue du cockpit pour exposer le
  // kill switch dans le header (meme donnee que la page).
  const { data } = useSWR<Cockpit>("/api/cockpit", swrFetcher, {
    refreshInterval: 0,
  });

  return (
    <div className="min-h-screen flex flex-col">
      <header className="panel-alt border-b border-border flex items-center justify-between px-4 py-2.5 sticky top-0 z-10 backdrop-blur">
        <div className="flex items-center gap-6">
          <span className="text-sm font-semibold tracking-widest uppercase text-accent">
            Scalping Radar
          </span>
          <nav className="flex items-center gap-1 text-sm">
            <NavItem to="/">Cockpit</NavItem>
            <NavItem to="/analytics">Analytics</NavItem>
            <NavItem to="/trades">Trades</NavItem>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          {data?.kill_switch && <KillSwitchToggle status={data.kill_switch} />}
          {user && (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span>{user.display_name ?? user.username}</span>
              <button
                onClick={logout}
                className="text-slate-500 hover:text-slate-200 underline"
              >
                logout
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="flex-1 p-4 max-w-[1600px] w-full mx-auto">
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `px-3 py-1 rounded transition ${
          isActive
            ? "bg-accent/20 text-accent"
            : "text-slate-400 hover:text-slate-100"
        }`
      }
    >
      {children}
    </NavLink>
  );
}
