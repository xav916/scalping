"""Journalisation shadow V1 des paires en état PAUSED (2026-08-05).

Contexte : une paire passe en PAUSED (pair_admission_controller) après avoir
saigné en réel. Elle ne trade plus pendant `PAUSE_COOL_OFF_DAYS` (14 jours),
mais tant qu'elle n'était pas OBSERVED ni dans
`SHADOW_V1_UNOBSERVED_ASSET_CLASSES`, `log_v1_shadows_for_tracked_pairs` ne
journalisait aucun setup virtuel pour elle : à l'issue du cool-off, la
condition de retour (battre une entrée aléatoire, mesurée sur les trades
shadow) n'a aucune donnée sur laquelle s'appuyer.

Ce fichier verrouille le nouveau comportement : une paire en état PAUSED est
désormais journalisée, au même titre qu'une paire OBSERVED — sans toucher au
réglage `SHADOW_V1_UNOBSERVED_ASSET_CLASSES` (classes d'actif) ni au filtre
de confiance en amont, et sans élargir la garde à n'importe quel état.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import shadow_v1
from backend.services import shadow_v2_core_long as shadow


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shadow_v1_paused_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)
    # Forcer le réglage de classes d'actif hors admission à vide : ce test ne
    # doit pas dépendre de la crypto pour prouver que PAUSED est journalisé.
    monkeypatch.setattr(shadow_v1, "SHADOW_V1_UNOBSERVED_ASSET_CLASSES", [])
    shadow.ensure_schema()
    return db_path


def _setup(pair, direction="buy", entry=1.08, sl=1.075, tp=1.09):
    return SimpleNamespace(
        pair=pair,
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=None,
        pattern=None,
    )


def _rows(db_path, pair):
    with sqlite3.connect(db_path) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(
            "SELECT * FROM shadow_setups WHERE pair = ?", (pair,)
        ).fetchall()]


CYCLE = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


# ─── 1. Paire PAUSED → désormais journalisée ───────────────────────────────


def test_paire_paused_est_desormais_journalisee(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_PAUSED)

    setups = [_setup("EUR/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 1
    assert counts["skipped_not_tracked"] == 0
    assert len(_rows(temp_db, "EUR/USD")) == 1


# ─── 2. Paire OBSERVED continue d'être journalisée exactement comme avant ──


def test_paire_observed_continue_detre_journalisee(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_OBSERVED)

    setups = [_setup("GBP/USD", "sell", entry=1.25, sl=1.255, tp=1.24)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 1
    assert counts["skipped_not_tracked"] == 0
    assert len(_rows(temp_db, "GBP/USD")) == 1


# ─── 3. Ni PAUSED, ni OBSERVED, ni classe suivie → toujours pas journalisée ─


@pytest.mark.parametrize("autre_etat_nom", ["STATE_DEMOTED", "STATE_TELEGRAM", "STATE_AUTO_EXEC"])
def test_paire_dans_un_autre_etat_nest_pas_journalisee(temp_db, monkeypatch, autre_etat_nom):
    from backend.services import pair_admission_controller as pac

    autre_etat = getattr(pac, autre_etat_nom)
    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: autre_etat)

    setups = [_setup("USD/JPY", "buy", entry=150.0, sl=149.5, tp=151.0)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)

    assert counts["logged"] == 0
    assert counts["skipped_not_tracked"] == 1
    assert _rows(temp_db, "USD/JPY") == []


# ─── 4. Les lignes produites pour une paire en pause portent les champs attendus


def test_ligne_paused_porte_les_champs_attendus(temp_db, monkeypatch):
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_PAUSED)

    setups = [_setup("XAU/USD", "buy", entry=2400.0, sl=2390.0, tp=2420.0)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(setups, cycle_at=CYCLE)
    assert counts["logged"] == 1

    rows = _rows(temp_db, "XAU/USD")
    assert len(rows) == 1
    row = rows[0]

    assert row["system_id"] == shadow_v1.system_id_for("XAU/USD", "buy")
    assert row["pair"] == "XAU/USD"
    assert row["direction"] == "buy"
    assert row["timeframe"] == shadow_v1.V1_TIMEFRAME
    assert row["entry_price"] == pytest.approx(2400.0)
    assert row["stop_loss"] == pytest.approx(2390.0)
    assert row["take_profit_1"] == pytest.approx(2420.0)
    assert row["risk_pct"] == pytest.approx((2400.0 - 2390.0) / 2400.0)
    assert row["rr"] == pytest.approx((2420.0 - 2400.0) / (2400.0 - 2390.0))
    assert row["sizing_capital_eur"] == pytest.approx(shadow_v1.DEFAULT_CAPITAL_EUR)
    assert row["sizing_risk_pct"] == pytest.approx(shadow_v1.DEFAULT_RISK_PCT)
    assert row["outcome"] is None
    assert row["cycle_at"] == CYCLE.isoformat()
    assert row["bar_timestamp"] == shadow_v1._bar_timestamp(CYCLE)
