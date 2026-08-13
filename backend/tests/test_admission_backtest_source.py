"""Régression 2026-08-04 — le scoring d'admission lisait une table corrompue.

`compute_promotion_score` pilote des transitions automatiques réelles
(OBSERVED → TELEGRAM → AUTO_EXEC → PAUSED). Il s'alimentait sur
`shadow_setups`, dont la contrainte UNIQUE de déduplication était
inopérante : une même idée de trade y était répliquée jusqu'à 960 fois
(cf. `shadow_v1._bar_timestamp`).

Conséquence constatée en prod le 2026-08-04 à 09:18:45 — trois paires
equity rétrogradées sur un `wr 0.0` qui n'était qu'un unique trade perdant
compté 457 fois :

    MSFT/sell → OBSERVED   auto-demote: pnl_pct -103.71 ; wr 0.0 < 45.0
    NVDA/sell → OBSERVED   auto-demote: pnl_pct -102.94 ; wr 0.0 < 45.0
    TSLA/sell → OBSERVED   auto-demote: pnl_pct -102.60 ; wr 0.0 < 45.0

La source est désormais `backtest.db.trades`, saine (duplication ×1,00
vérifiée sur 100 657 lignes).
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import backtest_service as bs
from backend.services import pair_admission_controller as pac


@pytest.fixture(autouse=True)
def _isolated_dbs(tmp_path, monkeypatch):
    """Isole les deux DB : trades.db (admission) et backtest.db (signaux)."""
    trades_db = tmp_path / "trades.db"
    backtest_db = tmp_path / "backtest.db"

    from backend.services import trade_log_service, ea_closed_trades_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", trades_db)
    monkeypatch.setattr(bs, "_DB_PATH", backtest_db)
    monkeypatch.setattr(pac, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)

    with sqlite3.connect(trades_db) as c:
        c.execute(
            """
            CREATE TABLE personal_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT, direction TEXT, status TEXT, pnl REAL,
                closed_at TEXT, is_auto INTEGER
            )
            """
        )
    bs._init_schema()
    return tmp_path


def _emit(pair, direction, rr, outcome="WIN_TP1", checked_at="2026-08-01T10:00:00"):
    with bs._conn() as c:
        c.execute(
            """
            INSERT INTO trades (pair, direction, entry_price, stop_loss,
                                take_profit_1, take_profit_2, emitted_at,
                                checked_at, outcome, rr_realized)
            VALUES (?, ?, 1.0, 0.9, 1.2, 1.4, '2026-08-01T09:00:00', ?, ?, ?)
            """,
            (pair, direction, checked_at, outcome, rr),
        )


# --- la source elle-même ---------------------------------------------------

def test_seuls_les_trades_resolus_comptent():
    """OPEN et rr_realized NULL n'ont pas de résultat exploitable."""
    _emit("EUR/USD", "buy", 1.8)
    _emit("EUR/USD", "buy", None, outcome="OPEN")
    _emit("EUR/USD", "buy", None, outcome="WIN_TP1")
    assert bs.fetch_recent_rr("EUR/USD", "buy", 30) == [1.8]


def test_filtre_par_direction():
    _emit("EUR/USD", "buy", 1.8)
    _emit("EUR/USD", "sell", -1.0, outcome="LOSS")
    assert bs.fetch_recent_rr("EUR/USD", "buy", 30) == [1.8]
    assert bs.fetch_recent_rr("EUR/USD", "sell", 30) == [-1.0]
    assert sorted(bs.fetch_recent_rr("EUR/USD", None, 30)) == [-1.0, 1.8]


def test_les_plus_recents_dabord():
    _emit("EUR/USD", "buy", 1.0, checked_at="2026-08-01T10:00:00")
    _emit("EUR/USD", "buy", 2.0, checked_at="2026-08-03T10:00:00")
    assert bs.fetch_recent_rr("EUR/USD", "buy", 1) == [2.0]


# --- la conversion R → euros ----------------------------------------------

def test_unite_de_risque_suit_la_politique_de_sizing(monkeypatch):
    """1 R = capital × risque_par_trade. Pas une constante.

    L'ancien chemin figeait 1 R = 100 € contre un capital réel de 3 000 €,
    d'où des `pnl_pct` au-delà de −100 %, impossibles sur un cumul de
    pourcentages.
    """
    import config.settings as st
    monkeypatch.setattr(st, "TRADING_CAPITAL", 3000.0)
    monkeypatch.setattr(st, "RISK_PER_TRADE_PCT", 1.0)
    assert pac._r_unit_eur() == 30.0

    _emit("EUR/USD", "buy", 1.8)
    assert pac._fetch_signal_pnls("EUR/USD", "buy", 30) == [54.0]


