"""Réconciliation des clôtures Kraken (2026-08-04).

``send_close`` n'était appelé que depuis ``mt5_sync``. Le 2026-08-04, quatre
positions Kraken réelles ont touché leur stop — quatre pertes encaissées —
sans notification ni ligne de clôture. Le côté qui coûte de l'argent était
celui qui n'était pas couvert.

Les données de ces tests sont **réelles** : ce sont les exécutions du compte
Kraken ce jour-là, avec leurs identifiants d'ordre et le P&L que Kraken a
lui-même calculé. Elles vérifient la propriété qui fait tout l'intérêt de
Kraken sur MT5 : la cause de sortie est **connue** par l'``order_id``, elle
n'est pas devinée par proximité du prix.
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from backend.services import kraken_sync as ks


# --- les données réelles du 2026-08-04 ------------------------------------

SL_ETH = "a26c7120-c94d-4bbd-a493-1f1fc428821b"
SL_BTC = "a26c6df2-47a3-464a-b29d-149c418e40ed"
OUV_ETH = "a26c6df2-33b3-4681-9751-55dc29752f64"
OUV_BTC = "a26c6df2-2846-4e18-8840-b26ceab21741"

FILLS = [
    {"order_id": SL_ETH, "symbol": "PF_ETHUSD", "side": "buy", "size": 0.054,
     "price": 1878.8, "fill_time": "2026-08-04T18:20:33.000Z",
     "realized_pnl": -0.36018440406},
    {"order_id": SL_BTC, "symbol": "PF_XBTUSD", "side": "buy", "size": 0.0023,
     "price": 64199.0, "fill_time": "2026-08-04T18:15:21.000Z",
     "realized_pnl": -0.6325},
    {"order_id": OUV_ETH, "symbol": "PF_ETHUSD", "side": "sell", "size": 0.054,
     "price": 1868.0, "fill_time": "2026-08-04T17:59:41.000Z",
     "realized_pnl": 0.0},
    {"order_id": OUV_BTC, "symbol": "PF_XBTUSD", "side": "sell", "size": 0.0023,
     "price": 63924.0, "fill_time": "2026-08-04T17:50:47.000Z",
     "realized_pnl": 0.0},
]


def _push(pid, pair, direction, order_id, sl_id, volume, entry, tp_id=None):
    return {"push_id": pid, "destination_id": "admin_kraken", "pair": pair,
            "direction": direction, "pushed_at": "2026-08-04T17:50:47+00:00",
            "symbol": "PF_ETHUSD" if pair.startswith("ETH") else "PF_XBTUSD",
            "order_id": order_id, "sl_order_id": sl_id, "tp_order_id": tp_id,
            "volume": volume, "entry_price": entry, "sl": None, "tp": None}


PUSHES = [
    _push(12963, "BTC/USD", "sell", OUV_BTC, SL_BTC, 0.0023, 63924.0),
    _push(12966, "ETH/USD", "sell", OUV_ETH, SL_ETH, 0.054, 1868.0),
]


# --- LE point : la cause de sortie est connue, pas devinée -----------------

def test_la_cause_de_sortie_vient_de_l_identifiant_d_ordre():
    """MT5 doit deviner par proximité du prix ; Kraken le dit."""
    cl = {c["push"]["push_id"]: c for c in ks.attribuer_clotures(PUSHES, FILLS)}
    assert cl[12963]["cause"] == ks.CAUSE_SL
    assert cl[12966]["cause"] == ks.CAUSE_SL


def test_un_take_profit_est_distingue_d_un_stop():
    pushes = [_push(1, "ETH/USD", "sell", "ouv", "sl-x", 0.1, 1868.0, tp_id="tp-x")]
    fills = [{"order_id": "tp-x", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.1, "price": 1850.0, "fill_time": "2026-08-04T19:00:00Z",
              "realized_pnl": 1.80}]
    c = ks.attribuer_clotures(pushes, fills)[0]
    assert c["cause"] == ks.CAUSE_TP
    assert c["pnl_usd"] == pytest.approx(1.80)


def test_le_pnl_vient_de_kraken_et_n_est_pas_recalcule():
    """Kraken tient compte du financement et des frais : on ne refait pas."""
    cl = {c["push"]["push_id"]: c for c in ks.attribuer_clotures(PUSHES, FILLS)}
    assert cl[12963]["pnl_usd"] == pytest.approx(-0.6325)
    assert cl[12966]["pnl_usd"] == pytest.approx(-0.36018, abs=1e-4)


def test_les_ordres_d_ouverture_ne_ferment_rien():
    """Un fill d'ouverture porte le `market_order_id`, pas le SL/TP."""
    fermes = {c["push"]["push_id"] for c in ks.attribuer_clotures(PUSHES, FILLS)}
    ouvertures = [f for f in FILLS if f["order_id"] in (OUV_ETH, OUV_BTC)]
    assert ouvertures, "jeu de donnees incomplet"
    assert len(fermes) == 2, "une ouverture a ete prise pour une cloture"


