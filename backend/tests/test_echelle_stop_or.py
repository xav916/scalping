"""L'échelle de stop sur l'or — dictée par Xavier le 2026-10-09.

> « lorsqu'on passe à 1 euro, mettre le stop loss à 0,75. Lorsqu'on passe à
> 1,25, mettre le stop loss à 1. Quand on passe à 1,75, mettre le stop loss à
> 1,50. Lorsqu'on passe à 2, le trade est fermé parce qu'on a atteint le TP. »

## ⛔ CE QUE LA MESURE DIT, et que ces tests ne contredisent pas

Le pont garde ce mécanisme à **1,0 R de coussin**, et son commentaire chiffre
pourquoi : *« un stop posé à l'équilibre sous ce coussin est collé au marché et
se fait sortir par le bruit — la mécanique exacte qui a coûté −0,329 R par
trade sur l'or »*. Le palier de +1 € vaut **0,0500 R** : vingt fois sous ce
garde-fou.

⇒ Ces tests ne disent pas que l'idée est bonne. Ils garantissent qu'elle fait
**exactement** ce qui a été dicté, qu'elle est **inerte par défaut**, et qu'elle
ne touche pas aux positions qui ne sont pas les nôtres.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import echelle_stop_or as E

_SRC = Path(__file__).resolve().parents[2] / "backend" / "services" / "echelle_stop_or.py"
TAUX = 1.1235


def _pos(**kw):
    base = {"symbol": "XAUUSD", "type": "buy", "price_open": 4200.0,
            "price_current": 4200.0, "sl": 0.0, "ticket": 1,
            "comment": "scalping-radar-2026-10-09"}
    base.update(kw)
    return base


# ─── ⛔ INERTE PAR DÉFAUT ─────────────────────────────────────────────────

def test_le_defaut_du_SOURCE_est_INERTE():
    """⛔ Épingle le défaut dans le FICHIER. Un `1` arrivé là par inadvertance
    modifierait les stops de l'argent réel au prochain déploiement."""
    ligne = next(l for l in _SRC.read_text(encoding="utf-8").splitlines()
                 if "ECHELLE_STOP_OR" in l and "getenv" in l)
    assert '"0"' in ligne, f"le defaut n'est plus inerte : {ligne!r}"


def test_desarme_il_ne_decide_RIEN(monkeypatch):
    monkeypatch.delenv("ECHELLE_STOP_OR", raising=False)
    assert E.arme() is False
    assert E.decision(_pos(price_current=4201.3), TAUX) is None


# ─── L'échelle est EXACTEMENT celle qui a été dictée ─────────────────────

def test_l_echelle_dictee_est_celle_du_source():
    assert E.ECHELLE_DEFAUT == ((1.00, 0.75), (1.25, 1.00), (1.75, 1.50))


@pytest.mark.parametrize("profit,attendu", [
    (0.00, None), (0.50, None), (0.99, None),
    (1.00, 0.75), (1.10, 0.75), (1.24, 0.75),
    (1.25, 1.00), (1.50, 1.00), (1.74, 1.00),
    (1.75, 1.50), (1.90, 1.50), (2.50, 1.50),
])
def test_chaque_palier_rend_le_stop_dicte(profit, attendu):
    assert E.palier_atteint(profit) == attendu


def test_on_prend_le_palier_le_PLUS_HAUT_franchi():
    """🔑 À +1,80 € le stop va à +1,50 €, pas à +0,75 €. Prendre le premier
    palier franchi au lieu du dernier annulerait toute l'échelle."""
    assert E.palier_atteint(1.80) == 1.50


# ─── La conversion en prix ───────────────────────────────────────────────