def test_pnl_pct_est_independant_du_capital(monkeypatch):
    """Même série de R → même pnl_pct, quel que soit le capital configuré.

    ⚠️ `PAC_MIN_REAL_TRADES=0` ici : depuis le 2026-08-13 un score bâti sur des
    signaux masque ses métriques (`backtest.db` les gonfle, cf.
    `test_metriques_de_signaux_ne_sont_pas_affichees`). Ce test-ci porte sur la
    FORMULE de `pnl_pct`, pas sur le masquage — on se place donc dans le régime
    où elle est observable.
    """
    import config.settings as st
    monkeypatch.setattr(st, "PAC_MIN_REAL_TRADES", 0)
    for rr in (1.8, -1.0, 1.8, -1.0, 1.8):
        _emit("EUR/USD", "buy", rr, outcome="WIN_TP1" if rr > 0 else "LOSS")

    scores = []
    for capital in (3000.0, 10000.0):
        monkeypatch.setattr(st, "TRADING_CAPITAL", capital)
        monkeypatch.setattr(st, "RISK_PER_TRADE_PCT", 1.0)
        scores.append(pac.compute_promotion_score("EUR/USD", window=30, direction="buy"))

    assert scores[0]["pnl_pct"] == scores[1]["pnl_pct"]
    # 3×1.8 − 2×1.0 = +3.4 R, à 1 % par R
    assert scores[0]["pnl_pct"] == pytest.approx(3.4, abs=0.01)


# --- l'incident lui-même ---------------------------------------------------

def test_shadow_setups_corrompu_nest_plus_lu(monkeypatch):
    """Le scénario exact du 2026-08-04 : shadow empoisonné, signaux sains.

    Avant correctif, les 30 lignes dupliquées de `shadow_setups` donnaient
    `wr 0.0` et déclenchaient la rétrogradation. Le score doit maintenant
    refléter les signaux réels.

    ⚠️ `PAC_MIN_REAL_TRADES=0` : ce test verifie QUELLE SOURCE alimente le
    score, ce qui suppose de pouvoir lire le `wr`. Le masquage des metriques de
    signaux est couvert ailleurs.
    """
    import config.settings as st
    monkeypatch.setattr(st, "PAC_MIN_REAL_TRADES", 0)
    from pathlib import Path
    from backend.services import shadow_v2_core_long as shadow
    monkeypatch.setattr(shadow, "DB_PATH", Path(pac._db_path()))
    shadow.ensure_schema()
    with sqlite3.connect(pac._db_path()) as c:
        for i in range(30):  # une seule idée, répliquée — l'artefact
            c.execute(
                """
                INSERT INTO shadow_setups (cycle_at, bar_timestamp, system_id,
                    pair, timeframe, direction, pattern, entry_price, stop_loss,
                    take_profit_1, risk_pct, rr, sizing_capital_eur,
                    sizing_risk_pct, sizing_position_eur, sizing_max_loss_eur,
                    outcome, pnl_eur, exit_at)
                VALUES (?, ?, 'V1_SHADOW_MSFT_sell', 'MSFT', '1h', 'sell',
                        'v1_signal', 300.0, 302.0, 296.0, 0.0067, 2.0,
                        10000.0, 0.01, 15000.0, 100.0, 'SL', -100.0, ?)
                """,
                (f"2026-08-0{i % 9 + 1}T10:0{i % 6}:00", f"bar-{i}",
                 f"2026-08-0{i % 9 + 1}T14:00:00"),
            )

    for _ in range(20):
        _emit("MSFT", "sell", 1.8)
    for _ in range(10):
        _emit("MSFT", "sell", -1.0, outcome="LOSS")

    score = pac.compute_promotion_score("MSFT", window=30, direction="sell")
    assert score["pnl_source"] == "backtest_trades"
    assert score["wr"] == pytest.approx(66.67, abs=0.01)
    assert score["sample"] == 30


def test_aucune_donnee_reste_conservateur():
    """Sans signal résolu, on ne promeut pas — surtout pas par défaut.

    Depuis le garde-fou échantillon réel du 2026-08-05
    (`PAC_MIN_REAL_TRADES`, cf. `test_pair_admission_controller.py`), ce cas
    devient explicitement INDÉCIDABLE plutôt que STATE_OBSERVED : « je ne
    sais rien » n'est plus confondu avec « je sais que c'est mauvais ». Le
    résultat pratique (aucune promotion) reste inchangé.
    """
    score = pac.compute_promotion_score("XAU/USD", window=30, direction="buy")
    assert score["sample"] == 0
    assert score["eligible_for"] == pac.STATE_INDETERMINATE
