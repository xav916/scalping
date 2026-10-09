"""L'objectif SUIT le prix : toujours 2 € d'écart devant.

Règle dictée par Xavier le 2026-10-09 :

> « Je veux qu'il y ait toujours 2 euros d'écart quand on se rapproche du TP :
> quand 1 euro est atteint, update SL:1 et TP:3 ; si 1,5 est atteint, SL:1,5 et
> TP:3,5, etc. »

## 🔑 CE QUE LA MESURE A CHANGÉ DANS SA DEMANDE

Son texte posait `SL = niveau atteint`, soit un stop **collé au cours**. Or le
spread de l'or valait **0,151 €** au moment de la mesure (bid 4196,47 / ask
4196,64) et le courtier n'impose **aucune** distance minimale
(`trade_stops_level = 0`) : le stop serait franchi par le spread seul, au
premier recul.

**Décision de Xavier après cette mesure : 0,25 € de marge sous le stop.**

⇒ `SL = niveau − 0,25` et `TP = niveau + 2,00`. L'écart entre le **cours** et
le TP reste donc bien de **2,00 €**, ce qu'il demandait.

🔑 **Et le côté SL ne change pas d'un centime** : `niveau − 0,25` est
*exactement* l'échelle déjà en production (1,00→0,75 ; 1,50→1,25 ; 1,75→1,50 ;
2,00→1,75). Seul le TP est nouveau.

## ⛔ Ce que ces tests épinglent

1. le TP vaut **palier + 2 €**, et l'écart au cours reste de 2 € ;
2. ⛔ **pas de TP sans palier** : sous +1 € on ne touche à rien. Déplacer
   l'objectif d'une position qui n'a rien prouvé serait gratuit ;
3. le TP est rendu en **PRIX**, comme le stop — la leçon du défaut de signe du
   matin : une distance se lit dans les deux sens, un prix non ;
4. ⚠️ l'écart est **réglable**, et un réglage illisible retombe sur 2 € plutôt
   que sur zéro — un écart nul collerait l'objectif au cours.
"""
from __future__ import annotations

import importlib
import os

import pytest

TAUX = 1.1235
MARQUE = "scalping-radar"


@pytest.fixture()
def E(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS",
                       "1.0:0.75,1.5:1.25,1.75:1.5,2.0:1.75")
    monkeypatch.delenv("ECHELLE_TP_ECART_EUR", raising=False)
    from backend.services import echelle_stop_or as mod
    importlib.reload(mod)
    return mod


def _pos(profit_eur, sens="buy", entree=4190.0, stop_eur=20.0,
         tp=0.0, comment=MARQUE + "-2026-10-09"):
    signe = 1 if sens == "buy" else -1
    return {"ticket": 1, "symbol": "XAUUSD", "type": sens,
            "price_open": entree,
            "price_current": entree + signe * profit_eur * TAUX,
            "sl": entree - signe * stop_eur * TAUX, "tp": tp,
            "volume": 0.01, "comment": comment}


# ─────────────────────────────────────────────────────────────────────────
# 1. Le TP suit, à 2 € devant
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profit,palier,tp_attendu", [
    (1.00, 0.75, 3.00),
    (1.50, 1.25, 3.50),
    (1.75, 1.50, 3.75),
    (2.00, 1.75, 4.00),
    (2.40, 1.75, 4.00),      # palier le plus haut franchi = 2,00
])
def test_le_tp_vaut_le_PALIER_plus_deux_euros(E, profit, palier, tp_attendu):
    """🔑 Ses deux exemples : +1 € => TP 3 € ; +1,5 € => TP 3,5 €."""
    assert E.tp_vise_eur(profit) == pytest.approx(tp_attendu)


def test_le_PRIX_du_tp_pour_un_ACHAT_est_au_dessus_du_cours(E):
    pos = _pos(1.00)
    d = E.decision(pos, TAUX)

    assert d is not None
    # TP a +3,00 € de l'entree.
    assert d["tp"] == pytest.approx(4190.0 + 3.00 * TAUX, abs=0.01)
    assert d["tp"] > pos["price_current"]
    # …et le stop, lui, est a +0,75 € : inchange par rapport a l'echelle.
    assert d["sl"] == pytest.approx(4190.0 + 0.75 * TAUX, abs=0.01)


