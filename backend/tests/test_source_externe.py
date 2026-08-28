"""Un signal venu d'un bot externe ne doit jamais atteindre l'argent réel.

⛔ Le verrou est dans le RÉSOLVEUR de destinations, pas dans l'appelant. Un
appelant peut oublier ; un résolveur non. Même motif que la porte du banc dans
`set_state`, et que `destination=None ⇒ argent réel` : on ne place pas une garde
là où il faut penser à l'appeler.

Conception : `docs/superpowers/specs/2026-08-26-bot-externe-demo-design.md`
"""
from __future__ import annotations

import sqlite3

import pytest


class _Setup:
    """Setup minimal, tel que le résolveur le lit."""

    def __init__(self, source=None, pair="XAU/USD", direction="sell"):
        self.pair = pair
        self.entry_price = 3400.0
        self.horizon = "4h"
        self.pattern = "momentum_up"

        class _D:
            value = direction
        self.direction = _D()
        if source is not None:
            self.source = source


def _reels(destinations):
    from backend.services.destinations_registry import is_real_money
    return [d for d in destinations
            if is_real_money(getattr(d, "destination_id", None))]


# ── Le verrou ─────────────────────────────────────────────────────────────


class _Dest:
    def __init__(self, did):
        self.destination_id = did
        self.bridge_type = "mt5"


@pytest.fixture
def routes(monkeypatch):
    """Injecte de VRAIES destinations dans le résolveur.

    ⛔ Sans ça, l'environnement de test n'en configure aucune et
    `resolve_destinations` rend une liste vide : le test du verrou passerait
    À VIDE, en prouvant seulement qu'il n'y a rien à filtrer. C'est le piège du
    détecteur testé sur son silence, et il s'est déclenché ici au premier essai.
    """
    from backend.services import bridge_destinations as bd
    monkeypatch.setattr(bd, "_admin_legacy_destination", lambda: _Dest("admin_legacy"))
    monkeypatch.setattr(bd, "_admin_live_destination", lambda: _Dest("admin_live"))
    for nom in ("_admin_binance_destination", "_admin_kraken_destination",
                "_admin_kraken_spot_destination", "_admin_kraken_stocks_destination"):
        if hasattr(bd, nom):
            monkeypatch.setattr(bd, nom, lambda: None)
    return bd


def test_les_routes_de_test_sont_bien_en_place(routes):
    """Garde-fou du garde-fou : si ce test tombe, tous ceux qui suivent
    deviennent des tests à vide."""
    dests = routes.resolve_destinations(_Setup(source=None))
    ids = {d.destination_id for d in dests}
    assert "admin_live" in ids and "admin_legacy" in ids, ids
    assert _reels(dests), "admin_live doit être reconnu comme argent réel"


def test_un_setup_externe_n_atteint_aucune_destination_reelle(routes):
    """⛔ Le test qui compte. S'il tombe, le dispositif de test devient un
    dispositif de trading."""
    dests = routes.resolve_destinations(_Setup(source="bot_x"))
    assert _reels(dests) == [],         f"argent réel atteint : {[d.destination_id for d in _reels(dests)]}"


def test_un_setup_interne_atteint_toujours_le_reel(routes):
    """Le pendant : le verrou ne doit pas déborder sur notre propre flux."""
    assert _reels(routes.resolve_destinations(_Setup(source=None))),         "un setup sans source est le nôtre"
    assert _reels(routes.resolve_destinations(_Setup(source="interne"))),         "`interne` est le nôtre"


def test_un_setup_externe_garde_le_demo(routes):
    """Il doit bien aller QUELQUE PART, sinon le test ne mesure rien."""
    ids = {d.destination_id for d in routes.resolve_destinations(_Setup(source="bot_x"))}
    assert "admin_legacy" in ids, f"aucune route de démo : {ids}"


def test_la_source_vide_ou_blanche_est_traitee_comme_interne(routes):
    """Une chaîne vide n'est pas un fournisseur. La traiter comme externe
    couperait notre propre flux au premier champ mal rempli."""
    for valeur in ("", "   ", None):
        assert _reels(routes.resolve_destinations(_Setup(source=valeur))),             f"source={valeur!r} a coupé le flux interne"


# ── L'attribution ─────────────────────────────────────────────────────────

@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    yield db_path


def test_la_poussee_retient_la_source(_isolated_db):
    """Même chemin que `horizon` : la poussée est la seule source de
    première main."""
    from backend.services import mt5_pushes_service as ps

    ps.try_register_push("admin_legacy", "2026-08-26", "XAU/USD", "sell", "3400.00",
                         horizon="4h", pattern="momentum_up", source="bot_x")
    p = ps.get_push("admin_legacy", "2026-08-26", "XAU/USD", "sell", "3400.00")
    assert p["source"] == "bot_x"


