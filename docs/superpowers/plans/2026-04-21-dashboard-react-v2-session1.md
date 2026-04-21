# Dashboard React V2 Session 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer un dashboard React V2 bout en bout sur `/v2/*` (dashboard principal + login + performance), coexistant avec l'ancien `/`, consommant les endpoints existants sans modifier le backend au-delà du mount SPA.

**Architecture:** Nouveau dossier `frontend-react/` à la racine, Vite + React 18 + TypeScript strict. Build produit `dist/` monté par FastAPI sur `/v2/*`. React Query pour REST, custom hook pour WebSocket. Direction esthétique "Trading Neo + Bento Polish" via Tailwind tokens custom + motion.

**Tech Stack:** Vite 5, React 18, TypeScript 5.5, react-router-dom 6, @tanstack/react-query 5, motion 11 (ex-framer-motion), Tailwind 3, clsx.

---

## File Structure

**Création (racine repo) :**
- `frontend-react/` — nouveau dossier, tout le code React
  - Configuration : `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `tailwind.config.ts`, `postcss.config.js`, `.gitignore`, `index.html`
  - Code : `src/main.tsx`, `src/App.tsx`
  - Pages : `src/pages/DashboardPage.tsx`, `src/pages/LoginPage.tsx`
  - Layout : `src/components/layout/Header.tsx`
  - Macro : `src/components/macro/MacroBanner.tsx`
  - Setups : `src/components/setups/SetupsGrid.tsx`, `src/components/setups/SetupCard.tsx`
  - Performance : `src/components/performance/PerformancePanel.tsx`
  - Auth : `src/components/auth/AuthGate.tsx`
  - UI primitives : `src/components/ui/GlassCard.tsx`, `src/components/ui/GradientText.tsx`, `src/components/ui/Skeleton.tsx`, `src/components/ui/MeshGradient.tsx`
  - Hooks : `src/hooks/useWebSocket.ts`, `src/hooks/useMacro.ts`, `src/hooks/useSetups.ts`, `src/hooks/usePerformance.ts`, `src/hooks/useAuth.ts`
  - Types : `src/types/domain.ts`
  - Lib : `src/lib/api.ts`, `src/lib/format.ts`, `src/lib/queryClient.ts`, `src/lib/constants.ts`
  - Styles : `src/styles/globals.css`

**Modification :**
- `backend/app.py` — ajout du mount `/v2/*` (2 blocs, aucune route existante touchée)
- `Dockerfile` — ajout d'une stage `node:20-alpine` amont

Le code React est réparti sur des fichiers courts (< 150 lignes chacun) pour rester lisibles en contexte unique.

---

## Task 1 — Scaffold Vite + React + TypeScript

**Files:**
- Create: `frontend-react/package.json`, `frontend-react/vite.config.ts`, `frontend-react/tsconfig.json`, `frontend-react/tsconfig.node.json`, `frontend-react/index.html`, `frontend-react/.gitignore`, `frontend-react/src/main.tsx`, `frontend-react/src/App.tsx`

- [ ] **Step 1.1 : Créer `frontend-react/package.json`**

```json
{
  "name": "scalping-radar-v2",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2",
    "@tanstack/react-query": "^5.56.2",
    "motion": "^11.11.17",
    "clsx": "^2.1.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.13",
    "typescript": "^5.5.4",
    "vite": "^5.4.8"
  }
}
```

- [ ] **Step 1.2 : Créer `frontend-react/vite.config.ts`**

```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/v2/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
});
```

- [ ] **Step 1.3 : Créer `frontend-react/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 1.4 : Créer `frontend-react/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "tailwind.config.ts", "postcss.config.js"]
}
```

- [ ] **Step 1.5 : Créer `frontend-react/.gitignore`**

```
node_modules
dist
dist-ssr
*.local
.vscode/*
!.vscode/extensions.json
.DS_Store
*.log
```

- [ ] **Step 1.6 : Créer `frontend-react/index.html`**

```html
<!DOCTYPE html>
<html lang="fr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#0a0e14" />
    <title>Scalping Radar V2</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 1.7 : Créer `frontend-react/src/main.tsx`**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 1.8 : Créer `frontend-react/src/App.tsx` (version minimale)**

```tsx
export default function App() {
  return (
    <div className="min-h-screen bg-radar-deep text-white flex items-center justify-center">
      <h1 className="text-2xl font-semibold">Scalping Radar V2 — boot OK</h1>
    </div>
  );
}
```

- [ ] **Step 1.9 : Installer les dépendances**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm install
```

Expected : `added XXX packages`, aucune error.

- [ ] **Step 1.10 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/package.json frontend-react/package-lock.json frontend-react/vite.config.ts frontend-react/tsconfig.json frontend-react/tsconfig.node.json frontend-react/index.html frontend-react/.gitignore frontend-react/src/main.tsx frontend-react/src/App.tsx
git commit -m "feat(v2): scaffold Vite + React 18 + TypeScript strict"
```

---

## Task 2 — Tailwind + design tokens + globals.css

**Files:**
- Create: `frontend-react/tailwind.config.ts`, `frontend-react/postcss.config.js`, `frontend-react/src/styles/globals.css`

- [ ] **Step 2.1 : Créer `frontend-react/tailwind.config.ts`**

```ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'neon-buy': '#22d3ee',
        'neon-sell': '#ec4899',
        'radar-deep': '#0a0e14',
        'radar-surface': '#13112a',
        'glass-soft': 'rgba(255,255,255,0.08)',
        'glass-strong': 'rgba(255,255,255,0.15)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      backdropBlur: {
        glass: '20px',
      },
      boxShadow: {
        'glass-ambient': '0 4px 24px rgba(139,92,246,0.15)',
        'glass-elevated': '0 8px 32px rgba(139,92,246,0.25)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 2.2 : Créer `frontend-react/postcss.config.js`**

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 2.3 : Créer `frontend-react/src/styles/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: dark;
}

html,
body,
#root {
  height: 100%;
}

body {
  font-family: 'Inter', system-ui, sans-serif;
  background: linear-gradient(135deg, #0a0e14 0%, #13112a 100%);
  background-attachment: fixed;
  color: #e6edf3;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-x: hidden;
}

/* Accessibilité : animations réduites respecte prefers-reduced-motion */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

