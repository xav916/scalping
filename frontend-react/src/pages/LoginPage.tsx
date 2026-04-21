import { FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { apiPost } from "@/api/client";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const nextParam = new URLSearchParams(location.search).get("next") ?? "/";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setPending(true);
    try {
      await apiPost("/api/login", { username, password });
      navigate(nextParam, { replace: true });
    } catch (e) {
      setErr((e as Error).message || "Identifiants invalides");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form
        onSubmit={submit}
        className="panel w-full max-w-sm p-6 space-y-4"
      >
        <h1 className="text-lg font-semibold">Scalping Radar</h1>
        <p className="text-xs text-slate-400">Identification requise</p>

        <div>
          <label className="stat-label block mb-1">Utilisateur</label>
          <input
            type="text"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full bg-bg border border-border rounded px-3 py-2 font-mono text-sm focus:border-accent outline-none"
            required
          />
        </div>
        <div>
          <label className="stat-label block mb-1">Mot de passe</label>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-bg border border-border rounded px-3 py-2 font-mono text-sm focus:border-accent outline-none"
            required
          />
        </div>

        {err && (
          <div className="text-sm text-danger bg-danger/10 border border-danger/40 rounded px-3 py-2">
            {err}
          </div>
        )}

        <button
          type="submit"
          disabled={pending}
          className="w-full bg-accent text-bg font-semibold rounded px-3 py-2 hover:bg-accent/90 disabled:opacity-50"
        >
          {pending ? "Connexion…" : "Se connecter"}
        </button>
      </form>
    </div>
  );
}