def test_une_poussee_sans_source_reste_acceptee(_isolated_db):
    from backend.services import mt5_pushes_service as ps

    assert ps.try_register_push("admin_legacy", "2026-08-26", "EUR/USD", "buy", "1.10000")
    p = ps.get_push("admin_legacy", "2026-08-26", "EUR/USD", "buy", "1.10000")
    assert p["source"] in (None, "interne")


def test_le_trade_retrouve_sa_source_par_le_ticket(_isolated_db):
    from backend.services import mt5_pushes_service as ps
    from backend.services.mt5_sync import source_du_push

    ps.try_register_push("admin_legacy", "2026-08-26", "XAU/USD", "sell", "3400.00",
                         source="bot_x")
    ps.update_push_result("admin_legacy", "2026-08-26", "XAU/USD", "sell", "3400.00",
                          ok=True, response={"ticket": 4242})
    assert source_du_push(4242) == "bot_x"


def test_un_ticket_inconnu_ne_rend_pas_une_source_inventee(_isolated_db):
    """⛔ `MANUAL` comme branche par défaut a déjà coûté assez cher."""
    from backend.services.mt5_sync import source_du_push

    assert source_du_push(999_999) is None
    assert source_du_push(None) is None


def test_personal_trades_porte_une_colonne_source(_isolated_db):
    from backend.services import trade_log_service

    trade_log_service._init_schema()
    with sqlite3.connect(_isolated_db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(personal_trades)")}
    assert "source" in cols


# ── Le sélecteur du banc ──────────────────────────────────────────────────

def test_le_selecteur_du_banc_filtre_par_source(_isolated_db, monkeypatch):
    """Sans ça, l'essai du fournisseur compterait nos propres clôtures."""
    from datetime import datetime, timedelta, timezone
    from backend.services import ea_closed_trades_service, research_bench as rb

    monkeypatch.setattr(rb, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)
    with sqlite3.connect(_isolated_db) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction TEXT,
            status TEXT, pnl REAL, signal_confidence REAL, closed_at TEXT,
            is_auto INTEGER, close_reason TEXT, mt5_ticket TEXT,
            destination_id TEXT, horizon TEXT, source TEXT)""")

    sel = {"pairs": ["XAU/USD"], "sources": ["bot_x"], "destinations": ["admin_legacy"]}
    rb.declare("bot-x", "Le bot X porte un edge", selector=sel,
               variants_declared=3, author="xavier", min_sample=2)

    apres = datetime.now(timezone.utc)
    with sqlite3.connect(_isolated_db) as c:
        for i, (src, pnl) in enumerate([("bot_x", 10.0), ("bot_x", 10.0),
                                        ("interne", 999.0), (None, 999.0)]):
            c.execute("INSERT INTO personal_trades (pair, direction, status, pnl,"
                      " closed_at, is_auto, mt5_ticket, destination_id, source)"
                      " VALUES ('XAU/USD','sell','CLOSED',?,?,1,?, 'admin_legacy', ?)",
                      (pnl, (apres + timedelta(minutes=i + 1)).isoformat(), str(700 + i), src))

    r = rb.evaluate("bot-x")
    assert r["n_obs"] == 2
    assert r["sum_pnl"] == pytest.approx(20.0)


def test_une_source_absente_n_est_pas_assimilee_a_celle_demandee(_isolated_db, monkeypatch):
    """⛔ Même règle que pour l'horizon : une absence ne se devine pas."""
    from datetime import datetime, timedelta, timezone
    from backend.services import ea_closed_trades_service, research_bench as rb

    monkeypatch.setattr(rb, "_SCHEMA_ENSURED", False)
    monkeypatch.setattr(ea_closed_trades_service, "_SCHEMA_ENSURED", False)
    with sqlite3.connect(_isolated_db) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction TEXT,
            status TEXT, pnl REAL, signal_confidence REAL, closed_at TEXT,
            is_auto INTEGER, close_reason TEXT, mt5_ticket TEXT,
            destination_id TEXT, horizon TEXT, source TEXT)""")

    rb.declare("bot-x", "…", selector={"sources": ["bot_x"]},
               variants_declared=1, author="x", min_sample=1)
    apres = datetime.now(timezone.utc)
    with sqlite3.connect(_isolated_db) as c:
        for i in range(5):
            c.execute("INSERT INTO personal_trades (pair, direction, status, pnl,"
                      " closed_at, is_auto, mt5_ticket, source)"
                      " VALUES ('XAU/USD','sell','CLOSED',10.0,?,1,?,NULL)",
                      ((apres + timedelta(minutes=i + 1)).isoformat(), str(800 + i)))

    r = rb.evaluate("bot-x")
    assert r["status"] == "open"
    assert r["n_obs"] == 0