.gradient-accent {
  background: linear-gradient(135deg, #22d3ee 0%, #ec4899 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}

.gradient-buy {
  background: linear-gradient(135deg, #22d3ee 0%, #a3e635 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}

.gradient-sell {
  background: linear-gradient(135deg, #ec4899 0%, #fb923c 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
```

- [ ] **Step 2.4 : Vérifier build & typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck && npm run build
```

Expected : `tsc --noEmit` sans erreur, puis `vite build` OK avec `dist/` généré.

- [ ] **Step 2.5 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/tailwind.config.ts frontend-react/postcss.config.js frontend-react/src/styles/globals.css
git commit -m "feat(v2): tailwind config + design tokens (Trading Neo + Bento Polish)"
```

---

## Task 3 — Types domaine + API client + queryClient

**Files:**
- Create: `frontend-react/src/types/domain.ts`, `frontend-react/src/lib/api.ts`, `frontend-react/src/lib/queryClient.ts`, `frontend-react/src/lib/format.ts`, `frontend-react/src/lib/constants.ts`

- [ ] **Step 3.1 : Créer `frontend-react/src/types/domain.ts`**

```ts
export type Direction = 'buy' | 'sell';
export type VerdictAction = 'TAKE' | 'WAIT' | 'SKIP';
export type RiskRegime = 'risk_on' | 'risk_off' | 'neutral';
export type MacroDirection = 'up' | 'down' | 'neutral';
export type VixLevel = 'low' | 'normal' | 'elevated' | 'high';

export interface ConfidenceFactor {
  name: string;
  score: number;
  detail: string;
  positive: boolean;
  source?: string;
}

export interface TradeSetup {
  pair: string;
  direction: Direction;
  entry_price: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2?: number;
  confidence_score: number;
  confidence_factors?: ConfidenceFactor[];
  verdict_action?: VerdictAction;
  verdict_summary?: string;
  verdict_reasons?: string[];
  verdict_warnings?: string[];
  verdict_blockers?: string[];
  is_simulated?: boolean;
  risk_reward_1?: number;
}

export interface MacroSnapshot {
  fetched_at: string;
  dxy: MacroDirection;
  spx: MacroDirection;
  vix_level: VixLevel;
  vix_value: number;
  us10y: MacroDirection;
  de10y: MacroDirection;
  oil: MacroDirection;
  nikkei: MacroDirection;
  gold: MacroDirection;
  risk_regime: RiskRegime;
}

export interface InsightsBucket {
  bucket: string;
  count: number;
  wins: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface InsightsPerformance {
  total_trades: number;
  win_rate?: number;
  total_pnl?: number;
  avg_pnl?: number;
  total_losses?: number;
  since?: string;
  message?: string;
  by_score_bucket?: InsightsBucket[];
  by_asset_class?: InsightsBucket[];
  by_direction?: InsightsBucket[];
  by_risk_regime?: InsightsBucket[];
  by_session?: InsightsBucket[];
  by_pair?: InsightsBucket[];
}

export interface User {
  username: string;
  email?: string;
}

export type WSMessage =
  | { type: 'setups_update'; payload: TradeSetup[] }
  | { type: 'signal'; payload: unknown }
  | { type: 'ping' | 'pong' };
```

- [ ] **Step 3.2 : Créer `frontend-react/src/lib/constants.ts`**

```ts
/** Filtre de date pour /api/insights/performance : exclut les trades
 *  pré-fix prix (bug prix fantôme corrigé le 2026-04-20 ~21h UTC). */
export const POST_FIX_CUTOFF = '2026-04-20T21:14:00+00:00';

/** Seuil minimum d'affichage d'un setup dans la grille (UI only). */
export const UI_MIN_CONFIDENCE = 50;
```

- [ ] **Step 3.3 : Créer `frontend-react/src/lib/api.ts`**

```ts
import type {
  TradeSetup,
  MacroSnapshot,
  InsightsPerformance,
  User,
} from '@/types/domain';
import { POST_FIX_CUTOFF } from '@/lib/constants';

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let body = '';
    try {
      body = await res.text();
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, body || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  whoami: () => request<User>('/api/me'),
  login: (username: string, password: string) =>
    request<{ ok: true }>('/api/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/api/logout', { method: 'POST' }),

  macro: async () => {
    const raw = await request<{ status: string; snapshot: MacroSnapshot | null }>(
      '/api/macro'
    );
    return raw.snapshot;
  },

  setups: async (): Promise<TradeSetup[]> => {
    const raw = await request<{ trade_setups?: TradeSetup[] }>('/api/overview');
    return raw.trade_setups ?? [];
  },

  performance: (since: string = POST_FIX_CUTOFF) =>
    request<InsightsPerformance>(
      `/api/insights/performance?since=${encodeURIComponent(since)}`
    ),
};

export { ApiError };
```

- [ ] **Step 3.4 : Créer `frontend-react/src/lib/queryClient.ts`**

```ts
import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './api';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status === 401) return false;
        return failureCount < 2;
      },
    },
  },
});
```

- [ ] **Step 3.5 : Créer `frontend-react/src/lib/format.ts`**

```ts
export function formatPrice(n: number | null | undefined, digits = 5): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  if (Math.abs(n) >= 1000) return n.toFixed(2);
  return n.toFixed(digits);
}

