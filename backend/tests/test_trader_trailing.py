"""Tests du trailing stop partagé (backend/services/trader_trailing.py).

Scénarios : désactivé, activation, ratchet one-way, buy vs sell,
expiration conditions, position mal formée.
"""
from __future__ import annotations

import pytest

from backend.services import trader_trailing as tt


PREFIX = "TEST"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        f"{PREFIX}_TRAILING_ENABLED",
        f"{PREFIX}_TRAILING_ACTIVATION_R",
        f"{PREFIX}_TRAILING_DISTANCE_R",
    ):
        monkeypatch.delenv(key, raising=False)


# ══════════════════════════════════════════════════════════════════════
# Désactivé = no-op
# ══════════════════════════════════════════════════════════════════════


def test_desactive_par_defaut():
    pos = {"entry": 100.0, "sl": 95.0, "sl_initial": 95.0, "direction": "buy"}
    assert tt.update_trailing_sl(pos, 110.0, PREFIX) is None


def test_desactive_explicite(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "false")
    pos = {"entry": 100.0, "sl": 95.0, "sl_initial": 95.0, "direction": "buy"}
    assert tt.update_trailing_sl(pos, 110.0, PREFIX) is None


# ══════════════════════════════════════════════════════════════════════
# BUY : activation + ratchet
# ══════════════════════════════════════════════════════════════════════


def test_buy_pas_active_sous_le_seuil(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ACTIVATION_R", "1.0")
    monkeypatch.setenv(f"{PREFIX}_TRAILING_DISTANCE_R", "0.5")
    # Entry 100, SL 95 → R=5. Activation à +5 profit.
    pos = {"entry": 100.0, "sl": 95.0, "sl_initial": 95.0, "direction": "buy"}
    # Prix 104 : profit 4 < 5 → pas d'activation
    assert tt.update_trailing_sl(pos, 104.0, PREFIX) is None


def test_buy_s_active_au_seuil(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ACTIVATION_R", "1.0")
    monkeypatch.setenv(f"{PREFIX}_TRAILING_DISTANCE_R", "0.5")
    pos = {"entry": 100.0, "sl": 95.0, "sl_initial": 95.0, "direction": "buy"}
    # Prix 105 : profit 5 = 1R → activation
    # new_sl = 105 - 0.5*5 = 102.5 (> 95, ratchet)
    assert tt.update_trailing_sl(pos, 105.0, PREFIX) == 102.5


def test_buy_ratchet_one_way_ne_recule_pas(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {"entry": 100.0, "sl": 108.0, "sl_initial": 95.0, "direction": "buy"}
    # SL déjà avancé à 108. Prix 110 : nouveau proposé = 110 - 2.5 = 107.5
    # 107.5 < 108, donc pas de ratchet
    assert tt.update_trailing_sl(pos, 110.0, PREFIX) is None


def test_buy_prix_monte_puis_redescend(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    # Prix monte à 110, puis redescend à 106
    pos = {"entry": 100.0, "sl": 107.5, "sl_initial": 95.0, "direction": "buy"}
    # À 106, profit = 6 ≥ 5 (activation), proposé = 106 - 2.5 = 103.5
    # 103.5 < 107.5 → pas de ratchet (one-way)
    assert tt.update_trailing_sl(pos, 106.0, PREFIX) is None


# ══════════════════════════════════════════════════════════════════════
# SELL : miroir
# ══════════════════════════════════════════════════════════════════════


def test_sell_s_active_au_seuil(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    # Entry 100, SL 105 → R=5. Sell : profit = entry - price.
    pos = {
        "entry": 100.0, "sl": 105.0, "sl_initial": 105.0, "direction": "sell",
    }
    # Prix 95 : profit 5 = 1R → activation
    # new_sl = 95 + 0.5*5 = 97.5 (< 105, ratchet)
    assert tt.update_trailing_sl(pos, 95.0, PREFIX) == 97.5


def test_sell_ratchet_one_way(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {
        "entry": 100.0, "sl": 93.0, "sl_initial": 105.0, "direction": "sell",
    }
    # Prix 95 : proposé = 95 + 2.5 = 97.5 > 93 → pas de ratchet
    assert tt.update_trailing_sl(pos, 95.0, PREFIX) is None


# ══════════════════════════════════════════════════════════════════════
# Position mal formée = fail-silent (None)
# ══════════════════════════════════════════════════════════════════════


def test_sl_egal_entry_renvoie_none(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {
        "entry": 100.0, "sl": 100.0, "sl_initial": 100.0, "direction": "buy",
    }
    assert tt.update_trailing_sl(pos, 105.0, PREFIX) is None


def test_direction_invalide_renvoie_none(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {"entry": 100.0, "sl": 95.0, "sl_initial": 95.0, "direction": "???"}
    assert tt.update_trailing_sl(pos, 110.0, PREFIX) is None


def test_champ_entry_manquant_renvoie_none(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {"sl": 95.0, "sl_initial": 95.0, "direction": "buy"}
    assert tt.update_trailing_sl(pos, 110.0, PREFIX) is None


def test_sl_initial_manquant_utilise_sl_courant(monkeypatch):
    """Fallback : si sl_initial absent, on prend sl comme sl_initial."""
    monkeypatch.setenv(f"{PREFIX}_TRAILING_ENABLED", "true")
    pos = {"entry": 100.0, "sl": 95.0, "direction": "buy"}  # pas de sl_initial
    # Doit marcher avec sl = sl_initial = 95
    assert tt.update_trailing_sl(pos, 105.0, PREFIX) == 102.5
