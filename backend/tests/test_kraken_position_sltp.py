"""Kraken : reposer ou déplacer un stop sur une position vivante (2026-09-06).

Le bridge Kraken n'avait aucune route équivalente à `/position/sltp` du bridge
MT5. Conséquences, les deux mesurées le 06/09 :

- rien ne pouvait **réparer** une position ouverte sans stop — la détection
  existait (`/openorders` → `positions_non_protegees`), la réparation non ;
- rien ne pouvait **déplacer** un stop, donc la sortie à l'équilibre du 23/08
  n'avait aucun bras côté Kraken.

⛔ Le piège est propre à Kraken : **le stop n'est pas un attribut de la
position, c'est un ordre indépendant.** « Déplacer un stop » veut donc dire en
poser un nouveau et annuler l'ancien — et l'ORDRE de ces deux gestes décide si
la position passe, ou non, par un instant sans protection.

🔑 **On pose d'abord, on annule ensuite.** Deux stops coexistent une fraction de
seconde : le premier déclenché ferme la position, le second devient sans objet
(il est `reduceOnly`, il ne peut rien ouvrir). L'ordre inverse ouvrirait une
fenêtre nue — exactement le défaut corrigé dans `/kill` le même jour.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Courtier:
    def __init__(self, positions, ordres=(), pose_ko=False):
        self.positions = list(positions)
        self.ordres = list(ordres)
        self.pose_ko = pose_ko
        self.appels: list = []

    def __call__(self, methode, chemin, params=None, *a, **k):
        p = dict(params or {})
        self.appels.append((chemin, p))
        if chemin == "/api/v3/openpositions":
            return {"result": "success", "openPositions": self.positions}
        if chemin == "/api/v3/openorders":
            return {"result": "success", "openOrders": self.ordres}
        if chemin == "/api/v3/sendorder":
            if self.pose_ko:
                return {"result": "error", "error": "invalidPrice"}
            return {"result": "success",
                    "sendStatus": {"status": "placed", "order_id": "neuf"}}
        if chemin == "/api/v3/cancelorder":
            return {"result": "success", "cancelStatus": {"status": "cancelled"}}
        raise AssertionError("appel inattendu : " + str(chemin))

    def poses(self):
        return [p for c, p in self.appels if c == "/api/v3/sendorder"]

    def annulations(self):
        return [p.get("order_id") for c, p in self.appels if c == "/api/v3/cancelorder"]

    def rang(self, chemin, **filtre):
        for i, (c, p) in enumerate(self.appels):
            if c == chemin and all(p.get(k) == v for k, v in filtre.items()):
                return i
        return -1


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    monkeypatch.setattr(bridge, "_get_specs", lambda sym: {"tickSize": 0.01})
    monkeypatch.setattr(bridge, "_resolve_symbol",
                        lambda pair: "PF_XBTUSD" if pair == "BTC/USD" else None)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _pos(symbol="PF_XBTUSD", side="long", size=0.5):
    return {"symbol": symbol, "side": side, "size": size, "price": 100.0}


def _ordre(order_id, symbol="PF_XBTUSD", type_="stop", reduce_only=True):
    return {"order_id": order_id, "symbol": symbol, "orderType": type_,
            "reduceOnly": reduce_only, "side": "sell", "size": 0.5,
            "stopPrice": 90.0}


def _poser(c, **corps):
    return c.post("/position/sltp", json=corps, headers={"X-Bridge-Key": "x"})


# ── Réparer une position nue ─────────────────────────────────────────

def test_pose_un_stop_sur_une_position_qui_n_en_a_pas(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=95.0,
               raison="reparation")

    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    poses = k.poses()
    assert len(poses) == 1
    assert poses[0]["orderType"] == "stp"
    assert poses[0]["side"] == "sell", "on borne un long par une VENTE"
    assert float(poses[0]["stopPrice"]) == 95.0
    assert str(poses[0]["reduceOnly"]).lower() == "true"


def test_une_position_VENDEUSE_se_borne_par_un_achat(bridge, monkeypatch):
    k = _Courtier([_pos(side="short")])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=110.0)
    assert k.poses()[0]["side"] == "buy"


def test_la_taille_vient_du_COURTIER(bridge, monkeypatch):
    """Un stop plus petit que la position en laisse une part NUE."""
    k = _Courtier([_pos(size=0.5)])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=95.0, size=0.001)
    assert float(k.poses()[0]["size"]) == 0.5


def test_le_prix_est_arrondi_au_tick(bridge, monkeypatch):
    k = _Courtier([_pos()])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=95.0123)
    assert float(k.poses()[0]["stopPrice"]) == 95.01


# ── ⛔ L'ordre des gestes ─────────────────────────────────────────────

def test_le_NOUVEAU_stop_est_pose_AVANT_l_annulation_de_l_ancien(bridge, monkeypatch):
    k = _Courtier([_pos()], ordres=[_ordre("vieux-stop")])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=97.0)

    rang_pose = k.rang("/api/v3/sendorder")
    rang_annul = k.rang("/api/v3/cancelorder", order_id="vieux-stop")
    assert rang_pose >= 0 and rang_annul >= 0
    assert rang_pose < rang_annul, (
        "⛔ annuler d'abord ouvrirait une fenetre SANS protection")


def test_une_pose_qui_ECHOUE_conserve_l_ancien_stop(bridge, monkeypatch):
    """⛔ Le pire resultat : plus d'ancien stop, pas de nouveau."""
    k = _Courtier([_pos()], ordres=[_ordre("vieux-stop")], pose_ko=True)
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=97.0)

    assert r.status_code == 502
    assert r.get_json()["ok"] is False
    assert k.annulations() == [], "l'ancien stop reste, la position reste bornee"


