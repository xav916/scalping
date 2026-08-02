"""Tests pour ``bridge_destinations.resolve_destinations()``.

Phase A.1 du chantier multi-tenant bridge routing — V1 ne résout qu'admin
legacy depuis l'env. Phase C ajoutera la résolution des users Premium.

Les patches sont appliqués sur ``mt5_bridge`` parce que
``_admin_legacy_destination()`` lit la config legacy via ce module (lazy
import) — voir le module bridge_destinations pour le rationale.
"""
import dataclasses
from unittest.mock import MagicMock

import pytest

from backend.services import bridge_destinations, mt5_bridge


def _mk_setup(pair: str = "EUR/USD") -> MagicMock:
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock(value="buy")
    s.entry_price = 1.0
    return s


def _set_admin_env(monkeypatch, **overrides):
    """Helper : force la config admin legacy via patches sur mt5_bridge."""
    defaults = {
        "MT5_BRIDGE_ENABLED": True,
        "MT5_BRIDGE_URL": "http://admin-bridge:8787",
        "MT5_BRIDGE_API_KEY": "x" * 32,
        "MT5_BRIDGE_MIN_CONFIDENCE": 55.0,
        "MT5_BRIDGE_ALLOWED_ASSET_CLASSES": ["forex", "metal"],
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(mt5_bridge, name, value)


# ─── admin_legacy résolu correctement ─────────────────────────────────


def test_admin_legacy_returned_when_env_set(monkeypatch):
    """Admin legacy doit être présent quand ENABLED + URL + KEY sont set."""
    _set_admin_env(monkeypatch)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert len(dests) == 1
    admin = dests[0]
    assert admin.destination_id == "admin_legacy"
    assert admin.user_id is None
    assert admin.bridge_url == "http://admin-bridge:8787"
    assert admin.bridge_api_key == "x" * 32
    assert admin.min_confidence == 55.0
    assert admin.allowed_asset_classes == frozenset({"forex", "metal"})
    assert admin.auto_exec_enabled is True


def test_admin_legacy_strips_trailing_slash(monkeypatch):
    """``bridge_url`` ne doit pas avoir de slash final."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_URL="http://admin-bridge:8787/")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].bridge_url == "http://admin-bridge:8787"


def test_bridge_config_is_frozen(monkeypatch):
    """Une ``BridgeConfig`` doit être immuable (frozen=True)."""
    _set_admin_env(monkeypatch)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    with pytest.raises(dataclasses.FrozenInstanceError):
        dests[0].destination_id = "user:1"  # type: ignore[misc]


# ─── admin_legacy court-circuité quand env manquant ───────────────────


def test_no_destinations_when_disabled(monkeypatch):
    """``MT5_BRIDGE_ENABLED=False`` → aucune destination admin_legacy."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_url_missing(monkeypatch):
    """URL vide → admin pas dans la liste."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_URL="")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_no_destinations_when_api_key_missing(monkeypatch):
    """API key vide → admin pas dans la liste."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_API_KEY="")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


# ─── placeholder Phase C ──────────────────────────────────────────────


def test_no_destinations_when_admin_off_and_no_users(monkeypatch):
    """Admin off + aucun user éligible → liste vide."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


# ─── Phase C : user destinations ──────────────────────────────────────


def _stub_premium_user(
    user_id: int = 42,
    bridge_url: str = "http://user-bridge:8787",
    bridge_api_key: str = "u" * 32,
    watched_pairs: list[str] | None = None,
) -> dict:
    return {
        "id": user_id,
        "email": "test@example.com",
        "broker_config": {
            "bridge_url": bridge_url,
            "bridge_api_key": bridge_api_key,
            "auto_exec_enabled": True,
        },
        "watched_pairs": watched_pairs if watched_pairs is not None else ["EUR/USD"],
    }


def test_premium_user_returned_when_pair_in_watchlist(monkeypatch):
    """Premium user + auto_exec + pair in watchlist → BridgeConfig avec user:id."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)  # admin off pour isoler
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 1
    user_dest = dests[0]
    assert user_dest.destination_id == "user:42"
    assert user_dest.user_id == 42
    assert user_dest.bridge_url == "http://user-bridge:8787"
    assert user_dest.bridge_api_key == "u" * 32
    assert user_dest.auto_exec_enabled is True


def test_premium_user_excluded_when_pair_not_in_watchlist(monkeypatch):
    """Pair pas dans watched_pairs du user → exclu."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(watched_pairs=["XAU/USD"])],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests == []


def test_admin_and_user_returned_in_order(monkeypatch):
    """Admin + user Premium → admin en premier (rétro-compat), user après."""
    _set_admin_env(monkeypatch)  # admin actif
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 2
    assert dests[0].destination_id == "admin_legacy"
    assert dests[1].destination_id == "user:42"


def test_multiple_users_returned(monkeypatch):
    """Deux users Premium éligibles → deux destinations."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [
            _stub_premium_user(user_id=42),
            _stub_premium_user(user_id=43),
        ],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert {d.destination_id for d in dests} == {"user:42", "user:43"}


