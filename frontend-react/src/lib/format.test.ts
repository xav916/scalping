import { describe, it, expect } from 'vitest';
import { formatPnl, formatPct, formatPrice, formatParisTime } from './format';

describe('formatPnl', () => {
  it('prefixe + sur valeur positive', () => {
    expect(formatPnl(42.5)).toBe('+42.50 €');
  });

  it('garde - sur valeur négative', () => {
    expect(formatPnl(-12.34)).toBe('-12.34 €');
  });

  it('pas de signe sur 0', () => {
    expect(formatPnl(0)).toBe('0.00 €');
  });

  it('retourne — sur null/undefined/NaN', () => {
    expect(formatPnl(null)).toBe('—');
    expect(formatPnl(undefined)).toBe('—');
    expect(formatPnl(Number.NaN)).toBe('—');
  });

  it('arrondit à 2 décimales', () => {
    expect(formatPnl(1.234567)).toBe('+1.23 €');
    expect(formatPnl(-9.999)).toBe('-10.00 €');
  });
});

describe('formatPct', () => {
  it('multiplie par 100 et ajoute %', () => {
    expect(formatPct(0.5)).toBe('50.0%');
    expect(formatPct(0.123)).toBe('12.3%');
  });

  it('gère 0 et 1', () => {
    expect(formatPct(0)).toBe('0.0%');
    expect(formatPct(1)).toBe('100.0%');
  });

  it('retourne — sur null/undefined/NaN', () => {
    expect(formatPct(null)).toBe('—');
    expect(formatPct(undefined)).toBe('—');
    expect(formatPct(Number.NaN)).toBe('—');
  });
});

describe('formatPrice', () => {
  it('5 décimales par défaut pour les petits nombres (forex)', () => {
    expect(formatPrice(1.08234)).toBe('1.08234');
  });

  it('2 décimales pour les nombres ≥ 1000 (BTC, indices)', () => {
    expect(formatPrice(50000.1234)).toBe('50000.12');
    expect(formatPrice(2650)).toBe('2650.00');
  });

  it('accepte un nombre de digits custom', () => {
    expect(formatPrice(0.123456, 3)).toBe('0.123');
  });

  it('retourne — sur null/undefined/NaN', () => {
    expect(formatPrice(null)).toBe('—');
    expect(formatPrice(undefined)).toBe('—');
    expect(formatPrice(Number.NaN)).toBe('—');
  });
});

describe('formatParisTime', () => {
  it('retourne un format HH:MM:SS', () => {
    const fixed = new Date('2026-04-21T18:30:45+00:00');
    const result = formatParisTime(fixed);
    // À Paris en avril = UTC+2 (heure d'été) → 20:30:45
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });

  it('utilise l\'heure Paris (UTC+1 ou UTC+2 selon la saison)', () => {
    const utcNoon = new Date('2026-04-21T12:00:00+00:00');
    const result = formatParisTime(utcNoon);
    // 12h UTC en avril = 14h à Paris
    expect(result).toBe('14:00:00');
  });
});
