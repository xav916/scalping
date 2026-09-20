"""L'ecart au hasard est ENREGISTRE — sinon aucun verdict n'est verifiable.

## ⛔ Le defaut que ces tests verrouillent

`_verdict` confronte au plafond `t_vs_hasard`, pas le `t` brut de la cellule.
Seul le `t` brut etait ecrit. La table portait donc le verdict et un nombre
qui ne joue aucun role dedans : le 2026-09-19, une cellule RETENU y affichait
`t = 0,47` contre un `plafond = 3,81` — ce qui ressemble a une contradiction
sans en etre une, parce que le nombre qui a decide n'existait plus.

🔑 Troisieme occurrence du meme defaut : l'horizon (26/08), la chaine (16/09),
l'ecart au hasard (20/09). Ces tests existent pour qu'il n'y ait pas de
quatrieme.

⚠️ Le test qui compte le plus est le DERNIER : il exige que les deux colonnes
portent des valeurs DIFFERENTES. Sans lui, ecrire le `t` brut dans les deux
colonnes passerait tous les autres, et on croirait avoir repare.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import laboratoire_or as labo
from backend.services import reglage_or as rg


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = str(tmp_path / "cellules.db")
    monkeypatch.setattr(rg, "_db", lambda: chemin)
    rg._cache.clear()
    yield chemin
    rg._cache.clear()


def _cellule(**kw):
    c = {"horizon": "5min", "motif": "liquidity_sweep_up", "sens": "buy",
         "n": 149, "r_moyen": 0.086, "t": 0.76, "delta_hasard": 0.27,
         "t_vs_hasard": 4.10, "plafond": 3.81, "verdict": labo.RETENU}
    c.update(kw)
    return c


def _lire(chemin, colonne="t_vs_hasard"):
    with sqlite3.connect(chemin) as c:
        return [r[0] for r in c.execute(
            f"SELECT {colonne} FROM labo_or_cellules ORDER BY id")]


def test_l_ecart_au_hasard_est_ECRIT(base):
    rg.enregistrer({"pair": rg.PAIRE, "cellules": [_cellule()]})
    assert _lire(base) == [4.10]


def test_une_cellule_SANS_ecart_ecrit_NULL_pas_zero(base):
    """⛔ `0.0` serait un ecart NUL — une mesure. `NULL` est son absence."""
    cellule = _cellule()
    del cellule["t_vs_hasard"]
    rg.enregistrer({"pair": rg.PAIRE, "cellules": [cellule]})
    assert _lire(base) == [None]


def test_une_base_SANS_la_colonne_est_MIGREE(base):
    """La production ne se recree pas : elle s'altere, ou elle reste muette."""
    with sqlite3.connect(base) as c:
        c.execute("""CREATE TABLE labo_or_cellules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mesure_le TEXT NOT NULL, pair TEXT NOT NULL, horizon TEXT NOT NULL,
            motif TEXT NOT NULL, sens TEXT NOT NULL, n INTEGER NOT NULL,
            r_moyen REAL, t REAL, delta_hasard REAL, plafond REAL,
            verdict TEXT NOT NULL)""")
        c.execute("""INSERT INTO labo_or_cellules
            (mesure_le, pair, horizon, motif, sens, n, r_moyen, t,
             delta_hasard, plafond, verdict)
            VALUES ('2026-09-18 04:00:00','XAU/USD','5min','bos_up','buy',
                    23,-0.399,-1.35,1.092,3.81,'INSUFFISANT')""")

    rg.enregistrer({"pair": rg.PAIRE, "cellules": [_cellule()]})

    with sqlite3.connect(base) as c:
        colonnes = [r[1] for r in c.execute("PRAGMA table_info(labo_or_cellules)")]
    assert "t_vs_hasard" in colonnes
    # ⚠️ L'ancienne ligne garde NULL : son ecart est PERDU, il ne se recalcule
    # pas sans rejouer la nuit. Une valeur reconstituee mentirait.
    assert _lire(base) == [None, 4.10]


def test_le_t_BRUT_et_l_ecart_au_hasard_sont_DEUX_colonnes(base):
    """⛔ LE CONTROLE NEGATIF. C'est lui qui garantit la reparation.

    Le cas reel du 19/09 : `t` brut a 0,47, sous le plafond, et un ecart au
    hasard au-dessus. Si les deux colonnes portaient la meme valeur, le
    verdict RETENU resterait aussi invraisemblable qu'avant le correctif.
    """
    rg.enregistrer({"pair": rg.PAIRE,
                    "cellules": [_cellule(t=0.47, t_vs_hasard=4.10)]})
    assert _lire(base, "t") == [0.47]
    assert _lire(base, "t_vs_hasard") == [4.10]


def test_un_verdict_RETENU_est_desormais_JUSTIFIABLE_par_la_table(base):
    """Le point de tout l'exercice : la table suffit a refaire le calcul."""
    rg.enregistrer({"pair": rg.PAIRE,
                    "cellules": [_cellule(t=0.47, t_vs_hasard=4.10,
                                          plafond=3.81, r_moyen=0.141)]})
    with sqlite3.connect(base) as c:
        ecart, plafond, r, verdict = c.execute(
            "SELECT t_vs_hasard, plafond, r_moyen, verdict "
            "FROM labo_or_cellules").fetchone()
    assert abs(ecart) >= plafond and ecart > 0 and r > 0
    assert verdict == labo.RETENU
