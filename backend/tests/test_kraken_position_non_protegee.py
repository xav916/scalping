"""Kraken : une position ouverte SANS stop doit se voir (2026-09-06).

Sur Kraken, l'entrée est **trois ordres indépendants** : marché, stop,
objectif. Le stop peut échouer à la pose sans que l'entrée échoue.

⛔ `/order` rendait alors `ok: True` comme si tout allait bien. Le champ
`sl_error` existait dans la réponse, mais `kraken_bridge_client` ne le lisait
**jamais** — une position pouvait donc s'ouvrir nue en silence, exactement
l'incident du 2026-08-05 (XAU/USD sans stop, découverte 7 h plus tard à −51 €).

⛔ **`ok` ne devient PAS `False` pour autant.** L'ordre de marché, lui, est
bien parti : le faire passer pour un échec ferait retenter l'appelant, donc
**ouvrirait une seconde position** par-dessus la première. Ce qui rate, c'est
la protection, pas l'ordre — et les deux ne se disent pas avec le même mot.

🔑 Le contrat est celui du bridge MT5, éprouvé depuis le 06/08 :

    sl_applied  : bool | None   True = stop confirmé posé chez le courtier
    tp_applied  : bool | None
    protected   : bool          True SSI sl_applied est True

⚠️ Et côté radar, l'alerte se déclenche sur `protected is False`, **jamais**
sur `not protected` : un bridge pas encore mis à jour n'a pas le champ, et
« pas de champ » ne veut pas dire « pas de stop ».
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


# ── Le bridge dit-il la vérité ? ─────────────────────────────────────

class _Courtier:
    """Kraken factice pour `/order`. `stop_ko` fait rater la pose du stop."""

    def __init__(self, stop_ko=False, objectif_ko=False):
        self.stop_ko = stop_ko
        self.objectif_ko = objectif_ko
        self.envois: list = []

    def __call__(self, methode, chemin, params=None, *a, **k):
        p = dict(params or {})
        if chemin == "/api/v3/openpositions":
            return {"result": "success", "openPositions": []}
        if chemin == "/api/v3/openorders":
            return {"result": "success", "openOrders": []}
        if chemin == "/api/v3/accounts":
            return {"result": "success", "accounts": {"flex": {
                "portfolioValue": 1000.0, "availableMargin": 900.0,
                "balanceValue": 1000.0, "initialMargin": 0.0,
                "maintenanceMargin": 0.0}, "cash": {}}}
        if chemin == "/api/v3/sendorder":
            self.envois.append(p)
            genre = p.get("orderType")
            if genre == "stp" and self.stop_ko:
                return {"result": "error", "error": "invalidPrice"}
            if genre == "take_profit" and self.objectif_ko:
                return {"result": "error", "error": "invalidPrice"}
            return {"result": "success", "sendStatus": {
                "status": "placed", "order_id": "o-" + str(genre),
                "orderEvents": [{"executionId": "e1", "amount": 1.0,
                                 "price": 100.0,
                                 "orderPriorExecution": {"limitPrice": 100.0}}]}}
        raise AssertionError("appel inattendu : " + str(chemin))


def _client(bridge, monkeypatch, courtier):
    monkeypatch.setattr(bridge, "_signed_request", courtier)
    monkeypatch.setattr(bridge, "require_bridge_key", lambda f: f)
    monkeypatch.setattr(bridge, "_resolve_symbol", lambda pair: "PF_XBTUSD")
    monkeypatch.setattr(bridge, "_specs_pour", lambda sym: {"tickSize": 0.01,
                                                           "contractValueTradePrecision": 4},
                        raising=False)
    bridge.app.config["TESTING"] = True
    return bridge.app.test_client()


def _commander(c, **extra):
    corps = {"pair": "BTC/USD", "direction": "buy", "qty": 0.001,
             "sl": 95.0, "tp": 110.0}
    corps.update(extra)
    return c.post("/order", json=corps, headers={"X-Bridge-Key": "x"})


def test_stop_pose_la_position_est_protegee(bridge, monkeypatch):
    r = _commander(_client(bridge, monkeypatch, _Courtier()))
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["sl_applied"] is True
    assert d["protected"] is True


def test_stop_RATE_la_position_n_est_PAS_protegee(bridge, monkeypatch):
    """⛔ Le cœur du sujet : l'entrée réussit, la protection non."""
    r = _commander(_client(bridge, monkeypatch, _Courtier(stop_ko=True)))
    d = r.get_json()

    assert d["sl_applied"] is False
    assert d["protected"] is False, "une position sans stop n'est pas protegee"
    assert d["sl_error"], "la raison doit accompagner le constat"