def test_user_destinations_resilient_to_users_service_error(monkeypatch):
    """Si users_service raise, retomber sur [] (pas de crash global)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)

    def boom():
        raise RuntimeError("DB unreachable")

    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", boom
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests == []  # safe fallback


def test_user_destination_skipped_on_malformed_broker_config(monkeypatch):
    """broker_config sans bridge_api_key → ce user-là est skip, les autres passent."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    bad = _stub_premium_user(user_id=99)
    bad["broker_config"] = {"auto_exec_enabled": True}  # manque bridge_api_key
    good = _stub_premium_user(user_id=42)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [bad, good],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    # Seul le user bien configuré passe
    assert {d.destination_id for d in dests} == {"user:42"}


def test_premium_user_ea_only_without_bridge_url(monkeypatch):
    """EA-only user (broker_config sans bridge_url) → inclus, bridge_url='' dans
    le BridgeConfig. Le path EA queue (mt5_bridge.send_setup user_id is not None)
    n'utilise jamais bridge_url, donc pas de crash en aval. Cf. fix Cédric 2026-05-05.
    """
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    ea_user = _stub_premium_user(user_id=17)
    ea_user["broker_config"] = {
        "auto_exec_enabled": True,
        "bridge_api_key": "u" * 32,
        # pas de bridge_url
    }
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [ea_user],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 1
    assert dests[0].destination_id == "user:17"
    assert dests[0].bridge_url == ""


# ─── symbol_map flow (multi-tenant broker mapping) ────────────────────