def test_le_PRIX_du_tp_pour_une_VENTE_est_en_dessous_du_cours(E):
    pos = _pos(1.00, sens="sell")
    d = E.decision(pos, TAUX)

    assert d["tp"] == pytest.approx(4190.0 - 3.00 * TAUX, abs=0.01)
    assert d["tp"] < pos["price_current"]
    assert d["sl"] == pytest.approx(4190.0 - 0.75 * TAUX, abs=0.01)


def test_l_ecart_entre_le_COURS_et_le_tp_reste_de_deux_euros(E):
    """⛔ C'est la formulation EXACTE de Xavier : << toujours 2 euros d'ecart
    quand on se rapproche du TP >>."""
    for profit in (1.00, 1.50, 1.75, 2.00):
        d = E.decision(_pos(profit), TAUX)
        cours = 4190.0 + profit * TAUX
        ecart_eur = (d["tp"] - cours) / TAUX
        # Le TP suit le PALIER, donc l'ecart au cours vaut 2 € au palier et
        # se reduit entre deux paliers — c'est la granularite assumee.
        assert 1.0 <= ecart_eur <= 2.05, (profit, ecart_eur)
    # Au palier exact, l'ecart vaut bien 2,00 €.
    d = E.decision(_pos(1.50), TAUX)
    assert (d["tp"] - (4190.0 + 1.50 * TAUX)) / TAUX == pytest.approx(2.0, abs=0.01)


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Les refus
# ─────────────────────────────────────────────────────────────────────────

def test_SOUS_le_premier_palier_aucun_tp_n_est_pose(E):
    """⛔ Deplacer l'objectif d'une position qui n'a rien prouve serait
    gratuit : sous +1 €, on ne touche a RIEN."""
    assert E.tp_vise_eur(0.99) is None
    assert E.decision(_pos(0.99), TAUX) is None


def test_une_position_A_LA_MAIN_n_est_pas_touchee(E):
    assert E.decision(_pos(1.50, comment=""), TAUX) is None


def test_sans_taux_aucun_tp(E):
    """⛔ Sans le taux, les euros sont inconvertibles."""
    assert E.decision(_pos(1.50), 0) is None


# ─────────────────────────────────────────────────────────────────────────
# 3. L'écart est réglable, et son repli est SÛR
# ─────────────────────────────────────────────────────────────────────────

def test_l_ecart_est_reglable(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:0.75")
    monkeypatch.setenv("ECHELLE_TP_ECART_EUR", "3.5")
    from backend.services import echelle_stop_or as mod
    importlib.reload(mod)

    assert mod.tp_vise_eur(1.00) == pytest.approx(4.50)   # 1,00 + 3,50


@pytest.mark.parametrize("mauvais", ["zero", "", "-1", "0"])
def test_un_ecart_ILLISIBLE_ou_NUL_retombe_sur_deux_euros(monkeypatch, mauvais):
    """⚠️ Un ecart nul collerait l'objectif au cours : le trade sortirait
    instantanement. Le repli vaut donc 2 €, jamais zero."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:0.75")
    monkeypatch.setenv("ECHELLE_TP_ECART_EUR", mauvais)
    from backend.services import echelle_stop_or as mod
    importlib.reload(mod)

    assert mod.tp_vise_eur(1.00) == pytest.approx(3.00)   # 1,00 + 2,00


# ─────────────────────────────────────────────────────────────────────────
# 4. La boucle TRANSMET le TP
# ─────────────────────────────────────────────────────────────────────────

def test_la_boucle_envoie_le_tp_absolu():
    """⛔ Sans cela le TP serait calcule et jamais pose — exactement le defaut
    de l'echelle ce matin, qui calculait juste et n'appliquait rien."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "services"
           / "echelle_stop_boucle.py").read_text(encoding="utf-8")

    assert "tp_absolu" in src, "la boucle ne transmet pas le TP"
    # …et elle le prend de la DECISION, pas d'un calcul en double.
    assert 'd.get("tp")' in src or 'd["tp"]' in src
