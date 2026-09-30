"""Le risque engagé du Kraken SPOT, lu là où il se décide (2026-09-30).

`admin_kraken_spot` était mesurable mais jamais montré : `_lire_kraken` le
route déjà vers `/risque`, un endpoint que le bridge spot n'exposait pas.
L'ajouter à la liste affichée sans l'endpoint l'aurait rendu `illisible` à
chaque appel — et un compte illisible REFUSE le total tous comptes.

## ⛔ Sur le spot, le stop n'est pas un ordre : c'est un THREAD

Kraken Spot n'accepte pas d'OCO. Le bridge lance un watcher logiciel qui
surveille le prix et vend au marché quand le niveau est touché. Deux
conséquences que ces tests verrouillent :

1. Le risque se lit dans le WATCHER (`entry`, `sl`, `qty`), pas dans un
   carnet d'ordres.
2. ⛔ Un watcher meurt avec le processus. `stop_logiciel` le DIT, parce que
   le présenter comme un stop courtier surestimerait la protection — et cette
   différence-là ne se voit nulle part ailleurs.

## ⛔ Le spot n'a AUCUNE porte de risque engagé

Pas de `MAX_RISQUE_ENGAGE_PCT` : `porte_armee` vaut donc False, et il n'y a
ni plafond ni pourcentage à publier. En inventer un donnerait un chiffre
d'apparence comparable à celui de Kraken Futures sans mesurer la même chose.
"""
from __future__ import annotations

import pathlib
import types

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[2]
        / "kraken-spot-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def m():
    """Charge la seule tranche de risque — le module entier importe httpx et
    lit des variables d'environnement."""
    src = _SRC.read_text(encoding="utf-8")
    bloc = src[src.index("def risque_position_stop("):
               src.index("# ─── Flask app")]
    mod = types.ModuleType("kraken_spot_risque")
    exec(compile(bloc, str(_SRC), "exec"), mod.__dict__)
    return mod


def _watcher(entry=61000.0, sl=59000.0, qty=0.001, pair="BTC/USD"):
    return {"pair": pair, "kraken_pair": "XBTUSD", "qty": qty,
            "entry": entry, "sl": sl, "tp": 65000.0}


def _position(asset="XBT", qty=0.001, prix=60000.0):
    return {"asset": asset, "pair": "BTC/USD", "kraken_pair": "XBTUSD",
            "qty": qty, "price_usd": prix, "value_usd": qty * prix}


# --------------------------------------------------------------------------
# |entrée − stop| × taille
# --------------------------------------------------------------------------

def test_le_risque_est_la_distance_au_stop_fois_la_taille(m):
    assert m.risque_position_stop(61000.0, 59000.0, 0.001) == pytest.approx(2.0)


def test_un_stop_A_L_ENTREE_est_un_VRAI_zero(m):
    """La position ne peut plus perdre. C'est une mesure, pas une faute de
    mesure — et le distinguer de l'inconnu est tout l'enjeu."""
    assert m.risque_position_stop(1.2345, 1.2345, 10.0) == 0.0


@pytest.mark.parametrize("entree,stop,taille", [
    (None, 59000.0, 0.001),      # watcher d'un bridge pas encore à jour
    (0.0, 59000.0, 0.001),       # prix de remplissage non consolidé
    (61000.0, None, 0.001),
    (61000.0, 59000.0, None),
    (61000.0, 59000.0, 0.0),
    ("illisible", 59000.0, 0.001),
])
def test_une_donnee_manquante_rend_None_JAMAIS_zero(m, entree, stop, taille):
    """⛔ Zéro dirait « aucun risque ». None dit « on ne sait pas ».

    Le cas `0.0` en entrée n'est pas théorique : `_prix_de_remplissage` rend
    zéro quand Kraken n'a pas encore consolidé le prix moyen d'un ordre au
    marché. Le compter pour zéro rabaisserait le total en silence.
    """
    assert m.risque_position_stop(entree, stop, taille) is None