def test_user_destination_no_symbol_map_by_default(monkeypatch):
    """broker_config sans ``symbol_map`` → ``BridgeConfig.symbol_map`` est None."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 1
    assert dests[0].symbol_map is None


def test_user_destination_picks_up_symbol_map_from_broker_config(monkeypatch):
    """broker_config.symbol_map → BridgeConfig.symbol_map dict.

    Permet le mapping multi-tenant : un user Pepperstone UK mappe
    XAU/USD → GOLD, alors qu'un autre sur Razor garde le strip-slash par
    défaut côté EA. Driver = bug Cédric 2026-06-11 (152 dispatch/0 exec).
    """
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    user = _stub_premium_user(user_id=2)
    user["broker_config"]["symbol_map"] = {
        "XAU/USD": "GOLD",
        "ETH/USD": "ETHUSD",
        "WTI/USD": "USOIL",
    }
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [user],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert len(dests) == 1
    assert dests[0].symbol_map == {
        "XAU/USD": "GOLD",
        "ETH/USD": "ETHUSD",
        "WTI/USD": "USOIL",
    }


def test_user_destination_empty_symbol_map_normalized_to_none(monkeypatch):
    """broker_config.symbol_map={} → traité comme None (pas d'injection inutile)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    user = _stub_premium_user(user_id=42)
    user["broker_config"]["symbol_map"] = {}
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [user],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests[0].symbol_map is None


def test_user_destination_invalid_symbol_map_type_ignored(monkeypatch):
    """broker_config.symbol_map non-dict (str, list, etc.) → None safe fallback."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    user = _stub_premium_user(user_id=42)
    user["broker_config"]["symbol_map"] = "XAU/USD=GOLD"  # malformé
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [user],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert dests[0].symbol_map is None


# ─── admin_live : 2e destination admin parallèle (Demo + Live) ────────


def _set_live_env(monkeypatch, **overrides):
    """Helper : force la config admin LIVE via patches sur config.settings."""
    from config import settings as st
    defaults = {
        "MT5_BRIDGE_LIVE_ENABLED": True,
        "MT5_BRIDGE_LIVE_URL": "http://live-bridge:8788",
        "MT5_BRIDGE_LIVE_API_KEY": "L" * 32,
        "MT5_BRIDGE_LIVE_MIN_CONFIDENCE": 75.0,
        "MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES": ["forex", "metal", "energy"],
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(st, name, value)


def test_admin_live_returned_when_env_set(monkeypatch):
    """MT5_BRIDGE_LIVE_* set → admin_live BridgeConfig retourné."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)  # désactive Demo pour isoler
    _set_live_env(monkeypatch)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert len(dests) == 1
    live = dests[0]
    assert live.destination_id == "admin_live"
    assert live.user_id is None
    assert live.bridge_url == "http://live-bridge:8788"
    assert live.bridge_api_key == "L" * 32
    assert live.min_confidence == 75.0
    assert live.allowed_asset_classes == frozenset({"forex", "metal", "energy"})


def test_admin_live_excluded_when_disabled(monkeypatch):
    """MT5_BRIDGE_LIVE_ENABLED=false → admin_live PAS retourné même si URL/KEY set."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    _set_live_env(monkeypatch, MT5_BRIDGE_LIVE_ENABLED=False)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_admin_live_excluded_when_url_missing(monkeypatch):
    """URL Live vide → admin_live PAS retourné (safe fallback)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    _set_live_env(monkeypatch, MT5_BRIDGE_LIVE_URL="")
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_admin_live_excluded_when_api_key_missing(monkeypatch):
    """API_KEY Live vide → admin_live PAS retourné (safe fallback)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    _set_live_env(monkeypatch, MT5_BRIDGE_LIVE_API_KEY="")
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests == []


def test_admin_legacy_and_live_returned_together(monkeypatch):
    """Demo + Live actifs → 2 destinations admin dans l'ordre (legacy puis live).

    Cas d'usage 2026-06-12 : Demo Pepperstone continue + Live IC Markets en
    parallèle pour comparer side-by-side.
    """
    _set_admin_env(monkeypatch)  # Demo ON
    _set_live_env(monkeypatch)   # Live ON
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert [d.destination_id for d in dests] == ["admin_legacy", "admin_live"]
    assert dests[0].bridge_url == "http://admin-bridge:8787"
    assert dests[1].bridge_url == "http://live-bridge:8788"


def test_admin_live_and_users_returned_together(monkeypatch):
    """Live + Premium users actifs → admin_live d'abord, puis users (Demo off)."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)  # Demo off
    _set_live_env(monkeypatch)
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users",
        lambda: [_stub_premium_user(user_id=42)],
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup("EUR/USD"))

    assert [d.destination_id for d in dests] == ["admin_live", "user:42"]


def test_admin_live_uses_legacy_defaults_when_overrides_absent(monkeypatch):
    """Si MT5_BRIDGE_LIVE_MIN_CONFIDENCE non set, fallback sur MT5_BRIDGE_MIN_CONFIDENCE.

    Permet de configurer Live avec juste URL/KEY/ENABLED, sans dupliquer
    min_confidence et asset classes.
    """
    from config import settings as st
    _set_admin_env(monkeypatch, MT5_BRIDGE_ENABLED=False)
    # Live activé avec juste URL/KEY/ENABLED, les autres restent valeurs par défaut
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ENABLED", True)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_URL", "http://live:8788")
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_API_KEY", "L" * 32)
    # min_confidence + asset_classes : utiliser ce qui est dans settings live
    # (qui est lui-même chargé via os.getenv au boot, mais on ne le re-évalue pas
    # ici — on vérifie juste que ces fields sont set sur le BridgeConfig)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_MIN_CONFIDENCE", 90.0)
    monkeypatch.setattr(st, "MT5_BRIDGE_LIVE_ALLOWED_ASSET_CLASSES", ["forex", "metal"])
    monkeypatch.setattr(
        "backend.services.users_service.list_premium_auto_exec_users", lambda: []
    )

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert len(dests) == 1
    assert dests[0].destination_id == "admin_live"
    assert dests[0].min_confidence == 90.0
    assert dests[0].allowed_asset_classes == frozenset({"forex", "metal"})


# ─── admin_legacy : overrides MT5_BRIDGE_LEGACY_* (2026-07-29) ────────
# Permet d'aligner Demo sur Live comme miroir pour tester avant promotion,
# sans toucher aux globals partagés avec les user:N destinations.


def test_admin_legacy_min_confidence_override_from_env(monkeypatch):
    """MT5_BRIDGE_LEGACY_MIN_CONFIDENCE=60 override le global (55.0 dans _set_admin_env)."""
    _set_admin_env(monkeypatch)  # global = 55.0
    monkeypatch.setenv("MT5_BRIDGE_LEGACY_MIN_CONFIDENCE", "60")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert len(dests) == 1
    assert dests[0].destination_id == "admin_legacy"
    assert dests[0].min_confidence == 60.0  # override respecté, pas 55.0


