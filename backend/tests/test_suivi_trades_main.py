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


# ─── ④ Les bornes PROPRES aux trades à la main (13 € / 20 €) ────────────

@pytest.fixture
def EQB(monkeypatch):
    """Comme `EQ`, mais sans aucun réglage de bornes posé."""
    import backend.services.equiper_trades_main as mod
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    for k in ("MAIN_SL_FIXE_EUR", "MAIN_TP_FIXE_EUR",
              "XAU_SL_FIXE_EUR", "XAU_TP_FIXE_EUR"):
        monkeypatch.delenv(k, raising=False)
    return importlib.reload(mod)


def test_sans_reglage_le_comportement_d_avant(EQB):
    """Stop au POURCENTAGE (0,35 %) et aucun objectif — l'existant."""
    assert EQB.stop_eur(4180.0, 1.1198) == pytest.approx(13.065, abs=0.01)
    assert EQB.objectif_eur() is None


def test_les_bornes_de_Xavier_13_et_20(EQB, monkeypatch):
    """🔑 Sa demande du 2026-10-13, mot pour mot : « l'objectif de base 20 €
    et le stop loss à 13 € »."""
    monkeypatch.setenv("MAIN_SL_FIXE_EUR", "13")
    monkeypatch.setenv("MAIN_TP_FIXE_EUR", "20")
    E = importlib.reload(EQB)
    assert E.stop_eur(4180.0, 1.1198) == pytest.approx(13.0)
    assert E.objectif_eur() == pytest.approx(20.0)


def test_le_reglage_de_la_MAIN_ne_touche_PAS_le_chemin_AUTOMATIQUE(EQB, monkeypatch):
    """⛔ LA RAISON D'ÊTRE DE CES DEUX NOMS.

    `XAU_SL_FIXE_EUR` et `XAU_TP_FIXE_EUR` sont lus AUSSI par
    `pattern_detector`, donc par le robot. Les poser à 13 et 20 aurait donné
    au ROBOT un stop fixe et un objectif de 20 € — en défaisant en silence
    deux décisions que Xavier a prises le 11/10 (stop au pourcentage, « plus
    d'objectif du tout »).

    ⚠️ Et c'est la même variable qui a déjà coûté une heure d'argent réel ce
    jour-là : `0` vaut « inerte » d'un côté et « ne pose rien » de l'autre.
    """
    monkeypatch.setenv("MAIN_SL_FIXE_EUR", "13")
    monkeypatch.setenv("MAIN_TP_FIXE_EUR", "20")
    importlib.reload(EQB)
    import backend.services.pattern_detector as PD
    PD = importlib.reload(PD)
    assert PD.XAU_SL_FIXE_EUR == 0.0, "le robot a herite d'un stop fixe"
    assert PD.XAU_TP_FIXE_EUR == 0.0, "le robot a herite d'un objectif"
    # et sa regle du 0,35 % est intacte
    assert PD._distance_sl_or(4180.0) == pytest.approx(14.63, abs=0.01)


def test_le_reglage_PARTAGE_reste_le_repli(EQB, monkeypatch):
    """Absent côté main ⇒ on retombe sur le partagé, à l'identique."""
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "7")
    E = importlib.reload(EQB)
    assert E.objectif_eur() == pytest.approx(7.0), "le repli ne marche plus"
    monkeypatch.setenv("MAIN_TP_FIXE_EUR", "20")
    E = importlib.reload(E)
    assert E.objectif_eur() == pytest.approx(20.0), "le propre ne PRIME pas"


@pytest.mark.parametrize("brut", ["zero", "-5", "treize"])
def test_un_reglage_de_main_ILLISIBLE_rend_MUET(EQB, monkeypatch, brut):
    """⛔ Illisible ≠ absent. Quelqu'un a voulu poser une valeur et s'est
    trompé : retomber en silence masquerait sa faute."""
    monkeypatch.setenv("MAIN_SL_FIXE_EUR", brut)
    E = importlib.reload(EQB)
    assert E.stop_eur(4180.0, 1.1198) is None


def test_bout_en_bout_un_trade_a_la_main_recoit_13_et_20(EQB, monkeypatch):
    monkeypatch.setenv("MAIN_SL_FIXE_EUR", "13")
    monkeypatch.setenv("MAIN_TP_FIXE_EUR", "20")
    E = importlib.reload(EQB)
    taux, entree = 1.1198, 4180.0
    d = E.decision(_main(sl=None), taux)
    assert d is not None
    assert d["sl"] == pytest.approx(entree - 13.0 * taux, abs=0.02)
    assert d["tp"] == pytest.approx(entree + 20.0 * taux, abs=0.02)


def test_une_borne_DEJA_POSEE_n_est_PAS_remplacee(EQB, monkeypatch):
    """🔑 « Après, je me laisse la liberté de les modifier à la main. »
    Si Xavier déplace son stop ou son objectif, l'équipeur ne doit PAS le
    réécrire au passage suivant."""
    monkeypatch.setenv("MAIN_SL_FIXE_EUR", "13")
    monkeypatch.setenv("MAIN_TP_FIXE_EUR", "20")
    E = importlib.reload(EQB)
    p = _main(sl=4160.0)
    p["tp"] = 4210.0
    d = E.decision(p, 1.1198)
    assert d is None or (not d.get("sl") and not d.get("tp")), (
        f"l'equipeur reecrit des bornes deja posees : {d}")