# ── Ce qu'il ne faut pas emporter au passage ─────────────────────────

def test_poser_un_stop_ne_touche_PAS_a_l_objectif(bridge, monkeypatch):
    k = _Courtier([_pos()], ordres=[_ordre("vieux-stop"),
                                    _ordre("objectif", type_="take_profit")])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=97.0)
    assert k.annulations() == ["vieux-stop"]


def test_poser_un_objectif_ne_touche_PAS_au_stop(bridge, monkeypatch):
    k = _Courtier([_pos()], ordres=[_ordre("vieux-stop"),
                                    _ordre("vieil-objectif", type_="take_profit")])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", tp=120.0)
    assert k.annulations() == ["vieil-objectif"]
    assert k.poses()[0]["orderType"] == "take_profit"


def test_les_ordres_d_un_AUTRE_symbole_survivent(bridge, monkeypatch):
    k = _Courtier([_pos()], ordres=[_ordre("vieux-stop"),
                                    _ordre("stop-eth", symbol="PF_ETHUSD")])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=97.0)
    assert k.annulations() == ["vieux-stop"]


def test_un_ordre_d_ENTREE_du_meme_symbole_n_est_pas_annule(bridge, monkeypatch):
    k = _Courtier([_pos()], ordres=[_ordre("entree", type_="lmt", reduce_only=False)])
    _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=97.0)
    assert k.annulations() == []


# ── Refus ────────────────────────────────────────────────────────────

def test_position_introuvable_rend_404_et_ne_pose_RIEN(bridge, monkeypatch):
    k = _Courtier([_pos(symbol="PF_ETHUSD")])
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=95.0)
    assert r.status_code == 404
    assert k.poses() == []


def test_ni_sl_ni_tp_rend_400(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", raison="rien")
    assert r.status_code == 400
    assert k.poses() == []


def test_la_paire_du_radar_est_acceptee(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poser(_client(bridge, monkeypatch, k), pair="BTC/USD", sl=95.0)
    assert r.status_code == 200
    assert k.poses()[0]["symbol"] == "PF_XBTUSD"


def test_la_raison_est_rendue(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=95.0,
               raison="stop_equilibre")
    assert r.get_json()["raison"] == "stop_equilibre"
