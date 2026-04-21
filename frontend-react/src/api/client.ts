// Client HTTP minimal. Meme-origine → le cookie de session HttpOnly
// est automatiquement envoye par le navigateur, pas de token a gerer.
// Un 401 declenche une redirection vers /login (via window.location
// pour forcer un flush propre, plutot que router.navigate).

export class HttpError extends Error {
  status: number;
  constructor(status: number, msg: string) {
    super(msg);
    this.status = status;
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (r.status === 401) {
    const here = window.location.pathname + window.location.search;
    if (!here.startsWith("/login")) {
      window.location.replace(`/login?next=${encodeURIComponent(here)}`);
    }
    throw new HttpError(401, "Unauthorized");
  }
  if (!r.ok) {
    let detail: string;
    try {
      detail = (await r.json()).detail ?? r.statusText;
    } catch {
      detail = r.statusText;
    }
    throw new HttpError(r.status, detail);
  }
  return (await r.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  return handle<T>(r);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return handle<T>(r);
}

// SWR fetcher : meme logique mais l'erreur 401 est propagee pour
// que SWR puisse re-render avec error.status = 401.
export const swrFetcher = <T>(path: string): Promise<T> => apiGet<T>(path);
