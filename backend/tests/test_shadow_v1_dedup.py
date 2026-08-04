"""Régression 2026-08-04 — la déduplication des shadows V1 était inopérante.

``_persist_v1_shadow`` passait ``cycle_at`` à la fois dans ``cycle_at`` ET
dans ``bar_timestamp``. La contrainte ``UNIQUE (system_id, bar_timestamp)``
ne pouvait donc jamais mordre : chaque cycle radar (~6 min) créait une row,
alors que le docstring annonçait une collision « même bar logué au cycle
précédent ».

Effet mesuré en prod avant correctif, sur 19 928 rows résolues :
  SPX   960 lignes →   1 setup distinct  (×960)
  AAPL  458 lignes →   2 setups distincts (×229)
  MSFT  457 lignes →   2 setups distincts (×229)
  global : 8 125 distincts pour 19 928 lignes (×2,5)

Conséquence : toute statistique tirée du shadow sur ces paires était fausse
— « 1832 ventes, 25% de réussite » était en réalité 7 idées de trade
répliquées des centaines de fois.

Amplificateur : hors séance, le prix ne bouge plus, donc le radar régénère
un setup identique à chaque cycle. D'où le filtre marché-fermé, testé ici
aussi.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services import shadow_v1
from backend.services import shadow_v2_core_long as shadow


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shadow_v1_test.db"
    monkeypatch.setattr(shadow, "DB_PATH", db_path)
    monkeypatch.setattr(shadow_v1, "DB_PATH", db_path)
    shadow.ensure_schema()
    return db_path


def _setup(pair="AAPL", entry=300.0, sl=302.0, tp=296.0):
    """TradeSetup minimal — seuls les champs lus par _persist_v1_shadow."""
    return SimpleNamespace(
        pair=pair,
        direction=SimpleNamespace(value="sell"),
        entry_price=entry,
        stop_loss=sl,
        take_profit_1=tp,
        take_profit_2=None,
        pattern=None,
    )


def _rows(db_path):
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT bar_timestamp, entry_price FROM shadow_setups"
        ).fetchall()


def test_meme_bar_nest_persiste_quune_fois(temp_db):
    """Dix cycles dans la même heure → une seule row.

    C'est le cœur du bug : avant correctif, ces dix appels créaient dix rows
    identiques, gonflant l'échantillon d'un facteur 10.
    """
    base = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    for i in range(10):
        shadow_v1._persist_v1_shadow(
            _setup(), "AAPL", "sell", base + timedelta(minutes=6 * i),
        )
    assert len(_rows(temp_db)) == 1


def test_bar_suivant_cree_bien_une_row(temp_db):
    """La dédup ne doit pas non plus tout écraser : un nouveau bar compte."""
    base = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    shadow_v1._persist_v1_shadow(_setup(), "AAPL", "sell", base)
    shadow_v1._persist_v1_shadow(_setup(), "AAPL", "sell", base + timedelta(hours=1))
    assert len(_rows(temp_db)) == 2


def test_bar_timestamp_est_aligne_sur_lheure(temp_db):
    """bar_timestamp doit porter le début du bar, pas l'heure du cycle."""
    shadow_v1._persist_v1_shadow(
        _setup(), "AAPL", "sell",
        datetime(2026, 8, 4, 14, 37, 42, tzinfo=timezone.utc),
    )
    bar_ts = _rows(temp_db)[0][0]
    assert "14:00:00" in bar_ts, f"bar_timestamp non aligné : {bar_ts}"


def test_marche_ferme_nest_pas_logue(temp_db, monkeypatch):
    """Hors séance, le prix est figé — un setup n'aurait aucun sens.

    C'est l'amplificateur du bug : AAPL scanné 24h/24 alors que le NYSE
    n'ouvre que 6h30, avec un dernier cours inchangé le reste du temps.
    """
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: False)
    logged = shadow_v1._persist_v1_shadow(
        _setup(), "AAPL", "sell", datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc),
    )
    assert logged is False
    assert _rows(temp_db) == []


def test_marche_ouvert_est_logue(temp_db, monkeypatch):
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)
    logged = shadow_v1._persist_v1_shadow(
        _setup(), "AAPL", "sell", datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc),
    )
    assert logged is True
    assert len(_rows(temp_db)) == 1


def test_pairs_distinctes_ne_se_bloquent_pas(temp_db, monkeypatch):
    """Le system_id inclut la paire et le sens — pas de collision croisée."""
    monkeypatch.setattr(shadow_v1, "is_market_open_for", lambda pair, now=None: True)
    ts = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
    shadow_v1._persist_v1_shadow(_setup("AAPL"), "AAPL", "sell", ts)
    shadow_v1._persist_v1_shadow(_setup("MSFT"), "MSFT", "sell", ts)
    assert len(_rows(temp_db)) == 2
