"""Kraken : le garde-fou qui pose un stop sur une position nue (2026-09-06).

Le bridge Kraken savait DÉTECTER une position sans stop (`/openorders` →
`positions_non_protegees`) et, depuis ce soir, la RÉPARER (`/position/sltp`).
Rien ne reliait les deux : il fallait un humain entre la détection et le geste.

Politique reprise telle quelle des bridges MT5, armés le 28/08 :

  - **deux drapeaux indépendants**, lus ensemble — l'orchestrateur décide
    d'agir, le bridge décide si la position est touchable ;
  - **`ACTIVATED_AT` vide ⇒ fail-closed**, même avec `enabled=true` : sans date
    d'armement on ne sait pas ce qui lui est antérieur, donc rien n'est
    éligible ;
  - une position ouverte **avant** l'armement reste gelée pour toujours — un
    simple redémarrage ne doit pas la rendre éligible ;
  - le stop d'urgence vaut **1 % du prix d'entrée** : il borne un risque
    *infini*, il ne cherche pas le bon niveau.

⛔ Une ouverture **indatable** refuse aussi. C'est le sens sur lequel se
tromper : côté MT5, le décalage d'heure serveur faisait passer une position
ouverte jusqu'à 3 h AVANT l'armement pour postérieure — fail-OPEN sur un
garde-fou, l'exact inverse de son rôle.

🔑 Cette règle n'était pas applicable sur Kraken avant le 05/09 :
`openpositions` rendait `fillTime = 1970-01-01` pour tout le monde. **L'âge
reconstruit depuis les fills est ce qui rend ce verrou opposable.**
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_BRIDGE = (pathlib.Path(__file__).resolve().parents[2]
           / "kraken-bridge" / "bridge.py")

_ARMEMENT = "2026-09-06T00:00:00+00:00"


@pytest.fixture(scope="module")
def bridge():
    spec = importlib.util.spec_from_file_location("kraken_futures_bridge", _BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def arme(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "SLTP_GUARD_ACTIVATED_AT", _ARMEMENT)
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_SYMBOLS", frozenset())
    return bridge


# ── L'éligibilité, verrou par verrou ─────────────────────────────────

def test_desarme_rien_n_est_eligible(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", False)
    monkeypatch.setattr(bridge, "SLTP_GUARD_ACTIVATED_AT", _ARMEMENT)
    ok, motif = bridge.garde_fou_eligible("PF_XBTUSD", "2026-09-06T10:00:00Z")
    assert ok is False
    assert "desarme" in motif


def test_ARMEMENT_VIDE_est_fail_closed_meme_si_enabled(arme, monkeypatch):
    """⛔ Le verrou qui compte : `enabled=true` ne suffit pas."""
    monkeypatch.setattr(arme, "SLTP_GUARD_ACTIVATED_AT", "")
    ok, motif = arme.garde_fou_eligible("PF_XBTUSD", "2026-09-06T10:00:00Z")
    assert ok is False
    assert "ACTIVATED_AT" in motif


def test_position_POSTERIEURE_a_l_armement_est_eligible(arme):
    ok, motif = arme.garde_fou_eligible("PF_XBTUSD", "2026-09-06T10:00:00Z")
    assert ok is True, motif


def test_position_ANTERIEURE_reste_gelee(arme):
    ok, motif = arme.garde_fou_eligible("PF_XBTUSD", "2026-09-05T18:42:48Z")
    assert ok is False
    assert "avant" in motif


def test_position_ouverte_A_L_INSTANT_de_l_armement_est_gelee(arme):
    """La borne est inclusive : à égalité, on ne touche pas."""
    ok, _ = arme.garde_fou_eligible("PF_XBTUSD", _ARMEMENT)
    assert ok is False


def test_ouverture_INDATABLE_refuse(arme):
    """⛔ Fail-CLOSED. C'est ce que l'age reconstruit rend possible : avant le
    05/09, `fillTime` valait 1970 pour toutes les positions."""
    ok, motif = arme.garde_fou_eligible("PF_XBTUSD", None)
    assert ok is False
    assert "indatable" in motif


def test_l_epoque_unix_ne_passe_pas_pour_une_date_ANCIENNE_eligible(arme):
    """1970 est antérieur à tout armement : gelé, jamais éligible."""
    ok, _ = arme.garde_fou_eligible("PF_XBTUSD", "1970-01-01T00:00:00.000Z")
    assert ok is False


def test_symbole_GELE_refuse_quelle_que_soit_la_date(arme, monkeypatch):
    monkeypatch.setattr(arme, "SLTP_GUARD_FROZEN_SYMBOLS", frozenset({"PF_XBTUSD"}))
    ok, motif = arme.garde_fou_eligible("PF_XBTUSD", "2026-09-06T10:00:00Z")
    assert ok is False
    assert "gele" in motif


# ── La porte s'applique à l'appel MARQUÉ, et à lui seul ──────────────

class _Courtier:
    def __init__(self, positions, ordres=(), fills=()):
        self.positions = list(positions)
        self.ordres = list(ordres)
        self.fills = list(fills)
        self.appels: list = []

    def __call__(self, methode, chemin, params=None, *a, **k):
        self.appels.append((chemin, dict(params or {})))
        if chemin == "/api/v3/openpositions":
            return {"result": "success", "openPositions": self.positions}
        if chemin == "/api/v3/openorders":
            return {"result": "success", "openOrders": self.ordres}
        if chemin == "/api/v3/fills":
            return {"result": "success", "fills": self.fills}
        if chemin == "/api/v3/sendorder":
            return {"result": "success",
                    "sendStatus": {"status": "placed", "order_id": "neuf"}}
        if chemin == "/api/v3/cancelorder":
            return {"result": "success", "cancelStatus": {"status": "cancelled"}}
        raise AssertionError("appel inattendu : " + str(chemin))

    def poses(self):
        return [p for c, p in self.appels if c == "/api/v3/sendorder"]


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    monkeypatch.setattr(bridge, "_get_specs", lambda sym: {"tickSize": 0.01})
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _pos(symbol="PF_XBTUSD", side="long", size=0.5):
    return {"symbol": symbol, "side": side, "size": size, "price": 100.0}


def _fill(symbol, t, side="buy", size=0.5):
    return {"symbol": symbol, "side": side, "size": size, "fillTime": t}


def _poser(c, **corps):
    return c.post("/position/sltp", json=corps, headers={"X-Bridge-Key": "x"})


def test_appel_marque_sur_position_ANTERIEURE_rend_403(arme, monkeypatch):
    k = _Courtier([_pos()], fills=[_fill("PF_XBTUSD", "2026-09-05T18:00:00.000Z")])
    r = _poser(_client(arme, monkeypatch, k),
               symbol="PF_XBTUSD", sl=99.0, garde_fou=True, raison="auto")

    assert r.status_code == 403
    assert r.get_json()["exclu"] is True
    assert k.poses() == [], "aucun ordre ne part sur une position gelee"


def test_appel_marque_sur_position_POSTERIEURE_pose_le_stop(arme, monkeypatch):
    k = _Courtier([_pos()], fills=[_fill("PF_XBTUSD", "2026-09-06T10:00:00.000Z")])
    r = _poser(_client(arme, monkeypatch, k),
               symbol="PF_XBTUSD", sl=99.0, garde_fou=True, raison="auto")

    assert r.status_code == 200
    assert len(k.poses()) == 1


def test_un_appel_NON_marque_n_est_PAS_soumis_a_la_porte(bridge, monkeypatch):
    """⚠️ Une sortie a l'equilibre, ou une reparation a la main, reste libre :
    c'est un appelant qui sait ce qu'il fait, pas une machine qui decide."""
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", False)
    k = _Courtier([_pos()], fills=[_fill("PF_XBTUSD", "2026-09-05T18:00:00.000Z")])
    r = _poser(_client(bridge, monkeypatch, k), symbol="PF_XBTUSD", sl=99.0,
               raison="equilibre")

    assert r.status_code == 200
    assert len(k.poses()) == 1


def test_position_DEJA_protegee_est_un_no_op(arme, monkeypatch):
    """Reposer un second stop n'ajoute pas de protection, seulement un ordre
    a annuler."""
    k = _Courtier([_pos()],
                  ordres=[{"order_id": "stop-1", "symbol": "PF_XBTUSD",
                           "orderType": "stop", "reduceOnly": True}],
                  fills=[_fill("PF_XBTUSD", "2026-09-06T10:00:00.000Z")])
    r = _poser(_client(arme, monkeypatch, k),
               symbol="PF_XBTUSD", sl=99.0, garde_fou=True, raison="auto")

    assert r.status_code == 200
    assert r.get_json()["deja_protegee"] is True
    assert k.poses() == []


def test_un_OBJECTIF_seul_ne_compte_pas_comme_protection(arme, monkeypatch):
    """Un take-profit ne borne pas la perte. La position est nue."""
    k = _Courtier([_pos()],
                  ordres=[{"order_id": "tp-1", "symbol": "PF_XBTUSD",
                           "orderType": "take_profit", "reduceOnly": True}],
                  fills=[_fill("PF_XBTUSD", "2026-09-06T10:00:00.000Z")])
    r = _poser(_client(arme, monkeypatch, k),
               symbol="PF_XBTUSD", sl=99.0, garde_fou=True, raison="auto")

    assert r.status_code == 200
    assert r.get_json().get("deja_protegee") is not True
    assert len(k.poses()) == 1


# ── L'orchestrateur ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_scan_compte_les_positions_nues(monkeypatch):
    from backend.services import kraken_sltp_guard as g

    async def _faux_get(url, cle="", **k):
        if url.endswith("/openorders"):
            return {"positions_non_protegees": ["PF_XBTUSD"]}
        if url.endswith("/positions"):
            return {"positions": [{"symbol": "PF_XBTUSD", "side": "long",
                                   "size": 0.5, "price": 100.0,
                                   "fill_time": "2026-09-06T10:00:00Z"}]}
        raise AssertionError(url)

    monkeypatch.setattr(g, "BRIDGE_URL", "http://bridge-factice:8790")
    monkeypatch.setattr(g, "_lire", _faux_get)
    monkeypatch.setattr(g, "AUTO_PROTECT_ENABLED", False)
    rapport = await g.scanner()

    assert rapport["nues_total"] == 1
    assert rapport["auto_protect_enabled"] is False
    assert rapport["protegees_total"] == 0
    assert rapport["nues"][0]["symbol"] == "PF_XBTUSD"


@pytest.mark.asyncio
async def test_desarme_le_scan_n_ENVOIE_rien(monkeypatch):
    """⛔ Detection seule tant que le drapeau n'est pas mis sciemment."""
    from backend.services import kraken_sltp_guard as g
    envois: list = []

    async def _faux_get(url, cle="", **k):
        if url.endswith("/openorders"):
            return {"positions_non_protegees": ["PF_XBTUSD"]}
        return {"positions": [{"symbol": "PF_XBTUSD", "side": "long", "size": 0.5,
                               "price": 100.0, "fill_time": "2026-09-06T10:00:00Z"}]}

    async def _faux_post(url, corps, cle="", **k):
        envois.append(corps)
        return {"ok": True}

    monkeypatch.setattr(g, "BRIDGE_URL", "http://bridge-factice:8790")
    monkeypatch.setattr(g, "_lire", _faux_get)
    monkeypatch.setattr(g, "_poser", _faux_post)
    monkeypatch.setattr(g, "AUTO_PROTECT_ENABLED", False)
    await g.scanner()
    assert envois == []