def test_un_fill_etranger_est_ignore():
    """Les ordres passés à la main ne doivent rien fermer du radar."""
    fills = FILLS + [{"order_id": "inconnu-9999", "symbol": "PF_AAPLXUSD",
                      "side": "sell", "size": 1.0, "price": 200.0,
                      "fill_time": "2026-08-02T15:23:39Z", "realized_pnl": -1.27}]
    assert len(ks.attribuer_clotures(PUSHES, fills)) == 2


# --- clôtures fractionnées -------------------------------------------------

def test_une_cloture_en_plusieurs_morceaux_est_agregee():
    """Trois ventes ETH ont été stoppées en trois exécutions le 2026-08-04."""
    pushes = [_push(1, "ETH/USD", "sell", "ouv", "sl-x", 0.24, 1868.0)]
    fills = [{"order_id": "sl-x", "symbol": "PF_ETHUSD", "side": "buy",
              "size": t, "price": 1878.8, "realized_pnl": p,
              "fill_time": f"2026-08-04T18:20:3{i}Z"}
             for i, (t, p) in enumerate([(0.054, -0.36), (0.089, -0.59),
                                         (0.098, -0.65)])]
    c = ks.attribuer_clotures(pushes, fills)[0]
    assert c["taille"] == pytest.approx(0.241)
    assert c["pnl_usd"] == pytest.approx(-1.60)
    assert c["exit_price"] == pytest.approx(1878.8)
    assert c["complete"] is True


def test_une_cloture_partielle_n_est_pas_declaree_fermee():
    """Fermer un trade encore ouvert ferait disparaître une position réelle."""
    pushes = [_push(1, "ETH/USD", "sell", "ouv", "sl-x", 0.24, 1868.0)]
    fills = [{"order_id": "sl-x", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.05, "price": 1878.8, "realized_pnl": -0.36,
              "fill_time": "2026-08-04T18:20:33Z"}]
    assert ks.attribuer_clotures(pushes, fills)[0]["complete"] is False


def test_la_date_retenue_est_celle_de_la_derniere_execution():
    pushes = [_push(1, "ETH/USD", "sell", "ouv", "sl-x", 0.2, 1868.0)]
    fills = [{"order_id": "sl-x", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.1, "price": 1878.0, "realized_pnl": -0.3,
              "fill_time": "2026-08-04T18:20:33Z"},
             {"order_id": "sl-x", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.1, "price": 1879.0, "realized_pnl": -0.4,
              "fill_time": "2026-08-04T18:21:10Z"}]
    assert ks.attribuer_clotures(pushes, fills)[0]["closed_at"].endswith("18:21:10Z")


# --- le nettage, propre à Kraken ------------------------------------------

def test_sans_exposition_restante_le_trade_est_ferme_par_nettage():
    """Un ordre opposé absorbe la position : ni SL ni TP n'a été exécuté."""
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.0}, deja_closes=set())
    assert {c["push"]["push_id"] for c in r} == {12963, 12966}
    assert all(c["cause"] == ks.CAUSE_NET for c in r)


def test_un_pnl_non_attribuable_reste_absent():
    """Un montant inventé serait lu comme vrai."""
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.0}, deja_closes=set())
    assert all(c["pnl_usd"] is None for c in r)


def test_une_position_encore_ouverte_n_est_pas_fermee():
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.107, "PF_XBTUSD": 0.0},
                                deja_closes=set())
    assert {c["push"]["push_id"] for c in r} == {12963}