# --------------------------------------------------------------------------
# Le résumé, au même contrat que le bridge Futures
# --------------------------------------------------------------------------

def test_le_resume_somme_les_watchers(m):
    r = m.resume_risque_spot([_watcher()], [_position()], equity_usd=127.0)
    assert r["risque_ouvert_usd"] == pytest.approx(2.0)
    assert r["positions"] == 1
    assert r["non_bornables"] == []


def test_une_position_SANS_watcher_est_NON_BORNABLE(m):
    """⛔ Aucun stop du tout : le risque n'est pas grand, il est NON BORNÉ.
    Une seule suffit à rendre toute somme trompeuse — c'est ce champ qui
    compte, pas la saturation calculée à côté."""
    r = m.resume_risque_spot([], [_position(asset="ETH")], equity_usd=127.0)
    assert r["non_bornables"] == ["ETH"]


def test_un_watcher_SANS_entree_est_non_bornable_lui_aussi(m):
    """Le bridge d'avant le 30/09 n'enregistrait pas `entry`. ⛔ Sa position
    n'est pas « à risque nul » : elle est non mesurable, et le taire
    rabaisserait le total."""
    r = m.resume_risque_spot([_watcher(entry=None)], [_position()],
                             equity_usd=127.0)
    assert r["non_bornables"] == ["XBT"]
    assert r["risque_ouvert_usd"] == 0.0


def test_le_spot_n_a_AUCUNE_porte_de_risque_engage(m):
    """⛔ `porte_armee` False, donc ni plafond ni pourcentage.

    Publier un pourcentage donnerait un chiffre d'apparence comparable à
    celui de Kraken Futures sans mesurer la même chose. Côté backend,
    `_lire_kraken` traduit ce False en « plafond désarmé » — une phrase, pas
    un zéro.
    """
    r = m.resume_risque_spot([_watcher()], [_position()], equity_usd=127.0)
    assert r["porte_armee"] is False
    assert r["plafond_usd"] is None
    assert r["saturation_pct"] is None


def test_le_stop_LOGICIEL_est_annonce(m):
    """⛔ Un watcher est un thread du bridge, pas un ordre du carnet : un
    redémarrage le perd et laisse la position nue. Le champ existe pour que
    cette différence puisse être dite."""
    r = m.resume_risque_spot([_watcher()], [_position()], equity_usd=127.0)
    assert r["stop_logiciel"] is True


def test_vide_mesure_n_est_PAS_illisible(m):
    """Le spot est vide aujourd'hui. Zéro position et zéro watcher, c'est un
    vrai zéro — à ne pas confondre avec un bridge muet."""
    r = m.resume_risque_spot([], [], equity_usd=127.0)
    assert r["risque_ouvert_usd"] == 0.0
    assert r["non_bornables"] == []
    assert r["positions"] == 0


def test_une_equity_INCONNUE_ne_devient_pas_zero(m):
    r = m.resume_risque_spot([_watcher()], [_position()], equity_usd=None)
    assert r["equity_usd"] is None


def test_le_contrat_est_CELUI_du_bridge_futures(m):
    """⛔ `_lire_kraken` lit les deux bridges avec le MÊME code.

    Une clé manquante ne lève pas : elle se lit comme « non mesurable ». Ce
    test verrouille donc la forme, pas seulement les valeurs — c'est le
    défaut qui avait fait disparaître `restant` du bloc Kraken le 08/09.
    """
    attendues = {"porte_armee", "risque_ouvert_usd", "equity_usd",
                 "plafond_pct", "plafond_usd", "saturation_pct",
                 "non_bornables", "positions"}
    r = m.resume_risque_spot([_watcher()], [_position()], equity_usd=127.0)
    manquantes = attendues - set(r)
    assert not manquantes, f"clés absentes du résumé spot : {manquantes}"
