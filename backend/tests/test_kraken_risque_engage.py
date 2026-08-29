"""Plafond par le RISQUE ENGAGE sur Kraken (2026-08-29).

Kraken n'avait AUCUNE porte de risque cumule : seulement une perte journaliere
a 3 % et un compteur de positions a 10. Or un compteur traite toutes les
positions comme equivalentes alors qu'elles ne le sont pas — exactement le
constat qui avait fait poser cette porte cote MT5 le 20/08.

## ⛔ Sur Kraken, le stop n'est PAS un attribut de la position

C'est un **ordre conditionnel independant** (`reduceOnly`, `orderType: stop`).
`/openpositions` ne dit donc rien du risque : il faut le joindre a
`/openorders`. Une position et son stop peuvent diverger sans que rien ne le
signale — c'est ainsi qu'une position peut tourner des jours sans protection.

## Ce que ces tests verrouillent

1. ⛔ **Une position sans ordre stop rend `None`, jamais `0.0`** : nue = risque
   *infini*, pas risque *nul*. Les confondre laisserait passer precisement ce
   qu'on veut interdire.
2. ⛔ Seuls les ordres `reduceOnly` de type stop comptent — un ordre d'entree
   en attente sur le meme symbole n'est pas une protection.
3. ⛔ Un stop AU-DELA de l'entree ne peut plus rien perdre : son risque vaut
   VRAIMENT zero. Zero mesure et zero faute de mesure ne sont pas le meme zero.
4. Une position nue **bloque toute nouvelle ouverture**, comme cote MT5.
5. Le sens (long/short) est respecte.
"""
from __future__ import annotations

import pathlib
import types

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "kraken-bridge" / "bridge.py"


@pytest.fixture(scope="module")
def m():
    """Charge les fonctions de risque, sans le module entier (il importe des
    dependances reseau et lit des variables d'environnement)."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def _stops_par_symbole(")
    fin = src.index("def _protection_par_symbole(")
    mod = types.ModuleType("kraken_risque")
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


def _ordre(symbole="PF_XBTUSD", type_="stop", prix=60000.0, reduce=True):
    return {"symbol": symbole, "orderType": type_, "stopPrice": prix,
            "reduceOnly": reduce}


def _pos(symbole="PF_XBTUSD", side="long", entree=64000.0, taille=0.01):
    return {"symbol": symbole, "side": side, "price": entree, "size": taille}


# ── La jointure position <-> ordre stop ───────────────────────────────────

def test_un_stop_reduceOnly_est_retenu(m):
    assert m._stops_par_symbole([_ordre()]) == {"PF_XBTUSD": 60000.0}


def test_un_ordre_d_ENTREE_n_est_PAS_une_protection(m):
    """⛔ Sans le filtre `reduceOnly`, on annoncerait protegee une position qui
    ne l'est pas."""
    assert m._stops_par_symbole([_ordre(reduce=False)]) == {}


def test_un_TAKE_PROFIT_n_est_pas_un_stop(m):
    """Il borne le gain, pas la perte."""
    assert m._stops_par_symbole([_ordre(type_="take_profit")]) == {}


def test_un_prix_de_stop_illisible_est_ecarte(m):
    assert m._stops_par_symbole([_ordre(prix=None)]) == {}
    assert m._stops_par_symbole([_ordre(prix="bof")]) == {}


# ── Le risque d'une position ──────────────────────────────────────────────

def test_un_LONG_risque_jusqu_a_son_stop(m):
    """64 000 -> 60 000 sur 0,01 BTC = 40 USD."""
    r = m._risque_position_kraken(_pos(), {"PF_XBTUSD": 60000.0})
    assert r == pytest.approx(40.0)


def test_un_SHORT_est_mesure_dans_le_bon_sens(m):
    r = m._risque_position_kraken(_pos(side="short", entree=60000.0),
                                  {"PF_XBTUSD": 64000.0})
    assert r == pytest.approx(40.0)


def test_une_position_SANS_stop_rend_None_PAS_zero(m):
    """⛔ LE test central. Nue = risque infini, pas risque nul."""
    assert m._risque_position_kraken(_pos(), {}) is None


def test_un_stop_AU_DELA_de_l_entree_ne_risque_plus_RIEN(m):
    """Un stop qui verrouille un gain ne peut plus perdre : zero MESURE."""
    r = m._risque_position_kraken(_pos(), {"PF_XBTUSD": 65000.0})
    assert r == 0.0