def test_positions_indisponibles_ne_ferme_rien():
    """Ne jamais conclure d'une absence d'information."""
    assert ks.clotures_par_nettage(PUSHES, FILLS, {}, deja_closes=set()) == []


def test_un_trade_deja_ferme_par_son_stop_n_est_pas_refermé():
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.0},
                                deja_closes={12963, 12966})
    assert r == []


# --- écriture en base ------------------------------------------------------

@pytest.fixture
def base(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL DEFAULT 'x',
            pair TEXT NOT NULL, direction TEXT NOT NULL, entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL, take_profit REAL NOT NULL,
            size_lot REAL NOT NULL, status TEXT DEFAULT 'OPEN', exit_price REAL,
            pnl REAL DEFAULT 0, created_at TEXT NOT NULL, closed_at TEXT,
            close_reason TEXT, mt5_ticket, is_auto INTEGER DEFAULT 0)""")
    monkeypatch.setattr(ks, "_db_path", lambda: str(db))
    return str(db)


def _lignes(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM personal_trades")]


def test_la_cloture_est_ecrite_avec_le_pnl_en_euros(base):
    c = ks.attribuer_clotures(PUSHES, FILLS)[0]
    trade = ks.enregistrer_cloture(c, eur_usd=1.1525)
    assert trade is not None
    lignes = _lignes(base)
    assert len(lignes) == 1
    assert lignes[0]["status"] == "CLOSED"
    assert lignes[0]["pnl"] == pytest.approx(c["pnl_usd"] / 1.1525, abs=0.01)
    assert lignes[0]["is_auto"] == 1


def test_la_reference_kraken_est_conservee_telle_quelle(base):
    """C'est elle qui relie la clôture à son push, donc à sa destination."""
    c = ks.attribuer_clotures(PUSHES, FILLS)[0]
    ks.enregistrer_cloture(c, eur_usd=1.1525)
    assert _lignes(base)[0]["mt5_ticket"] == c["push"]["order_id"]


def test_une_cloture_deja_enregistree_n_est_pas_rejouee(base):
    """Sinon chaque cycle renotifierait la même perte."""
    c = ks.attribuer_clotures(PUSHES, FILLS)[0]
    assert ks.enregistrer_cloture(c, 1.1525) is not None
    assert ks.enregistrer_cloture(c, 1.1525) is None
    assert len(_lignes(base)) == 1


def test_les_colonnes_obligatoires_sont_renseignees(base):
    """`stop_loss` et `take_profit` sont NOT NULL : l'insertion echouerait."""
    for c in ks.attribuer_clotures(PUSHES, FILLS):
        assert ks.enregistrer_cloture(c, 1.1525) is not None
    assert len(_lignes(base)) == 2


def test_sans_pnl_attribuable_la_ligne_est_ecrite_sans_montant(base):
    c = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.0}, set())[0]
    trade = ks.enregistrer_cloture(c, 1.1525)
    assert trade["pnl"] is None
    assert _lignes(base)[0]["close_reason"] == ks.CAUSE_NET


# --- les hypothèses sur les autres modules --------------------------------

def test_les_fonctions_appelees_existent_vraiment():
    """`all_admin_destinations` n'existait pas : la faute n'aurait leve qu'en
    production, dans un `except` qui l'aurait avalee."""
    import ast
    import inspect

    from backend.services import bridge_destinations as bd

    src = inspect.getsource(ks.reconcile)
    appels = {n.func.attr for n in ast.walk(ast.parse(src.strip()))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name) and n.func.value.id == "bd"}
    assert appels, "aucun appel detecte : le test ne teste rien"
    manquantes = sorted(a for a in appels if not hasattr(bd, a))
    assert manquantes == [], f"fonctions inexistantes : {manquantes}"


def test_send_close_accepte_une_reference_non_numerique():
    """`int(ticket)` levait sur un UUID Kraken — donc sur toute cloture."""
    from backend.services import telegram_service as ts
    import inspect
    src = inspect.getsource(ts.send_close)
    assert "int(ticket)" not in src, "un UUID Kraken ferait lever la dedup"


def test_la_reconciliation_est_planifiee():
    """Un module jamais appelé ne notifie rien."""
    import inspect

    from backend.services import scheduler
    src = inspect.getsource(scheduler)
    assert "kraken_sync" in src
    assert "reconcile" in src
