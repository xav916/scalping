"""Kraken : `/kill` annulait les stops AVANT de fermer (2026-09-06).

La route d'urgence faisait, dans cet ordre :

    1. `cancelallorders`   -> tous les stops et objectifs disparaissent
    2. pour chaque position : ordre de fermeture au marché

⛔ **Si une fermeture échoue, la position reste ouverte et NUE.** Le stop qui la
bornait vient d'être annulé par l'étape 1. C'est l'incident de position nue du
2026-08-05 reproduit par le remède censé l'éviter — et dans la seule route
qu'on appelle quand ça va déjà mal.

⛔ **Et elle rendait `ok: True` sans jamais regarder le résultat des
fermetures.** Un kill-switch peut donc annoncer « tout est fermé » alors que
rien ne l'est. Un mécanisme qui ment sur son propre résultat est pire que son
absence : il fait renoncer à vérifier.

⛔ **Une exception au milieu de la boucle abandonnait les positions
suivantes**, stops déjà annulés. Pire cas : la première fermée, la deuxième
lève, la troisième jamais tentée — deux positions nues.

🔑 L'ordre correct distingue deux familles d'ordres, que `cancelallorders`
confondait :

  - un ordre d'**ENTRÉE** en attente peut OUVRIR du risque : il s'annule
    **en premier**, c'est le geste même du kill ;
  - un ordre de **PROTECTION** (`reduceOnly`) borne du risque existant : il ne
    s'annule qu'**APRÈS** que sa position soit effectivement fermée, et
    seulement pour ce symbole-là.
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
    """Kraken factice. `echecs` : symboles dont la fermeture rate.
    `explose` : symboles dont la fermeture lève une exception."""

    def __init__(self, positions, ordres=(), echecs=(), explose=()):
        self.positions = list(positions)
        self.ordres = list(ordres)
        self.echecs = set(echecs)
        self.explose = set(explose)
        self.appels: list = []

    def __call__(self, methode, chemin, params=None, *a, **k):
        p = dict(params or {})
        self.appels.append((chemin, p))
        if chemin == "/api/v3/openpositions":
            return {"result": "success", "openPositions": self.positions}
        if chemin == "/api/v3/openorders":
            return {"result": "success", "openOrders": self.ordres}
        if chemin == "/api/v3/sendorder":
            sym = p.get("symbol")
            if sym in self.explose:
                raise RuntimeError("kraken timeout sur " + str(sym))
            if sym in self.echecs:
                return {"result": "error", "error": "insufficientAvailableFunds"}
            return {"result": "success",
                    "sendStatus": {"status": "placed", "order_id": "f-" + str(sym)}}
        if chemin == "/api/v3/cancelorder":
            return {"result": "success", "cancelStatus": {"status": "cancelled"}}
        if chemin == "/api/v3/cancelallorders":
            return {"result": "success"}
        raise AssertionError("appel inattendu : " + str(chemin))

    def chemins(self):
        return [c for c, _ in self.appels]

    def fermetures(self):
        return [p.get("symbol") for c, p in self.appels if c == "/api/v3/sendorder"]

    def annulations(self):
        return [p.get("order_id") for c, p in self.appels if c == "/api/v3/cancelorder"]

    def rang(self, chemin, **filtre):
        """Position du premier appel correspondant, ou -1."""
        for i, (c, p) in enumerate(self.appels):
            if c == chemin and all(p.get(k) == v for k, v in filtre.items()):
                return i
        return -1


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _pos(symbol, side="long", size=1.0):
    return {"symbol": symbol, "side": side, "size": size, "price": 100.0}


def _ordre(order_id, symbol, reduce_only=True, type_="stop"):
    return {"order_id": order_id, "symbol": symbol, "orderType": type_,
            "reduceOnly": reduce_only, "side": "sell", "size": 1.0}


def _kill(c):
    return c.post("/kill", json={}, headers={"X-Bridge-Key": "x"})


# ── L'ordre des gestes ───────────────────────────────────────────────

def test_le_stop_n_est_annule_QU_APRES_la_fermeture(bridge, monkeypatch):
    k = _Courtier([_pos("PF_XBTUSD")], ordres=[_ordre("stop-btc", "PF_XBTUSD")])
    _kill(_client(bridge, monkeypatch, k))

    rang_fermeture = k.rang("/api/v3/sendorder", symbol="PF_XBTUSD")
    rang_annulation = k.rang("/api/v3/cancelorder", order_id="stop-btc")
    assert rang_fermeture < rang_annulation, (
        "⛔ annuler le stop avant la fermeture laisse la position nue si "
        "la fermeture echoue")


def test_un_ordre_d_ENTREE_est_annule_EN_PREMIER(bridge, monkeypatch):
    """Un ordre d'entree en attente peut OUVRIR du risque pendant le kill."""
    k = _Courtier([_pos("PF_XBTUSD")],
                  ordres=[_ordre("entree", "PF_ETHUSD", reduce_only=False, type_="lmt"),
                          _ordre("stop-btc", "PF_XBTUSD")])
    _kill(_client(bridge, monkeypatch, k))

    rang_entree = k.rang("/api/v3/cancelorder", order_id="entree")
    rang_fermeture = k.rang("/api/v3/sendorder", symbol="PF_XBTUSD")
    assert rang_entree >= 0, "l'ordre d'entree doit etre annule"
    assert rang_entree < rang_fermeture, (
        "un ordre d'entree s'annule AVANT de fermer, sinon il peut se remplir "
        "pendant le kill")


