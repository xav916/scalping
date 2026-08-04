"""Sizing par destination (2026-08-04).

`compute_risk_money` sizait **toujours** sur le `TRADING_CAPITAL` global
(3 000 €). Sur le compte Kraken, qui vaut 103,60 USD, cela produisait :

    qty = risk_money / |entry - sl| = 30 / 188,90 = 0,1588 BTC
        ≈ 10 175 USD de notionnel, soit ~20× la capacité du compte

Kraken rejetait en `invalidSize`. C'est la raison pour laquelle aucun ordre
n'y est jamais passé — découvert le 2026-08-04 en remontant la chaîne
d'exécution couche par couche.

Les bridges MT5 ne le voyaient pas : ils ramènent le volume au minimum du
broker côté bridge. Les bridges crypto envoient la quantité telle quelle.

⚠️ **En cas de doute, refuser de trader.** Retomber sur le capital global
reproduirait exactement le défaut. C'est la même leçon que
`VALID_DESTINATIONS` : un repli qui élargit n'est pas un repli sûr.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.services import sizing


@pytest.fixture(autouse=True)
def _cache_propre():
    sizing._BALANCE_CACHE.clear()
    yield
    sizing._BALANCE_CACHE.clear()


def _dest(bridge_type="kraken", dest_id="admin_kraken", trading_capital=None):
    return NS(destination_id=dest_id, bridge_type=bridge_type,
              bridge_url="http://bridge:8790", bridge_api_key="k",
              trading_capital=trading_capital)


def _setup(score=75.0):
    return NS(pair="BTC/USD", direction=NS(value="sell"),
              confidence_score=score, entry_price=64064.70, stop_loss=64253.60)


# --- la cascade de résolution ---------------------------------------------

def test_sans_destination_le_capital_reste_global():
    """Chemin legacy mono-tenant : rien ne doit changer."""
    from config.settings import TRADING_CAPITAL
    assert sizing.destination_capital(None) == (TRADING_CAPITAL, "global")


def test_les_bridges_mt5_gardent_le_capital_global():
    """Leur sizing est reclampé côté bridge : ne pas y toucher."""
    from config.settings import TRADING_CAPITAL
    cap, src = sizing.destination_capital(_dest(bridge_type="mt5", dest_id="admin_live"))
    assert (cap, src) == (TRADING_CAPITAL, "global")


def test_la_surcharge_explicite_prime():
    assert sizing.destination_capital(_dest(trading_capital=250.0)) == (250.0, "destination")


def test_bridge_crypto_sans_solde_en_cache_refuse():
    """LE point du correctif : pas de repli sur le global."""
    cap, src = sizing.destination_capital(_dest())
    assert cap is None
    assert src == sizing.CAPITAL_UNAVAILABLE


def test_bridge_crypto_avec_solde_en_cache():
    sizing._cache_put("admin_kraken", 103.60)
    assert sizing.destination_capital(_dest()) == (103.60, "live")


# --- le calcul du risque ---------------------------------------------------

def test_le_risque_suit_le_capital_de_la_destination():
    sizing._cache_put("admin_kraken", 103.60)
    sz = sizing.compute_risk_money(_setup(), _dest())
    assert sz["capital"] == 103.60
    assert sz["capital_source"] == "live"
    # base = 1 % de 103,60, puis multiplicateurs
    assert sz["base"] == pytest.approx(1.04, abs=0.01)


def test_capital_indisponible_donne_un_risque_nul():
    """Fail-closed : les clients rejettent ensuite sur `qty <= 0`."""
    sz = sizing.compute_risk_money(_setup(), _dest())
    assert sz["risk_money"] == 0.0
    assert sz["capital"] is None
    assert sz["capital_source"] == sizing.CAPITAL_UNAVAILABLE


def test_l_incident_ne_peut_plus_se_reproduire():
    """Le scénario exact : 103,60 USD de compte, BTC à 64 064.

    Avant correctif : qty 0,1588 BTC ≈ 10 175 USD, soit ~20× le compte.
    """
    sizing._cache_put("admin_kraken", 103.60)
    s = _setup()
    sz = sizing.compute_risk_money(s, _dest())
    qty = sz["risk_money"] / abs(s.entry_price - s.stop_loss)
    notionnel = qty * s.entry_price
    assert notionnel < 103.60 * 5, f"notionnel {notionnel:.0f} USD au-delà du levier 5"
    assert qty < 0.01, f"qty {qty} encore de l'ordre de l'ancienne (0,1588)"


def test_le_chemin_global_reste_intact():
    """Régression : le sizing MT5 ne doit pas bouger d'un centime.

    La destination doit être cohérente : `admin_kraken` avec
    `bridge_type="mt5"` n'existe pas, et depuis l'ajout du plafond de
    notionnel — déclaré par destination — cet identifiant apportait le
    plafond crypto de 2× sur un chemin censé être MT5.
    """
    avant = sizing.compute_risk_money(_setup())
    apres = sizing.compute_risk_money(
        _setup(), _dest(bridge_type="mt5", dest_id="admin_live"))
    assert avant["risk_money"] == apres["risk_money"]
    assert avant["capital"] == apres["capital"]


# --- le rafraîchissement du solde -----------------------------------------

def _client_http(payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): return _Resp()
    return _Client


def test_le_refresh_alimente_le_cache(monkeypatch):
    import asyncio, httpx
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: _client_http({"portfolio_value_usd": 103.60})())
    cap = asyncio.run(sizing.refresh_destination_capital(_dest()))
    assert cap == 103.60
    assert sizing.destination_capital(_dest()) == (103.60, "live")


@pytest.mark.parametrize("payload,status", [
    ({"portfolio_value_usd": 0}, 200),
    ({"ok": False}, 200),
    ({}, 500),
])
def test_le_refresh_refuse_plutot_que_de_deviner(monkeypatch, payload, status):
    """Solde nul, clé absente ou HTTP en erreur : pas de capital inventé."""
    import asyncio, httpx
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **k: _client_http(payload, status)())
    assert asyncio.run(sizing.refresh_destination_capital(_dest())) is None
    assert sizing.destination_capital(_dest())[1] == sizing.CAPITAL_UNAVAILABLE


def test_bridge_injoignable_ne_leve_pas(monkeypatch):
    import asyncio, httpx
    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Boom())
    assert asyncio.run(sizing.refresh_destination_capital(_dest())) is None


def test_le_cache_evite_un_second_appel(monkeypatch):
    import asyncio, httpx
    appels = {"n": 0}
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            appels["n"] += 1
            return type("R", (), {"status_code": 200,
                                  "json": lambda self: {"portfolio_value_usd": 103.6}})()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client())
    asyncio.run(sizing.refresh_destination_capital(_dest()))
    asyncio.run(sizing.refresh_destination_capital(_dest()))
    assert appels["n"] == 1


def test_chaque_destination_a_son_propre_solde(monkeypatch):
    sizing._cache_put("admin_kraken", 103.60)
    sizing._cache_put("admin_kraken_spot", 107.82)
    assert sizing.destination_capital(_dest(dest_id="admin_kraken"))[0] == 103.60
    assert sizing.destination_capital(
        _dest(bridge_type="kraken_spot", dest_id="admin_kraken_spot"))[0] == 107.82


# --- le câblage dans le dispatch ------------------------------------------

def _dest_dispatch(bridge_type, dest_id):
    return NS(destination_id=dest_id, bridge_type=bridge_type,
              bridge_url="http://bridge:8790", bridge_api_key="k",
              trading_capital=None, user_id=None, min_confidence=0.0,
              allowed_asset_classes=frozenset({"crypto"}),
              excluded_pairs=frozenset(), auto_exec_enabled=True,
              extra_pairs_allowed=frozenset(), allowed_patterns=frozenset(),
              symbol_map=None, leverage=5)


@pytest.mark.parametrize("bridge_type,client_mod,client_fn,dest_id", [
    ("kraken", "kraken_bridge_client", "push_to_kraken", "admin_kraken"),
    ("kraken_spot", "kraken_spot_bridge_client", "push_to_kraken_spot", "admin_kraken_spot"),
    ("binance", "binance_bridge_client", "push_to_binance", "admin_binance"),
])
def test_le_dispatch_passe_bien_dest_au_sizing(monkeypatch, bridge_type, client_mod,
                                               client_fn, dest_id):
    """Sans ce câblage, le sizing retomberait sur le capital global.

    ⚠️ Tester `sizing` isolément ne suffit pas : c'est l'oubli du paramètre
    dans `_push_to_destination` qui a produit le défaut d'origine.
    """
    import asyncio, importlib
    from unittest.mock import patch
    from backend.services import mt5_bridge

    recu = {}

    def _fake_compute(setup, dest=None):
        recu["dest"] = dest
        return {"risk_money": 1.0, "capital": 103.6, "capital_source": "live"}

    async def _fake_refresh(dest):
        recu["refresh"] = getattr(dest, "destination_id", None)
        return 103.6

    async def _fake_push(setup, sz, dest):
        recu["pushed"] = True

    client = importlib.import_module(f"backend.services.{client_mod}")
    setup = NS(pair="BTC/USD", direction=NS(value="sell"), confidence_score=90,
               entry_price=64064.70, stop_loss=64253.60, take_profit_1=63000.0,
               take_profit_2=None, verdict_action="TAKE", verdict_blockers=[],
               is_simulated=False, pattern=None)

    with patch("backend.services.sizing.compute_risk_money", _fake_compute), \
         patch("backend.services.sizing.refresh_destination_capital", _fake_refresh), \
         patch.object(client, client_fn, _fake_push), \
         patch.object(mt5_bridge, "_check_rejection", return_value=None):
        asyncio.run(mt5_bridge._push_to_destination(
            setup, _dest_dispatch(bridge_type, dest_id)))

    assert recu.get("pushed"), "le client n'a pas été appelé"
    assert recu["refresh"] == dest_id, "le solde n'a pas été rafraîchi pour cette destination"
    assert recu["dest"] is not None, "compute_risk_money appelé SANS dest"
    assert recu["dest"].destination_id == dest_id
