"""La règle d'arrêt du WTI : 10 ordres OU −30 €, le premier atteint.

## ⛔ POURQUOI ELLE EXISTE

Le motif d'admission signé par Xavier le 2026-10-03, à la réouverture du WTI
sur l'argent réel, se termine par cette phrase :

    ⛔ AUCUNE regle d arret n est posee.

Elle était encore vraie le 05/10 au soir. Le WTI tradait sans limite propre sur
un compte de 608 €, avec pour seul garde-fou le plafond journalier global.

🔑 Ce que la règle change : elle transforme un **pari ouvert** en **expérience
bornée**. Elle ne prétend pas que le WTI va gagner — elle décide d'avance
combien on accepte de payer pour le savoir.

## Ce que les mesures disent du WTI

    banc pré-enregistré : 493 cellules, 0 retenue
    le seul candidat    : tué par la phase, puis +0,48 → −0,49 hors échantillon
    coût à 5 min        : 8 % du risque par trade
    historique réel     : −20,6 % puis −28,1 % sur 30 trades (pf 0,72 puis 0,63)

## ⚠️ LE PIÈGE DU P&L, ET POURQUOI LE COMPTEUR D'ORDRES EXISTE

`sum(pnl)` **ignore les NULL en silence**. Sur ce dépôt, l'argent n'est vérifié
chez le courtier que sur 36,7 % des trades : un total tiré des 100 % est un
total d'air.

⇒ La somme peut donc **sous-estimer** les pertes et déclencher trop tard. C'est
pourquoi le compteur d'ordres est le déclencheur principal : il ne dépend
d'aucune valeur manquante. La couverture est mesurée et annoncée.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import regle_arret_wti as ra


DEPUIS = "2026-10-03T09:47:53+00:00"


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "trades.db"
    with sqlite3.connect(chemin) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, pair TEXT, status TEXT, pnl REAL,
            created_at TEXT, destination_id TEXT)""")
    return chemin


def _trade(chemin, i, pnl=None, status="CLOSED", pair="WTI/USD",
           dest="admin_live", quand=None):
    with sqlite3.connect(chemin) as c:
        c.execute("INSERT INTO personal_trades VALUES (?,?,?,?,?,?)",
                  (i, pair, status, pnl,
                   quand or f"2026-10-03T1{i % 10}:00:00+00:00", dest))


# ─── Le relevé ──────────────────────────────────────────────────────────────

def test_compte_les_ordres_et_la_somme_VERIFIEE(base):
    for i in range(3):
        _trade(base, i, pnl=-2.0)
    _trade(base, 9, pnl=None)          # argent NON verifie
    m = ra.releve(base, depuis=DEPUIS)
    assert m["ordres"] == 4
    assert m["pnl"] == pytest.approx(-6.0)
    assert m["sans_pnl"] == 1, "le trade sans montant doit etre COMPTE a part"


def test_la_couverture_du_PNL_est_annoncee(base):
    """⛔ `sum()` ignore les NULL en silence. Un total tire des 100 % serait un
    total d'air : on dit toujours sur combien il porte."""
    for i in range(3):
        _trade(base, i, pnl=-1.0)
    for i in range(3, 10):
        _trade(base, i, pnl=None)
    m = ra.releve(base, depuis=DEPUIS)
    assert m["ordres"] == 10
    assert m["sans_pnl"] == 7
    assert m["couverture"] == pytest.approx(0.3, abs=1e-6)


def test_n_a_cure_des_AUTRES_paires_et_des_autres_destinations(base):
    _trade(base, 1, pnl=-100.0, pair="XAU/USD")
    _trade(base, 2, pnl=-100.0, dest="admin_legacy")
    _trade(base, 3, pnl=-1.0)
    m = ra.releve(base, depuis=DEPUIS)
    assert m["ordres"] == 1
    assert m["pnl"] == pytest.approx(-1.0)


def test_ignore_ce_qui_PRECEDE_la_reouverture(base):
    """⛔ La fenetre part de la REOUVERTURE. Compter l'historique d'aout
    declencherait la regle avant le premier trade de l'experience."""
    _trade(base, 1, pnl=-50.0, quand="2026-08-04T10:00:00+00:00")
    _trade(base, 2, pnl=-1.0)
    m = ra.releve(base, depuis=DEPUIS)
    assert m["ordres"] == 1
    assert m["pnl"] == pytest.approx(-1.0)


def test_une_base_INJOIGNABLE_rend_None(tmp_path):
    """Trois etats, jamais deux : « je n'ai pas pu regarder » n'est pas
    « rien a signaler »."""
    assert ra.releve(tmp_path / "absente.db", depuis=DEPUIS) is None


# ─── Le verdict ─────────────────────────────────────────────────────────────

def test_dix_ordres_DECLENCHENT():
    v = ra.verdict({"ordres": 10, "pnl": +50.0, "sans_pnl": 0, "couverture": 1.0})
    assert v["arreter"] is True
    assert "10" in v["motif"]


def test_neuf_ordres_ne_declenchent_pas():
    v = ra.verdict({"ordres": 9, "pnl": -5.0, "sans_pnl": 0, "couverture": 1.0})
    assert v["arreter"] is False


def test_moins_trente_euros_DECLENCHENT_meme_a_deux_ordres():
    v = ra.verdict({"ordres": 2, "pnl": -30.0, "sans_pnl": 0, "couverture": 1.0})
    assert v["arreter"] is True
    assert "30" in v["motif"]


def test_un_gain_ne_declenche_jamais_par_l_argent():
    v = ra.verdict({"ordres": 3, "pnl": +100.0, "sans_pnl": 0, "couverture": 1.0})
    assert v["arreter"] is False


def test_le_motif_DIT_la_couverture_quand_elle_est_partielle():
    """⚠️ Un arret decide sur une somme incomplete doit le dire : sinon on
    croit avoir mesure 30 € de pertes alors qu'on en a mesure une partie."""
    v = ra.verdict({"ordres": 10, "pnl": -12.0, "sans_pnl": 6, "couverture": 0.4})
    assert v["arreter"] is True
    assert "40" in v["motif"] or "0,4" in v["motif"] or "6" in v["motif"]


def test_un_releve_ABSENT_n_arrete_RIEN():
    """⛔ Une panne de lecture ne doit pas fermer une paire : ce serait agir
    sur une mesure qu'on n'a pas."""
    v = ra.verdict(None)
    assert v["arreter"] is False
    assert "pas" in v["motif"].lower() or "aucun" in v["motif"].lower()


# ─── Les seuils sont ceux demandes ──────────────────────────────────────────

def test_les_seuils_sont_bien_DIX_et_MOINS_TRENTE():
    assert ra.MAX_ORDRES == 10
    assert ra.MAX_PERTE_EUR == -30.0


def test_les_seuils_se_changent_SANS_redeploiement(monkeypatch):
    monkeypatch.setattr(ra, "MAX_ORDRES", 3)
    v = ra.verdict({"ordres": 3, "pnl": 0.0, "sans_pnl": 0, "couverture": 1.0})
    assert v["arreter"] is True