def test_cancelallorders_n_est_PLUS_appele(bridge, monkeypatch):
    """⛔ Il confondait les deux familles d'ordres : celui qui ouvre du risque
    et celui qui le borne."""
    k = _Courtier([_pos("PF_XBTUSD")], ordres=[_ordre("stop-btc", "PF_XBTUSD")])
    _kill(_client(bridge, monkeypatch, k))
    assert "/api/v3/cancelallorders" not in k.chemins()


# ── Le résultat doit être VRAI ───────────────────────────────────────

def test_une_fermeture_qui_ECHOUE_rend_ok_False(bridge, monkeypatch):
    """⛔ Le kill annoncait le succes sans regarder le resultat."""
    k = _Courtier([_pos("PF_XBTUSD")], echecs={"PF_XBTUSD"})
    r = _kill(_client(bridge, monkeypatch, k))

    assert r.status_code == 502
    corps = r.get_json()
    assert corps["ok"] is False
    assert "PF_XBTUSD" in str(corps.get("non_fermees"))


def test_une_fermeture_ratee_LAISSE_son_stop_en_place(bridge, monkeypatch):
    """Le geste qui protege : position encore ouverte ⇒ stop conserve."""
    k = _Courtier([_pos("PF_XBTUSD")], ordres=[_ordre("stop-btc", "PF_XBTUSD")],
                  echecs={"PF_XBTUSD"})
    _kill(_client(bridge, monkeypatch, k))
    assert "stop-btc" not in k.annulations()


def test_toutes_fermees_rend_ok_True(bridge, monkeypatch):
    k = _Courtier([_pos("PF_XBTUSD"), _pos("PF_ETHUSD", side="short")])
    r = _kill(_client(bridge, monkeypatch, k))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert sorted(k.fermetures()) == ["PF_ETHUSD", "PF_XBTUSD"]


def test_compte_deja_a_plat_rend_ok_True(bridge, monkeypatch):
    k = _Courtier([])
    r = _kill(_client(bridge, monkeypatch, k))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert k.fermetures() == []


# ── ⛔ Une position ne doit jamais faire tomber les autres ────────────

def test_une_exception_n_ABANDONNE_PAS_les_positions_suivantes(bridge, monkeypatch):
    """⛔ Pire cas de l'ancienne version : la 1re fermee, la 2e leve, la 3e
    jamais tentee — et les stops de toutes deja annules."""
    k = _Courtier([_pos("PF_XBTUSD"), _pos("PF_ETHUSD"), _pos("PF_SOLUSD")],
                  explose={"PF_ETHUSD"})
    r = _kill(_client(bridge, monkeypatch, k))

    assert sorted(k.fermetures()) == ["PF_ETHUSD", "PF_SOLUSD", "PF_XBTUSD"], (
        "les trois doivent etre TENTEES")
    corps = r.get_json()
    assert corps["ok"] is False
    assert "PF_ETHUSD" in str(corps.get("non_fermees"))
    assert sorted(corps.get("fermees") or []) == ["PF_SOLUSD", "PF_XBTUSD"]


def test_le_stop_de_la_position_qui_a_LEVE_survit(bridge, monkeypatch):
    k = _Courtier([_pos("PF_XBTUSD"), _pos("PF_ETHUSD")],
                  ordres=[_ordre("stop-btc", "PF_XBTUSD"),
                          _ordre("stop-eth", "PF_ETHUSD")],
                  explose={"PF_ETHUSD"})
    _kill(_client(bridge, monkeypatch, k))

    assert "stop-btc" in k.annulations(), "la position fermee libere son stop"
    assert "stop-eth" not in k.annulations(), (
        "⛔ la position encore ouverte GARDE son stop")


def test_les_stops_d_un_AUTRE_symbole_ne_partent_pas_avec(bridge, monkeypatch):
    k = _Courtier([_pos("PF_XBTUSD")],
                  ordres=[_ordre("stop-btc", "PF_XBTUSD"),
                          _ordre("stop-doge", "PF_DOGEUSD")])
    _kill(_client(bridge, monkeypatch, k))
    assert k.annulations() == ["stop-btc"]
