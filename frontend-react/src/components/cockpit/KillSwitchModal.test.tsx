import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { KillSwitchModal } from './KillSwitchModal';

describe('KillSwitchModal', () => {
  it('ne rend rien si open=false', () => {
    const { container } = render(
      <KillSwitchModal open={false} onConfirm={vi.fn()} onCancel={vi.fn()} />
    );
    expect(container.querySelector('[role="dialog"], input')).toBeNull();
  });

  it('affiche l\'input avec la raison par défaut quand open=true', () => {
    render(<KillSwitchModal open={true} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByPlaceholderText(/maintenance broker/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue('maintenance');
  });

  it('appelle onCancel sur clic Annuler', async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<KillSwitchModal open={true} onConfirm={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByText('Annuler'));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('appelle onConfirm avec la raison au clic Geler', async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<KillSwitchModal open={true} onConfirm={onConfirm} onCancel={vi.fn()} />);
    const input = screen.getByPlaceholderText(/maintenance broker/i) as HTMLInputElement;
    // fireEvent.change contourne les effets async (setTimeout focus)
    fireEvent.change(input, { target: { value: 'news imminente NFP' } });
    await user.click(screen.getByRole('button', { name: /geler l'auto-exec/i }));
    expect(onConfirm).toHaveBeenCalledWith('news imminente NFP');
  });

  it('appelle onConfirm sur Enter dans l\'input', () => {
    const onConfirm = vi.fn();
    render(<KillSwitchModal open={true} onConfirm={onConfirm} onCancel={vi.fn()} />);
    const input = screen.getByPlaceholderText(/maintenance broker/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'weekend' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onConfirm).toHaveBeenCalledWith('weekend');
  });

  it('désactive le bouton confirmer si raison vide', () => {
    render(<KillSwitchModal open={true} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const input = screen.getByPlaceholderText(/maintenance broker/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    const confirmBtn = screen.getByRole('button', { name: /geler l'auto-exec/i });
    expect(confirmBtn).toBeDisabled();
  });

  it('ferme sur touche Escape', () => {
    const onCancel = vi.fn();
    render(<KillSwitchModal open={true} onConfirm={vi.fn()} onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalled();
  });
});
