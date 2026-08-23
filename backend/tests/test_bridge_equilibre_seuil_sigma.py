"""Le seuil d'éligibilité en ÉCARTS-TYPES, pas en R (2026-08-24).

⛔ Le défaut du seuil en R : ce n'est pas sa valeur, c'est son **unité**. Le
même `EQUILIBRE_MARGE_R = 0,40` place le stop à des distances du bruit qui
varient d'un facteur **4,5** selon l'instrument — mesuré sur les positions
réellement ouvertes et 1067 bougies H1 chez le courtier :

    paire      0,40 R vaut     verdict
    EUR/GBP      1,07 σ        confortable
    GBP/USD      0,80 σ        moderé
    GBP/JPY      0,48 σ        exposé
    USD/JPY      0,24 σ        ⛔ c'est du BE 0 %, mesuré à −0,099 R (t=−2,61)

> **Aucune valeur en R ne peut être bonne partout.** On choisirait toujours un
> compromis trop lâche ici et trop serré là. Le seuil en σ supprime
> l'arbitrage au lieu de le trancher.

## Les deux conditions se CUMULENT

Un candidat doit satisfaire **le plus strict des deux** : le plancher en R
(politique de Xavier, 0,40) ET la porte de bruit en σ. Sur EUR/GBP c'est le R
qui mord ; sur USD/JPY c'est le σ.

## ⛔ Volatilité inconnue ⇒ PAS candidat

Le choix qui compte. Se rabattre sur le seuil en R seul serait **fail-open**,
et précisément sur le cas dangereux : USD/JPY, dont le R vaut 0,24 σ. Une
volatilité illisible doit donc **écarter** la position, pas la laisser passer.

Le coût est acceptable : la soupape ne se déclenche pas, donc l'ordre reste
refusé — c'est le côté sûr de l'erreur. Le coût de l'inverse serait de poser
un stop dans le bruit en croyant le contraire.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture(scope="module")
def m():
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _risque_realise(")
    fin = src.index("def _remonter_a_l_equilibre(")
    mod = types.ModuleType("bridge_sigma")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    mod.logger = types.SimpleNamespace(info=lambda *a, **k: None,
                                       warning=lambda *a, **k: None)
    return mod


class _Pos:
    def __init__(self, ticket, symbol, price_open, sl, volume, price_current,
                 type_=0):
        self.ticket, self.symbol = ticket, symbol
        self.price_open, self.sl, self.volume = price_open, sl, volume
        self.price_current, self.type = price_current, type_


class _Info:
    point, trade_tick_value = 0.00001, 1.0


def _specs(_):
    return _Info()


# Achat EUR/USD : entrée 1,10000, stop 1,09500 => R = 0,00500 (50 pips)
def _pos(acquis_prix, ticket=1):
    return _Pos(ticket, "EURUSD", 1.10000, 1.09500, 0.10, 1.10000 + acquis_prix)


# --------------------------------------------------------------------------
# La porte de bruit
# --------------------------------------------------------------------------

def test_sans_seuil_sigma_le_comportement_est_INCHANGE(m):
    """`marge_min_sigma=0` doit rendre exactement l'ancien résultat — sinon on
    changerait le comportement de tous les appelants existants."""
    p = _pos(0.00250)                                    # +0,50 R
    assert len(m._candidats_equilibre([p], _specs, 0.40)) == 1
    assert len(m._candidats_equilibre([p], _specs, 0.40,
                                      sigmas=lambda s: None,
                                      marge_min_sigma=0.0)) == 1


def test_le_sigma_ECARTE_une_position_que_le_R_acceptait(m):
    """Le cas USD/JPY : 0,40 R franchi, mais on est dans le bruit.

    acquis 0,00250 (0,50 R). Avec sigma_jour = 0,00500, ça ne fait que
    0,50 sigma — sous le seuil de 1,0.
    """
    p = _pos(0.00250)
    cands = m._candidats_equilibre([p], _specs, 0.40,
                                   sigmas=lambda s: 0.00500,
                                   marge_min_sigma=1.0)
    assert cands == []


def test_le_R_ECARTE_une_position_que_le_sigma_acceptait(m):
    """Le cas EUR/GBP : peu de bruit, mais le plancher de politique tient.

    acquis 0,00150 (0,30 R) avec sigma_jour = 0,00100 => 1,5 sigma, largement
    au-dessus. Mais 0,30 R < 0,40 R : refusé.
    """
    p = _pos(0.00150)
    cands = m._candidats_equilibre([p], _specs, 0.40,
                                   sigmas=lambda s: 0.00100,
                                   marge_min_sigma=1.0)
    assert cands == [], "le plancher en R doit rester un plancher"


def test_les_DEUX_conditions_satisfaites_rend_candidat(m):
    p = _pos(0.00300)                                    # 0,60 R
    cands = m._candidats_equilibre([p], _specs, 0.40,
                                   sigmas=lambda s: 0.00200,   # 1,5 sigma
                                   marge_min_sigma=1.0)
    assert len(cands) == 1 and cands[0]["ticket"] == 1


def test_le_seuil_sigma_est_INCLUSIF(m):
    """Pile au seuil : accepté. Un seuil annoncé inclusif doit l'être."""
    p = _pos(0.00250)
    cands = m._candidats_equilibre([p], _specs, 0.40,
                                   sigmas=lambda s: 0.00250,   # exactement 1,0
                                   marge_min_sigma=1.0)
    assert len(cands) == 1


# --------------------------------------------------------------------------
# ⛔ Volatilité inconnue : fail-CLOSED
# --------------------------------------------------------------------------

def test_volatilite_inconnue_ECARTE_la_position(m):
    """⛔ Le choix qui compte. Retomber sur le R seul serait fail-open, et
    justement sur l'instrument dangereux."""
    p = _pos(0.00300)                                    # 0,60 R, R-eligible
    assert m._candidats_equilibre([p], _specs, 0.40,
                                  sigmas=lambda s: None,
                                  marge_min_sigma=1.0) == []


def test_volatilite_a_zero_ou_negative_ECARTE_aussi(m):
    """Un sigma nul diviserait par zéro ou rendrait tout éligible."""
    p = _pos(0.00300)
    for mauvais in (0.0, -0.001):
        assert m._candidats_equilibre([p], _specs, 0.40,
                                      sigmas=lambda s: mauvais,
                                      marge_min_sigma=1.0) == []


def test_une_source_de_volatilite_qui_LEVE_ne_casse_pas_l_ordre(m):
    """Appelée sur le chemin d'un ordre : une exception ferait tomber le
    trading pour un calcul d'aide à la décision."""
    def _explose(_):
        raise RuntimeError("MT5 injoignable")
    p = _pos(0.00300)
    assert m._candidats_equilibre([p], _specs, 0.40,
                                  sigmas=_explose,
                                  marge_min_sigma=1.0) == []


# --------------------------------------------------------------------------
# Le sens VENTE
# --------------------------------------------------------------------------

def test_une_VENTE_est_jugee_dans_le_bon_sens(m):
    """Vente à 1,10000, stop 1,10500, prix 1,09700 => acquis 0,00300."""
    v = _Pos(1, "EURUSD", 1.10000, 1.10500, 0.10, 1.09700, type_=1)
    assert len(m._candidats_equilibre([v], _specs, 0.40,
                                      sigmas=lambda s: 0.00200,
                                      marge_min_sigma=1.0)) == 1
    assert m._candidats_equilibre([v], _specs, 0.40,
                                  sigmas=lambda s: 0.00500,
                                  marge_min_sigma=1.0) == []
