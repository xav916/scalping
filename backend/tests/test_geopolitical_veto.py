"""Tests pour `backend.services.geopolitical_veto.apply`.

Couvre les 4 règles V1 + master switch + best-effort.
Tous les snapshots Polymarket/GDELT sont mockés via patch direct des services.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.services import geopolitical_veto


def _poly_market(question: str, yes_prob: float, days: int, theme: str = "geopolitical") -> dict:
    """Forge une entrée Polymarket pour les tests."""
    end_date = (date.today() + timedelta(days=days)).isoformat()
    return {
        "question": question,
        "slug": "test-slug",
        "event_slug": "test-event",
        "yes_prob": yes_prob,
        "no_prob": round(1 - yes_prob, 3),
        "volume_24h": 1_000_000,
        "liquidity": 100_000,
        "end_date": end_date,
        "matched_themes": [theme],
    }


def _poly_snapshot(by_theme: dict[str, list[dict]]) -> dict:
    """Forge un snapshot Polymarket complet."""
    all_themes = {"monetary": [], "geopolitical": [], "economy": [], "crypto": [], "politics": []}
    all_themes.update(by_theme)
    return {
        "fetched_at": "2026-05-08T10:00:00Z",
        "n_total_fetched": 200,
        "n_matched": sum(len(v) for v in all_themes.values()),
        "themes": all_themes,
        "top_volume": [],
    }


def _gdelt_snapshot(overall_stress: str, geo_stress: str, geo_tone: float = -8.0) -> dict:
    return {
        "fetched_at": "2026-05-08T10:00:00Z",
        "timespan": "24h",
        "overall_stress": overall_stress,
        "overall_tone": -2.0,
        "themes": {
            "geopolitical": {
                "theme": "geopolitical",
                "avg_tone": geo_tone,
                "volume": 100,
                "stress_level": geo_stress,
                "samples": 96,
            },
        },
    }


# ─── Master switch ───────────────────────────────────────────────────


def test_disabled_master_returns_no_veto():
    """GEOPOLITICAL_VETO_ENABLED=false → court-circuit complet."""
    with patch.object(geopolitical_veto, "GEOPOLITICAL_VETO_ENABLED", False):
        vetoed, reasons, meta = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False
    assert reasons == []
    assert meta == {}


def _enable_all_rules(monkeypatch):
    """Active master + toutes les règles à leurs seuils par défaut."""
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_ENABLED", True)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED", True)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_IRAN_HORMUZ_PROB", 0.30)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_IRAN_HORMUZ_DAYS", 14)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_FED_DOVISH_ENABLED", True)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_FED_DOVISH_PROB", 0.70)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_FED_DOVISH_DAYS", 14)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_RECESSION_ENABLED", True)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_RECESSION_PROB", 0.50)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_GDELT_STRESS_ENABLED", True)


def _patch_snapshots(monkeypatch, poly: dict | None, gdelt: dict | None):
    """Mock les services polymarket + gdelt."""
    from backend.services import polymarket_service, geopolitical_news_service
    monkeypatch.setattr(polymarket_service, "get_current", lambda: poly)
    monkeypatch.setattr(geopolitical_news_service, "get_current", lambda: gdelt)


# ─── Règle 1 : IRAN_HORMUZ ────────────────────────────────────────────


def test_iran_hormuz_vetoes_long_xau(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Will Iran sign a permanent peace deal by 2026-05-31?", 0.40, 10),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, reasons, meta = geopolitical_veto.apply("XAU/USD", "buy")

    assert vetoed is True
    assert "iran_hormuz" in meta["rules_matched"]
    assert "Iran peace deal prob 40%" in reasons[0]


def test_iran_hormuz_vetoes_long_wti_and_xag(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("US x Iran permanent peace deal by 2026-05-31?", 0.35, 12),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    for pair in ("WTI/USD", "XAG/USD"):
        vetoed, _, _ = geopolitical_veto.apply(pair, "buy")
        assert vetoed is True, f"expected veto on long {pair}"


def test_iran_hormuz_no_veto_below_prob_threshold(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-05-31?", 0.20, 10),  # < 30%
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, reasons, _ = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False


def test_iran_hormuz_no_veto_when_too_far(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-12-31?", 0.40, 200),  # > 14j
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False


def test_iran_hormuz_no_veto_on_short(monkeypatch):
    """Sell XAU = side qui PROFITE d'un peace deal → ne pas veto."""
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-05-31?", 0.50, 10),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("XAU/USD", "sell")
    assert vetoed is False