def test_admin_legacy_min_confidence_fallback_to_global_when_env_missing(monkeypatch):
    """Sans MT5_BRIDGE_LEGACY_MIN_CONFIDENCE → fallback global mt5_bridge.MT5_BRIDGE_MIN_CONFIDENCE."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_MIN_CONFIDENCE=72.0)
    monkeypatch.delenv("MT5_BRIDGE_LEGACY_MIN_CONFIDENCE", raising=False)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].min_confidence == 72.0  # rétro-compat globale


def test_admin_legacy_allowed_asset_classes_override_from_env(monkeypatch):
    """MT5_BRIDGE_LEGACY_ALLOWED_ASSET_CLASSES restreint la classe autorisée Demo."""
    _set_admin_env(monkeypatch)  # global = [forex, metal]
    monkeypatch.setenv("MT5_BRIDGE_LEGACY_ALLOWED_ASSET_CLASSES", "metal")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].allowed_asset_classes == frozenset({"metal"})


def test_admin_legacy_allowed_asset_classes_fallback_when_env_missing(monkeypatch):
    """Sans override, fallback sur le global."""
    _set_admin_env(monkeypatch, MT5_BRIDGE_ALLOWED_ASSET_CLASSES=["forex", "crypto"])
    monkeypatch.delenv("MT5_BRIDGE_LEGACY_ALLOWED_ASSET_CLASSES", raising=False)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].allowed_asset_classes == frozenset({"forex", "crypto"})


def test_admin_legacy_extra_pairs_from_env(monkeypatch):
    """MT5_BRIDGE_LEGACY_EXTRA_PAIRS ajoute des pairs autorisées en plus des stars.

    Miroir strict du pattern MT5_BRIDGE_LIVE_EXTRA_PAIRS — permet à Demo
    d'accepter EUR/USD (non-star) sans que le filtre stars-only l'écarte.
    """
    _set_admin_env(monkeypatch)
    monkeypatch.setenv("MT5_BRIDGE_LEGACY_EXTRA_PAIRS", "EUR/USD, GBP/JPY")

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].extra_pairs_allowed == frozenset({"EUR/USD", "GBP/JPY"})


def test_admin_legacy_extra_pairs_empty_by_default(monkeypatch):
    """Sans env var → frozenset() vide (comportement legacy inchangé)."""
    _set_admin_env(monkeypatch)
    monkeypatch.delenv("MT5_BRIDGE_LEGACY_EXTRA_PAIRS", raising=False)

    dests = bridge_destinations.resolve_destinations(_mk_setup())

    assert dests[0].extra_pairs_allowed == frozenset()


# ─── admin_kraken_spot long-only filter (Gap 4 2026-08-02) ────────────


def _set_kraken_spot_env(monkeypatch):
    """Active la destination admin_kraken_spot via config.settings."""
    from config import settings as st
    monkeypatch.setattr(st, "KRAKEN_SPOT_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "KRAKEN_SPOT_BRIDGE_URL", "http://127.0.0.1:8791", raising=False)
    monkeypatch.setattr(st, "KRAKEN_SPOT_BRIDGE_API_KEY", "y" * 32, raising=False)
    monkeypatch.setattr(st, "KRAKEN_SPOT_BRIDGE_MIN_CONFIDENCE", 75.0, raising=False)


def test_admin_kraken_spot_included_when_buy(monkeypatch):
    """Signal BUY sur crypto → admin_kraken_spot doit être présent."""
    _set_admin_env(monkeypatch)
    _set_kraken_spot_env(monkeypatch)

    setup = _mk_setup(pair="BTC/USD")
    setup.direction = MagicMock(value="buy")

    dests = bridge_destinations.resolve_destinations(setup)
    ids = [d.destination_id for d in dests]

    assert "admin_kraken_spot" in ids


def test_admin_kraken_spot_excluded_when_sell(monkeypatch):
    """Signal SELL sur crypto → admin_kraken_spot doit être filtré (long-only)."""
    _set_admin_env(monkeypatch)
    _set_kraken_spot_env(monkeypatch)

    setup = _mk_setup(pair="BTC/USD")
    setup.direction = MagicMock(value="sell")

    dests = bridge_destinations.resolve_destinations(setup)
    ids = [d.destination_id for d in dests]

    assert "admin_kraken_spot" not in ids
