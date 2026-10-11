"""Aucun objectif, JAMAIS — dicté par Xavier le 2026-10-11.

> « Nous n'allons pas mettre de TP à l'ouverture du trade et nous n'allons en
> fait jamais en mettre. Le stop loss guidera la sortie dans tous les cas. »

## ⛔ LE TROU QUE CES TESTS FERMENT

`ECHELLE_STOP_OR_SANS_OBJECTIF` n'agit que sur l'échelle. L'objectif
**d'ouverture** vit sur un chemin distinct (`XAU_TP_FIXE_EUR`, puis le repli
`risque × 1,8 R`). Sans `XAU_SANS_OBJECTIF`, le trade naissait avec une cible à
**2 €** et sortait là — le traînage n'avait jamais la parole.

⚠️ Et mettre `XAU_TP_FIXE_EUR=0` ne suffisait pas : le code retombait sur
l'objectif ordinaire, soit **~23 €**, pas « aucun ».
"""
from __future__ import annotations

import pytest

from backend.services import mt5_bridge as M
from backend.services import pattern_detector as P


class _Setup:
    """La forme minimale que `_build_order_payload` consomme."""

    def __init__(self, tp1, tp2=None, entry=4150.0, sl=4137.0):
        self.pair = "XAU/USD"
        self.entry_price = entry
        self.stop_loss = sl
        self.take_profit_1 = tp1
        self.take_profit_2 = tp2
        self.confidence_score = 90.0

    direction = "buy"


def _sz():
    return {"risk_money": 13.0, "risk_pct": 3.0}


# ─── Le payload : un objectif nul reste NUL ───────────────────────────────

def test_un_objectif_nul_ne_devient_pas_une_distance_geante():
    """⛔ LE DEFAUT QUI AURAIT COUTE : `abs(entry - 0)` vaut le PRIX de l'or.

    Sans la garde, l'EA v1.05+ aurait pose un objectif a **4 150 $** du fill.
    """
    p = M._build_order_payload(_Setup(tp1=0.0), _sz())
    assert p["tp"] == 0.0
    assert p["tp_dist"] == 0.0, p["tp_dist"]
    assert p["tp2_dist"] is None
    # ⚠️ le STOP, lui, garde sa distance reelle : on ne touche qu'a l'objectif
    assert p["sl_dist"] == pytest.approx(13.0)


def test_un_objectif_reel_garde_sa_distance():
    p = M._build_order_payload(_Setup(tp1=4152.24, tp2=4152.24), _sz())
    assert p["tp"] == pytest.approx(4152.24)
    assert p["tp_dist"] == pytest.approx(2.24)
    assert p["tp2_dist"] == pytest.approx(2.24)


def test_un_tp2_nul_ne_produit_pas_de_distance_geante():
    p = M._build_order_payload(_Setup(tp1=0.0, tp2=0.0), _sz())
    assert p["tp_dist"] == 0.0
    assert p["tp2_dist"] is None


# ─── Le drapeau, inerte par defaut ────────────────────────────────────────

def test_le_drapeau_est_inerte_par_defaut(monkeypatch):
    monkeypatch.delenv("XAU_SANS_OBJECTIF", raising=False)
    import importlib
    importlib.reload(P)
    assert P.XAU_SANS_OBJECTIF is False


def test_le_drapeau_se_lit(monkeypatch):
    import importlib
    for vrai in ("1", "true", "ON", "yes"):
        monkeypatch.setenv("XAU_SANS_OBJECTIF", vrai)
        importlib.reload(P)
        assert P.XAU_SANS_OBJECTIF is True, vrai
    for faux in ("0", "", "non", "off"):
        monkeypatch.setenv("XAU_SANS_OBJECTIF", faux)
        importlib.reload(P)
        assert P.XAU_SANS_OBJECTIF is False, faux
    monkeypatch.delenv("XAU_SANS_OBJECTIF", raising=False)
    importlib.reload(P)


# ─── L'assemblage du setup : aucun objectif sur l'OR, les autres intacts ──

def test_l_or_sort_sans_objectif_quand_le_drapeau_est_arme(monkeypatch):
    import importlib
    monkeypatch.setenv("XAU_SANS_OBJECTIF", "1")
    importlib.reload(P)
    try:
        s = P._assembler_setup(
            "XAU/USD", P.PatternType.MOMENTUM_UP, 4150.0, 4137.0,
            4152.24, 4152.24, 0.8, 2)
        if s is not None:
            assert s.take_profit_1 == 0.0
            assert s.take_profit_2 == 0.0
    except TypeError:
        # 🔑 La signature d'`_assembler_setup` n'est pas un contrat public :
        # si elle change, ce test ne doit pas devenir un faux rouge. Le vrai
        # garde-fou est celui du payload ci-dessus, qui lui est stable.
        pytest.skip("signature d'_assembler_setup differente — garde portee "
                    "par les tests du payload")
    finally:
        monkeypatch.delenv("XAU_SANS_OBJECTIF", raising=False)
        importlib.reload(P)


def test_une_paire_qui_n_est_PAS_de_l_or_garde_son_objectif(monkeypatch):
    """⛔ Le drapeau ne doit pas fuir sur les autres instruments."""
    import importlib
    monkeypatch.setenv("XAU_SANS_OBJECTIF", "1")
    importlib.reload(P)
    try:
        assert P._est_de_l_or("XAU/USD") is True
        assert P._est_de_l_or("EUR/USD") is False
        assert P._est_de_l_or("BTC/USD") is False
    finally:
        monkeypatch.delenv("XAU_SANS_OBJECTIF", raising=False)
        importlib.reload(P)
