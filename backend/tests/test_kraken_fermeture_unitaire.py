"""Kraken : fermer UNE position, pas toutes (2026-09-05).

Le bridge Kraken ne savait fermer que `/kill` : annuler tous les ordres et
solder tout le compte. Fermer une ligne obligeait à fermer les autres.

> **Un interrupteur général n'est pas un outil de précision.** Les deux gestes
> portent le même nom et n'ont rien de commun.

C'est le défaut corrigé sur les deux bridges MT5 le 28/08 et jamais propagé
ici — *un correctif ne se propage pas seul aux routes jumelles*.

⛔ Deux pièges propres à Kraken, absents côté MT5 :

1. **La taille se lit CHEZ LE COURTIER**, jamais chez l'appelant. Une taille
   fournie de l'extérieur peut sur-fermer (et ouvrir la position inverse) ou
   sous-fermer en silence. `reduceOnly` borne les dégâts, il ne les évite pas.

2. **Le stop est un ordre indépendant.** Fermer la position laisse le stop et
   l'objectif vivants : `/openorders` continuerait d'annoncer une protection
   pour une position qui n'existe plus. Ils doivent être annulés — mais
   **APRÈS** la fermeture, jamais avant : si la fermeture échoue et que le stop
   est déjà annulé, la position reste ouverte et NUE. C'est l'incident du
   2026-08-05, provoqué par le remède.
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
    """Kraken factice : enregistre les appels, dans l'ordre."""

    def __init__(self, positions, ordres=(), echec_fermeture=False):
        self.positions = list(positions)
        self.ordres = list(ordres)
        self.echec_fermeture = echec_fermeture
        self.appels: list = []

    def __call__(self, methode, chemin, params=None, *a, **k):
        self.appels.append((chemin, dict(params or {})))
        if chemin == "/api/v3/openpositions":
            return {"result": "success", "openPositions": self.positions}
        if chemin == "/api/v3/openorders":
            return {"result": "success", "openOrders": self.ordres}
        if chemin == "/api/v3/sendorder":
            if self.echec_fermeture:
                return {"result": "error", "error": "insufficientAvailableFunds"}
            return {"result": "success",
                    "sendStatus": {"status": "placed", "order_id": "ferm-1"}}
        if chemin == "/api/v3/cancelorder":
            return {"result": "success", "cancelStatus": {"status": "cancelled"}}
        raise AssertionError("appel inattendu : " + str(chemin))

    def envois(self):
        return [p for c, p in self.appels if c == "/api/v3/sendorder"]

    def annulations(self):
        return [p.get("order_id") for c, p in self.appels if c == "/api/v3/cancelorder"]


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _pos(symbol="PF_XLMUSD", side="long", size=82.0):
    return {"symbol": symbol, "side": side, "size": size, "price": 0.18}


def _ordre(order_id, symbol="PF_XLMUSD", type_="stop", reduce_only=True):
    return {"order_id": order_id, "symbol": symbol, "orderType": type_,
            "reduceOnly": reduce_only, "side": "sell", "size": 82.0}


def _poster(c, **corps):
    return c.post("/position/close", json=corps, headers={"X-Bridge-Key": "x"})


# ── Le cas nominal ───────────────────────────────────────────────────