@pytest.mark.asyncio
async def test_arme_le_stop_d_urgence_vaut_1_pourcent_de_l_entree(monkeypatch):
    from backend.services import kraken_sltp_guard as g
    envois: list = []

    async def _faux_get(url, cle="", **k):
        if url.endswith("/openorders"):
            return {"positions_non_protegees": ["PF_XBTUSD"]}
        return {"positions": [{"symbol": "PF_XBTUSD", "side": "long", "size": 0.5,
                               "price": 100.0, "fill_time": "2026-09-06T10:00:00Z"}]}

    async def _faux_post(url, corps, cle="", **k):
        envois.append(corps)
        return {"ok": True}

    monkeypatch.setattr(g, "BRIDGE_URL", "http://bridge-factice:8790")
    monkeypatch.setattr(g, "_lire", _faux_get)
    monkeypatch.setattr(g, "_poser", _faux_post)
    monkeypatch.setattr(g, "AUTO_PROTECT_ENABLED", True)
    monkeypatch.setattr(g, "EMERGENCY_SL_PCT", 1.0)
    rapport = await g.scanner()

    assert len(envois) == 1
    assert envois[0]["garde_fou"] is True, "l'appel doit se DECLARER automatique"
    assert envois[0]["sl"] == pytest.approx(99.0), "1 % SOUS l'entree d'un long"
    assert rapport["protegees_total"] == 1


