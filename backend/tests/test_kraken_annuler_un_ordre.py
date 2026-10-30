"""`/order/annuler` : annuler UN ordre d'entree, jamais une protection.

## Pourquoi cette route existe (2026-10-30)

Deux achats limite BTC du 27/09 dormaient a 63 366 USD (`reduceOnly: false`,
938 USD de notionnel si touches). Impossible de les annuler : le pont
n'exposait AUCUNE annulation par ordre, et `/kill` -- qui est `kill_all()`
sans parametre -- aurait aussi ferme au marche la position INJ, correctement
protegee.

🔑 Et la lecon qui a rendu la route necessaire : **REM-002 empeche le radar
d'ENVOYER des ordres, il n'annule pas ceux qui dorment deja chez le
courtier.** « L'IA est coupee » ne veut pas dire « rien ne peut s'ouvrir ».

Ces tests gardent la propriete qui fait toute la surete de la route : **elle
ne peut que RETIRER du risque, jamais en decouvrir.**
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")

# Les deux ordres REELS du 27/09, et la protection reelle d'INJ.
BTC = {"order_id": "a2d8bded-cd2f-4aa4-86b3-f8d3a9dba7b2",
       "symbol": "PF_XBTUSD", "orderType": "lmt", "side": "buy",
       "size": 0.0074, "limitPrice": 63366, "reduceOnly": False}
STOP_INJ = {"order_id": "a2f5e01e-a67a-4298-b4b2-409b94de9793",
            "symbol": "PF_INJUSD", "orderType": "stop", "side": "sell",
            "size": 0.4, "stopPrice": 6.307, "reduceOnly": True}


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge",
                                                  _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Courtier:
    """Kraken factice. `restants` = les ordres encore la APRES annulation."""

    def __init__(self, ordres, echec=False, restants=None, lecture_ko=False,
                 relecture_ko=False):
        self.ordres = list(ordres)
        self.echec = echec
        self.restants = ordres if restants is None else restants
        self.lecture_ko = lecture_ko
        self.relecture_ko = relecture_ko
        self.appels: list = []
        self._lectures = 0

    def __call__(self, methode, chemin, params=None, *a, **k):
        self.appels.append((chemin, dict(params or {})))
        if chemin == "/api/v3/openorders":
            self._lectures += 1
            if self.lecture_ko:
                raise RuntimeError("liaison coupee")
            if self._lectures == 1:
                return {"result": "success", "openOrders": self.ordres}
            if self.relecture_ko:
                raise RuntimeError("liaison coupee a la relecture")
            return {"result": "success", "openOrders": list(self.restants)}
        if chemin == "/api/v3/cancelorder":
            if self.echec:
                raise RuntimeError("cancel refuse par Kraken")
            return {"result": "success", "cancelStatus": {"status": "cancelled"}}
        raise AssertionError("appel inattendu : " + str(chemin))

    def annulations(self):
        return [p.get("order_id") for c, p in self.appels
                if c == "/api/v3/cancelorder"]


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _poster(c, **corps):
    return c.post("/order/annuler", json=corps,
                  headers={"X-Bridge-Key": "x"})


# ── Le cas nominal : les deux ordres BTC du 27/09 ──────────────────────────

def test_un_ordre_d_ENTREE_est_annule(bridge, monkeypatch):
    k = _Courtier([BTC, STOP_INJ], restants=[STOP_INJ])
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"],
                raison="dormant depuis le 27/09")
    assert r.status_code == 200
    corps = r.get_json()
    assert corps["ok"] is True
    assert corps["confirme"] is True
    assert corps["symbol"] == "PF_XBTUSD"
    assert corps["limitPrice"] == 63366
    assert k.annulations() == [BTC["order_id"]]


def test_la_PROTECTION_voisine_n_est_pas_touchee(bridge, monkeypatch):
    """⛔ C'est la difference avec `/kill` : le stop d'INJ survit."""
    k = _Courtier([BTC, STOP_INJ], restants=[STOP_INJ])
    _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"])
    assert STOP_INJ["order_id"] not in k.annulations()
    assert len(k.annulations()) == 1


def test_la_raison_suit_jusqu_a_la_reponse(bridge, monkeypatch):
    k = _Courtier([BTC], restants=[])
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"],
                raison="decision de Xavier")
    assert r.get_json()["raison"] == "decision de Xavier"


# ── LE REFUS QUI FAIT LA SURETE ───────────────────────────────────────────

def test_un_ordre_reduceOnly_est_REFUSE(bridge, monkeypatch):
    """⛔ LE test qui compte. Annuler un stop laisse la position NUE —
    l'incident du 2026-08-05. La route ne peut, par construction, que
    retirer du risque."""
    k = _Courtier([BTC, STOP_INJ])
    r = _poster(_client(bridge, monkeypatch, k),
                order_id=STOP_INJ["order_id"])
    assert r.status_code == 409
    corps = r.get_json()
    assert corps["ok"] is False
    assert "PROTECTION" in corps["error"]
    assert k.annulations() == [], "aucun appel d'annulation ne doit partir"


def test_le_refus_INDIQUE_la_bonne_route(bridge, monkeypatch):
    """Un refus utile dit quoi faire a la place."""
    k = _Courtier([STOP_INJ])
    r = _poster(_client(bridge, monkeypatch, k),
                order_id=STOP_INJ["order_id"])
    assert "/position/close" in r.get_json()["detail"]


# ── On ne juge pas un ordre qu'on ne voit pas ─────────────────────────────

def test_des_ordres_ILLISIBLES_donnent_503_et_n_annulent_RIEN(bridge, monkeypatch):
    """⛔ `reduceOnly` ne peut pas s'evaluer sur un ordre invisible. Une
    liaison coupee ne doit jamais devenir une annulation a l'aveugle."""
    k = _Courtier([BTC], lecture_ko=True)
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"])
    assert r.status_code == 503
    assert k.annulations() == []


