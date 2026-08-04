"""Bloc monétaire des pushes Telegram — deux régimes (2026-08-04).

`_estimate_eur_amounts` s'appuie sur `_PIP_VALUE_AT_001_LOT_EUR`, une table
calibrée pour du CFD MT5 en **lot 0,01**. Appliquée à une destination Kraken,
elle produisait sur ETH/USD :

    💵 En euros (estimation, lot 0.01)
    Argent engagé : ~€8 (margin requise)
    Risque max    : −€0.08 si SL touché
    _Demo (×0.10 lot) ≈ ×10 · Live IC Markets (0.02 lot) ≈ ×2_

Trois erreurs d'un coup : montants sans rapport, devise fausse, et une note
sur des lots MT5 qui n'existent pas chez Kraken.

Sur les bridges qui dimensionnent sur leur propre solde, `risk_money` **est**
le risque réel dans la devise du compte. Le gain s'en déduit par le R:R, sans
table intermédiaire.
"""
from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from backend.models.schemas import PatternType
from backend.services import bridge_destinations as bd, sizing
from backend.services import telegram_service as ts


@pytest.fixture(autouse=True)
def _cache_propre():
    sizing._BALANCE_CACHE.clear()
    yield
    sizing._BALANCE_CACHE.clear()


def _setup(pair="ETH/USD", aclass="crypto"):
    return NS(pair=pair, direction=NS(value="sell"),
              pattern=NS(pattern=PatternType.RANGE_BOUNCE_DOWN,
                         confidence=0.72, description="Rejet"),
              confidence_score=68.0, verdict_action="TAKE", verdict_summary=None,
              verdict_reasons=[], verdict_warnings=[], verdict_blockers=[],
              entry_price=1868.0, stop_loss=1876.7, take_profit_1=1852.34,
              take_profit_2=1843.9, risk_pips=8.7, reward_pips_1=15.66,
              reward_pips_2=24.1, risk_reward_1=1.8, risk_reward_2=2.8,
              asset_class=aclass, is_simulated=False, detected_at=None)


def _dest(bridge_type, dest_id, classes):
    return NS(destination_id=dest_id, user_id=None, auto_exec_enabled=True,
              min_confidence=55, allowed_asset_classes=classes,
              bridge_type=bridge_type, bridge_url="", bridge_api_key="",
              allowed_patterns=frozenset(), trading_capital=None)


def _rendu(setup, dests):
    with patch.object(bd, "resolve_destinations", return_value=dests):
        return ts._format_setup(setup)


# --- le régime « solde réel » ---------------------------------------------

def test_kraken_affiche_les_montants_reels():
    sizing._cache_put("admin_kraken", 103.60)
    txt = _rendu(_setup(), [_dest("kraken", "admin_kraken", {"crypto"})])
    assert "Montants réels (USD)" in txt
    assert "103.60 USD" in txt, "le solde du compte doit être cité"


def test_kraken_ne_parle_plus_de_lots_mt5():
    """La mention « Demo ×0,10 lot » n'a aucun sens chez Kraken."""
    sizing._cache_put("admin_kraken", 103.60)
    txt = _rendu(_setup(), [_dest("kraken", "admin_kraken", {"crypto"})])
    assert "lot" not in txt.lower()
    assert "Demo" not in txt and "IC Markets" not in txt


def test_le_risque_correspond_au_sizing_reel():
    sizing._cache_put("admin_kraken", 103.60)
    d = _dest("kraken", "admin_kraken", {"crypto"})
    attendu = sizing.compute_risk_money(_setup(), d)["risk_money"]
    txt = _rendu(_setup(), [d])
    assert f"−{attendu:.2f} USD" in txt


def test_le_gain_se_deduit_du_rr():
    sizing._cache_put("admin_kraken", 103.60)
    d = _dest("kraken", "admin_kraken", {"crypto"})
    s = _setup()
    risque = sizing.compute_risk_money(s, d)["risk_money"]
    txt = _rendu(s, [d])
    assert f"+{risque * s.risk_reward_1:.2f} USD" in txt
    assert f"+{risque * s.risk_reward_2:.2f} USD" in txt


def test_sans_solde_connu_aucun_bloc_montant():
    """Mieux vaut pas de bloc qu'un bloc faux."""
    txt = _rendu(_setup(), [_dest("kraken", "admin_kraken", {"crypto"})])
    assert "Montants réels" not in txt
    assert "En euros" not in txt


# --- le régime MT5 reste intact -------------------------------------------

def test_mt5_garde_l_estimation_en_euros():
    """Régression : le message forex/métaux ne doit pas bouger."""
    txt = _rendu(_setup(pair="XAU/USD", aclass="metal"),
                 [_dest("mt5", "admin_live", {"metal"})])
    assert "En euros (estimation, lot 0.01)" in txt
    assert "Montants réels" not in txt


def test_une_destination_crypto_ne_contamine_pas_le_bloc_mt5():
    """Kraken absent des destinations : on garde l'estimation historique."""
    txt = _rendu(_setup(pair="XAU/USD", aclass="metal"),
                 [_dest("mt5", "admin_live", {"metal"}),
                  _dest("mt5", "admin_legacy", {"metal"})])
    assert "En euros" in txt


# --- cohérence entre le badge broker et les montants ----------------------

def test_le_badge_et_les_montants_parlent_du_meme_trade():
    """Les deux lisent `_executing_destinations` : pas deux vérités."""
    sizing._cache_put("admin_kraken", 103.60)
    txt = _rendu(_setup(), [_dest("kraken", "admin_kraken", {"crypto"})])
    assert "🐙 Kraken Futures" in txt
    assert "Montants réels" in txt


def test_une_destination_qui_nexecute_pas_nest_pas_annoncee():
    """Score sous le seuil : ni badge, ni montants pour cette destination."""
    d = _dest("kraken", "admin_kraken", {"crypto"})
    d.min_confidence = 95
    sizing._cache_put("admin_kraken", 103.60)
    txt = _rendu(_setup(), [d])
    assert "Kraken" not in txt
    assert "Montants réels" not in txt
