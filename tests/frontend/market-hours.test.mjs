import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    MARKETS,
    isForexWeekendClosed,
    computeMarketStatus,
    formatCountdown,
    toParisHHMM,
} from '../../frontend/js/modules/market-hours.js';

const atUTC = (s) => new Date(`${s.replace(' ', 'T')}:00Z`);

test('MARKETS contient les 8 marchés attendus', () => {
    assert.equal(MARKETS.length, 8);
    const ids = MARKETS.map(m => m.id);
    assert.deepEqual(ids, ['sydney','tokyo','london','newyork','crypto','equity','metals','oil']);
});

test('isForexWeekendClosed : samedi fermé toute la journée', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-18 12:00')), true);
});

test('isForexWeekendClosed : dimanche avant 22h UTC fermé', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-19 19:00')), true);
    assert.equal(isForexWeekendClosed(atUTC('2026-04-19 22:00')), false);
});

test('isForexWeekendClosed : vendredi après 22h UTC fermé', () => {
    assert.equal(isForexWeekendClosed(atUTC('2026-04-17 22:30')), true);
    assert.equal(isForexWeekendClosed(atUTC('2026-04-17 21:00')), false);
});

test('computeMarketStatus forex : London ouvert à 10h UTC lundi', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-20 10:00'));
    assert.equal(s.isOpen, true);
});

test('computeMarketStatus forex : London fermé dimanche 19h UTC', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-19 19:00'));
    assert.equal(s.isOpen, false);
});

test('computeMarketStatus crypto : toujours ouvert', () => {
    const crypto = MARKETS.find(m => m.id === 'crypto');
    assert.equal(computeMarketStatus(crypto, atUTC('2026-04-19 19:00')).isOpen, true);
    assert.equal(computeMarketStatus(crypto, atUTC('2026-04-18 03:00')).isOpen, true);
});

test('computeMarketStatus equity (SPX) : ouvert lundi 14h UTC, fermé samedi', () => {
    const eq = MARKETS.find(m => m.id === 'equity');
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-20 14:00')).isOpen, true);
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-20 13:00')).isOpen, false);
    assert.equal(computeMarketStatus(eq, atUTC('2026-04-18 14:00')).isOpen, false);
});

test('computeMarketStatus forex_follow (metals) : ouvert si au moins une session forex', () => {
    const metals = MARKETS.find(m => m.id === 'metals');
    assert.equal(computeMarketStatus(metals, atUTC('2026-04-20 10:00')).isOpen, true);
    assert.equal(computeMarketStatus(metals, atUTC('2026-04-19 19:00')).isOpen, false);
});

test('computeMarketStatus overlap London/NY : isOverlap à 15h UTC', () => {
    const london = MARKETS.find(m => m.id === 'london');
    const s = computeMarketStatus(london, atUTC('2026-04-20 15:00'));
    assert.equal(s.isOverlap, true);
});

test('toParisHHMM : 13:00 UTC → 15:00 Paris en avril (CEST)', () => {
    assert.equal(toParisHHMM(atUTC('2026-04-20 13:00')), '15:00');
});

test('toParisHHMM : 13:00 UTC → 14:00 Paris en janvier (CET)', () => {
    assert.equal(toParisHHMM(atUTC('2026-01-15 13:00')), '14:00');
});

test('formatCountdown : arrondit correctement', () => {
    assert.equal(formatCountdown(0), '0 min');
    assert.equal(formatCountdown(45 * 60 * 1000), '45 min');
    assert.equal(formatCountdown(90 * 60 * 1000), '1h30');
    assert.equal(formatCountdown(2 * 60 * 60 * 1000 + 5 * 60 * 1000), '2h05');
});
