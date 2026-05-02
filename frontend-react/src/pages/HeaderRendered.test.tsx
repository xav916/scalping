import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider } from '@/components/ui/Toast';

// Stub des hooks à effets de bord (timers, queries, websocket) pour isoler
// le test sur le rendu du Header dans le JSX des pages auth-gated.
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    whoami: { data: { username: 'admin@test', is_admin: true } },
    logout: { mutate: vi.fn() },
  }),
}));

vi.mock('@/hooks/useSystemStatus', () => ({
  useSystemStatus: () => ({ status: 'POLL', secondsSinceLastCycle: 0, wsOpen: false }),
}));

vi.mock('@/hooks/useAudioAlerts', () => ({
  useAudioAlerts: () => ({ enabled: false, toggle: vi.fn() }),
}));

import { SettingsPage } from './SettingsPage';
import { AdminPage } from './AdminPage';

function renderPage(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ToastProvider>{ui}</ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

describe('Header rendu sur les pages auth-gated', () => {
  it('SettingsPage rend un <header> en haut', () => {
    renderPage(<SettingsPage />);
    const headers = screen.getAllByRole('banner');
    expect(headers.length).toBeGreaterThanOrEqual(1);
    expect(headers[0].textContent).toMatch(/Scalping Radar/i);
  });

  it('AdminPage rend un <header> en haut', () => {
    renderPage(<AdminPage />);
    const headers = screen.getAllByRole('banner');
    expect(headers.length).toBeGreaterThanOrEqual(1);
    expect(headers[0].textContent).toMatch(/Scalping Radar/i);
  });

  it('Header affiche le lien Admin pour un user is_admin=true', () => {
    renderPage(<SettingsPage />);
    expect(screen.getByRole('link', { name: /^Admin$/ })).toBeInTheDocument();
  });
});
