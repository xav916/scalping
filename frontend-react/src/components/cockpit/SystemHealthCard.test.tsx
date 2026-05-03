import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SystemHealthCard } from './SystemHealthCard';

const baseProps = {
  healthy: true,
  bridgeReachable: true,
  bridgeConfigured: true,
  secondsSince: 5,
  wsClients: 1,
};

describe('SystemHealthCard — marchés stars', () => {
  it('rend un badge ouvert/fermé pour chaque paire star', () => {
    render(
      <SystemHealthCard
        {...baseProps}
        marketsOpen={{
          'XAU/USD': true,
          'XAG/USD': true,
          'WTI/USD': false,
          'ETH/USD': true,
        }}
      />
    );
    expect(screen.getByText('Marchés stars')).toBeInTheDocument();
    expect(screen.getByText('XAU')).toBeInTheDocument();
    expect(screen.getByText('XAG')).toBeInTheDocument();
    expect(screen.getByText('WTI')).toBeInTheDocument();
    expect(screen.getByText('ETH')).toBeInTheDocument();
  });

  it('le tooltip title indique ouvert ou fermé selon l\'état', () => {
    render(
      <SystemHealthCard
        {...baseProps}
        marketsOpen={{
          'XAU/USD': true,
          'WTI/USD': false,
        }}
      />
    );
    expect(screen.getByTitle('XAU/USD — marché ouvert')).toBeInTheDocument();
    expect(screen.getByTitle('WTI/USD — marché fermé')).toBeInTheDocument();
  });

  it('omet la ligne "Marchés stars" si la prop marketsOpen est absente', () => {
    render(<SystemHealthCard {...baseProps} />);
    expect(screen.queryByText('Marchés stars')).not.toBeInTheDocument();
  });
});