export function formatPnl(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)} €`;
}

export function formatPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

export function formatParisTime(date: Date = new Date()): string {
  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'Europe/Paris',
  }).format(date);
}
```

- [ ] **Step 3.6 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 3.7 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/types/ frontend-react/src/lib/
git commit -m "feat(v2): types domaine + api client + queryClient + helpers format"
```

---

## Task 4 — Hooks de données (auth, macro, setups, performance, ws)

**Files:**
- Create: `frontend-react/src/hooks/useAuth.ts`, `frontend-react/src/hooks/useMacro.ts`, `frontend-react/src/hooks/useSetups.ts`, `frontend-react/src/hooks/usePerformance.ts`, `frontend-react/src/hooks/useWebSocket.ts`

- [ ] **Step 4.1 : Créer `frontend-react/src/hooks/useAuth.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';

export function useAuth() {
  const qc = useQueryClient();

  const whoami = useQuery({
    queryKey: ['auth', 'whoami'],
    queryFn: api.whoami,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 401) return false;
      return failureCount < 1;
    },
    staleTime: 5 * 60_000,
  });

  const login = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth'] }),
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.clear();
    },
  });

  return { whoami, login, logout };
}
```

- [ ] **Step 4.2 : Créer `frontend-react/src/hooks/useMacro.ts`**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useMacro() {
  return useQuery({
    queryKey: ['macro'],
    queryFn: api.macro,
    staleTime: 20_000,
    refetchInterval: 30_000,
  });
}
```

- [ ] **Step 4.3 : Créer `frontend-react/src/hooks/useSetups.ts`**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function useSetups() {
  return useQuery({
    queryKey: ['setups'],
    queryFn: api.setups,
    staleTime: 60_000,
    refetchInterval: 90_000,
  });
}
```

- [ ] **Step 4.4 : Créer `frontend-react/src/hooks/usePerformance.ts`**

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { POST_FIX_CUTOFF } from '@/lib/constants';

export function usePerformance(since: string = POST_FIX_CUTOFF) {
  return useQuery({
    queryKey: ['performance', since],
    queryFn: () => api.performance(since),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}
```

- [ ] **Step 4.5 : Créer `frontend-react/src/hooks/useWebSocket.ts`**

```ts
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { WSMessage } from '@/types/domain';

export type WSStatus = 'connecting' | 'open' | 'closed';

export function useWebSocket(path = '/ws') {
  const [status, setStatus] = useState<WSStatus>('connecting');
  const qc = useQueryClient();
  const reconnectAttemptsRef = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      setStatus('connecting');
      const url = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${path}`;
      const sock = new WebSocket(url);
      socketRef.current = sock;

      sock.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setStatus('open');
      };

      sock.onmessage = (ev) => {
        try {
          const msg: WSMessage = JSON.parse(ev.data);
          if (msg.type === 'setups_update') {
            qc.invalidateQueries({ queryKey: ['setups'] });
          }
        } catch {
          /* ignore malformed */
        }
      };

      sock.onclose = () => {
        setStatus('closed');
        if (stopped) return;
        const backoff = Math.min(30_000, 1_000 * 2 ** reconnectAttemptsRef.current);
        reconnectAttemptsRef.current += 1;
        setTimeout(connect, backoff);
      };

      sock.onerror = () => {
        sock.close();
      };
    };

    connect();
    return () => {
      stopped = true;
      socketRef.current?.close();
    };
  }, [path, qc]);

  return { status };
}
```

- [ ] **Step 4.6 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 4.7 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/hooks/
git commit -m "feat(v2): hooks React Query (auth, macro, setups, performance) + useWebSocket"
```

---

## Task 5 — UI primitives (GlassCard, GradientText, Skeleton, MeshGradient)

**Files:**
- Create: `frontend-react/src/components/ui/GlassCard.tsx`, `frontend-react/src/components/ui/GradientText.tsx`, `frontend-react/src/components/ui/Skeleton.tsx`, `frontend-react/src/components/ui/MeshGradient.tsx`

- [ ] **Step 5.1 : Créer `frontend-react/src/components/ui/GlassCard.tsx`**

```tsx
import clsx from 'clsx';
import type { ReactNode, HTMLAttributes } from 'react';

interface Props extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'elevated';
  children: ReactNode;
}

export function GlassCard({ variant = 'default', className, children, ...rest }: Props) {
  return (
    <div
      {...rest}
      className={clsx(
        'rounded-2xl border backdrop-blur-glass',
        variant === 'default' && 'border-glass-soft bg-white/[0.03] shadow-glass-ambient',
        variant === 'elevated' && 'border-glass-strong bg-white/[0.05] shadow-glass-elevated',
        className
      )}
    >
      {children}
    </div>
  );
}
```

