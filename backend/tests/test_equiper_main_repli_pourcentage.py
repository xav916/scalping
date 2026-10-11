"""Un trade à la main reçoit le MÊME stop que l'automatique.

> Xavier, 2026-10-11 : « si j'ouvre un trade à la main qui n'a ni TP ni SL,
> est-ce que le SL à 13 va se mettre ? »

## ⛔ LA RÉPONSE ÉTAIT NON, et c'était un défaut d'une heure sur l'argent réel

`XAU_SL_FIXE_EUR` sert **deux chemins** qui lui donnent des sens **opposés** :

    chemin AUTOMATIQUE   0 = inerte, c'est `XAU_SL_PCT` qui gouverne
    chemin A LA MAIN     0 = ne pose RIEN  (seule source du stop)

En le passant de 20 à 0 pour donner à Xavier son stop au pourcentage, j'ai
éteint l'équipement des trades à la main. Le journal de production le disait
mot pour mot : « XAU_SL_FIXE_EUR = 0.0, non strictement positif — rien ne sera
posé ».

⛔ **Et le trou était du côté de la PERTE**, le plus mauvais : la protection
exige un stop **existant** pour le resserrer (`sl is None` ⇒ elle s'abstient).
En profit le trade était couvert dès +0,50 € par le traînage ; en perte, rien,
jusqu'à l'appel de marge.
"""
from __future__ import annotations

import pytest

from backend.services import equiper_trades_main as E


@pytest.fixture(autouse=True)
def _arme(monkeypatch):
    monkeypatch.setenv("EQUIPER_TRADES_MAIN", "1")
    monkeypatch.delenv("XAU_SL_FIXE_EUR", raising=False)
    monkeypatch.delenv("XAU_TP_FIXE_EUR", raising=False)
    monkeypatch.setenv("XAU_SL_PCT", "0.35")
    yield


def test_a_zero_le_stop_retombe_sur_le_POURCENTAGE(monkeypatch):
    """⛔ LE DÉFAUT. À 0 le module était muet ; il doit maintenant rendre la
    MÊME distance que le chemin automatique."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    d = E.stop_eur(4195.11, 1.125)
    assert d is not None, "à 0, le module est resté muet — le défaut est revenu"
    assert d == pytest.approx(13.05, abs=0.02), f"attendu ~13,05 €, obtenu {d}"


def test_le_repli_appelle_la_MEME_fonction_que_l_automatique(monkeypatch):
    """🔑 Pas une copie du calcul : l'APPEL. Écrire `prix * 0,35 / 100` ici
    créerait la seconde source de vérité que l'en-tête du module interdit."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    from backend.services.pattern_detector import _distance_sl_or
    for prix in (3500.0, 4195.11, 5000.0):
        attendu = _distance_sl_or(prix) / 1.125
        assert E.stop_eur(prix, 1.125) == pytest.approx(attendu)


def test_un_montant_fixe_PRIME_toujours(monkeypatch):
    """Rétro-compatibilité : si quelqu'un repose 20 €, c'est 20 €."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "20")
    assert E.stop_eur(4195.11, 1.125) == pytest.approx(20.0)
    assert E.stop_eur() == pytest.approx(20.0), "sans prix, le fixe suffit"


@pytest.mark.parametrize("prix,taux", [
    (None, 1.125), (0, 1.125), (4195.11, None), (4195.11, 0), (4195.11, -1),
])
def test_sans_prix_ou_sans_taux_on_ne_DEVINE_rien(monkeypatch, prix, taux):
    """⛔ On ne fabrique pas un stop sur de l'argent réel."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    assert E.stop_eur(prix, taux) is None


def test_aucun_objectif_n_est_pose(monkeypatch):
    """✅ Et celui-là est VOULU : `XAU_TP_FIXE_EUR=0` ⇒ aucun objectif, comme
    sur le chemin automatique depuis `XAU_SANS_OBJECTIF=1`. Le stop suiveur
    est la seule sortie."""
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "0")
    assert E.objectif_eur() is None


def _position(**kw):
    base = {"ticket": 1, "symbol": "XAUUSD", "comment": "a la main",
            "type": "buy", "price_open": 4195.11, "price_current": 4195.11,
            "sl": 0, "tp": 0}
    base.update(kw)
    return base


def test_la_decision_COMPLETE_pose_bien_un_stop_et_AUCUN_objectif(monkeypatch):
    """Le bout en bout : la question exacte de Xavier."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "0")
    d = E.decision(_position(), 1.125)
    assert d is not None, "rien n'est posé sur un trade à la main nu"
    assert d["tp"] is None, "un objectif a été posé alors qu'on n'en veut plus"
    assert d["sl"] is not None
    # un achat : le stop est SOUS l'entrée, a ~13,05 EUR de distance
    distance_eur = (4195.11 - d["sl"]) / 1.125
    assert distance_eur == pytest.approx(13.05, abs=0.03)


def test_un_stop_DEJA_pose_n_est_jamais_touche(monkeypatch):
    """Garde n°2 du module : il COMBLE, il ne REMPLACE pas."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "0")
    d = E.decision(_position(sl=4180.0), 1.125)
    assert d is None or d.get("sl") is None, "un stop choisi a été remplacé"


def test_un_stop_DEJA_FRANCHI_n_est_pas_pose(monkeypatch):
    """Garde n°3 : poser un stop du mauvais côté du cours FERMERAIT la
    position, et fermer n'est pas protéger."""
    monkeypatch.setenv("XAU_SL_FIXE_EUR", "0")
    monkeypatch.setenv("XAU_TP_FIXE_EUR", "0")
    # un achat qui perd deja plus de 13 EUR (≈ 14,7 $)
    d = E.decision(_position(price_current=4195.11 - 20.0), 1.125)
    assert d is not None
    assert d["sl"] is None, "un stop déjà franchi a été posé"
    assert d["alerte"], "le cas n'a pas été signalé"