def test_l_ordre_reste_ok_meme_sans_stop(bridge, monkeypatch):
    """⛔ Faire passer l'ordre pour un echec ferait RETENTER l'appelant, donc
    ouvrir une SECONDE position par-dessus la premiere."""
    r = _commander(_client(bridge, monkeypatch, _Courtier(stop_ko=True)))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert r.get_json()["market_order_id"], "l'ordre de marche est bien parti"


def test_l_objectif_rate_ne_rend_pas_la_position_NON_protegee(bridge, monkeypatch):
    """Un objectif manquant coûte du gain, pas de la protection. `protected`
    ne parle que du STOP — les confondre banaliserait l'alerte."""
    r = _commander(_client(bridge, monkeypatch, _Courtier(objectif_ko=True)))
    d = r.get_json()
    assert d["tp_applied"] is False
    assert d["protected"] is True


def test_sans_stop_demande_la_protection_est_INCONNUE(bridge, monkeypatch):
    """Aucun stop demandé : `sl_applied` vaut None, et `protected` est False —
    une position sans stop n'est pas protégée, même si personne n'en voulait."""
    r = _commander(_client(bridge, monkeypatch, _Courtier()), sl=None)
    d = r.get_json()
    assert d["sl_applied"] is None
    assert d["protected"] is False


# ── Le radar écoute-t-il ? ───────────────────────────────────────────
#
# ⛔ Une réponse juste que personne ne lit ne protège de rien : c'est le trou
# du détecteur de positions nues, parfait et jamais branché.

@pytest.mark.asyncio
async def test_le_radar_ALERTE_quand_protected_est_False(monkeypatch):
    from backend.services import kraken_bridge_client as kbc

    envoyes: list = []

    async def _faux_envoi(texte, *a, **k):
        envoyes.append(texte)

    from backend.services import telegram_service
    monkeypatch.setattr(telegram_service, "send_infra_text", _faux_envoi)

    await kbc.alerter_si_non_protegee(
        {"protected": False, "sl_error": "invalidPrice",
         "market_order_id": "abc", "symbol": "PF_XBTUSD"},
        pair="BTC/USD", direction="buy", destination_id="admin_kraken")

    assert len(envoyes) == 1
    message = envoyes[0]
    assert "SANS stop" in message
    assert "PF_XBTUSD" in message or "BTC/USD" in message
    assert "invalidPrice" in message


@pytest.mark.asyncio
async def test_le_radar_se_TAIT_quand_la_position_est_protegee(monkeypatch):
    from backend.services import kraken_bridge_client as kbc
    envoyes: list = []

    async def _faux_envoi(texte, *a, **k):
        envoyes.append(texte)

    from backend.services import telegram_service
    monkeypatch.setattr(telegram_service, "send_infra_text", _faux_envoi)

    await kbc.alerter_si_non_protegee(
        {"protected": True}, pair="BTC/USD", direction="buy",
        destination_id="admin_kraken")
    assert envoyes == []


@pytest.mark.asyncio
async def test_un_bridge_SANS_le_champ_ne_declenche_RIEN(monkeypatch):
    """⛔ `protected is False`, jamais `not protected`. Un bridge pas encore
    deploye n'a pas le champ, et « pas de champ » ne veut pas dire
    « pas de stop » : alerter la-dessus apprendrait a ignorer l'alerte."""
    from backend.services import kraken_bridge_client as kbc
    envoyes: list = []

    async def _faux_envoi(texte, *a, **k):
        envoyes.append(texte)

    from backend.services import telegram_service
    monkeypatch.setattr(telegram_service, "send_infra_text", _faux_envoi)

    await kbc.alerter_si_non_protegee(
        {"ok": True, "market_order_id": "abc"}, pair="BTC/USD",
        direction="buy", destination_id="admin_kraken")
    assert envoyes == []


@pytest.mark.asyncio
async def test_une_alerte_qui_echoue_ne_casse_PAS_le_flux(monkeypatch):
    """Le flux d'ordre ne doit jamais dependre de Telegram."""
    from backend.services import kraken_bridge_client as kbc

    async def _explose(*a, **k):
        raise RuntimeError("telegram down")

    from backend.services import telegram_service
    monkeypatch.setattr(telegram_service, "send_infra_text", _explose)

    await kbc.alerter_si_non_protegee(
        {"protected": False}, pair="BTC/USD", direction="buy",
        destination_id="admin_kraken")   # ne doit pas lever