- [ ] **Step 5.2 : Créer `frontend-react/src/components/ui/GradientText.tsx`**

```tsx
import clsx from 'clsx';
import type { ReactNode, HTMLAttributes } from 'react';

interface Props extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'accent' | 'buy' | 'sell';
  children: ReactNode;
}

export function GradientText({ variant = 'accent', className, children, ...rest }: Props) {
  const cls =
    variant === 'buy'
      ? 'gradient-buy'
      : variant === 'sell'
      ? 'gradient-sell'
      : 'gradient-accent';
  return (
    <span {...rest} className={clsx(cls, 'font-mono font-semibold', className)}>
      {children}
    </span>
  );
}
```

- [ ] **Step 5.3 : Créer `frontend-react/src/components/ui/Skeleton.tsx`**

```tsx
import clsx from 'clsx';

interface Props {
  className?: string;
}

export function Skeleton({ className }: Props) {
  return (
    <div
      className={clsx(
        'animate-pulse-slow rounded-lg bg-white/[0.04] border border-glass-soft',
        className
      )}
    />
  );
}
```

- [ ] **Step 5.4 : Créer `frontend-react/src/components/ui/MeshGradient.tsx`**

```tsx
export function MeshGradient() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10"
      style={{
        background: `
          radial-gradient(ellipse 600px 300px at 15% 10%, rgba(139,92,246,0.18), transparent 60%),
          radial-gradient(ellipse 500px 300px at 85% 90%, rgba(236,72,153,0.12), transparent 60%),
          radial-gradient(ellipse 500px 200px at 50% 50%, rgba(34,211,238,0.08), transparent 60%)
        `,
      }}
    />
  );
}
```

- [ ] **Step 5.5 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 5.6 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/components/ui/
git commit -m "feat(v2): UI primitives (GlassCard, GradientText, Skeleton, MeshGradient)"
```

---

## Task 6 — Header + LoginPage + AuthGate

**Files:**
- Create: `frontend-react/src/components/layout/Header.tsx`, `frontend-react/src/components/auth/AuthGate.tsx`, `frontend-react/src/pages/LoginPage.tsx`

- [ ] **Step 6.1 : Créer `frontend-react/src/components/layout/Header.tsx`**

```tsx
import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { useAuth } from '@/hooks/useAuth';
import { useWebSocket } from '@/hooks/useWebSocket';
import { formatParisTime } from '@/lib/format';

export function Header() {
  const { whoami, logout } = useAuth();
  const { status } = useWebSocket();
  const [now, setNow] = useState(() => formatParisTime());

  useEffect(() => {
    const id = setInterval(() => setNow(formatParisTime()), 1000);
    return () => clearInterval(id);
  }, []);

  const statusColor =
    status === 'open' ? 'bg-emerald-400' : status === 'connecting' ? 'bg-amber-400' : 'bg-rose-400';

  return (
    <header className="sticky top-0 z-20 px-6 py-4 flex items-center justify-between border-b border-glass-soft backdrop-blur-glass bg-radar-deep/50">
      <div className="flex items-center gap-3">
        <span className="text-xl font-semibold tracking-tight">📡 Scalping Radar</span>
        <span className="text-xs font-mono text-white/40 px-2 py-0.5 rounded bg-white/5 border border-glass-soft">V2</span>
      </div>
      <div className="flex items-center gap-5 text-sm text-white/70">
        <span className="font-mono tabular-nums">{now} Paris</span>
        <span className="flex items-center gap-2">
          <span className={clsx('w-2 h-2 rounded-full', statusColor)} />
          <span className="text-xs uppercase tracking-wider">{status}</span>
        </span>
        {whoami.data && (
          <button
            type="button"
            onClick={() => {
              logout.mutate(undefined, {
                onSuccess: () => {
                  window.location.href = '/v2/login';
                },
              });
            }}
            className="text-xs px-3 py-1.5 rounded-lg border border-glass-soft hover:border-glass-strong transition-colors"
          >
            Logout ({whoami.data.username})
          </button>
        )}
      </div>
    </header>
  );
}
```

- [ ] **Step 6.2 : Créer `frontend-react/src/components/auth/AuthGate.tsx`**

```tsx
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Skeleton } from '@/components/ui/Skeleton';

export function AuthGate() {
  const { whoami } = useAuth();

  if (whoami.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Skeleton className="w-48 h-8" />
      </div>
    );
  }
  if (whoami.isError || !whoami.data) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
```

- [ ] **Step 6.3 : Créer `frontend-react/src/pages/LoginPage.tsx`**

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/ui/GlassCard';
import { MeshGradient } from '@/components/ui/MeshGradient';
import { GradientText } from '@/components/ui/GradientText';

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    login.mutate(
      { username, password },
      {
        onSuccess: () => navigate('/', { replace: true }),
        onError: () => setError('Identifiants invalides'),
      }
    );
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <MeshGradient />
      <GlassCard variant="elevated" className="w-full max-w-sm p-8">
        <h1 className="text-2xl font-semibold mb-1">
          <GradientText>Scalping Radar</GradientText>
        </h1>
        <p className="text-sm text-white/50 mb-8">Connexion requise</p>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
              Utilisateur
            </label>
            <input
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-glass-strong focus:outline-none transition-colors font-mono text-sm"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-wider text-white/50 mb-1.5">
              Mot de passe
            </label>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl bg-white/5 border border-glass-soft focus:border-glass-strong focus:outline-none transition-colors font-mono text-sm"
            />
          </div>
          {error && <p className="text-xs text-rose-400">{error}</p>}
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full py-2.5 rounded-xl bg-gradient-to-br from-cyan-400 to-pink-500 text-slate-900 font-semibold text-sm disabled:opacity-50 transition-opacity"
          >
            {login.isPending ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>
      </GlassCard>
    </div>
  );
}
```