def test_des_donnees_illisibles_rendent_None(m):
    assert m._risque_position_kraken({"symbol": "X"}, {"X": 1.0}) is None
    assert m._risque_position_kraken(_pos(entree=0.0), {"PF_XBTUSD": 1.0}) is None


# ── La somme ──────────────────────────────────────────────────────────────

def test_la_somme_des_risques(m):
    positions = [_pos(), _pos("PF_ETHUSD", entree=3000.0, taille=1.0)]
    stops = {"PF_XBTUSD": 60000.0, "PF_ETHUSD": 2900.0}
    total, nus = m._risque_engage_kraken(positions, stops)
    assert nus == []
    assert total == pytest.approx(140.0)


def test_une_position_nue_est_rendue_A_PART(m):
    total, nus = m._risque_engage_kraken(
        [_pos(), _pos("PF_ETHUSD")], {"PF_XBTUSD": 60000.0})
    assert nus == ["PF_ETHUSD"]
    assert total == pytest.approx(40.0)


# ── Le controle ───────────────────────────────────────────────────────────

def test_sous_le_plafond_ca_passe(m):
    ok, _ = m._controle_risque_engage_kraken(40.0, [], 20.0, 1000.0, 50.0)
    assert ok is True


def test_au_dessus_du_plafond_c_est_refuse(m):
    ok, raison = m._controle_risque_engage_kraken(400.0, [], 200.0, 1000.0, 50.0)
    assert ok is False
    assert "Risque engage" in raison and "500.00" in raison


def test_une_position_NUE_bloque_toute_ouverture(m):
    """⛔ Son risque n'etant pas borne, aucun total n'a de sens tant qu'elle
    est la. C'est volontaire, et c'est la meme regle que cote MT5."""
    ok, raison = m._controle_risque_engage_kraken(0.0, ["PF_ETHUSD"], 10.0,
                                                  1000.0, 50.0)
    assert ok is False and "sans stop" in raison


def test_equity_inconnue_refuse_plutot_que_deviner(m):
    for equity in (None, 0.0, -5.0):
        ok, raison = m._controle_risque_engage_kraken(10.0, [], 10.0, equity, 50.0)
        assert ok is False and "Equity" in raison


def test_risque_du_nouvel_ordre_non_mesurable_refuse(m):
    ok, raison = m._controle_risque_engage_kraken(10.0, [], None, 1000.0, 50.0)
    assert ok is False and "non mesurable" in raison


def test_plafond_a_zero_DESARME_la_porte(m):
    """0 = comportement d'avant : seuls le drawdown et le compteur agissent."""
    ok, _ = m._controle_risque_engage_kraken(9999.0, ["nue"], None, 1000.0, 0.0)
    assert ok is True


def test_le_plafond_grandit_avec_le_capital(m):
    """50 % de 1 000 laisse passer ce que 50 % de 100 refuse."""
    assert m._controle_risque_engage_kraken(400.0, [], 90.0, 1000.0, 50.0)[0] is True
    assert m._controle_risque_engage_kraken(400.0, [], 90.0, 100.0, 50.0)[0] is False


# ── Le reglage, et sa lisibilite ──────────────────────────────────────────

def test_le_defaut_est_50_pct():
    """⚠️ 50 % est une DECISION, pas une mesure : la moitie du compte si tous
    les stops tombent, soit deux fois et demie le total des comptes MT5."""
    import re
    src = _SRC.read_text(encoding="utf-8")
    trouve = re.search(
        r'MAX_RISQUE_ENGAGE_PCT = float\(os\.getenv\("KRAKEN_MAX_RISQUE_ENGAGE_PCT",\s*"([\d.]+)"\)\)',
        src)
    assert trouve and float(trouve.group(1)) == 50.0


def test_le_plafond_est_publie_dans_health():
    """⛔ Un garde-fou qu'on ne peut pas lire est un garde-fou dont on ne sait
    jamais s'il s'applique."""
    src = _SRC.read_text(encoding="utf-8")
    assert '"max_risque_engage_pct": MAX_RISQUE_ENGAGE_PCT,' in src


def test_la_porte_est_BRANCHEE_dans_le_chemin_de_l_ordre():
    """⛔ Les fonctions pures ci-dessus ne diraient rien si `place_order`
    oubliait de les appeler. C'est la lecon du detecteur de positions nues :
    une logique correcte, jamais atteinte."""
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def place_order(")
    fin = src.index("def ", src.index("Get specs pour valider"))
    corps = src[debut:fin]
    assert "_controle_risque_engage_kraken(" in corps
    assert "_risque_engage_kraken(" in corps
    assert "_stops_par_symbole(" in corps
