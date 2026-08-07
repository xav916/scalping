"""Excursions favorable et adverse maximales (2026-08-07).

Question à laquelle aucune donnée existante ne répondait : **une cible plus
proche aurait-elle été touchée ?** `shadow_setups` n'enregistrait que le prix
de SORTIE, si bien qu'on savait qu'un take-profit n'était jamais atteint sans
pouvoir dire de combien il manquait. Mesuré sur ETH journalier : 0 TP sur 11,
`R:R` figé à 1,80, cibles jusqu'à 24 % du prix.

⚠️ Ce que ces tests verrouillent :
  - le sens (une vente doit rendre une favorable POSITIVE quand le prix baisse) ;
  - la borne de fenêtre au prix de sortie RÉEL, pas au timeout ;
  - `None` quand rien n'est mesurable, jamais `0.0` — « inconnu » ≠ « nul ».
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.schemas import Candle, TradeDirection
from backend.services.backtest_engine import excursions_pct

T0 = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


class _Setup:
    def __init__(self, direction, entry=100.0):
        self.direction = direction
        self.entry_price = entry
        self.stop_loss = 95.0 if direction == TradeDirection.BUY else 105.0
        self.take_profit_1 = 109.0 if direction == TradeDirection.BUY else 91.0
        self.pair = "ETH/USD"


def _c(minute, high, low):
    return Candle(timestamp=T0 + timedelta(minutes=minute), open=100.0,
                  high=high, low=low, close=(high + low) / 2, volume=1.0)


# ── Sens ──────────────────────────────────────────────────────────────

def test_achat_favorable_vers_le_haut():
    bougies = [_c(5, 104.0, 99.0), _c(10, 106.0, 98.0), _c(15, 102.0, 101.0)]
    mfe, mae = excursions_pct(_Setup(TradeDirection.BUY), bougies, T0, T0 + timedelta(minutes=20))
    assert mfe == pytest.approx(6.0), "le plus haut atteint est 106 sur une entree a 100"
    assert mae == pytest.approx(2.0), "le plus bas atteint est 98"


def test_vente_favorable_vers_le_BAS():
    """Le piege de signe : sur une vente, la baisse est FAVORABLE."""
    bougies = [_c(5, 101.0, 96.0), _c(10, 103.0, 94.0)]
    mfe, mae = excursions_pct(_Setup(TradeDirection.SELL), bougies, T0, T0 + timedelta(minutes=20))
    assert mfe == pytest.approx(6.0), "le plus bas atteint est 94, soit +6 % en faveur"
    assert mae == pytest.approx(3.0), "le plus haut atteint est 103, soit 3 % contre"


def test_les_deux_sont_toujours_positives():
    """Comparables directement aux distances du TP et du stop, quel que soit le sens."""
    for direction in (TradeDirection.BUY, TradeDirection.SELL):
        mfe, mae = excursions_pct(_Setup(direction), [_c(5, 103.0, 97.0)],
                                  T0, T0 + timedelta(minutes=10))
        assert mfe >= 0 and mae >= 0, f"{direction} rend une valeur negative"


def test_aucune_excursion_favorable_donne_zero_pas_du_negatif():
    """Un achat qui n'est jamais monte : favorable = 0, pas -2 %."""
    bougies = [_c(5, 98.0, 96.0)]
    mfe, mae = excursions_pct(_Setup(TradeDirection.BUY), bougies, T0, T0 + timedelta(minutes=10))
    assert mfe == pytest.approx(0.0)
    assert mae == pytest.approx(4.0)


# ── Bornes de fenêtre ─────────────────────────────────────────────────

def test_la_fenetre_s_arrete_a_la_SORTIE_REELLE():
    """Une excursion posterieure a la cloture decrirait un trade qui n'existe plus."""
    bougies = [_c(5, 103.0, 99.0), _c(30, 130.0, 98.0)]  # +30 % APRES la sortie
    mfe, _ = excursions_pct(_Setup(TradeDirection.BUY), bougies, T0, T0 + timedelta(minutes=10))
    assert mfe == pytest.approx(3.0), "la bougie a 30 min ne doit pas compter"


def test_les_bougies_avant_l_entree_sont_ignorees():
    avant = Candle(timestamp=T0 - timedelta(minutes=5), open=100.0, high=140.0,
                   low=60.0, close=100.0, volume=1.0)
    mfe, mae = excursions_pct(_Setup(TradeDirection.BUY), [avant, _c(5, 102.0, 99.0)],
                              T0, T0 + timedelta(minutes=10))
    assert mfe == pytest.approx(2.0) and mae == pytest.approx(1.0)


# ── « Inconnu » n'est pas « nul » ─────────────────────────────────────

def test_aucune_bougie_dans_la_fenetre_rend_None():
    mfe, mae = excursions_pct(_Setup(TradeDirection.BUY), [], T0, T0 + timedelta(minutes=10))
    assert mfe is None and mae is None, "0.0 ferait passer un trade non mesure pour un trade plat"


def test_entree_absente_rend_None():
    s = _Setup(TradeDirection.BUY)
    s.entry_price = 0
    assert excursions_pct(s, [_c(5, 103.0, 99.0)], T0, T0 + timedelta(minutes=10)) == (None, None)


# ── Ce à quoi ça sert ─────────────────────────────────────────────────

def test_permet_de_dire_si_une_cible_plus_proche_aurait_ete_touchee():
    """Le cas ETH reel : TP a 13,66 % jamais atteint, mais jusqu'ou est-on alle ?"""
    bougies = [_c(5, 104.2, 99.0), _c(10, 100.5, 98.0)]
    mfe, _ = excursions_pct(_Setup(TradeDirection.BUY), bougies, T0, T0 + timedelta(minutes=20))
    assert mfe == pytest.approx(4.2)
    assert mfe < 13.66, "le TP reel n'aurait pas ete touche"
    assert mfe >= 4.0, "une cible a 4 % l'aurait ete — c'est exactement ce qu'on veut pouvoir dire"