- [ ] **Step 6.4 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 6.5 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/components/layout/ frontend-react/src/components/auth/ frontend-react/src/pages/LoginPage.tsx
git commit -m "feat(v2): Header + LoginPage + AuthGate"
```

---

## Task 7 — MacroBanner

**Files:**
- Create: `frontend-react/src/components/macro/MacroBanner.tsx`

- [ ] **Step 7.1 : Créer `frontend-react/src/components/macro/MacroBanner.tsx`**

```tsx
import clsx from 'clsx';
import { motion } from 'motion/react';
import { useMacro } from '@/hooks/useMacro';
import { GlassCard } from '@/components/ui/GlassCard';
import { Skeleton } from '@/components/ui/Skeleton';
import type { MacroDirection, MacroSnapshot } from '@/types/domain';

function arrow(d: MacroDirection): string {
  if (d === 'up') return '↑';
  if (d === 'down') return '↓';
  return '→';
}

function Pill({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div
      className={clsx(
        'flex items-baseline gap-1.5 px-3 py-1.5 rounded-xl border backdrop-blur-glass',
        tone
      )}
    >
      <span className="text-[10px] uppercase tracking-wider font-medium opacity-70">{label}</span>
      <span className="text-sm font-mono font-semibold">{value}</span>
    </div>
  );
}

function toneForRegime(regime: MacroSnapshot['risk_regime']): string {
  if (regime === 'risk_on') return 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30';
  if (regime === 'risk_off') return 'bg-rose-400/10 text-rose-300 border-rose-400/30';
  return 'bg-white/5 text-white/70 border-glass-soft';
}

function toneForDirection(d: MacroDirection): string {
  if (d === 'up') return 'bg-cyan-400/10 text-cyan-300 border-cyan-400/30';
  if (d === 'down') return 'bg-pink-400/10 text-pink-300 border-pink-400/30';
  return 'bg-white/5 text-white/60 border-glass-soft';
}

export function MacroBanner() {
  const { data, isLoading } = useMacro();

  if (isLoading) {
    return <Skeleton className="h-16 w-full" />;
  }
  if (!data) {
    return (
      <GlassCard className="p-4 text-sm text-white/50">
        Aucun snapshot macro disponible.
      </GlassCard>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <GlassCard className="p-4 flex flex-wrap items-center gap-3">
        <Pill label="Régime" value={data.risk_regime.replace('_', '-').toUpperCase()} tone={toneForRegime(data.risk_regime)} />
        <Pill label="DXY" value={arrow(data.dxy)} tone={toneForDirection(data.dxy)} />
        <Pill label="SPX" value={arrow(data.spx)} tone={toneForDirection(data.spx)} />
        <Pill label="VIX" value={`${data.vix_level} · ${data.vix_value.toFixed(1)}`} tone={toneForDirection(data.vix_level === 'low' ? 'down' : data.vix_level === 'high' ? 'up' : 'neutral')} />
        <Pill label="US10Y" value={arrow(data.us10y)} tone={toneForDirection(data.us10y)} />
        <Pill label="Gold" value={arrow(data.gold)} tone={toneForDirection(data.gold)} />
        <Pill label="Oil" value={arrow(data.oil)} tone={toneForDirection(data.oil)} />
      </GlassCard>
    </motion.div>
  );
}
```

- [ ] **Step 7.2 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 7.3 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/components/macro/
git commit -m "feat(v2): MacroBanner (pills risk_regime + DXY/SPX/VIX/US10Y/Gold/Oil)"
```

---

## Task 8 — SetupsGrid + SetupCard

**Files:**
- Create: `frontend-react/src/components/setups/SetupCard.tsx`, `frontend-react/src/components/setups/SetupsGrid.tsx`

- [ ] **Step 8.1 : Créer `frontend-react/src/components/setups/SetupCard.tsx`**

```tsx
import clsx from 'clsx';
import { motion } from 'motion/react';
import type { TradeSetup } from '@/types/domain';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { formatPrice } from '@/lib/format';

interface Props {
  setup: TradeSetup;
}

export function SetupCard({ setup }: Props) {
  const isBuy = setup.direction === 'buy';
  const accentBorder = isBuy ? 'before:bg-neon-buy' : 'before:bg-neon-sell';

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.2 } }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <GlassCard
        variant="elevated"
        className={clsx(
          'relative p-5 overflow-hidden',
          'before:absolute before:inset-y-0 before:left-0 before:w-0.5',
          accentBorder
        )}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <div className="text-lg font-mono font-bold tracking-tight">{setup.pair}</div>
            <div className={clsx('text-xs font-semibold uppercase tracking-wider', isBuy ? 'text-neon-buy' : 'text-neon-sell')}>
              {setup.direction}
            </div>
          </div>
          <GradientText variant={isBuy ? 'buy' : 'sell'} className="text-3xl leading-none">
            {setup.confidence_score.toFixed(0)}
          </GradientText>
        </div>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div>
            <dt className="text-white/40 uppercase tracking-wider">Entry</dt>
            <dd className="font-mono tabular-nums text-white/90 mt-0.5">{formatPrice(setup.entry_price)}</dd>
          </div>
          <div>
            <dt className="text-white/40 uppercase tracking-wider">SL</dt>
            <dd className="font-mono tabular-nums text-rose-300 mt-0.5">{formatPrice(setup.stop_loss)}</dd>
          </div>
          <div>
            <dt className="text-white/40 uppercase tracking-wider">TP1</dt>
            <dd className="font-mono tabular-nums text-emerald-300 mt-0.5">{formatPrice(setup.take_profit_1)}</dd>
          </div>
        </dl>
        {setup.verdict_summary && (
          <p className="mt-3 text-xs text-white/60 line-clamp-2">{setup.verdict_summary}</p>
        )}
      </GlassCard>
    </motion.div>
  );
}
```

- [ ] **Step 8.2 : Créer `frontend-react/src/components/setups/SetupsGrid.tsx`**

```tsx
import { AnimatePresence } from 'motion/react';
import { useSetups } from '@/hooks/useSetups';
import { SetupCard } from './SetupCard';
import { Skeleton } from '@/components/ui/Skeleton';
import { UI_MIN_CONFIDENCE } from '@/lib/constants';

function setupKey(s: { pair: string; direction: string; entry_price: number }) {
  return `${s.pair}-${s.direction}-${s.entry_price.toFixed(5)}`;
}

export function SetupsGrid() {
  const { data, isLoading } = useSetups();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  const setups = (data ?? [])
    .filter((s) => s.confidence_score >= UI_MIN_CONFIDENCE)
    .sort((a, b) => b.confidence_score - a.confidence_score);

  if (setups.length === 0) {
    return (
      <div className="text-center py-12 text-white/40 text-sm">
        Aucun setup ≥ {UI_MIN_CONFIDENCE} pour l'instant.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <AnimatePresence>
        {setups.map((s) => (
          <SetupCard key={setupKey(s)} setup={s} />
        ))}
      </AnimatePresence>
    </div>
  );
}
```

- [ ] **Step 8.3 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 8.4 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/components/setups/
git commit -m "feat(v2): SetupsGrid + SetupCard (glass + gradient score + motion AnimatePresence)"
```

---

## Task 9 — PerformancePanel

**Files:**
- Create: `frontend-react/src/components/performance/PerformancePanel.tsx`

- [ ] **Step 9.1 : Créer `frontend-react/src/components/performance/PerformancePanel.tsx`**

```tsx
import { useState } from 'react';
import clsx from 'clsx';
import { usePerformance } from '@/hooks/usePerformance';
import { GlassCard } from '@/components/ui/GlassCard';
import { GradientText } from '@/components/ui/GradientText';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatPct, formatPnl } from '@/lib/format';
import type { InsightsBucket } from '@/types/domain';

