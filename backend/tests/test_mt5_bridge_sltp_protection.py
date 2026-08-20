"""Vérifie le fix de l'incident 2026-08-05 (position XAU/USD ouverte sans
SL/TP, découverte 7h après à -51€) sur mt5-bridge/bridge.py.

Deux garanties testées ici :

1. Le bridge ne peut plus AVALER un échec de pose SL/TP. Avant ce fix,
   `_apply_sltp_from_fill` ne retournait rien : un échec de
   `mt5.order_send(TRADE_ACTION_SLTP)` finissait en warning dans un log
   local du VPS, et l'appelant HTTP recevait `{"ok": true}` — identique à
   une position protégée. `test_send_market_order_use_dist_path_...` est la
   régression directe de ce bug : elle simule EXACTEMENT le scénario de
   l'incident (order_send du market OK, order_send du SLTP KO) et vérifie
   que le résultat renvoyé par `_send_market_order` — et donc la réponse
   JSON de `/order` — dit désormais la vérité.

2. La route `/position/sltp` (garde-fou sur position déjà ouverte) ne
   touche JAMAIS une position exclue (gelée par ticket ou antérieure à
   l'activation). Ces tests vérifient par MUTATION que `mt5.order_send`
   n'est PAS appelé dans les cas d'exclusion — pas seulement que la réponse
   HTTP dit "refusé" (ce qui ne prouverait rien si le refus était cosmétique
   et l'ordre parti quand même).

Note d'environnement : `mt5-bridge/bridge.py` importe le vrai package
`MetaTrader5` (installé sur cette machine de dev), mais seulement pour ses
constantes et sa forme d'API — aucune connexion à un terminal MT5 réel n'a
lieu ici. `mt5.order_send`, `mt5.symbol_info`, `mt5.symbol_info_tick`,
`mt5.positions_get` et `ensure_mt5_connected` sont monkeypatchés dans
CHAQUE test qui en a besoin, directement sur l'objet module chargé (pas sur
`MetaTrader5` importé ailleurs) — donc pas de risque de patcher le mauvais
module.
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

_BRIDGE_PATH = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


@pytest.fixture()
def bridge(monkeypatch):
    """Charge une instance FRAÎCHE de mt5-bridge/bridge.py pour chaque test.

    Fraîche à chaque test (pas de fixture module-scope) car le module porte
    de l'état mutable au niveau module (ex: `_breakeven_applied`,
    `_position_meta`) que d'autres tests pourraient sinon polluer.

    Exécuté avec cwd=mt5-bridge/ le temps de l'import : `bridge.py` ouvre
    `bridge.log` en chemin relatif au niveau module (FileHandler), et ce
    fichier est gitignored uniquement dans mt5-bridge/ (mt5-bridge/.gitignore
    contient `*.log`) — l'écrire ailleurs polluerait le repo avec un fichier
    non ignoré.
    """
    mod_name = f"_mt5_bridge_under_test_{id(monkeypatch)}"
    spec = importlib.util.spec_from_file_location(mod_name, _BRIDGE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    old_cwd = os.getcwd()
    os.chdir(_BRIDGE_PATH.parent)
    try:
        spec.loader.exec_module(mod)
    finally:
        os.chdir(old_cwd)
    # BRIDGE_API_KEY dépend de .env / génération aléatoire au chargement —
    # fixé ici pour que les tests HTTP soient déterministes.
    mod.BRIDGE_API_KEY = "test-key"
    yield mod
    del sys.modules[mod_name]


def _mk_symbol_info(**overrides):
    base = dict(
        digits=2, point=0.01, trade_stops_level=0,
        filling_mode=2, volume_min=0.01, volume_max=100.0, volume_step=0.01,
        trade_contract_size=100.0, trade_tick_value=1.0,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _mk_tick(bid=2650.0, ask=2650.2, time=1_700_000_000):
    return types.SimpleNamespace(bid=bid, ask=ask, time=time)


def _mk_order_result(retcode, order=123456, comment="ok", price=2650.1, volume=0.01):
    return types.SimpleNamespace(retcode=retcode, order=order, comment=comment, price=price, volume=volume)


def _mk_position(**overrides):
    base = dict(
        ticket=999, symbol="XAUUSD", type=0,  # 0 = POSITION_TYPE_BUY
        volume=0.01, price_open=2650.0, price_current=2650.5,
        sl=0.0, tp=0.0, profit=0.0, time=1_700_000_500, comment="",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ─────────────────────────────────────────────────────────────────────
# _clamp_stops — extraction pure, aucun call mt5.order_send
# ─────────────────────────────────────────────────────────────────────

def test_clamp_stops_noop_when_symbol_info_missing(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: None)
    sl, tp = bridge._clamp_stops("XAUUSD", True, 2640.0, 2660.0)
    assert (sl, tp) == (2640.0, 2660.0)


def test_clamp_stops_never_invents_a_missing_take_profit(bridge, monkeypatch):
    """new_tp == 0 ('pas de TP') doit rester 0, jamais devenir une valeur
    plausible poussée par le clamp de la forbidden zone."""
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info(trade_stops_level=50))
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick(bid=2650.0, ask=2650.2))
    sl, tp = bridge._clamp_stops("XAUUSD", True, 2640.0, 0.0)
    assert tp == 0.0


def test_clamp_stops_pushes_sl_out_of_forbidden_zone_for_buy(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info(point=0.01, trade_stops_level=50))
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick(bid=2650.0, ask=2650.2))
    # SL demandé bien trop proche du bid (dans la forbidden zone) → repoussé.
    sl, tp = bridge._clamp_stops("XAUUSD", True, 2649.99, 0.0)
    min_dist = max(50 * 0.01 * 1.2, 0.01 * 5)
    assert sl == pytest.approx(2650.0 - min_dist)


# ─────────────────────────────────────────────────────────────────────
# _apply_stops — un seul call TRADE_ACTION_SLTP, résultat structuré
# ─────────────────────────────────────────────────────────────────────

def test_apply_stops_ok_true_on_done(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))
    result = bridge._apply_stops(symbol="XAUUSD", ticket=1, new_sl=2640.0, new_tp=2660.0)
    assert result == {"ok": True, "sl": 2640.0, "tp": 2660.0, "retcode": bridge.mt5.TRADE_RETCODE_DONE, "error": None}


def test_apply_stops_ok_false_on_rejected_retcode(bridge, monkeypatch):
    monkeypatch.setattr(
        bridge.mt5, "order_send",
        lambda req: _mk_order_result(10016, comment="Invalid stops"),
    )
    result = bridge._apply_stops(symbol="XAUUSD", ticket=1, new_sl=2640.0, new_tp=2660.0)
    assert result["ok"] is False
    assert result["retcode"] == 10016
    assert result["error"] == "Invalid stops"


def test_apply_stops_ok_none_when_mt5_does_not_respond(bridge, monkeypatch):
    """order_send() → None : MT5 n'a pas répondu. L'état réel est INCONNU,
    ni protégé ni nu de façon certaine — ok doit être None, pas False."""
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: None)
    monkeypatch.setattr(bridge.mt5, "last_error", lambda: (1, "no connection"))
    result = bridge._apply_stops(symbol="XAUUSD", ticket=1, new_sl=2640.0, new_tp=2660.0)
    assert result["ok"] is None
    assert "no connection" in result["error"]


# ─────────────────────────────────────────────────────────────────────
# _apply_sltp_from_fill — LE fix : retourne un dict exploitable, plus None
# ─────────────────────────────────────────────────────────────────────

def test_apply_sltp_from_fill_returns_dict_on_success(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))
    result = bridge._apply_sltp_from_fill(
        symbol="XAUUSD", ticket=1, is_buy=True, fill=2650.0, sl_dist=5.0, tp_dist=10.0,
    )
    assert result["ok"] is True
    assert result["sl"] == pytest.approx(2645.0)
    assert result["tp"] == pytest.approx(2660.0)


def test_apply_sltp_from_fill_invalid_params_is_false_not_none(bridge):
    """fill<=0 : on SAIT qu'aucun ordre n'est parti → ok=False (pas None,
    qui est réservé au cas où MT5 ne répond pas à une tentative réelle)."""
    result = bridge._apply_sltp_from_fill(
        symbol="XAUUSD", ticket=1, is_buy=True, fill=0.0, sl_dist=5.0, tp_dist=10.0,
    )
    assert result["ok"] is False
    assert result["error"]


def test_apply_sltp_from_fill_symbol_info_none_is_false_not_none(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: None)
    result = bridge._apply_sltp_from_fill(
        symbol="XAUUSD", ticket=1, is_buy=True, fill=2650.0, sl_dist=5.0, tp_dist=10.0,
    )
    assert result["ok"] is False
    assert "symbol_info" in result["error"]


# ─────────────────────────────────────────────────────────────────────
# _send_market_order — régression directe de l'incident 2026-08-05
# ─────────────────────────────────────────────────────────────────────

def test_send_market_order_legacy_path_marks_stops_applied(bridge, monkeypatch):
    """Chemin absolu (sl_dist/tp_dist absents) : un fill réussi implique
    sl/tp acceptés dans la même transaction MT5."""
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))
    result = bridge._send_market_order("XAUUSD", "buy", 0.01, 2640.0, 2660.0, "test")
    assert result["ok"] is True
    assert result["sl_applied"] is True
    assert result["tp_applied"] is True
    assert result["sl_error"] is None


def test_send_market_order_use_dist_path_propagates_sltp_failure(bridge, monkeypatch):
    """LA régression de l'incident : le market order réussit, MAIS le
    TRADE_ACTION_SLTP qui pose le stop échoue ensuite. Avant le fix, ce cas
    produisait un dict SANS aucune trace de l'échec — l'appelant ne pouvait
    pas savoir que la position venait de rester nue. Après le fix, le dict
    retourné par `_send_market_order` doit exposer sl_applied=False et
    sl_error non vide, alors même que ok=True (le fill, lui, a réussi)."""
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())

    calls = {"n": 0}

    def _fake_order_send(req):
        calls["n"] += 1
        if req["action"] == bridge.mt5.TRADE_ACTION_DEAL:
            # Le market order lui-même réussit (position ouverte, sans SL/TP
            # puisque use_dist=True → sl=0/tp=0 dans la requête initiale).
            return _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE)
        # Le modify TRADE_ACTION_SLTP qui suit échoue (ex: 10016 réel de
        # l'incident, ou toute autre raison broker).
        return _mk_order_result(10016, comment="Invalid stops")

    monkeypatch.setattr(bridge.mt5, "order_send", _fake_order_send)

    result = bridge._send_market_order(
        "XAUUSD", "buy", 0.01, 2640.0, 2660.0, "test",
        sl_dist=5.0, tp_dist=10.0,
    )

    # Le fill a bien eu lieu (ok=True) : la position EST ouverte, comme dans
    # l'incident réel. C'est justement pour ça que l'ancien code répondait
    # {"ok": true} sans que rien ne signale l'absence de stop.
    assert result["ok"] is True
    # Mais la protection, elle, a échoué — et ça doit être visible.
    assert result["sl_applied"] is False
    assert result["tp_applied"] is False
    assert result["sl_error"] is not None
    assert "Invalid stops" in result["sl_error"]
    # Preuve que les DEUX appels ont bien eu lieu (deal + modify) — sinon le
    # test pourrait passer sans exercer le vrai chemin de code.
    assert calls["n"] == 2


def test_send_market_order_use_dist_path_success_marks_protected(bridge, monkeypatch):
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))
    result = bridge._send_market_order(
        "XAUUSD", "buy", 0.01, 2640.0, 2660.0, "test",
        sl_dist=5.0, tp_dist=10.0,
    )
    assert result["ok"] is True
    assert result["sl_applied"] is True
    assert result["sl_error"] is None


# ─────────────────────────────────────────────────────────────────────
# /order (Flask) — la réponse HTTP dit désormais la vérité, sans casser
# les champs déjà consommés par backend/services/mt5_bridge.py
# ─────────────────────────────────────────────────────────────────────

_BACKWARD_COMPAT_ORDER_PAYLOAD = {
    "pair": "XAU/USD", "direction": "buy", "entry": 2650.0,
    "sl": 2640.0, "tp": 2660.0, "lots": 0.01,
    "sl_dist": 5.0, "tp_dist": 10.0,
}


def test_order_route_live_success_exposes_protection_fields_without_breaking_legacy_ones(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "PAPER_MODE", False)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(bridge, "resolve_symbol", lambda pair: "XAUUSD")
    monkeypatch.setattr(bridge, "_check_safety_gates", lambda sym, direction, **kw: (True, "OK"))
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))

    client = bridge.app.test_client()
    resp = client.post("/order", json=_BACKWARD_COMPAT_ORDER_PAYLOAD, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.get_json()

    # Champs historiques — le backend en prod les lit tels quels, ne doivent
    # ni disparaître ni changer de type.
    assert body["ok"] is True
    assert body["mode"] == "live"
    assert isinstance(body["ticket"], int)
    assert "price" in body and "volume" in body

    # Champs additifs 2026-08-06.
    assert body["sl_applied"] is True
    assert body["tp_applied"] is True
    assert body["protected"] is True
    assert body["sl_error"] is None


def test_order_route_live_naked_fill_reports_unprotected(bridge, monkeypatch):
    """Reproduction bout-en-bout de l'incident via la route HTTP réelle :
    le fill réussit, le modify SLTP échoue → la réponse JSON doit dire
    protected=False, PAS ok=false ni un silence sur le sujet."""
    monkeypatch.setattr(bridge, "PAPER_MODE", False)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(bridge, "resolve_symbol", lambda pair: "XAUUSD")
    monkeypatch.setattr(bridge, "_check_safety_gates", lambda sym, direction, **kw: (True, "OK"))
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())

    def _fake_order_send(req):
        if req["action"] == bridge.mt5.TRADE_ACTION_DEAL:
            return _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE)
        return _mk_order_result(10016, comment="Invalid stops")

    monkeypatch.setattr(bridge.mt5, "order_send", _fake_order_send)

    client = bridge.app.test_client()
    resp = client.post("/order", json=_BACKWARD_COMPAT_ORDER_PAYLOAD, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["ok"] is True  # le fill a bien eu lieu
    assert body["protected"] is False  # mais AUCUN stop confirmé
    assert body["sl_applied"] is False
    assert body["sl_error"] and "Invalid stops" in body["sl_error"]


def test_order_route_requires_api_key(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "PAPER_MODE", True)
    client = bridge.app.test_client()
    resp = client.post("/order", json=_BACKWARD_COMPAT_ORDER_PAYLOAD)
    assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# _sltp_guard_eligible — le mécanisme d'exclusion, en isolation
# ─────────────────────────────────────────────────────────────────────

def test_guard_eligible_fails_closed_without_activation_timestamp(bridge):
    eligible, reason = bridge._sltp_guard_eligible(ticket=1, position_open_epoch=2_000_000_000)
    assert eligible is False
    assert "ACTIVATED_AT" in reason


def test_guard_eligible_frozen_ticket_blocks_regardless_of_timestamp(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_TICKETS", frozenset({42}))
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", 0)  # activé depuis epoch 0
    eligible, reason = bridge._sltp_guard_eligible(ticket=42, position_open_epoch=2_000_000_000)
    assert eligible is False
    assert "gelé" in reason


def test_guard_eligible_position_opened_before_activation_is_excluded(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", 1_700_000_000)
    eligible, reason = bridge._sltp_guard_eligible(ticket=1, position_open_epoch=1_699_999_999)
    assert eligible is False


def test_guard_eligible_position_opened_after_activation_is_eligible(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", 1_700_000_000)
    eligible, reason = bridge._sltp_guard_eligible(ticket=1, position_open_epoch=1_700_000_001)
    assert eligible is True


# ─────────────────────────────────────────────────────────────────────
# /position/sltp — la route, avec preuve par mutation que l'exclusion
# empêche VRAIMENT tout ordre de partir (pas seulement un refus cosmétique)
# ─────────────────────────────────────────────────────────────────────

def _sltp_client(bridge):
    return bridge.app.test_client()


def test_position_sltp_disabled_by_default_refuses_and_never_calls_mt5(bridge, monkeypatch):
    order_send_calls = []
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: order_send_calls.append(req))
    # SLTP_GUARD_ENABLED est False par défaut (pas monkeypatché) — la route
    # doit refuser AVANT même de toucher ensure_mt5_connected/positions_get.
    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 1, "sl_dist": 5.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 403
    assert order_send_calls == []


def test_position_sltp_frozen_ticket_is_never_touched(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_TICKETS", frozenset({999}))
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", 0)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(bridge.mt5, "positions_get", lambda ticket: [_mk_position(ticket=999, sl=0.0)])
    order_send_calls = []
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: order_send_calls.append(req))

    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 999, "sl_dist": 5.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["excluded"] is True
    assert order_send_calls == []  # LA preuve : rien n'est parti vers MT5


def test_position_sltp_opened_before_activation_is_never_touched(bridge, monkeypatch):
    """Le cas de l'incident : une position déjà ouverte au moment où le
    garde-fou est activé ne doit JAMAIS recevoir de stop automatique."""
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_TICKETS", frozenset())
    activation = 1_700_000_000
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", activation)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    # Position ouverte AVANT l'activation.
    monkeypatch.setattr(
        bridge.mt5, "positions_get",
        lambda ticket: [_mk_position(ticket=1, sl=0.0, time=activation - 3600)],
    )
    order_send_calls = []
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: order_send_calls.append(req))

    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 1, "sl_dist": 5.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 403
    assert resp.get_json()["excluded"] is True
    assert order_send_calls == []


def test_position_sltp_eligible_naked_position_gets_protected(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_TICKETS", frozenset())
    activation = 1_700_000_000
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", activation)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(
        bridge.mt5, "positions_get",
        lambda ticket: [_mk_position(ticket=1, sl=0.0, tp=0.0, price_open=2650.0, time=activation + 100)],
    )
    monkeypatch.setattr(bridge.mt5, "symbol_info", lambda s: _mk_symbol_info())
    monkeypatch.setattr(bridge.mt5, "symbol_info_tick", lambda s: _mk_tick())
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: _mk_order_result(bridge.mt5.TRADE_RETCODE_DONE))

    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 1, "sl_dist": 20.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["sl"] == pytest.approx(2630.0)  # BUY : price_open - sl_dist


def test_position_sltp_already_protected_is_a_noop(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "SLTP_GUARD_FROZEN_TICKETS", frozenset())
    activation = 1_700_000_000
    monkeypatch.setattr(bridge, "_SLTP_GUARD_ACTIVATED_AT_EPOCH", activation)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(
        bridge.mt5, "positions_get",
        lambda ticket: [_mk_position(ticket=1, sl=2600.0, time=activation + 100)],
    )
    order_send_calls = []
    monkeypatch.setattr(bridge.mt5, "order_send", lambda req: order_send_calls.append(req))

    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 1, "sl_dist": 20.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["already_protected"] is True
    assert order_send_calls == []


def test_position_sltp_unknown_ticket_returns_404(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    monkeypatch.setattr(bridge, "ensure_mt5_connected", lambda: True)
    monkeypatch.setattr(bridge.mt5, "positions_get", lambda ticket: [])
    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 404, "sl_dist": 5.0}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 404


def test_position_sltp_missing_fields_returns_400(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "SLTP_GUARD_ENABLED", True)
    client = _sltp_client(bridge)
    resp = client.post("/position/sltp", json={"ticket": 1}, headers={"X-API-Key": "test-key"})
    assert resp.status_code == 400
