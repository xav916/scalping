"""Le laboratoire doit savoir dire combien de ses trades ont été soldés de FORCE.

Pré-inscription : `docs/predictions/2026-11-01_retour-moyenne-hors-echantillon.md`,
dont la condition de validité du rejeu exige `non_resolus_pct < 5`.

⛔ **Sans cette information, un R n'est pas interprétable.** Un trade qui n'a
touché ni son stop ni son objectif en `MAX_BOUGIES_TENUE` bougies est soldé à
la clôture courante : son R mesure alors une **liquidation administrative**, pas
une issue de marché. Si ces trades dominent une cellule, sa moyenne décrit la
dérive du prix pendant la fenêtre de tenue et rien d'autre.

⚠️ Changement **purement additif** : une clé de plus dans le dict de trade, un
compteur de plus par cellule. Aucune décision du laboratoire n'en dépend, et la
sonde nocturne rend les mêmes verdicts qu'avant.
"""
from __future__ import annotations

import pytest

from backend.services import laboratoire_or as labo


def _b(h, l, c, o=None):
    """Une bougie au format du laboratoire (dicts `{t,o,h,l,c}`)."""
    return {"t": None, "o": o if o is not None else c, "h": h, "l": l, "c": c}


class _Setup:
    """Le minimum que `rejouer_cellule` lit d'un setup."""
    def __init__(self, entree, stop, cible):
        self.entry_price = entree
        self.stop_loss = stop
        self.take_profit_1 = cible


def _releve(indice, setup, motif="mean_reversion_up", sens="buy"):
    """⚠️ `_nom_motif` et `_sens` lisent le setup — on les contourne en
    posant directement les attributs qu'ils consultent."""
    setup.pattern = type("P", (), {"pattern": type("E", (), {"value": motif})()})()
    setup.direction = type("D", (), {"value": sens})()
    return {indice: [setup]}


def test_un_trade_qui_touche_son_STOP_est_resolu():
    # Entrée 100, stop 99 (risque 1 % du prix, au-dessus du placebo), cible 102.
    bougies = [_b(100.5, 99.5, 100) for _ in range(labo.FENETRE + 1)]
    bougies.append(_b(100.2, 98.0, 98.5))          # le stop est pris
    bougies += [_b(100.5, 99.5, 100) for _ in range(5)]

    s = _Setup(100.0, 99.0, 102.0)
    trades = labo.rejouer_cellule(bougies, _releve(labo.FENETRE, s),
                                  "mean_reversion_up", "buy", spread=0.0)
    assert len(trades) == 1
    assert trades[0]["resolu"] is True


def test_un_trade_qui_touche_sa_CIBLE_est_resolu():
    bougies = [_b(100.5, 99.5, 100) for _ in range(labo.FENETRE + 1)]
    bougies.append(_b(102.5, 100.0, 102.2))        # la cible est prise
    bougies += [_b(100.5, 99.5, 100) for _ in range(5)]

    s = _Setup(100.0, 99.0, 102.0)
    trades = labo.rejouer_cellule(bougies, _releve(labo.FENETRE, s),
                                  "mean_reversion_up", "buy", spread=0.0)
    assert len(trades) == 1
    assert trades[0]["resolu"] is True


def test_un_trade_SOLDE_DE_FORCE_est_marque_NON_resolu():
    """⛔ Le cas qui rend un R trompeur : ni stop ni cible, jamais.

    Le prix reste coincé entre les deux niveaux jusqu'à la fin des bougies
    disponibles. Le laboratoire solde à la dernière clôture — ce R ne décrit
    aucune issue de marché.
    """
    bougies = [_b(100.4, 99.6, 100) for _ in range(labo.FENETRE + 40)]
    s = _Setup(100.0, 99.0, 102.0)
    trades = labo.rejouer_cellule(bougies, _releve(labo.FENETRE, s),
                                  "mean_reversion_up", "buy", spread=0.0)
    assert len(trades) == 1
    assert trades[0]["resolu"] is False


def test_mesurer_agrege_le_compte_des_NON_resolus():
    """La cellule doit porter `non_resolus`, sinon le banc ne peut pas calculer
    la part pré-inscrite — une barre sans instrument, la faute du 31/10."""
    import inspect
    src = inspect.getsource(labo.mesurer)
    assert "non_resolus" in src, (
        "`mesurer` n'agrege pas les trades non resolus : la condition de "
        "validite `non_resolus_pct < 5` serait incalculable")


def test_le_champ_resolu_n_est_JAMAIS_absent():
    """⛔ Un `.get(\"resolu\", True)` chez l'appelant transformerait une absence
    en « tout va bien ». La cle doit toujours etre la."""
    bougies = [_b(100.5, 99.5, 100) for _ in range(labo.FENETRE + 1)]
    bougies.append(_b(100.2, 98.0, 98.5))
    s = _Setup(100.0, 99.0, 102.0)
    trades = labo.rejouer_cellule(bougies, _releve(labo.FENETRE, s),
                                  "mean_reversion_up", "buy", spread=0.0)
    for t in trades:
        assert "resolu" in t
        assert isinstance(t["resolu"], bool)
