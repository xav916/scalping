"""La largeur du traînage indexée sur le SPREAD mesuré.

> Xavier, 2026-10-12 : « dès qu'on passe 0, et dès qu'on passe 0 plus le
> spread, on doit ramener le SL à cette valeur-là. J'ai pas l'impression que
> ça fonctionne. »

✅ **Il avait raison : ça ne fonctionnait pas, parce que ça n'existait pas.**
Le `PROTECTION_PERTE_PLANCHER_SPREAD_K` armé le matin vit côté PERTE ;
`echelle_stop_or` ne lisait le spread nulle part.

## ⚠️ CE QUE LA MESURE DIT, posé ici avant les tests

Banc `3cdd76e`, verdict `dbfb6f4`. 4 115 positions appariées, trade par trade :

    ce qu'etait le trade   production   sa regle    effet
    gagnant   n=2879        +0,823      +0,428     -1 136 EUR
    perdant   n=900         -2,643      -1,438     +1 084 EUR
    net                     -0,0008     +0,0031    t +0,26

⇒ gagnants **−48 %**, pertes **−46 %**, solde **indistinguable de zéro**.
Et au spread RÉEL (22 points), `k=2` donne **0,393 €** contre **0,500 €** en
production : un ajustement de 11 centimes. **On arme pour la justesse du
principe, pas pour un gain promis.** Ces tests vérifient la mécanique, ils ne
prétendent pas à un gain.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def E(monkeypatch):
    import backend.services.echelle_stop_or as mod
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "0.50")
    monkeypatch.delenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", raising=False)
    return importlib.reload(mod)


SPREAD = 0.1965          # le spread REEL mesure le 12/10 : 22 points


# ─── ① Inerte par défaut, au centime ─────────────────────────────────────

def test_inerte_par_defaut(E):
    assert E.trainage_spread_k() is None
    assert E.trainage_eur() == pytest.approx(0.50)
    assert E.palier_atteint(0.39) is None
    assert E.palier_atteint(0.50) == pytest.approx(0.0)
    assert E.palier_atteint(1.00) == pytest.approx(0.50)


def test_le_spread_passe_mais_sans_k_ne_change_RIEN(E):
    """⛔ Transmettre le spread ne doit rien faire tant que k est absent."""
    for pr in (0.10, 0.39, 0.50, 1.00, 30.0):
        assert E.palier_atteint(pr, SPREAD) == E.palier_atteint(pr)


# ─── ② La règle de Xavier, telle qu'il l'a dite ──────────────────────────

def test_le_stop_vaut_ZERO_quand_le_profit_atteint_k_spreads(E, monkeypatch):
    """🔑 LE CŒUR. « dès qu'on passe 0 + le spread, on ramène le SL là. »"""
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    seuil = 2 * SPREAD
    assert E.palier_atteint(seuil - 0.01, SPREAD) is None, "pose trop tot"
    assert E.palier_atteint(seuil, SPREAD) == pytest.approx(0.0, abs=1e-4), (
        "a k x spread de profit le stop doit valoir exactement 0")
    assert E.palier_atteint(seuil + 0.10, SPREAD) == pytest.approx(0.10, abs=1e-4)


def test_le_declencheur_BAISSE_avec_le_spread(E, monkeypatch):
    """Indexer la largeur deplace AUSSI le declencheur — c'est voulu."""
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    # production : rien sous 0,50. Indexe : rien sous 0,393.
    assert E.palier_atteint(0.45, SPREAD) is not None, (
        "a 0,45 EUR la regle indexee doit deja poser (seuil 0,393)")
    monkeypatch.delenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K")
    E = importlib.reload(E)
    assert E.palier_atteint(0.45) is None, "la production ne pose rien a 0,45"