def test_un_ordre_INCONNU_donne_404(bridge, monkeypatch):
    k = _Courtier([STOP_INJ])
    r = _poster(_client(bridge, monkeypatch, k), order_id="jamais-vu")
    assert r.status_code == 404
    assert k.annulations() == []


def test_sans_order_id_c_est_400(bridge, monkeypatch):
    k = _Courtier([BTC])
    r = _poster(_client(bridge, monkeypatch, k), raison="rien")
    assert r.status_code == 400
    assert k.annulations() == []


@pytest.mark.parametrize("valeur", ["", "   ", None])
def test_un_order_id_vide_est_refuse(bridge, monkeypatch, valeur):
    k = _Courtier([BTC])
    r = _poster(_client(bridge, monkeypatch, k), order_id=valeur)
    assert r.status_code == 400


# ── Le succes se VERIFIE, il ne se suppose pas ────────────────────────────

def test_un_cancel_REFUSE_par_kraken_donne_502(bridge, monkeypatch):
    k = _Courtier([BTC], echec=True)
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"])
    assert r.status_code == 502
    assert r.get_json()["ok"] is False


def test_un_ordre_TOUJOURS_PRESENT_apres_annulation_n_est_pas_un_succes(
        bridge, monkeypatch):
    """⛔ L'ancienne version de `/kill` rendait `ok: True` sans regarder. Un
    mecanisme qui ment sur son propre resultat fait renoncer a verifier."""
    k = _Courtier([BTC], restants=[BTC])     # Kraken accepte mais ne retire pas
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"])
    assert r.status_code == 409
    assert r.get_json()["ok"] is False


def test_une_relecture_IMPOSSIBLE_dit_non_confirme_plutot_que_de_mentir(
        bridge, monkeypatch):
    """L'annulation est acceptee mais pas CONFIRMEE : `confirme` vaut False,
    et ce n'est pas la meme chose qu'un echec."""
    k = _Courtier([BTC], relecture_ko=True)
    r = _poster(_client(bridge, monkeypatch, k), order_id=BTC["order_id"])
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert r.get_json()["confirme"] is False


# ── La route existe bel et bien, et `/kill` est intact ────────────────────

def test_la_route_est_declaree_en_POST_seulement(bridge):
    regles = {str(r.rule): sorted(r.methods - {"HEAD", "OPTIONS"})
              for r in bridge.app.url_map.iter_rules()}
    assert regles.get("/order/annuler") == ["POST"]


def test_kill_reste_present_et_distinct(bridge):
    """La route chirurgicale n'enleve pas le geste d'urgence."""
    regles = {str(r.rule) for r in bridge.app.url_map.iter_rules()}
    assert "/kill" in regles and "/order/annuler" in regles
