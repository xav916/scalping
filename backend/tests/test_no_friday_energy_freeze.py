"""Tests pour la règle no-weekend-hold energy (2026-08-03).

Incident driver : 2 positions WTI Live gardées weekend, SL slippé -4 USD/ticket
au gap réouverture dimanche = €20.75 perte au lieu de €4-5 attendus.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _mk_setup(pair: str) -> MagicMock:
    s = MagicMock()
    s.pair = pair
    s.direction = MagicMock(value="buy")
    s.entry_price = 85.0
    s.stop_loss = 83.0
    s.take_profit = 90.0
    s.confidence_score = 75
    s.is_simulated = False
    s.verdict_blockers = None
    return s


def _mk_dest():
    d = MagicMock()
    d.destination_id = "admin_live"
    d.bridge_url = "http://mock:8788"
    d.user_id = None
    d.min_confidence = 60
    d.allowed_asset_classes = frozenset({"forex", "metal", "energy"})
    d.symbol_map = None
    d.extra_pairs_allowed = frozenset()
    d.excluded_pairs = frozenset()
    return d


def test_settings_flags_loaded():
    """Les 2 env vars sont bien chargées avec les defaults."""
    from config.settings import (
        NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED,
        NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC,
    )
    assert NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED is True
    assert NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC == 18


def test_energy_pre_weekend_freeze_friday_18h():
    """Vendredi 18h UTC + energy pair → conditions du freeze satisfaites."""
    from config.settings import (
        NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED,
        NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC,
        asset_class_for,
    )
    friday_18h = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)  # vendredi 2026-08-07
    assert NO_FRIDAY_LATE_OPEN_ENERGY_ENABLED
    assert asset_class_for("WTI/USD") == "energy"
    assert friday_18h.weekday() == 4  # vendredi
    assert friday_18h.hour >= NO_FRIDAY_LATE_OPEN_ENERGY_HOUR_UTC
    # → toutes les conditions du freeze sont satisfaites, rejection code
    # "energy_pre_weekend_freeze" sera retourné par _pre_push_rejection_reason


def test_no_freeze_thursday_18h():
    """Jeudi 18h UTC + energy → pas de freeze (weekday != 4)."""
    thursday_18h = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)
    assert thursday_18h.weekday() == 3  # jeudi


def test_no_freeze_friday_17h():
    """Vendredi 17h UTC + energy → pas de freeze (hour < 18)."""
    friday_17h = datetime(2026, 8, 7, 17, 0, tzinfo=timezone.utc)
    assert friday_17h.weekday() == 4
    assert friday_17h.hour < 18


def test_no_freeze_forex_pair_friday_18h():
    """Vendredi 18h UTC + forex pair (EUR/USD) → pas de freeze (asset_class != energy)."""
    from config.settings import asset_class_for
    assert asset_class_for("EUR/USD") == "forex"
    assert asset_class_for("XAU/USD") == "metal"
    # → le freeze ne s'applique QUE si asset_class == "energy"