@pytest.mark.asyncio
async def test_une_position_VENDEUSE_recoit_son_stop_AU_DESSUS(monkeypatch):
    from backend.services import kraken_sltp_guard as g
    envois: list = []

    async def _faux_get(url, cle="", **k):
        if url.endswith("/openorders"):
            return {"positions_non_protegees": ["PF_XBTUSD"]}
        return {"positions": [{"symbol": "PF_XBTUSD", "side": "short", "size": 0.5,
                               "price": 100.0, "fill_time": "2026-09-06T10:00:00Z"}]}

    async def _faux_post(url, corps, cle="", **k):
        envois.append(corps)
        return {"ok": True}

    monkeypatch.setattr(g, "BRIDGE_URL", "http://bridge-factice:8790")
    monkeypatch.setattr(g, "_lire", _faux_get)
    monkeypatch.setattr(g, "_poser", _faux_post)
    monkeypatch.setattr(g, "AUTO_PROTECT_ENABLED", True)
    monkeypatch.setattr(g, "EMERGENCY_SL_PCT", 1.0)
    await g.scanner()
    assert envois[0]["sl"] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_un_bridge_INJOIGNABLE_ne_fait_pas_planter_le_scan(monkeypatch):
    from backend.services import kraken_sltp_guard as g

    async def _faux_get(url, cle="", **k):
        raise RuntimeError("bridge down")

    monkeypatch.setattr(g, "BRIDGE_URL", "http://bridge-factice:8790")
    monkeypatch.setattr(g, "_lire", _faux_get)
    rapport = await g.scanner()
    assert rapport["joignable"] is False
    assert rapport["nues_total"] == 0
