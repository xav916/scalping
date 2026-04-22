"""Tests du service d'insights de performance."""
import json
import sqlite3

import pytest

from backend.services import insights_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY,
            user TEXT, pair TEXT, direction TEXT,
            entry_price REAL, stop_loss REAL, take_profit REAL,
            size_lot REAL, signal_pattern TEXT, signal_confidence REAL,
            checklist_passed INTEGER, notes TEXT, status TEXT,
            created_at TEXT, mt5_ticket INTEGER, is_auto INTEGER,
            post_entry_sl INTEGER, post_entry_tp INTEGER, post_entry_size INTEGER,
            context_macro TEXT, exit_price REAL, pnl REAL, closed_at TEXT,
            close_reason TEXT
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(insights_service, "_db_path", lambda: str(db_file))
    return str(db_file)


def _insert(db, **kw):
    defaults = {
        "user": "u", "pair": "EUR/USD", "direction": "buy",
        "entry_price": 1.1, "stop_loss": 1.09, "take_profit": 1.12,
        "size_lot": 0.1, "status": "CLOSED", "is_auto": 1,
        "created_at": "2026-04-21T10:00:00+00:00",
        "signal_confidence": 70.0, "pnl": 5.0, "mt5_ticket": 1,
        "context_macro": json.dumps({"risk_regime": "neutral"}),
    }
    defaults.update(kw)
    cols = ",".join(defaults.keys())
    ph = ",".join("?" * len(defaults))
    with sqlite3.connect(db) as c:
        c.execute(f"INSERT INTO personal_trades ({cols}) VALUES ({ph})", tuple(defaults.values()))


def test_empty_db_returns_no_data(db):
    out = insights_service.get_performance()
    assert out["total_trades"] == 0


def test_excludes_non_auto_trades(db):
    _insert(db, is_auto=0, mt5_ticket=10)
    assert insights_service.get_performance()["total_trades"] == 0


def test_excludes_open_trades(db):
    _insert(db, status="OPEN", mt5_ticket=20)
    assert insights_service.get_performance()["total_trades"] == 0


def test_excludes_null_pnl(db):
    _insert(db, pnl=None, mt5_ticket=30)
    assert insights_service.get_performance()["total_trades"] == 0


