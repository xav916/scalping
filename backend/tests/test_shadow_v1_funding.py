"""Persistance du funding Kraken dans le flux shadow V1.

Contexte : le veto funding Kraken (soft veto ×0.85, cf.
``kraken_funding_scoring.py``) est une hypothèse dosée sur une fréquence de
déclenchement plausible, jamais démontrée prédictive — le taux au moment du
signal n'était persisté nulle part. `shadow_v2_core_long._capture_funding_snapshot`
comble ce trou côté V2 ; ces tests couvrent le branchement côté V1, qui
couvre beaucoup plus de paires crypto (donc beaucoup plus d'observations)
que le seul ETH/USD Daily de V2.

⚠️ Avant ce chantier, `shadow_v1.py` ne capturait AUCUNE feature — la
persistance funding est la première. On reste strictement minimal : on
n'ajoute PAS macro ni géopolitique à V1 ici.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import shadow_v1
from backend.services import shadow_v2_core_long as shadow


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shadow_v1_funding_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "DB_PATH", db_path)
    shadow.ensure_schema()
    return db_path


def _setup(pair="BTC/USD", direction="buy", entry=60000.0, sl=59000.0, tp=62000.0):
    return SimpleNamespace(
        pair=pair,
        direction=SimpleNamespace(value=direction),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=None,
        pattern=None,
    )


def _funding_json(db_path, pair):
    with sqlite3.connect(db_path) as c:
        row = c.execute(
            "SELECT funding_features_json FROM shadow_setups WHERE pair = ?",
            (pair,),
        ).fetchone()
    return row[0] if row else None


# ─── _persist_v1_shadow : stockage direct ───────────────────────────────────


def test_persist_v1_shadow_stores_funding_features(temp_db):
    """_persist_v1_shadow écrit bien funding_features_json quand fourni."""
    funding = {
        "captured_at": "2026-08-05T12:00:00Z",
        "symbol": "PF_XBTUSD",
        "rate": 3.5e-5,
        "extreme_threshold": 2.0e-5,
        "would_veto": True,
    }
    logged = shadow_v1._persist_v1_shadow(
        _setup(), "BTC/USD", "buy",
        datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        funding_features=funding,
    )
    assert logged is True

    raw = _funding_json(temp_db, "BTC/USD")
    assert raw is not None
    parsed = json.loads(raw)
    assert parsed["rate"] == pytest.approx(3.5e-5)
    assert parsed["extreme_threshold"] == pytest.approx(2.0e-5)
    assert parsed["would_veto"] is True


def test_persist_v1_shadow_funding_none_stores_null(temp_db):
    """Sans funding_features (paire non-crypto), la colonne reste NULL —
    pas un dict vide."""
    logged = shadow_v1._persist_v1_shadow(
        _setup("EUR/USD", entry=1.08, sl=1.075, tp=1.09), "EUR/USD", "buy",
        datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        funding_features=None,
    )
    assert logged is True
    assert _funding_json(temp_db, "EUR/USD") is None


# ─── log_v1_shadows_for_tracked_pairs : branchement bout en bout ─────────


def test_log_v1_shadows_capture_funding_for_observed_crypto_pair(temp_db, monkeypatch):
    """Pour une paire OBSERVED crypto, log_v1_shadows_for_tracked_pairs doit
    appeler _capture_funding_snapshot et faire parvenir son résultat jusqu'à
    la ligne persistée."""
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_OBSERVED)
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)

    marker = {"marker": "v1-funding-wiring-proof", "rate": 1.0e-5}
    appels = []

    def _fake_capture(pair, direction):
        appels.append((pair, direction))
        return marker

    monkeypatch.setattr(shadow, "_capture_funding_snapshot", _fake_capture)

    setups = [_setup("BTC/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(
        setups, cycle_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert counts["logged"] == 1
    assert appels == [("BTC/USD", "buy")]

    raw = _funding_json(temp_db, "BTC/USD")
    assert raw is not None
    assert json.loads(raw) == marker


def test_log_v1_shadows_non_crypto_pair_stores_null_funding(temp_db, monkeypatch):
    """Paire non-crypto OBSERVED : la capture réelle (non mockée) doit
    rendre None et la row doit avoir funding_features_json NULL — sans
    toucher le réseau (is_crypto_pair coupe avant tout fetch)."""
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_OBSERVED)
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)

    setups = [_setup("EUR/USD", "buy", entry=1.08, sl=1.075, tp=1.09)]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(
        setups, cycle_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert counts["logged"] == 1
    assert _funding_json(temp_db, "EUR/USD") is None


def test_log_v1_shadows_funding_capture_exception_does_not_block_persist(temp_db, monkeypatch):
    """Une exception dans _capture_funding_snapshot ne doit ni empêcher la
    persistance du setup, ni remonter — best-effort absolu : la
    persistance est la source de mesure, elle prime."""
    from backend.services import pair_admission_controller as pac

    monkeypatch.setattr(pac, "get_current_state", lambda pair, direction: pac.STATE_OBSERVED)
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)

    def _boom(pair, direction):
        raise RuntimeError("Kraken API down")

    monkeypatch.setattr(shadow, "_capture_funding_snapshot", _boom)

    setups = [_setup("BTC/USD", "buy")]
    counts = shadow_v1.log_v1_shadows_for_tracked_pairs(
        setups, cycle_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
    )

    assert counts["logged"] == 1
    assert counts["errors"] == 0
    assert _funding_json(temp_db, "BTC/USD") is None