def test_ferme_la_position_nommee(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")

    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    envois = k.envois()
    assert len(envois) == 1
    assert envois[0]["symbol"] == "PF_XLMUSD"
    assert envois[0]["side"] == "sell", "on ferme un long en VENDANT"
    assert float(envois[0]["size"]) == 82.0
    assert str(envois[0]["reduceOnly"]).lower() == "true"


def test_une_position_VENDEUSE_se_ferme_en_achetant(bridge, monkeypatch):
    k = _Courtier([_pos(side="short", size=3.0)])
    _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")
    assert k.envois()[0]["side"] == "buy"


def test_la_paire_du_radar_est_acceptee(bridge, monkeypatch):
    """L'appelant parle en `XLM/USD`, le courtier en `PF_XLMUSD`."""
    k = _Courtier([_pos()])
    r = _poster(_client(bridge, monkeypatch, k), pair="XLM/USD", raison="essai")
    assert r.status_code == 200
    assert k.envois()[0]["symbol"] == "PF_XLMUSD"


def test_la_taille_vient_du_COURTIER_pas_de_l_appelant(bridge, monkeypatch):
    """⛔ Une taille fournie de l'extérieur peut sur-fermer et retourner la
    position. Ce qui est ouvert ne se déclare pas, il se lit."""
    k = _Courtier([_pos(size=82.0)])
    _poster(_client(bridge, monkeypatch, k),
            symbol="PF_XLMUSD", size=999.0, raison="essai")
    assert float(k.envois()[0]["size"]) == 82.0


# ── ⛔ Ce qu'il ne faut SURTOUT pas faire ─────────────────────────────

def test_symbole_inconnu_rend_404_et_n_envoie_RIEN(bridge, monkeypatch):
    """⛔ Jamais « ferme ce qui y ressemble »."""
    k = _Courtier([_pos(symbol="PF_DOTUSD")])
    r = _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")

    assert r.status_code == 404
    assert k.envois() == [], "aucun ordre ne part sur une position introuvable"


def test_aucune_position_du_tout_rend_404(bridge, monkeypatch):
    k = _Courtier([])
    r = _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")
    assert r.status_code == 404
    assert k.envois() == []


def test_sans_symbole_ni_paire_rend_400(bridge, monkeypatch):
    k = _Courtier([_pos()])
    r = _poster(_client(bridge, monkeypatch, k), raison="essai")
    assert r.status_code == 400
    assert k.envois() == []


def test_les_AUTRES_positions_ne_sont_pas_touchees(bridge, monkeypatch):
    """Le point du chantier : ce n'est pas `/kill`."""
    k = _Courtier([_pos(symbol="PF_XLMUSD"), _pos(symbol="PF_DOTUSD", size=2.2)])
    _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")

    envoyes = [e["symbol"] for e in k.envois()]
    assert envoyes == ["PF_XLMUSD"], "une seule position visee, vu " + str(envoyes)
    assert "/api/v3/cancelallorders" not in [c for c, _ in k.appels], (
        "⛔ l'annulation GLOBALE des ordres appartient a /kill, pas ici")


# ── Les ordres conditionnels laissés derrière ────────────────────────

def test_le_stop_et_l_objectif_du_symbole_sont_annules_APRES(bridge, monkeypatch):
    k = _Courtier([_pos()],
                  ordres=[_ordre("stop-1"), _ordre("tp-1", type_="take_profit")])
    _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")

    assert sorted(k.annulations()) == ["stop-1", "tp-1"]
    chemins = [c for c, _ in k.appels]
    assert chemins.index("/api/v3/sendorder") < chemins.index("/api/v3/cancelorder"), (
        "⛔ annuler le stop AVANT la fermeture laisserait la position nue si "
        "la fermeture echouait")


def test_les_ordres_des_AUTRES_symboles_survivent(bridge, monkeypatch):
    k = _Courtier([_pos()],
                  ordres=[_ordre("stop-1"), _ordre("stop-dot", symbol="PF_DOTUSD")])
    _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")
    assert k.annulations() == ["stop-1"]


def test_un_ordre_d_ENTREE_en_attente_n_est_pas_annule(bridge, monkeypatch):
    """Seul un ordre qui RÉDUIT accompagne la position. Un ordre d'entrée sur
    le même symbole est une autre intention."""
    k = _Courtier([_pos()],
                  ordres=[_ordre("stop-1"),
                          _ordre("entree", type_="lmt", reduce_only=False)])
    _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")
    assert k.annulations() == ["stop-1"]


def test_une_fermeture_QUI_ECHOUE_laisse_le_stop_en_place(bridge, monkeypatch):
    """⛔ Le pire résultat possible : position ouverte et stop annulé."""
    k = _Courtier([_pos()], ordres=[_ordre("stop-1")], echec_fermeture=True)
    r = _poster(_client(bridge, monkeypatch, k), symbol="PF_XLMUSD", raison="essai")

    assert r.status_code == 502
    assert r.get_json()["ok"] is False
    assert k.annulations() == [], "le stop reste, la position reste protegee"


def test_la_raison_est_rendue_dans_la_reponse(bridge, monkeypatch):
    """`raison` doit survivre jusqu'au journal : c'est elle qui distinguera
    plus tard une fermeture automatique d'une fermeture a la main."""
    k = _Courtier([_pos()])
    r = _poster(_client(bridge, monkeypatch, k),
                symbol="PF_XLMUSD", raison="pre_weekend")
    assert r.get_json()["raison"] == "pre_weekend"
