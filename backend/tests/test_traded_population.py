"""Restriction du backtest à la population réellement tradée.

Le point de vigilance n'est pas l'appariement lui-même — il est quasi exact
grâce au prix à 5 décimales — mais tout ce qu'il ne doit PAS apparier : un
autre sens, un autre prix, un autre cycle. Un appariement trop laxiste
recréerait exactement le problème qu'on corrige, en prétendant tracer un lien
qui n'existe pas.
"""
import sqlite3

import pytest

from backend.services import traded_population as tp

T0 = "2026-06-01T12:00:00+00:00"


@pytest.fixture
def bases(tmp_path, monkeypatch):
    sig = tmp_path / "backtest.db"
    psh = tmp_path / "trades.db"
    with sqlite3.connect(sig) as c:
        c.execute("""CREATE TABLE signals (
            id INTEGER PRIMARY KEY, emitted_at TEXT, pair TEXT,
            direction TEXT, entry_price REAL, verdict_action TEXT)""")
    with sqlite3.connect(psh) as c:
        c.execute("""CREATE TABLE mt5_pushes (
            id INTEGER PRIMARY KEY, destination_id TEXT, pair TEXT,
            direction TEXT, entry_price_5dp REAL, pushed_at TEXT)""")
    monkeypatch.setattr(tp, "_signals_db", lambda: str(sig))
    monkeypatch.setattr(tp, "_pushes_db", lambda: str(psh))
    return sig, psh


def _signal(db, sid, *, pair="EUR/USD", direction="sell", prix=1.10000,
            quand=T0, verdict="SKIP"):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO signals VALUES (?,?,?,?,?,?)",
                  (sid, quand, pair, direction, prix, verdict))


def _push(db, *, pair="EUR/USD", direction="sell", prix=1.10000,
          quand=T0, dest="admin_live"):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id, pair, direction, "
                  "entry_price_5dp, pushed_at) VALUES (?,?,?,?,?)",
                  (dest, pair, direction, prix, quand))


# ── L'appariement nominal ─────────────────────────────────────────────

def test_un_push_retrouve_son_signal(bases):
    sig, psh = bases
    _signal(sig, 1)
    _push(psh)
    assert tp.traded_signal_ids() == {1}


def test_signal_jamais_pousse_est_exclu(bases):
    """Le cas qui fait tout l'intérêt du module : un signal existe, il n'a
    jamais été tradé, il ne doit pas peser dans la validation."""
    sig, psh = bases
    _signal(sig, 1)
    _signal(sig, 2, prix=1.20000)
    _push(psh, prix=1.10000)
    assert tp.traded_signal_ids() == {1}


def test_un_signal_pousse_vers_deux_destinations_ne_compte_qu_une_fois(bases):
    sig, psh = bases
    _signal(sig, 1)
    _push(psh, dest="admin_live")
    _push(psh, dest="user:2")
    assert tp.traded_signal_ids() == {1}


def test_filtre_par_destination(bases):
    sig, psh = bases
    _signal(sig, 1)
    _signal(sig, 2, prix=1.20000)
    _push(psh, prix=1.10000, dest="admin_live")
    _push(psh, prix=1.20000, dest="user:2")
    assert tp.traded_signal_ids(destination="admin_live") == {1}
    assert tp.traded_signal_ids(destination="user:2") == {2}


# ── Ce qu'il ne doit surtout PAS apparier ─────────────────────────────

def test_le_sens_oppose_n_est_jamais_apparie(bases):
    """Un appariement laxiste sur le sens fabriquerait exactement le biais
    directionnel qu'on cherche à mesurer."""
    sig, psh = bases
    _signal(sig, 1, direction="buy")
    _push(psh, direction="sell")
    assert tp.traded_signal_ids() == set()


def test_un_autre_prix_n_est_pas_apparie(bases):
    sig, psh = bases
    _signal(sig, 1, prix=1.10000)
    _push(psh, prix=1.10001)
    assert tp.traded_signal_ids() == set()


def test_une_autre_paire_n_est_pas_appariee(bases):
    sig, psh = bases
    _signal(sig, 1, pair="EUR/USD")
    _push(psh, pair="GBP/USD")
    assert tp.traded_signal_ids() == set()


def test_hors_tolerance_temporelle_pas_d_appariement(bases):
    """Même paire, même sens, même prix, mais une heure plus tard : c'est un
    autre cycle, pas le même signal."""
    sig, psh = bases
    _signal(sig, 1, quand="2026-06-01T12:00:00+00:00")
    _push(psh, quand="2026-06-01T13:00:00+00:00")
    assert tp.traded_signal_ids() == set()


def test_le_signal_le_plus_proche_dans_le_temps_gagne(bases):
    sig, psh = bases
    _signal(sig, 1, quand="2026-06-01T12:00:00+00:00")
    _signal(sig, 2, quand="2026-06-01T12:01:00+00:00")
    _push(psh, quand="2026-06-01T12:00:50+00:00")
    assert tp.traded_signal_ids() == {2}


def test_push_sans_prix_est_ignore_sans_planter(bases):
    sig, psh = bases
    _signal(sig, 1)
    with sqlite3.connect(psh) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id, pair, direction, "
                  "entry_price_5dp, pushed_at) VALUES ('admin_live','EUR/USD','sell',NULL,?)",
                  (T0,))
    assert tp.traded_signal_ids() == set()


# ── Le résumé ─────────────────────────────────────────────────────────

def test_le_resume_montre_l_ecart_de_sens(bases):
    """Le chiffre qui justifie tout : la population totale est équilibrée,
    la population tradée ne l'est pas."""
    sig, psh = bases
    for i in range(4):
        _signal(sig, i + 1, direction="buy", prix=1.10000 + i / 100000)
    for i in range(4):
        _signal(sig, i + 5, direction="sell", prix=1.20000 + i / 100000)
    # Seules les ventes partent réellement.
    for i in range(4):
        _push(psh, direction="sell", prix=1.20000 + i / 100000)

    r = tp.population_summary()
    assert r["signaux_total"] == 8
    assert r["signaux_trades"] == 4
    assert r["ventes_pct_total"] == pytest.approx(50.0)
    assert r["ventes_pct_trades"] == pytest.approx(100.0)


def test_le_resume_expose_la_part_de_TAKE_parmi_les_trades(bases):
    """L'indicateur qui a révélé le problème : si les signaux tradés sont
    majoritairement SKIP, alors filtrer le backtest sur TAKE étudie autre
    chose que l'auto-trading."""
    sig, psh = bases
    _signal(sig, 1, prix=1.10000, verdict="SKIP")
    _signal(sig, 2, prix=1.20000, verdict="SKIP")
    _signal(sig, 3, prix=1.30000, verdict="TAKE")
    for p in (1.10000, 1.20000, 1.30000):
        _push(psh, prix=p)
    r = tp.population_summary()
    assert r["signaux_trades"] == 3
    assert r["take_pct_parmi_trades"] == pytest.approx(33.3, abs=0.1)


def test_resume_sans_aucun_push_ne_plante_pas(bases):
    sig, _ = bases
    _signal(sig, 1)
    r = tp.population_summary()
    assert r["signaux_trades"] == 0
    assert r["ventes_pct_trades"] is None