def test_iran_hormuz_no_veto_on_non_safe_haven_pair(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-05-31?", 0.50, 10),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("EUR/USD", "buy")
    assert vetoed is False


def test_iran_hormuz_disabled_individually(monkeypatch):
    _enable_all_rules(monkeypatch)
    monkeypatch.setattr(geopolitical_veto, "GEOPOLITICAL_VETO_IRAN_HORMUZ_ENABLED", False)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-05-31?", 0.80, 5),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False


# ─── Règle 2 : FED_DOVISH ────────────────────────────────────────────


def test_fed_dovish_vetoes_buy_usd_jpy(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"monetary": [
        _poly_market("Will Fed announce rate cut by 2026-05-15?", 0.80, 7, theme="monetary"),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, reasons, _ = geopolitical_veto.apply("USD/JPY", "buy")
    assert vetoed is True
    assert "Fed cut" in reasons[0]


def test_fed_dovish_vetoes_sell_eur_usd(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"monetary": [
        _poly_market("Fed rate cut by 2026-05-15?", 0.75, 7, theme="monetary"),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("EUR/USD", "sell")
    assert vetoed is True


def test_fed_dovish_no_veto_on_buy_eur_usd(monkeypatch):
    """Buy EUR/USD = USD-bear, c'est le sens cohérent avec un cut → pas de veto."""
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"monetary": [
        _poly_market("Fed rate cut by 2026-05-15?", 0.80, 7, theme="monetary"),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("EUR/USD", "buy")
    assert vetoed is False


def test_fed_dovish_below_threshold(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"monetary": [
        _poly_market("Fed rate cut by 2026-05-15?", 0.50, 7, theme="monetary"),  # < 70
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("USD/JPY", "buy")
    assert vetoed is False


# ─── Règle 3 : RECESSION ─────────────────────────────────────────────


def test_recession_vetoes_long_spx(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"economy": [
        _poly_market("Will US enter recession in 2026?", 0.65, 200, theme="economy"),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, reasons, _ = geopolitical_veto.apply("SPX", "buy")
    assert vetoed is True
    assert "Recession prob 65%" in reasons[0]


def test_recession_no_veto_on_short(monkeypatch):
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"economy": [
        _poly_market("US recession 2026?", 0.65, 200, theme="economy"),
    ]})
    _patch_snapshots(monkeypatch, poly, None)

    vetoed, _, _ = geopolitical_veto.apply("SPX", "sell")
    assert vetoed is False


# ─── Règle 4 : GDELT_HIGH_STRESS ─────────────────────────────────────


def test_gdelt_high_stress_vetoes_long_eu_indices(monkeypatch):
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="high")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, reasons, _ = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is True
    assert "GDELT stress" in reasons[0]


def test_gdelt_elevated_stress_vetoes_long_eu_indices(monkeypatch):
    """v2026-06-11 : 'elevated' désormais accepté comme 'high'. Avant cette
    date la règle exigeait strict 'high' et ne matchait jamais en régime
    macro normal — d'où désactivation par flag. Cf. project_geopolitical_veto_*.
    """
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="elevated", geo_stress="elevated")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, reasons, _ = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is True
    assert "elevated" in reasons[0]


def test_gdelt_mixed_high_elevated_vetoes_long_eu_indices(monkeypatch):
    """overall=high + theme geo=elevated → veto (chaque niveau ∈ trigger set)."""
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="elevated")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, _, _ = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is True


def test_gdelt_normal_overall_no_veto(monkeypatch):
    """overall_stress ∉ {high, elevated} → pas de veto même si theme=high."""
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="normal", geo_stress="high")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, _, _ = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is False


def test_gdelt_normal_theme_no_veto(monkeypatch):
    """theme geopolitical stress_level ∉ {high, elevated} → pas de veto."""
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="normal")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, _, _ = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is False


def test_gdelt_vetoes_us_indices_too(monkeypatch):
    """v2026-06-11 : scope étendu à _INDICES_FOR_GDELT_STRESS = EU + US.
    Avant cette date la règle était EU-only, mais WATCHED_PAIRS ne contenait
    aucun EU index → règle inerte. Couvre désormais SPX/NDX/US30 aussi.
    """
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="high")
    _patch_snapshots(monkeypatch, None, gdelt)

    vetoed, reasons, _ = geopolitical_veto.apply("SPX", "buy")
    assert vetoed is True
    assert "SPX" in reasons[0]


def test_gdelt_vetoes_crypto_too(monkeypatch):
    """v2026-06-11 scope crypto : BTC/USD et ETH/USD sont risk-on aussi.
    Justification : V1 ne génère quasi jamais de setups SPX/NDX (0 en 30j),
    donc le veto avait 0 cible. Crypto a des centaines de signaux/jour →
    contrefactuel mesurable d'ici S8. Sémantique : stress géopolitique global
    impacte tout asset risk-on incluant crypto (BTC ↔ équités US en stress).
    """
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="high")
    _patch_snapshots(monkeypatch, None, gdelt)

    for pair in ("BTC/USD", "ETH/USD"):
        vetoed, reasons, _ = geopolitical_veto.apply(pair, "buy")
        assert vetoed is True, f"{pair} should be vetoed by GDELT_STRESS"
        assert pair in reasons[0]


def test_gdelt_no_veto_on_safe_haven_or_forex(monkeypatch):
    """Forex et safe-haven (XAU/XAG) ne sont pas couverts par GDELT_STRESS.
    Safe-haven gardent leur logique IRAN_HORMUZ séparée.
    """
    _enable_all_rules(monkeypatch)
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="high")
    _patch_snapshots(monkeypatch, None, gdelt)

    for pair in ("EUR/USD", "USD/JPY"):
        vetoed, _, meta = geopolitical_veto.apply(pair, "buy")
        # GDELT ne match pas — autres règles peuvent matcher mais pas GDELT
        assert "gdelt_stress" not in meta.get("rules_matched", [])