def test_le_stop_suit_SANS_PLAFOND(E, monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    for pr in (1.0, 5.0, 30.0, 41.0):
        # 🔑 tolerance au DEMI-CENTIME : `palier_atteint` arrondit a
        # 2 decimales, parce qu'un stop se pose au centime.
        assert E.palier_atteint(pr, SPREAD) == pytest.approx(
            pr - 2 * SPREAD, abs=0.006)


def test_un_spread_LARGE_eloigne_le_stop(E, monkeypatch):
    """🔑 Tout l'interet : quand le marche se tend, la largeur s'elargit."""
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    calme = E.palier_atteint(2.0, 0.0714)      # 8 points
    tendu = E.palier_atteint(2.0, 0.38)        # la reouverture du dimanche
    assert tendu < calme, f"tendu {tendu} >= calme {calme}"
    assert calme == pytest.approx(2.0 - 0.1428, abs=0.006)


# ─── ③ Les refus, qui comptent autant que le calcul ──────────────────────

@pytest.mark.parametrize("k", ["0.5", "0.99", "0", "-2"])
def test_un_k_SOUS_1_est_REFUSE(E, monkeypatch, k):
    """⛔ A k < 1 le stop se poserait a MOINS d'un spread du cours : il serait
    franchi par le seul rebond bid/ask. « Protection » deviendrait
    « fermeture », et la mesure ne saurait pas les distinguer."""
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", k)
    E = importlib.reload(E)
    assert E.trainage_spread_k() is None
    assert E.trainage_eur(SPREAD) == pytest.approx(0.50), (
        "un k refuse doit rendre la largeur FIXE, pas une largeur indexee")


@pytest.mark.parametrize("brut", ["", "   ", "deux"])
def test_un_k_illisible_retombe_sur_la_largeur_fixe(E, monkeypatch, brut):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", brut)
    E = importlib.reload(E)
    assert E.trainage_eur(SPREAD) == pytest.approx(0.50)


def test_un_spread_ILLISIBLE_retombe_et_le_DIT(E, monkeypatch, caplog):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    with caplog.at_level("WARNING"):
        v = E.trainage_eur(None)
    assert v == pytest.approx(0.50)
    assert any("spread illisible" in r.message for r in caplog.records)


def test_le_stop_reste_toujours_a_k_spreads_DERRIERE_le_cours(E, monkeypatch):
    """La propriete de securite : la distance stop-cours vaut k x spread."""
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    for sp in (0.05, 0.0714, 0.1965, 0.38, 1.40):
        for pr in (2 * sp, 2 * sp + 0.5, 5.0, 30.0):
            v = E.palier_atteint(pr, sp)
            if v is None:
                continue
            assert pr - v == pytest.approx(2 * sp, abs=0.006), (
                f"distance {pr - v:.4f} au lieu de {2 * sp:.4f}")
            assert pr - v >= sp, "le stop est DANS le spread"


# ─── ④ Les gardes qui ont déjà coûté : l'inertie silencieuse ─────────────

def test_le_spread_est_bien_TRANSMIS_par_la_BOUCLE(E):
    """⛔ LE DÉFAUT PAYÉ DEUX FOIS LE MÊME JOUR. Si la boucle ne transmet pas
    le spread, `trainage_spread_k()` trouve son k, ne reçoit rien, retombe sur
    la largeur fixe EN SILENCE : un réglage armé et inerte."""
    import inspect
    from backend.services import echelle_stop_boucle as B
    src = inspect.getsource(B)
    assert "spread_eur=spread" in src, "la boucle ne transmet pas le spread"
    i = src.index("E.decision(")
    assert "_spread_eur(" in src[:i], "le spread n'est pas lu avant l'appel"


def test_la_boucle_ne_lit_le_spread_QUE_si_le_reglage_est_pose(E):
    """Sans le réglage, aucun appel supplémentaire au pont."""
    import inspect
    from backend.services import echelle_stop_boucle as B
    src = inspect.getsource(B)
    assert "if E.trainage_spread_k() is not None else None" in src


def test_le_test_de_MODE_n_appelle_pas_trainage_eur_sans_spread(E):
    """⛔ Sinon `tp_vise_eur` déclencherait l'avertissement de repli à CHAQUE
    passage — un bruit qui ferait perdre de vue les vrais replis."""
    import inspect
    src = inspect.getsource(E.tp_vise_eur)
    assert "trainage_eur()" not in src, (
        "tp_vise_eur appelle encore trainage_eur() sans spread")
    assert "mode_trainage()" in src


def test_mode_trainage_ne_depend_pas_du_spread(E, monkeypatch):
    assert E.mode_trainage() is True
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E2 = importlib.reload(E)
    assert E2.mode_trainage() is True
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_EUR", "")
    E3 = importlib.reload(E2)
    assert E3.mode_trainage() is False


# ─── ⑤ Bout en bout, par `decision()` ────────────────────────────────────

def _position(entree=4187.0, sl=None):
    return {"ticket": 1, "symbol": "XAUUSD", "type": "buy",
            "price_open": entree, "sl": sl, "comment": "scalping-radar"}


def test_decision_bout_en_bout(E, monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_TRAINAGE_SPREAD_K", "2")
    E = importlib.reload(E)
    taux = 1.1198
    entree = 4187.0
    # profit de 0,45 EUR => 0,504 USD de hausse
    courant = entree + 0.45 * taux
    d = E.decision(_position(entree), taux, prix_courant=courant,
                   spread_eur=SPREAD)
    assert d is not None, "la regle indexee doit poser a 0,45 EUR"
    # stop a 0,45 - 0,393 = 0,057 EUR de profit
    attendu = entree + (0.45 - 2 * SPREAD) * taux
    assert d["sl"] == pytest.approx(round(attendu, 2), abs=0.02)
    assert d["sl"] < courant, "stop du mauvais cote du cours"
    # et sans le spread, la production ne pose RIEN a 0,45
    assert E.decision(_position(entree), taux, prix_courant=courant) is None