type TabKey =
  | 'by_score_bucket'
  | 'by_asset_class'
  | 'by_direction'
  | 'by_risk_regime'
  | 'by_session'
  | 'by_pair';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'by_score_bucket', label: 'Score' },
  { key: 'by_asset_class', label: 'Classe' },
  { key: 'by_direction', label: 'Sens' },
  { key: 'by_risk_regime', label: 'Régime macro' },
  { key: 'by_session', label: 'Session' },
  { key: 'by_pair', label: 'Pair' },
];

function BucketRow({ b }: { b: InsightsBucket }) {
  const winPct = b.win_rate;
  const winTone =
    winPct >= 0.6 ? 'text-emerald-300' : winPct >= 0.45 ? 'text-amber-300' : 'text-rose-300';
  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-4 py-2 border-b border-glass-soft last:border-none text-sm">
      <div className="font-mono text-white/80">{b.bucket}</div>
      <div className="text-xs text-white/50 tabular-nums">{b.count} trades</div>
      <div className={clsx('text-xs font-semibold tabular-nums', winTone)}>{formatPct(winPct)}</div>
      <div className="text-xs font-mono tabular-nums text-white/80 w-24 text-right">{formatPnl(b.total_pnl)}</div>
    </div>
  );
}

export function PerformancePanel() {
  const [tab, setTab] = useState<TabKey>('by_score_bucket');
  const { data, isLoading } = usePerformance();

  if (isLoading) {
    return <Skeleton className="h-64" />;
  }
  if (!data || data.total_trades === 0) {
    return (
      <GlassCard className="p-6 text-sm text-white/50">
        {data?.message ?? 'Pas de trades clôturés à analyser (attend quelques cycles).'}
      </GlassCard>
    );
  }

  const buckets = data[tab] ?? [];

  return (
    <GlassCard variant="elevated" className="p-6">
      <div className="flex items-end justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">Performance</h2>
          <p className="text-xs text-white/50 mt-1">
            {data.total_trades} trades ·{' '}
            <GradientText>{formatPct(data.win_rate ?? 0)}</GradientText> win rate · {formatPnl(data.total_pnl ?? 0)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={clsx(
                'text-xs px-3 py-1.5 rounded-lg border transition-colors',
                tab === t.key
                  ? 'border-glass-strong bg-white/10 text-white'
                  : 'border-glass-soft text-white/60 hover:text-white/90'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div>
        {buckets.length === 0 ? (
          <p className="text-sm text-white/40 py-6 text-center">Pas de données pour cette dimension.</p>
        ) : (
          buckets.map((b) => <BucketRow key={b.bucket} b={b} />)
        )}
      </div>
    </GlassCard>
  );
}
```

- [ ] **Step 9.2 : Typecheck**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck
```

Expected : 0 erreur.

- [ ] **Step 9.3 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/components/performance/
git commit -m "feat(v2): PerformancePanel (6 buckets tabs sur /api/insights/performance)"
```

---

## Task 10 — DashboardPage + App router final

**Files:**
- Create: `frontend-react/src/pages/DashboardPage.tsx`
- Modify: `frontend-react/src/App.tsx`, `frontend-react/src/main.tsx`

- [ ] **Step 10.1 : Créer `frontend-react/src/pages/DashboardPage.tsx`**

```tsx
import { Header } from '@/components/layout/Header';
import { MacroBanner } from '@/components/macro/MacroBanner';
import { SetupsGrid } from '@/components/setups/SetupsGrid';
import { PerformancePanel } from '@/components/performance/PerformancePanel';
import { MeshGradient } from '@/components/ui/MeshGradient';

export function DashboardPage() {
  return (
    <>
      <MeshGradient />
      <Header />
      <main className="px-6 py-6 max-w-[1400px] mx-auto space-y-6">
        <MacroBanner />
        <section>
          <h2 className="text-sm uppercase tracking-wider text-white/50 mb-3">Setups en cours</h2>
          <SetupsGrid />
        </section>
        <PerformancePanel />
      </main>
    </>
  );
}
```

- [ ] **Step 10.2 : Remplacer `frontend-react/src/App.tsx`**

```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import { AuthGate } from '@/components/auth/AuthGate';
import { DashboardPage } from '@/pages/DashboardPage';
import { LoginPage } from '@/pages/LoginPage';

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/v2">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AuthGate />}>
            <Route path="/" element={<DashboardPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 10.3 : Typecheck + build local**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping/frontend-react && npm run typecheck && npm run build
```

Expected : 0 erreur typecheck, build OK avec `dist/index.html` + `dist/assets/*.js` + `dist/assets/*.css`.

- [ ] **Step 10.4 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add frontend-react/src/pages/DashboardPage.tsx frontend-react/src/App.tsx
git commit -m "feat(v2): DashboardPage + App router avec AuthGate"
```

---

## Task 11 — Mount FastAPI /v2 + dev preuve locale

**Files:**
- Modify: `backend/app.py` (ajout à la suite des mounts existants)

- [ ] **Step 11.1 : Repérer la ligne des mounts existants dans `backend/app.py`**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping && grep -n "app.mount" backend/app.py | head -5
```

Expected : voir les mounts existants (probablement `/css`, `/js`, `/icons`). Noter la ligne juste après pour insertion.

- [ ] **Step 11.2 : Ajouter le mount v2 dans `backend/app.py`**

Trouver la zone (juste après les autres `app.mount(...)` et avant la première `@app.get(...)` ou `@app.post(...)`). Ajouter :

```python
# SPA React V2 (coexiste avec l'ancien frontend servi sur /)
from pathlib import Path as _PathV2
from fastapi.responses import FileResponse as _FileResponseV2
_V2_DIST = _PathV2(__file__).parent.parent / "frontend-react" / "dist"
if _V2_DIST.exists():
    app.mount(
        "/v2/assets",
        StaticFiles(directory=str(_V2_DIST / "assets")),
        name="v2-assets",
    )

    @app.get("/v2/{path:path}", include_in_schema=False)
    async def serve_v2(path: str):
        """SPA fallback : tout ce qui n'est pas un asset tombe sur index.html,
        React Router se charge du routing côté client."""
        candidate = _V2_DIST / path
        if candidate.is_file():
            return _FileResponseV2(str(candidate))
        return _FileResponseV2(str(_V2_DIST / "index.html"))
```

- [ ] **Step 11.3 : Smoke local**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Puis dans un navigateur : `http://127.0.0.1:8000/v2/` — doit servir le bundle React (HTML avec `<div id="root">`).

Note : si `main.py` utilise une autre variable, adapter la commande (souvent `uvicorn backend.app:app`).

Si OK, Ctrl+C le server.

- [ ] **Step 11.4 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add backend/app.py
git commit -m "feat(v2): mount FastAPI /v2/* pour servir le bundle React"
```

---

## Task 12 — Dockerfile stage node:20-alpine

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 12.1 : Lire le Dockerfile actuel**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping && cat Dockerfile
```

Noter la première ligne (`FROM python:3.11-slim` attendu).

- [ ] **Step 12.2 : Réécrire `Dockerfile` avec un multi-stage**

Ajouter le stage node AVANT le stage Python existant. Le stage Python doit renommer son alias (ajouter `AS runtime`) si ce n'est pas déjà le cas, et ajouter un `COPY --from=react-builder` juste après `WORKDIR /app` :

```dockerfile
# Stage 1 : build React
FROM node:20-alpine AS react-builder
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build

# Stage 2 : image finale Python (celle déjà existante, juste renommée)
FROM python:3.11-slim AS runtime

# ... (laisser tout le contenu existant inchangé jusqu'au WORKDIR)
WORKDIR /app

# Ajouter juste APRÈS WORKDIR /app :
COPY --from=react-builder /build/dist /app/frontend-react/dist

# ... (suite du Dockerfile existant inchangée — COPY requirements, pip install, COPY . . etc.)
```

Attention : la ligne existante `COPY . .` doit rester APRÈS le `COPY --from=react-builder`. Vérifier la cohérence après édition.

- [ ] **Step 12.3 : Build Docker local (optionnel si Docker Desktop actif)**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping && docker build -t scalping-radar:v2-test .
```

Expected : build complete without error, image créée.

Si Docker Desktop n'est pas actif localement, skip ce test et passer au deploy EC2 qui fera le build.

- [ ] **Step 12.4 : Commit**

```bash
cd C:/Users/xav91/Scalping/scalping
git add Dockerfile
git commit -m "build(v2): stage node:20-alpine pour build React + copy dist dans image Python"
```

---

## Task 13 — Deploy EC2 + smoke prod

**Files:**
- Aucun. Commandes de déploiement uniquement.

- [ ] **Step 13.1 : Push main**

Run :
```bash
cd C:/Users/xav91/Scalping/scalping && git push origin main
```

Expected : `main -> main` OK.

- [ ] **Step 13.2 : Pull + build + restart sur EC2**

Run :
```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && sudo git pull && \
   sudo docker build -t scalping-radar:latest . 2>&1 | tail -5 && \
   sudo systemctl restart scalping && sleep 6 && \
   sudo systemctl is-active scalping'
```

Expected : `active`. Si `docker build` échoue sur le stage React (ex: erreur TS), le container précédent reste tournant via `systemctl restart` (Docker restart pull l'image `:latest` qui est l'ancienne si la nouvelle a échoué).

- [ ] **Step 13.3 : Smoke test prod sans cookie**

Run :
```bash
curl -s --ssl-no-revoke -o /dev/null -w "HTTP %{http_code}\n" https://scalping-radar.duckdns.org/v2/login
```

Expected : `HTTP 200` (la page de login doit charger sans auth requise).

```bash
curl -s --ssl-no-revoke -o /dev/null -w "HTTP %{http_code}\n" https://scalping-radar.duckdns.org/v2/
```

Expected : `HTTP 200` également (SPA fallback renvoie index.html, le React fait la redirection côté client vers `/v2/login`).

- [ ] **Step 13.4 : Smoke test vérif ancien dashboard**

Run :
```bash
curl -s --ssl-no-revoke -o /dev/null -w "HTTP %{http_code}\n" https://scalping-radar.duckdns.org/
```

Expected : `HTTP 200` (ou `302` vers `/login` selon la config auth actuelle — conforme à ce qui existait avant cette session).

- [ ] **Step 13.5 : Smoke test interactif user**

Demander à l'utilisateur d'ouvrir `https://scalping-radar.duckdns.org/v2/login` dans son navigateur :
- [ ] Page de login s'affiche avec la direction esthétique (dark + glass + gradient)
- [ ] Login valide → redirection vers `/v2/` → dashboard charge MacroBanner + SetupsGrid + PerformancePanel
- [ ] Au moins 0 erreur console
- [ ] Logout → retour à `/v2/login`
- [ ] Ancien dashboard `/` reste fonctionnel

- [ ] **Step 13.6 : Rollback documenté si KO**

Si un critère de la 13.5 échoue, rollback immédiat :

```bash
ssh -i C:/Users/xav91/Scalping/scalping/scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && sudo git revert HEAD --no-edit && \
   sudo docker build -t scalping-radar:latest . && \
   sudo systemctl restart scalping'
```

L'ancien dashboard `/` n'ayant pas été modifié, il reste fonctionnel.

---

## Self-Review

**Spec coverage check :**
- Direction esthétique Trading Neo + Bento Polish → Task 2 (tokens) + Task 5 (primitives) + Tasks 6/7/8/9 (usage) ✓
- Stack Vite + React 18 + TS strict + Tailwind + motion + react-query + react-router → Task 1 (scaffold) + Tasks 3/4 (types/hooks) + Task 10 (router) ✓
- Structure fichiers (pages, components, hooks, lib, types) → Tasks 1, 3, 4, 5, 6, 7, 8, 9, 10 ✓
- Data flow (AuthGate, useMacro, useSetups, usePerformance, useWebSocket, invalidation) → Tasks 4, 6, 10 ✓
- Intégration FastAPI (mount /v2/, SPA fallback) → Task 11 ✓
- Dockerfile multi-stage → Task 12 ✓
- Tests = typecheck + smoke manuel → présent dans chaque task ✓
- Déploiement → Task 13 ✓
- Rollback → Task 13.6 ✓
- Critères de succès → Task 13.5 ✓
- Coexistence avec `/` → vérifiée explicitement en Task 13.4 ✓

**Placeholder scan :** aucun "TBD", "TODO", "similar to" — tout code visible, toutes commandes exactes. ✓

**Type consistency :**
- `TradeSetup`, `MacroSnapshot`, `InsightsBucket`, `InsightsPerformance`, `User`, `WSMessage` définis en Task 3.1, tous référencés dans Tasks 4/7/8/9 avec la même casse.
- `api.whoami / login / logout / macro / setups / performance` définis en Task 3.3 et utilisés tels quels en Task 4.
- `GlassCard` variants `default | elevated` cohérent entre Task 5 et usages 6/8/9.
- `GradientText` variants `accent | buy | sell` cohérent.
- `POST_FIX_CUTOFF` défini en Task 3.2 et utilisé en 3.3 + 4.4.

Aucune inconsistance détectée.