def test_global_stats_basic(db):
    _insert(db, pnl=10.0, mt5_ticket=1)
    _insert(db, pnl=-5.0, mt5_ticket=2)
    _insert(db, pnl=3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    assert out["total_trades"] == 3
    assert out["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert out["total_pnl"] == 8.0
    assert out["avg_pnl"] == pytest.approx(8 / 3, rel=1e-2)
    assert out["total_losses"] == -5.0


def test_by_score_bucket(db):
    # 2 trades dans 55-65, 1 trade dans 75-85
    _insert(db, signal_confidence=58, pnl=1.0, mt5_ticket=1)
    _insert(db, signal_confidence=62, pnl=-2.0, mt5_ticket=2)
    _insert(db, signal_confidence=80, pnl=10.0, mt5_ticket=3)

    out = insights_service.get_performance()
    buckets = {b["bucket"]: b for b in out["by_score_bucket"]}
    assert "55-65" in buckets
    assert buckets["55-65"]["count"] == 2
    assert buckets["55-65"]["wins"] == 1
    assert "75-85" in buckets
    assert buckets["75-85"]["count"] == 1
    assert buckets["75-85"]["win_rate"] == 1.0


def test_by_asset_class_detects_forex_metal_crypto(db):
    _insert(db, pair="EUR/USD", pnl=1.0, mt5_ticket=1)
    _insert(db, pair="XAU/USD", pnl=2.0, mt5_ticket=2)
    _insert(db, pair="BTC/USD", pnl=3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    classes = {b["bucket"]: b for b in out["by_asset_class"]}
    assert classes["forex"]["count"] == 1
    assert classes["metal"]["count"] == 1
    assert classes["crypto"]["count"] == 1


def test_by_risk_regime_from_context_macro(db):
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_on"}), pnl=1.0, mt5_ticket=1)
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_off"}), pnl=-1.0, mt5_ticket=2)
    _insert(db, context_macro=json.dumps({"risk_regime": "risk_off"}), pnl=-2.0, mt5_ticket=3)

    out = insights_service.get_performance()
    regimes = {b["bucket"]: b for b in out["by_risk_regime"]}
    assert regimes["risk_on"]["count"] == 1
    assert regimes["risk_off"]["count"] == 2
    assert regimes["risk_off"]["win_rate"] == 0.0


def test_null_signal_confidence_not_in_score_bucket(db):
    """Trades anciens avec confidence=NULL ne sont pas groupés par score."""
    _insert(db, signal_confidence=None, pnl=5.0, mt5_ticket=1)
    _insert(db, signal_confidence=70, pnl=3.0, mt5_ticket=2)

    out = insights_service.get_performance()
    assert out["total_trades"] == 2
    total_in_buckets = sum(b["count"] for b in out["by_score_bucket"])
    assert total_in_buckets == 1


def test_since_filter(db):
    _insert(db, created_at="2026-04-19T10:00:00+00:00", pnl=1.0, mt5_ticket=1)
    _insert(db, created_at="2026-04-21T10:00:00+00:00", pnl=2.0, mt5_ticket=2)

    out = insights_service.get_performance(since_iso="2026-04-20T00:00:00+00:00")
    assert out["total_trades"] == 1
    assert out["total_pnl"] == 2.0


def test_by_direction(db):
    _insert(db, direction="buy", pnl=1.0, mt5_ticket=1)
    _insert(db, direction="buy", pnl=2.0, mt5_ticket=2)
    _insert(db, direction="sell", pnl=-3.0, mt5_ticket=3)

    out = insights_service.get_performance()
    dirs = {b["bucket"]: b for b in out["by_direction"]}
    assert dirs["buy"]["count"] == 2
    assert dirs["sell"]["count"] == 1
    assert dirs["sell"]["win_rate"] == 0.0


# ─── Tests range custom + pnl buckets ─────────────────────────────────────


def test_period_stats_range_returns_custom_label(db):
    _insert(db, pnl=10.0, mt5_ticket=1,
            created_at="2026-04-20T10:00:00+00:00",
            closed_at="2026-04-20T11:00:00+00:00")
    out = insights_service.get_period_stats_range(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-20T23:59:59+00:00",
    )
    assert out["period"] == "custom"
    assert out["n_trades"] == 1
    assert out["pnl"] == 10.0


def test_period_stats_range_filters_outside_trades(db):
    _insert(db, pnl=5.0, mt5_ticket=1,
            closed_at="2026-04-19T12:00:00+00:00")
    _insert(db, pnl=10.0, mt5_ticket=2,
            closed_at="2026-04-21T12:00:00+00:00")
    out = insights_service.get_period_stats_range(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-20T23:59:59+00:00",
    )
    assert out["n_trades"] == 0


def test_resolve_auto_granularity():
    # span ≤ 36h → hour
    assert insights_service._resolve_auto_granularity(
        "2026-04-22T00:00:00+00:00", "2026-04-22T23:59:59+00:00"
    ) == "hour"
    # 36h < span ≤ 93j → day
    assert insights_service._resolve_auto_granularity(
        "2026-04-15T00:00:00+00:00", "2026-04-22T23:59:59+00:00"
    ) == "day"
    # span > 93j → month
    assert insights_service._resolve_auto_granularity(
        "2025-01-01T00:00:00+00:00", "2026-04-22T23:59:59+00:00"
    ) == "month"


def test_bucket_key_day():
    key = insights_service._bucket_key("2026-04-20T14:35:00+00:00", "day")
    assert key == "2026-04-20"


def test_bucket_key_hour():
    key = insights_service._bucket_key("2026-04-20T14:35:00+00:00", "hour")
    assert key == "2026-04-20T14"


def test_bucket_key_5min_floors_to_nearest_5():
    assert insights_service._bucket_key("2026-04-20T14:37:00+00:00", "5min") == "2026-04-20T14:35"
    assert insights_service._bucket_key("2026-04-20T14:00:00+00:00", "5min") == "2026-04-20T14:00"
    assert insights_service._bucket_key("2026-04-20T14:59:59+00:00", "5min") == "2026-04-20T14:55"


def test_bucket_key_month():
    assert insights_service._bucket_key("2026-04-20T14:35:00+00:00", "month") == "2026-04"
    assert insights_service._bucket_key("2025-12-31T23:59:59+00:00", "month") == "2025-12"


def test_bucket_bounds_month_handles_year_rollover():
    start, end = insights_service._bucket_bounds("2025-12", "month")
    assert start.startswith("2025-12-01T00:00:00")
    assert end.startswith("2025-12-31T23:59:59")


def test_next_bucket_key_rolls_over_year():
    assert insights_service._next_bucket_key("2025-12", "month") == "2026-01"
    assert insights_service._next_bucket_key("2026-04-30", "day") == "2026-05-01"
    assert insights_service._next_bucket_key("2026-04-20T23", "hour") == "2026-04-21T00"
    assert insights_service._next_bucket_key("2026-04-20T14:55", "5min") == "2026-04-20T15:00"


def test_pnl_buckets_empty_range_returns_empty_buckets_with_zero_pnl(db):
    out = insights_service.get_pnl_buckets(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-20T23:59:59+00:00",
        granularity="hour",
    )
    # 24 heures dans la journée, aucune avec trade
    assert len(out["buckets"]) == 24
    assert out["total_trades"] == 0
    assert out["final_pnl"] == 0.0
    assert all(b["n_trades"] == 0 for b in out["buckets"])
    assert all(b["pnl"] == 0.0 for b in out["buckets"])


def test_pnl_buckets_day_granularity_aggregates_multiple_trades(db):
    _insert(db, pnl=10.0, mt5_ticket=1,
            closed_at="2026-04-20T10:00:00+00:00")
    _insert(db, pnl=-5.0, mt5_ticket=2,
            closed_at="2026-04-20T14:00:00+00:00")
    _insert(db, pnl=7.0, mt5_ticket=3,
            closed_at="2026-04-21T09:00:00+00:00")

    out = insights_service.get_pnl_buckets(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-21T23:59:59+00:00",
        granularity="day",
    )
    assert len(out["buckets"]) == 2
    assert out["buckets"][0]["pnl"] == 5.0  # 10 - 5
    assert out["buckets"][0]["n_trades"] == 2
    assert out["buckets"][0]["cumulative_pnl"] == 5.0
    assert out["buckets"][1]["pnl"] == 7.0
    assert out["buckets"][1]["cumulative_pnl"] == 12.0
    assert out["total_trades"] == 3
    assert out["final_pnl"] == 12.0


def test_pnl_buckets_fills_gaps_with_zero(db):
    _insert(db, pnl=10.0, mt5_ticket=1,
            closed_at="2026-04-20T10:00:00+00:00")
    # Skip 21 and 22
    _insert(db, pnl=5.0, mt5_ticket=2,
            closed_at="2026-04-23T10:00:00+00:00")

    out = insights_service.get_pnl_buckets(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-23T23:59:59+00:00",
        granularity="day",
    )
    assert len(out["buckets"]) == 4
    assert out["buckets"][0]["pnl"] == 10.0
    assert out["buckets"][1]["pnl"] == 0.0 and out["buckets"][1]["n_trades"] == 0
    assert out["buckets"][2]["pnl"] == 0.0 and out["buckets"][2]["n_trades"] == 0
    assert out["buckets"][3]["pnl"] == 5.0
    # Cumul reste monotone dans les trous
    assert out["buckets"][1]["cumulative_pnl"] == 10.0
    assert out["buckets"][2]["cumulative_pnl"] == 10.0
    assert out["buckets"][3]["cumulative_pnl"] == 15.0


def test_pnl_buckets_5min_rejects_long_range(db):
    with pytest.raises(ValueError, match="5min"):
        insights_service.get_pnl_buckets(
            since="2026-04-20T00:00:00+00:00",
            until="2026-04-22T00:00:00+00:00",  # 48h > 24h cap
            granularity="5min",
        )


def test_pnl_buckets_5min_within_one_hour_ok(db):
    _insert(db, pnl=3.0, mt5_ticket=1,
            closed_at="2026-04-20T14:07:00+00:00")
    _insert(db, pnl=-1.0, mt5_ticket=2,
            closed_at="2026-04-20T14:08:00+00:00")  # même bucket 14:05
    _insert(db, pnl=5.0, mt5_ticket=3,
            closed_at="2026-04-20T14:32:00+00:00")

    out = insights_service.get_pnl_buckets(
        since="2026-04-20T14:00:00+00:00",
        until="2026-04-20T14:59:59+00:00",
        granularity="5min",
    )
    # 12 buckets de 5 min dans 1 heure
    assert len(out["buckets"]) == 12
    # Bucket 14:05 contient 2 trades (14:07 + 14:08)
    b_1405 = next(b for b in out["buckets"] if b["bucket_start"].startswith("2026-04-20T14:05"))
    assert b_1405["n_trades"] == 2
    assert b_1405["pnl"] == 2.0  # 3 - 1
    # Bucket 14:30 contient 1 trade
    b_1430 = next(b for b in out["buckets"] if b["bucket_start"].startswith("2026-04-20T14:30"))
    assert b_1430["n_trades"] == 1
    assert b_1430["pnl"] == 5.0
    assert out["total_trades"] == 3
    assert out["final_pnl"] == 7.0


def test_pnl_buckets_auto_resolves_based_on_span(db):
    _insert(db, pnl=4.0, mt5_ticket=1, closed_at="2026-04-20T10:00:00+00:00")
    out = insights_service.get_pnl_buckets(
        since="2026-04-20T00:00:00+00:00",
        until="2026-04-20T23:59:59+00:00",
        granularity="auto",
    )
    assert out["granularity_used"] == "hour"


def test_pnl_buckets_invalid_granularity_raises(db):
    with pytest.raises(ValueError):
        insights_service.get_pnl_buckets(
            since="2026-04-20T00:00:00+00:00",
            until="2026-04-21T00:00:00+00:00",
            granularity="year",
        )


def test_exposure_timeseries_no_trades_returns_zero_points(db):
    out = insights_service.get_exposure_timeseries(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T23:59:59+00:00",
        granularity="hour",
    )
    assert len(out["points"]) == 24
    assert all(p["capital_at_risk"] == 0.0 and p["n_open"] == 0 for p in out["points"])
    assert out["peak_at_risk"] == 0.0
    assert out["max_open"] == 0


def test_exposure_timeseries_counts_position_within_its_lifetime(db):
    # Trade ouvert à 10:00 UTC, fermé à 14:00 UTC. Entry 1.10, SL 1.08,
    # lot 0.1, EUR/USD → risk = 0.02 × 0.1 × 100_000 = 200 €
    _insert(db,
        pair="EUR/USD",
        entry_price=1.10,
        stop_loss=1.08,
        size_lot=0.1,
        created_at="2026-04-22T10:00:00+00:00",
        closed_at="2026-04-22T14:00:00+00:00",
        mt5_ticket=1,
        pnl=5.0,
    )
    out = insights_service.get_exposure_timeseries(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T23:59:59+00:00",
        granularity="hour",
    )
    # La granularité hour → chaque bucket se termine à HH:59:59.
    # Trade open [10:00, 14:00) → buckets 10, 11, 12, 13 doivent avoir n_open=1.
    # Bucket 14 se termine à 14:59:59 ; closed_at=14:00:00 < 14:59:59 → fermé.
    hours_with_open = [
        int(p["bucket_time"][11:13]) for p in out["points"] if p["n_open"] > 0
    ]
    assert hours_with_open == [10, 11, 12, 13]
    for p in out["points"]:
        if p["n_open"] > 0:
            assert p["capital_at_risk"] == 200.0
    assert out["peak_at_risk"] == 200.0
    assert out["max_open"] == 1


def test_exposure_timeseries_stacks_overlapping_trades(db):
    _insert(db, pair="EUR/USD", entry_price=1.10, stop_loss=1.08, size_lot=0.1,
            created_at="2026-04-22T10:00:00+00:00", closed_at="2026-04-22T15:00:00+00:00",
            mt5_ticket=1, pnl=1.0)  # risk = 200
    _insert(db, pair="XAU/USD", entry_price=2000.0, stop_loss=1990.0, size_lot=0.01,
            created_at="2026-04-22T11:00:00+00:00", closed_at="2026-04-22T13:00:00+00:00",
            mt5_ticket=2, pnl=2.0)  # risk = 10 × 0.01 × 100 = 10
    out = insights_service.get_exposure_timeseries(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T23:59:59+00:00",
        granularity="hour",
    )
    by_hour = {int(p["bucket_time"][11:13]): p for p in out["points"]}
    # Heures 11, 12 : les 2 trades ouverts
    assert by_hour[11]["n_open"] == 2
    assert by_hour[11]["capital_at_risk"] == 210.0
    # Heure 14 : seulement EUR/USD ouvert
    assert by_hour[14]["n_open"] == 1
    assert by_hour[14]["capital_at_risk"] == 200.0


def test_exposure_timeseries_open_trade_no_closed_at(db):
    _insert(db, pair="EUR/USD", entry_price=1.10, stop_loss=1.08, size_lot=0.1,
            status="OPEN", closed_at=None,
            created_at="2026-04-22T08:00:00+00:00",
            mt5_ticket=1, pnl=None)
    out = insights_service.get_exposure_timeseries(
        since="2026-04-22T00:00:00+00:00",
        until="2026-04-22T12:59:59+00:00",
        granularity="hour",
    )
    by_hour = {int(p["bucket_time"][11:13]): p for p in out["points"]}
    # Heures 8-12 : trade toujours ouvert
    for h in range(8, 13):
        assert by_hour[h]["n_open"] == 1
    # Avant 8h : pas encore créé
    for h in range(0, 8):
        assert by_hour[h]["n_open"] == 0


def test_pnl_buckets_sum_matches_period_stats_pnl(db):
    """Cohérence croisée : somme des pnl des buckets === period_stats.pnl sur
    le même range."""
    _insert(db, pnl=10.0, mt5_ticket=1, closed_at="2026-04-20T10:00:00+00:00")
    _insert(db, pnl=-3.0, mt5_ticket=2, closed_at="2026-04-20T14:00:00+00:00")
    _insert(db, pnl=8.0, mt5_ticket=3, closed_at="2026-04-21T09:00:00+00:00")

    since = "2026-04-20T00:00:00+00:00"
    until = "2026-04-21T23:59:59+00:00"
    buckets_out = insights_service.get_pnl_buckets(since, until, "day")
    stats_out = insights_service.get_period_stats_range(since, until)

    sum_buckets = sum(b["pnl"] for b in buckets_out["buckets"])
    assert sum_buckets == pytest.approx(stats_out["pnl"])
    assert buckets_out["total_trades"] == stats_out["n_trades"]
