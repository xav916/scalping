"""Poser un stop sur un trade à la main, SANS le suivre ensuite.

> Xavier, 2026-10-13 : « pour les trades lancés à la main, je ne veux pas
> avoir le SL qui va s'updater. »

🔑 **DEUX CHOSES ÉTAIENT CONFONDUES DANS `concerne()`** :
  - **POSER** un stop sur une position qui n'en a pas (`equiper_trades_main`) ;
  - le **SUIVRE** ensuite (l'échelle côté gain, la protection côté perte).

Il voulait couper le second sans perdre le premier. Sans cette séparation il
aurait fallu `EQUIPER_TRADES_MAIN=0`, qui laisse **nue** une position ouverte
sans stop — et le 09/10, **40 de ses 43 trades** du terminal n'avaient ni stop
ni objectif, ses trois pires faisant **−41,72 €** à eux seuls.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def EQ(monkeypatch):
    import backend.services.equiper_trades_main as mod
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.delenv("EQUIPER_TRADES_MAIN_SUIVI", raising=False)
    return importlib.reload(mod)


def _main(sl=None):
    """Une position d'or ouverte A LA MAIN : pas de marque du radar."""
    return {"ticket": 7, "symbol": "XAUUSD", "type": "buy",
            "price_open": 4180.0, "price_current": 4182.0,
            "sl": sl, "tp": None, "comment": "MANUEL-TERM"}


def _radar(sl=None):
    return {"ticket": 8, "symbol": "XAUUSD", "type": "buy",
            "price_open": 4180.0, "price_current": 4182.0,
            "sl": sl, "tp": None, "comment": "scalping-radar"}


# ─── ① Inerte par défaut : le comportement d'avant, à l'identique ───────

def test_le_suivi_est_ARME_par_defaut(EQ):
    """⛔ Un réglage absent ne doit jamais changer la façon dont l'argent réel
    est protégé."""
    assert EQ.suivi_arme() is True
    assert EQ.concerne_suivi(_main()) is True


@pytest.mark.parametrize("brut", ["1", "true", "oui", "ON", "yes"])
def test_les_valeurs_qui_ARMENT(EQ, monkeypatch, brut):
    monkeypatch.setenv("EQUIPER_TRADES_MAIN_SUIVI", brut)
    assert importlib.reload(EQ).suivi_arme() is True


@pytest.mark.parametrize("brut", ["0", "false", "non", "", "   ", "nimporte"])
def test_les_valeurs_qui_DESARMENT(EQ, monkeypatch, brut):
    """🔑 Tout ce qui n'est pas explicitement vrai désarme — SAUF l'absence,
    testée plus haut. Un réglage illisible coupe le suivi plutôt que de le
    laisser courir sur une intention qu'on n'a pas comprise."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN_SUIVI", brut)
    assert importlib.reload(EQ).suivi_arme() is False


# ─── ② LE CŒUR : poser oui, suivre non ──────────────────────────────────

def test_desarme_on_POSE_encore_le_stop_initial(EQ, monkeypatch):
    """🔑 LA SÉPARATION. C'est tout l'intérêt du réglage : une position
    ouverte sans stop en reçoit un, et ensuite on n'y touche plus."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN_SUIVI", "0")
    E = importlib.reload(EQ)
    assert E.concerne(_main()) is True, (
        "l'equipement initial ne doit PAS etre coupe")
    d = E.decision(_main(sl=None), 1.1198)
    assert d is not None, "une position nue doit encore recevoir un stop"
    assert d.get("sl"), "le stop initial n'est plus pose"


def test_desarme_le_SUIVI_est_REFUSE(EQ, monkeypatch):
    monkeypatch.setenv("EQUIPER_TRADES_MAIN_SUIVI", "0")
    E = importlib.reload(EQ)
    assert E.concerne_suivi(_main()) is False
    assert E.concerne_suivi(_main(sl=4165.0)) is False


def test_le_reglage_ne_touche_PAS_les_trades_du_RADAR(EQ, monkeypatch):
    """⛔ Il porte sur les trades A LA MAIN. Les positions du radar portent sa
    marque et ne passent pas par `concerne` du tout — les couper aussi serait
    un effet de bord silencieux."""
    monkeypatch.setenv("EQUIPER_TRADES_MAIN_SUIVI", "0")
    E = importlib.reload(EQ)
    assert E.est_du_radar(_radar()) is True
    # une position du radar n'est jamais << concernee >> par l'equipeur :
    # c'est l'echelle qui la suit directement, sans passer par ce garde.
    assert E.concerne(_radar()) is False
    assert E.concerne_suivi(_radar()) is False


# ─── ③ Les DEUX suiveurs lisent bien le nouveau garde ───────────────────

def test_l_ECHELLE_lit_concerne_suivi(EQ):
    """⛔ Si l'échelle lisait encore `concerne()`, le réglage serait armé et
    INERTE sur le côté gain."""
    import inspect
    from backend.services import echelle_stop_or as E
    src = inspect.getsource(E)
    assert "_eq.concerne_suivi(position)" in src, (
        "l'echelle lit encore concerne() : le reglage serait inerte")
    assert "_eq.concerne(position)" not in src.replace(
        "_eq.concerne_suivi(position)", "")


def test_la_PROTECTION_des_pertes_lit_concerne_suivi(EQ):
    """⛔ Et c'est le suiveur qui compte aujourd'hui : l'échelle est désarmée
    (`ECHELLE_STOP_OR=0`), donc la protection est la SEULE qui bougerait
    encore le stop d'un trade à la main."""
    import pathlib
    src = pathlib.Path("scripts/protection_perte_or.py").read_text(
        encoding="utf-8")
    assert "_eq.concerne_suivi(position)" in src, (
        "la protection lit encore concerne() : le reglage serait inerte "
        "LA OU IL COMPTE LE PLUS")


def test_l_equipement_initial_lit_concerne_TOUT_COURT(EQ):
    """🔑 La contrepartie : si l'équipement se mettait à lire `concerne_suivi`,
    désarmer le suivi laisserait les positions NUES — exactement ce que la
    séparation existe pour éviter."""
    import inspect
    src = inspect.getsource(EQ.decision)
    assert "if not concerne(position):" in src
    assert "concerne_suivi" not in src, (
        "l'equipement initial dependrait du suivi : une position nue "
        "resterait nue")