def test_le_stop_en_prix_pour_un_ACHAT(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    # +1,00 € atteint -> stop a +0,75 € = +0,843 $ au-dessus de l'entree
    sl = E.stop_vise(4200.0, "buy", 1.00, TAUX)
    assert sl == pytest.approx(4200.0 + 0.75 * TAUX)


def test_le_stop_en_prix_pour_une_VENTE(monkeypatch):
    """⚠️ Le signe : pour une vente, le profit est SOUS l'entrée."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    sl = E.stop_vise(4200.0, "sell", 1.00, TAUX)
    assert sl == pytest.approx(4200.0 - 0.75 * TAUX)


def test_taux_ILLISIBLE_rend_None_et_pas_un_stop_devine():
    for mauvais in (0.0, None, -1.0):
        assert E.stop_vise(4200.0, "buy", 1.5, mauvais) is None


# ─── 🔑 LE CLIQUET ───────────────────────────────────────────────────────

def test_le_stop_ne_REDESCEND_jamais_sur_un_achat(monkeypatch):
    """🔑 Sans cette garde, un sondage pendant un repli ferait redescendre le
    stop — l'inverse exact d'une protection."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    deja = 4200.0 + 1.50 * TAUX          # stop deja au palier du haut
    d = E.decision(_pos(price_current=4200.0 + 1.10 * TAUX, sl=deja), TAUX)
    assert d is None, f"le stop allait redescendre : {d}"


def test_le_stop_ne_REDESCEND_jamais_sur_une_vente(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    deja = 4200.0 - 1.50 * TAUX
    d = E.decision(_pos(type="sell",
                        price_current=4200.0 - 1.10 * TAUX, sl=deja), TAUX)
    assert d is None


def test_il_MONTE_bien_quand_le_palier_progresse(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    deja = 4200.0 + 0.75 * TAUX
    d = E.decision(_pos(price_current=4200.0 + 1.80 * TAUX, sl=deja), TAUX)
    assert d is not None
    assert d["palier"] == 1.50
    assert d["sl"] == pytest.approx(round(4200.0 + 1.50 * TAUX, 2))


def test_un_stop_ABSENT_est_accepte(monkeypatch):
    """⚠️ Une position nue (sl=0) doit pouvoir recevoir son premier stop."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    d = E.decision(_pos(price_current=4200.0 + 1.10 * TAUX, sl=0.0), TAUX)
    assert d is not None and d["palier"] == 0.75


# ─── ⛔ LA PORTÉE : nos positions SEULEMENT ──────────────────────────────

def test_il_NE_TOUCHE_PAS_une_position_ouverte_A_LA_MAIN(monkeypatch):
    """⛔ LE test de portée. Une position du terminal MT5 ne porte pas notre
    marque : elle n'est pas à nous, et modifier le stop de Xavier sans qu'il
    l'ait demandé serait une intervention sur SON trade."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    for com in ("", None, "autre chose"):
        d = E.decision(_pos(price_current=4200.0 + 1.80 * TAUX, comment=com),
                       TAUX)
        assert d is None, f"il a touche une position a la main ({com!r})"


def test_il_NE_TOUCHE_PAS_une_autre_paire(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    for sym in ("EURUSD", "XAGUSD", "BTCUSD"):
        d = E.decision(_pos(symbol=sym, price_current=4200.0 + 1.80 * TAUX),
                       TAUX)
        assert d is None, f"il a touche {sym}"


def test_l_argent_XAG_n_est_PAS_de_l_or(monkeypatch):
    """⚠️ `XAG` contient un `A` et un `G` : un test de sous-chaîne mal écrit
    l'aurait pris pour de l'or."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    assert E.decision(_pos(symbol="XAGUSD",
                           price_current=4200.0 + 1.80 * TAUX), TAUX) is None


# ─── Les données aberrantes ──────────────────────────────────────────────

def test_un_stop_du_MAUVAIS_COTE_est_refuse(monkeypatch):
    """⛔ Un stop au-dessus du prix sur un achat serait refusé par le courtier
    et masquerait un défaut de signe derrière une erreur réseau."""
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    # profit enorme mais prix courant incoherent : le stop vise depasserait
    d = E.decision(_pos(price_current=4200.0 + 0.10), TAUX)
    assert d is None


def test_une_position_ILLISIBLE_ne_fait_pas_tomber(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    for mauvaise in ({}, {"symbol": "XAUUSD"},
                     _pos(price_open=0), _pos(price_open="abc"),
                     _pos(type="autre")):
        assert E.decision(mauvaise, TAUX) is None


# ─── Le réglage des paliers ──────────────────────────────────────────────

def test_des_paliers_SURCHARGES_sont_lus(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "0.5:0.25,1.0:0.8")
    assert E.echelle() == ((0.5, 0.25), (1.0, 0.8))


def test_un_reglage_ILLISIBLE_retombe_sur_l_echelle_DICTEE(monkeypatch):
    """⛔ Une échelle vide serait silencieusement inerte alors que le drapeau
    est armé — le pire des deux mondes."""
    for mauvais in ("n'importe quoi", "1.0", "1.0:", ":0.5", ""):
        monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", mauvais)
        assert E.echelle() == E.ECHELLE_DEFAUT


def test_un_palier_INCOHERENT_est_refuse(monkeypatch):
    """⚠️ `1.0:1.5` placerait le stop AU-DESSUS du profit atteint : il serait
    déjà dépassé au moment où on le pose."""
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:1.5")
    assert E.echelle() == E.ECHELLE_DEFAUT
