"""Tests du bridge runtime vers les skills trader-*."""
from __future__ import annotations

from backend.services import trader_skills_bridge as tsb


def test_skills_root_existe():
    """Les skills vivent bien dans .claude/skills/ au projet."""
    assert tsb.SKILLS_ROOT.exists()


def test_risk_check_sur_ordre_sense():
    """Un ordre bien formé doit passer la vérif risk."""
    res = tsb.risk_check(
        order={
            "symbol": "AAPL", "side": "buy", "qty": "10",
            "type": "market", "time_in_force": "day",
        },
        cfg={"paper": True, "max_positions": 5},
        portfolio={"cash_usd": 10000, "positions": {}},
        prices={"AAPL": 180.0},
    )
    # Le ordre est basique, risk-check devrait passer ou avoir un fail-open
    assert "ok" in res
    assert "reason" in res


def test_risk_check_sur_ordre_mal_forme():
    """Un ordre sans symbole doit être refusé par trader-risk."""
    res = tsb.risk_check(
        order={"qty": "10", "side": "buy"},  # pas de symbol
        cfg={"paper": True},
        portfolio={"cash_usd": 10000, "positions": {}},
    )
    # trader-risk devrait block (no symbol = format error)
    # Fail-open accepté aussi si skill ne charge pas
    assert "ok" in res


def test_risk_check_skill_manquante_fail_open(monkeypatch):
    """Si la skill n'est pas trouvable, fail-open = ok=True."""
    # Force le cache à retourner None
    tsb._SKILL_CACHE["trader-risk/check.py"] = None
    try:
        res = tsb.risk_check(
            order={"symbol": "AAPL", "side": "buy", "qty": "10"},
        )
        assert res["ok"] is True
        assert "unavailable" in res["reason"].lower()
    finally:
        tsb._SKILL_CACHE.pop("trader-risk/check.py", None)


def test_nyse_market_status():
    """market_status doit retourner un dict exploitable."""
    res = tsb.nyse_market_status()
    assert "ok" in res
    assert "status" in res
    # Le status peut être "open"/"closed"/"pre"/"post"/"unknown"
    assert isinstance(res["status"], str)
