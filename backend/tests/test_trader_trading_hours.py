"""Tests du filtre d'heures de trading (backend/services/trader_trading_hours.py)."""
from __future__ import annotations

from datetime import time

import pytest

from backend.services import trader_trading_hours as th


PREFIX = "TEST"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(f"{PREFIX}_TRADING_HOURS_UTC", raising=False)


# ══════════════════════════════════════════════════════════════════════
# parse_ranges
# ══════════════════════════════════════════════════════════════════════


def test_parse_ranges_simple():
    out = th.parse_ranges("02:00-05:00")
    assert out == [(time(2, 0), time(5, 0))]


def test_parse_ranges_multiple():
    out = th.parse_ranges("02:00-05:00,08:00-21:00")
    assert out == [
        (time(2, 0), time(5, 0)),
        (time(8, 0), time(21, 0)),
    ]


def test_parse_ranges_vide_retourne_liste_vide():
    assert th.parse_ranges("") == []
    assert th.parse_ranges("  ") == []


def test_parse_ranges_ignore_invalides(caplog):
    out = th.parse_ranges("02:00-05:00,pas-une-plage,08:00-21:00")
    assert out == [
        (time(2, 0), time(5, 0)),
        (time(8, 0), time(21, 0)),
    ]


def test_parse_ranges_cross_midnight():
    out = th.parse_ranges("22:00-02:00")
    assert out == [(time(22, 0), time(2, 0))]


# ══════════════════════════════════════════════════════════════════════
# _now_in_any_range
# ══════════════════════════════════════════════════════════════════════


def test_aucune_range_autorise_tout():
    """Liste vide = aucune restriction = toujours OK."""
    assert th._now_in_any_range(time(3, 0), []) is True
    assert th._now_in_any_range(time(23, 59), []) is True


def test_inclusion_range_simple():
    ranges = [(time(2, 0), time(5, 0))]
    assert th._now_in_any_range(time(3, 0), ranges) is True
    assert th._now_in_any_range(time(2, 0), ranges) is True  # inclusif à gauche
    assert th._now_in_any_range(time(5, 0), ranges) is False  # exclusif à droite
    assert th._now_in_any_range(time(1, 59), ranges) is False


def test_exclusion_range_simple():
    ranges = [(time(2, 0), time(5, 0))]
    assert th._now_in_any_range(time(6, 0), ranges) is False
    assert th._now_in_any_range(time(0, 0), ranges) is False


def test_multiple_ranges():
    ranges = [(time(2, 0), time(5, 0)), (time(8, 0), time(21, 0))]
    assert th._now_in_any_range(time(3, 0), ranges) is True  # dans la 1ère
    assert th._now_in_any_range(time(15, 0), ranges) is True  # dans la 2ème
    assert th._now_in_any_range(time(6, 0), ranges) is False  # entre les 2
    assert th._now_in_any_range(time(22, 0), ranges) is False  # après


def test_cross_midnight_range():
    """22h-02h = autorise 22h, 23h, 00h, 01h, mais pas 02h, 10h, etc."""
    ranges = [(time(22, 0), time(2, 0))]
    assert th._now_in_any_range(time(22, 0), ranges) is True
    assert th._now_in_any_range(time(23, 30), ranges) is True
    assert th._now_in_any_range(time(0, 0), ranges) is True
    assert th._now_in_any_range(time(1, 59), ranges) is True
    assert th._now_in_any_range(time(2, 0), ranges) is False
    assert th._now_in_any_range(time(10, 0), ranges) is False
    assert th._now_in_any_range(time(21, 59), ranges) is False


# ══════════════════════════════════════════════════════════════════════
# is_within_trading_hours (lecture env var)
# ══════════════════════════════════════════════════════════════════════


def test_env_absente_autorise_tout(monkeypatch):
    """Comportement backward-compat : pas d'env = trade H24."""
    assert th.is_within_trading_hours(PREFIX) is True


def test_env_vide_autorise_tout(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}_TRADING_HOURS_UTC", "")
    assert th.is_within_trading_hours(PREFIX) is True


def test_env_malformee_autorise_tout(monkeypatch):
    """parse_ranges tolère les malformations → fail-open."""
    monkeypatch.setenv(f"{PREFIX}_TRADING_HOURS_UTC", "garbage-string-no-hyphen")
    # Pas de plage valide → liste vide → aucune restriction
    assert th.is_within_trading_hours(PREFIX) is True


def test_env_asie_illiquide_restrictive_bloque_bonne_heure(monkeypatch):
    """Config Tokyo+Londres+NY : skip Asie illiquide 00h-02h et 05h-07h."""
    monkeypatch.setenv(
        f"{PREFIX}_TRADING_HOURS_UTC", "02:00-05:00,08:00-21:00",
    )
    # Patch now() pour simuler 00:30 UTC (Asie illiquide, doit bloquer)
    class FixedDt:
        @staticmethod
        def now(tz):
            import datetime as _d
            return _d.datetime(2026, 11, 14, 0, 30, tzinfo=tz)
    monkeypatch.setattr(th, "datetime", FixedDt)
    assert th.is_within_trading_hours(PREFIX) is False


def test_env_asie_illiquide_restrictive_autorise_tokyo_matin(monkeypatch):
    """À 03:00 UTC (dans la range Tokyo matin), doit autoriser."""
    monkeypatch.setenv(
        f"{PREFIX}_TRADING_HOURS_UTC", "02:00-05:00,08:00-21:00",
    )
    class FixedDt:
        @staticmethod
        def now(tz):
            import datetime as _d
            return _d.datetime(2026, 11, 14, 3, 0, tzinfo=tz)
    monkeypatch.setattr(th, "datetime", FixedDt)
    assert th.is_within_trading_hours(PREFIX) is True


def test_fail_open_sur_exception():
    """Un bug du garde-fou lui-même ne doit pas bloquer le trading."""
    import os
    original = os.environ.get(f"{PREFIX}_TRADING_HOURS_UTC")
    try:
        # Force une exception en patchant parse_ranges
        def _bad(_):
            raise RuntimeError("corrompu")
        import backend.services.trader_trading_hours as _th
        orig_parse = _th.parse_ranges
        _th.parse_ranges = _bad
        os.environ[f"{PREFIX}_TRADING_HOURS_UTC"] = "02:00-05:00"
        try:
            assert _th.is_within_trading_hours(PREFIX) is True  # fail-open
        finally:
            _th.parse_ranges = orig_parse
    finally:
        if original is None:
            os.environ.pop(f"{PREFIX}_TRADING_HOURS_UTC", None)
        else:
            os.environ[f"{PREFIX}_TRADING_HOURS_UTC"] = original
