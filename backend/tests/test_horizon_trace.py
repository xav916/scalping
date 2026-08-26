"""L'horizon d'un trade doit survivre au dispatch.

⛔ Constaté le 2026-08-26 en voulant déclarer le premier essai du banc :
**l'horizon n'existe nulle part dans la chaîne persistée.** Ni `personal_trades`,
ni les 390 676 lignes de `signals`. Il n'existe que dans l'objet `setup` en
mémoire, le temps du dispatch — où il sert pourtant déjà à refuser des routes
(`_horizon_rejection`).

Et le repli par motif ne rattrape rien : `signal_pattern` est rempli par une
recherche après coup dans `signals` via `signal_id`, qui n'apparie que **16 à
35 %** des trades selon le mois — **0 % en juillet**.

Conséquence : l'hypothèse « le 4 h sur l'or porte un edge » n'était pas
mesurable. On ne peut pas juger ce qu'on n'enregistre pas.
"""
from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    yield db_path


# ── Le maillon 1 : la poussée retient l'horizon ───────────────────────────

def test_la_poussee_retient_l_horizon_et_le_motif():
    """C'est le seul endroit de la chaîne où l'horizon est encore connu."""
    from backend.services import mt5_pushes_service as ps

    ps.try_register_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                         horizon="4h", pattern="momentum_up")
    p = ps.get_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12")

    assert p["horizon"] == "4h"
    assert p["pattern"] == "momentum_up"


def test_une_poussee_sans_horizon_reste_acceptee():
    """Toutes les routes ne renseignent pas l'horizon. Aucune ne doit casser."""
    from backend.services import mt5_pushes_service as ps

    assert ps.try_register_push("admin_live", "2026-08-26", "EUR/USD", "buy", "1.10000")
    p = ps.get_push("admin_live", "2026-08-26", "EUR/USD", "buy", "1.10000")
    assert p["horizon"] is None


def test_le_ticket_est_extrait_de_la_reponse_du_pont():
    """Sans ticket rangé en colonne, relier une poussée à son trade obligerait à
    ré-analyser du JSON à chaque lecture — et personne ne le ferait."""
    from backend.services import mt5_pushes_service as ps

    ps.try_register_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                         horizon="4h", pattern="momentum_up")
    ps.update_push_result("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                          ok=True, response={"ok": True, "ticket": 987654321,
                                             "fill_price": 3400.10})

    p = ps.get_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12")
    assert p["mt5_ticket"] == 987654321


def test_une_reponse_sans_ticket_ne_casse_rien():
    from backend.services import mt5_pushes_service as ps

    ps.try_register_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12")
    ps.update_push_result("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                          ok=False, response={"ok": False, "error": "market closed"})

    assert ps.get_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12")["mt5_ticket"] is None


# ── Le maillon 2 : le trade récupère l'horizon par le ticket ──────────────

def test_le_trade_retrouve_son_horizon_par_le_ticket(_isolated_db):
    """La jointure qui manquait. Le ticket est le seul identifiant partagé entre
    la poussée et le trade."""
    from backend.services import mt5_pushes_service as ps
    from backend.services.mt5_sync import horizon_et_motif_du_push

    ps.try_register_push("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                         horizon="4h", pattern="engulfing_bullish")
    ps.update_push_result("admin_live", "2026-08-26", "XAU/USD", "sell", "3400.12",
                          ok=True, response={"ticket": 42})

    assert horizon_et_motif_du_push(42) == ("4h", "engulfing_bullish")


def test_un_ticket_inconnu_ne_rend_rien_plutot_que_de_deviner(_isolated_db):
    """⛔ `MANUAL` comme branche par défaut a déjà coûté assez cher : une absence
    se dit, elle ne s'invente pas."""
    from backend.services.mt5_sync import horizon_et_motif_du_push

    assert horizon_et_motif_du_push(999_999) == (None, None)
    assert horizon_et_motif_du_push(None) == (None, None)


# ── Le maillon 3 : la colonne existe sur le trade ─────────────────────────

def test_personal_trades_porte_une_colonne_horizon(_isolated_db):
    from backend.services import trade_log_service

    trade_log_service._init_schema()
    with sqlite3.connect(_isolated_db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(personal_trades)")}
    assert "horizon" in cols


# ── Le maillon 0 : le dispatch transmet ce qu'il sait ─────────────────────

class _Setup:
    pair = "XAU/USD"
    entry_price = 3400.12
    horizon = "4h"
    pattern = "momentum_up"


class _Dest:
    destination_id = "admin_live"


def test_le_registre_de_poussee_transmet_l_horizon_du_setup(_isolated_db):
    """⛔ Le maillon décisif. `setup.horizon` sert déjà à refuser des routes
    (`_horizon_rejection`) — il était donc disponible tout du long, et jeté."""
    from backend.services import mt5_pushes_service as ps
    from backend.services.bridge_push_ledger import PushLedger

    l = PushLedger.for_setup(_Dest(), _Setup(), "sell")
    assert l.horizon == "4h"
    assert l.pattern == "momentum_up"

    assert l.reserve() is True
    p = ps.get_push(l.destination_id, l.push_date, l.pair, l.direction, l.entry_5dp)
    assert p["horizon"] == "4h"
    assert p["pattern"] == "momentum_up"


def test_un_setup_sans_horizon_ne_fait_pas_echouer_la_poussee(_isolated_db):
    """Toutes les routes ne renseignent pas l'horizon. Aucune ne doit casser :
    une traçabilité qui empêche de trader serait pire que son absence."""
    from backend.services.bridge_push_ledger import PushLedger

    class _Nu:
        pair = "EUR/USD"
        entry_price = 1.1

    l = PushLedger.for_setup(_Dest(), _Nu(), "buy")
    assert l.horizon is None and l.pattern is None
    assert l.reserve() is True