# ─── Multi-rules + best-effort ───────────────────────────────────────


def test_multiple_rules_match_concurrent(monkeypatch):
    """Iran peace prob ET GDELT high stress → DAX long se prend les 2 vetos."""
    _enable_all_rules(monkeypatch)
    poly = _poly_snapshot({"geopolitical": [
        _poly_market("Iran peace deal by 2026-05-31?", 0.50, 10),
    ]})
    gdelt = _gdelt_snapshot(overall_stress="high", geo_stress="high")
    _patch_snapshots(monkeypatch, poly, gdelt)

    # XAU/USD long : touché par iran_hormuz uniquement (pas EU)
    vetoed, reasons, meta = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is True
    assert meta["rules_matched"] == ["iran_hormuz"]

    # DAX long : touché par gdelt_stress uniquement (pas safe-haven)
    vetoed, reasons, meta = geopolitical_veto.apply("DAX", "buy")
    assert vetoed is True
    assert meta["rules_matched"] == ["gdelt_stress"]


def test_best_effort_no_snapshots(monkeypatch):
    """Pas de snapshot Polymarket ni GDELT → pas de veto, pas d'exception."""
    _enable_all_rules(monkeypatch)
    _patch_snapshots(monkeypatch, None, None)

    vetoed, reasons, meta = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False
    assert reasons == []
    assert meta["rules_evaluated"] == ["iran_hormuz", "fed_dovish", "recession", "gdelt_stress", "tariff"]


def test_best_effort_polymarket_raises(monkeypatch):
    """polymarket_service.get_current() raise → degraded mode."""
    _enable_all_rules(monkeypatch)
    from backend.services import polymarket_service, geopolitical_news_service

    def boom():
        raise RuntimeError("DB down")

    monkeypatch.setattr(polymarket_service, "get_current", boom)
    monkeypatch.setattr(geopolitical_news_service, "get_current", lambda: None)

    vetoed, reasons, _ = geopolitical_veto.apply("XAU/USD", "buy")
    assert vetoed is False
    assert reasons == []


def test_metadata_lists_all_evaluated_rules(monkeypatch):
    _enable_all_rules(monkeypatch)
    _patch_snapshots(monkeypatch, None, None)

    _, _, meta = geopolitical_veto.apply("EUR/USD", "buy")
    assert set(meta["rules_evaluated"]) == {
        "iran_hormuz", "fed_dovish", "recession", "gdelt_stress", "tariff",
    }
    assert meta["rules_matched"] == []
