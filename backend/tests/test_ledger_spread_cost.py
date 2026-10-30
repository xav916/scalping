"""`spread_cost` : mesuré, ou NULL. Jamais estimé (2026-10-30).

Le ledger a une règle unique — « un champ inconnu vaut NULL, jamais 0 ». Ce
champ valait `None` pour tout le monde, et son commentaire disait pourquoi :
le courtier intègre le spread au prix d'exécution, donc il n'est pas
séparable a posteriori… **à moins d'avoir le bid et le ask de l'instant**.
`ticks_courtier.db` les a, pour l'or, depuis le 21/09.

Ces tests gardent les deux refus qui empêchent la réparation de devenir une
fabrication : pas d'hypothèse de classe dans un registre, et pas de moyenne
du magasin à la place du tick du trade.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import cout_execution as C
from backend.services import trade_ledger as L


def _ligne(**surcharges):
    """Une ligne de `personal_trades` suffisante pour `_spread`."""
    base = {"pair": "XAU/USD", "entry_price": 4129.01, "stop_loss": 4107.31,
            "created_at": "2026-10-15T12:00:30", "size_lot": 0.01}
    base.update(surcharges)
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cols = ", ".join(base)
    c.execute("CREATE TABLE t (%s)" % ", ".join("%s" % k for k in base))
    c.execute("INSERT INTO t (%s) VALUES (%s)"
              % (cols, ", ".join("?" * len(base))), tuple(base.values()))
    return c.execute("SELECT * FROM t").fetchone()


@pytest.fixture()
def mesure(monkeypatch):
    """Force `cout_execution` à rendre une mesure d'instant."""
    monkeypatch.setattr(L, "_cout_spread", lambda *a, **k: C.Cout(
        0.0000450, "tick_instant", "temoin"))


@pytest.fixture()
def hypothese(monkeypatch):
    monkeypatch.setattr(L, "_cout_spread", lambda *a, **k: C.Cout(
        0.0002, "hypothese_classe", "classe=crypto -- HYPOTHESE"))


# --- le cas qui marche ----------------------------------------------------

def test_un_tick_d_instant_donne_un_cout(mesure):
    """21,70 $ de stop, 0,186 $ de spread => 0,856 % du risque.

    Avec un risque de 20 €, le coût doit valoir ~0,171 € — l'ordre de
    grandeur mesuré sur les 410 trades réels (médiane 0,176 €)."""
    out = L._spread(_ligne(), risque=20.0)
    assert out["src_spread"] == "tick_courtier"
    attendu = 20.0 * (0.0000450 * 4129.01) / abs(4129.01 - 4107.31)
    assert out["spread_cost"] == pytest.approx(attendu)
    assert out["spread_cost"] == pytest.approx(0.171, abs=0.01)


def test_le_cout_est_PROPORTIONNEL_au_risque(mesure):
    """Il se déduit du risque : doubler l'un double l'autre. C'est ce qui
    évite de recalculer volume, taille de contrat et change."""
    a = L._spread(_ligne(), risque=10.0)["spread_cost"]
    b = L._spread(_ligne(), risque=20.0)["spread_cost"]
    assert b == pytest.approx(2 * a)


def test_un_stop_plus_LARGE_coute_moins_en_part_de_risque(mesure):
    """Le spread est un coût FIXE en prix : plus le stop est loin, moins il
    pèse en fraction de R. C'est l'arithmétique qui condamne un TP serré."""
    serre = L._spread(_ligne(stop_loss=4127.01), risque=20.0)["spread_cost"]
    large = L._spread(_ligne(stop_loss=4029.01), risque=20.0)["spread_cost"]
    assert serre > large


# --- les refus, qui font la sûreté ----------------------------------------

def test_une_HYPOTHESE_de_classe_est_REFUSEE(hypothese):
    """⛔ LE test qui compte. Un registre qui porte une valeur déclarée la
    rend indistinguable d'une mesure dans toute requête ultérieure."""
    out = L._spread(_ligne(pair="BTC/USD"), risque=20.0)
    assert out == {"spread_cost": None, "src_spread": None}


def test_une_MOYENNE_du_magasin_est_REFUSEE(monkeypatch):
    """`tick_moyen` est une mesure, mais pas celle de CE trade."""
    monkeypatch.setattr(L, "_cout_spread", lambda *a, **k: C.Cout(
        0.0000446, "tick_moyen", "moyenne du magasin"))
    assert L._spread(_ligne(), risque=20.0)["spread_cost"] is None


def test_un_risque_NULL_rend_un_cout_NULL(mesure):
    """La chaîne échoue fermée : sans risque en euros, pas de conversion."""
    assert L._spread(_ligne(), risque=None)["spread_cost"] is None


@pytest.mark.parametrize("manque", [
    {"entry_price": None}, {"stop_loss": None}, {"created_at": None},
    {"entry_price": 0}, {"stop_loss": 4129.01},   # stop == entree
])
def test_une_donnee_manquante_rend_NULL_sans_lever(mesure, manque):
    out = L._spread(_ligne(**manque), risque=20.0)
    assert out == {"spread_cost": None, "src_spread": None}


# --- le contrat de colonnes -----------------------------------------------

def test_src_spread_est_declaree_dans_la_provenance():
    """`COLONNES_CAHIER` vient du document d'audit et ne bouge pas ; la
    provenance est le point d'extension, et le module le dit."""
    assert "src_spread" in L.COLONNES_PROVENANCE
    assert "src_spread" not in L.COLONNES_CAHIER
    assert "spread_cost" in L.COLONNES_CAHIER


def test_spread_cost_est_un_REEL_dans_le_schema():
    assert "spread_cost" in L._REELS
