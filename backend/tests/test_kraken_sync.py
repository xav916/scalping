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
    # `EXTERNE` depuis le 2026-08-09 : `NET` couvrait deux situations opposées
    # — un ordre qui RÉDUIT une position (P&L connu) et une position DISPARUE
    # (P&L inconnu). Le même libellé rendait la seconde indétectable.
    assert all(c["cause"] == ks.CAUSE_EXTERNE for c in r)


def test_un_pnl_non_attribuable_reste_absent():
    """Un montant inventé serait lu comme vrai."""
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.0}, deja_closes=set())
    assert all(c["pnl_usd"] is None for c in r)


def test_une_position_encore_ouverte_n_est_pas_fermee():
    r = ks.clotures_par_nettage(PUSHES, FILLS, {"PF_ETHUSD": 0.107, "PF_XBTUSD": 0.0},
                                deja_closes=set())
    assert {c["push"]["push_id"] for c in r} == {12963}


def test_positions_indisponibles_ne_ferme_rien():
    """Ne jamais conclure d'une absence d'information.

    `None` = bridge injoignable ; `{}` = compte reellement a plat. Les deux
    valaient `{}` avant, ce qui empechait un compte solde de fermer nos
    lignes par prudence contre une panne qui n'avait pas eu lieu.
    """
    assert ks.clotures_par_nettage(PUSHES, FILLS, None, deja_closes=set()) == []


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
    assert _lignes(base)[0]["close_reason"] == ks.CAUSE_EXTERNE
    # ⚠️ Et la colonne doit valoir NULL, pas le 0.0 posé à l'ouverture.
    assert _lignes(base)[0]["pnl"] is None


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


# --- symétrie ouverture / clôture -----------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("pair", ["BTC/USD", "ETH/USD", "SOL/USD"])
async def test_toute_cloture_en_argent_reel_est_notifiee(pair, monkeypatch):
    """L'ouverture était notifiée pour toute destination réelle, la clôture
    filtrée aux « paires stars ». On recevait donc « trade ouvert BTC » sans
    jamais « trade fermé BTC » — or c'est la clôture qui porte le résultat.
    """
    from backend.services import telegram_service as ts

    envois: list[str] = []

    class _Rep:
        status_code = 200
        text = "ok"

    async def _post(self, url, **kw):
        envois.append(str(url))
        return _Rep()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    monkeypatch.setattr(ts, "destination_for_ticket", lambda t: "admin_kraken")
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("__any__", "1")])
    ts._notified_closes.clear()

    await ts.send_close({
        "pair": pair, "direction": "sell", "entry_price": 100.0,
        "exit_price": 101.0, "pnl": -0.55, "close_reason": "SL",
        "mt5_ticket": f"uuid-{pair}", "size_lot": 0.01,
        "created_at": "2026-08-04T17:50:47+00:00",
        "closed_at": "2026-08-04T18:15:21+00:00",
    })
    assert envois, f"{pair} : cloture en argent reel non notifiee"
    assert len(envois) == 1, (
        f"{pair} : {len(envois)} envois pour une seule cloture. Un miroir vers "
        "le canal sales dupliquait chaque message ; une cloture est un "
        "evenement de trade et n'appartient qu'au canal des trades."
    )


@pytest.mark.asyncio
async def test_une_paire_non_star_hors_argent_reel_reste_filtree(monkeypatch):
    """Le filtre garde son rôle pour les customers."""
    from backend.services import telegram_service as ts

    envois: list[str] = []

    async def _post(self, url, **kw):
        envois.append(str(url))
        raise AssertionError("ne devrait pas envoyer")

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    monkeypatch.setattr(ts, "destination_for_ticket", lambda t: "admin_legacy")
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("__any__", "1")])
    ts._notified_closes.clear()

    await ts.send_close({
        "pair": "SOL/USD", "direction": "sell", "entry_price": 100.0,
        "exit_price": 101.0, "pnl": -0.55, "close_reason": "SL",
        "mt5_ticket": "uuid-demo", "size_lot": 0.01,
        "created_at": "2026-08-04T17:50:47+00:00",
        "closed_at": "2026-08-04T18:15:21+00:00",
    })
    assert envois == []


@pytest.mark.asyncio
async def test_une_cloture_ne_part_que_sur_le_canal_des_trades(monkeypatch):
    """Répartition convenue : infra / trades / récap, un canal par nature.

    Chaque clôture partait sur le canal des trades ET en miroir sur sales,
    dans le même format — deux messages pour un évènement.
    """
    from backend.services import telegram_service as ts

    urls: list[str] = []

    class _Rep:
        status_code = 200
        text = "ok"

    async def _post(self, url, **kw):
        urls.append(str(url))
        return _Rep()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    monkeypatch.setattr(ts, "destination_for_ticket", lambda t: "admin_kraken")
    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("__any__", "1")])
    ts._notified_closes.clear()

    await ts.send_close({
        "pair": "ETH/USD", "direction": "sell", "entry_price": 1868.0,
        "exit_price": 1878.8, "pnl": -0.31, "close_reason": "SL",
        "mt5_ticket": "uuid-eth-unique", "size_lot": 0.054,
        "created_at": "2026-08-04T17:59:41+00:00",
        "closed_at": "2026-08-04T18:20:33+00:00",
    })
    assert len(urls) == 1, f"{len(urls)} envois pour une cloture : {urls}"


def test_le_miroir_sales_a_bien_disparu():
    """Garde-fou : le miroir ne doit pas revenir par recopie."""
    import inspect

    from backend.services import telegram_service as ts
    src = inspect.getsource(ts.send_close)
    assert "SALES_TELEGRAM_BOT_TOKEN" not in src, (
        "le miroir sales est de retour dans send_close"
    )


# --- un ordre qui reduit n'est pas une position ---------------------------

def test_un_ordre_qui_reduit_une_position_n_est_pas_une_ouverture():
    """Kraken nette par symbole : un achat pendant qu'on est vendeur ferme,
    il n'ouvre pas.

    Le 2026-08-04, deux achats ETH ont été comptés comme des positions
    ouvertes alors qu'ils réduisaient un short. Le garde-fou de corrélation
    voyait donc ETH ouvert dans les deux sens, et bloquait BTC dans les deux
    sens aussi.
    """
    ouv = "ordre-achat-reducteur"
    pushes = [_push(1, "ETH/USD", "buy", ouv, "sl-1", 0.057, 1874.0)]
    fills = [{"order_id": ouv, "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.057, "price": 1874.0,
              "fill_time": "2026-08-04T18:14:38Z", "realized_pnl": -0.3342}]
    c = ks.attribuer_clotures(pushes, fills)
    assert len(c) == 1, "l'ordre reducteur n'a pas ete reconnu comme cloture"
    assert c[0]["cause"] == ks.CAUSE_NET
    assert c[0]["pnl_usd"] == pytest.approx(-0.3342)
    assert c[0]["complete"] is True


def test_un_ordre_qui_ouvre_vraiment_reste_ouvert():
    """`realized_pnl` nul sur sa propre exécution = nouvelle exposition."""
    ouv = "ordre-vente-ouvrant"
    pushes = [_push(1, "ETH/USD", "sell", ouv, "sl-1", 0.215, 1874.6)]
    fills = [{"order_id": ouv, "symbol": "PF_ETHUSD", "side": "sell",
              "size": 0.215, "price": 1874.6,
              "fill_time": "2026-08-04T18:17:38Z", "realized_pnl": 0.0}]
    assert ks.attribuer_clotures(pushes, fills) == []


def test_le_stop_prime_sur_la_reduction():
    """Si le SL a été exécuté, la cause est SL — pas NET."""
    pushes = [_push(1, "ETH/USD", "sell", "ouv", "sl-1", 0.1, 1868.0)]
    fills = [{"order_id": "ouv", "symbol": "PF_ETHUSD", "side": "sell",
              "size": 0.1, "price": 1868.0, "fill_time": "2026-08-04T17:00:00Z",
              "realized_pnl": -0.05},
             {"order_id": "sl-1", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.1, "price": 1878.8, "fill_time": "2026-08-04T18:20:33Z",
              "realized_pnl": -1.08}]
    c = ks.attribuer_clotures(pushes, fills)
    assert len(c) == 1
    assert c[0]["cause"] == ks.CAUSE_SL


def test_chaque_pnl_realise_n_est_compte_qu_une_fois():
    """La propriété qui compte : rien de double, rien d'invente."""
    pushes = [_push(1, "ETH/USD", "sell", "ouv-a", "sl-a", 0.1, 1868.0),
              _push(2, "ETH/USD", "buy", "ouv-b", "sl-b", 0.05, 1874.0)]
    fills = [{"order_id": "sl-a", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.1, "price": 1878.8, "fill_time": "2026-08-04T18:20:33Z",
              "realized_pnl": -1.08},
             {"order_id": "ouv-b", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.05, "price": 1874.0, "fill_time": "2026-08-04T18:14:38Z",
              "realized_pnl": -0.33}]
    total = sum(c["pnl_usd"] for c in ks.attribuer_clotures(pushes, fills))
    assert total == pytest.approx(-1.41)


# --- volume des positions partiellement reduites --------------------------

def test_le_volume_suit_le_net_de_l_exchange():
    """Le cas du 2026-08-04 : vendu 0,215, racheté 0,108, net 0,107.

    La ligne restait affichée à 0,215 — soit le double de l'exposition
    réelle. Toute lecture d'exposition en était faussée.
    """
    ouvertes = [{"order_id": "D", "volume": 0.215,
                 "pushed_at": "2026-08-04T18:17:37"}]
    assert ks.repartir_volume_net(ouvertes, -0.107) == {"D": 0.107}


def test_le_sens_du_net_selectionne_les_lignes_eligibles():
    """Si l'exchange est vendeur, une ligne acheteuse est contredite par la
    realite du compte : elle ne peut porter aucun residuel."""
    vendeuse = {"order_id": "S", "volume": 0.215, "direction": "sell",
                "pushed_at": "1"}
    acheteuse = {"order_id": "B", "volume": 0.100, "direction": "buy",
                 "pushed_at": "2"}
    r = ks.repartir_volume_net([vendeuse, acheteuse], -0.107)
    assert r["S"] == pytest.approx(0.107), "la vendeuse doit porter le net"
    assert r["B"] == 0.0, "une acheteuse ne peut porter un net vendeur"

    r = ks.repartir_volume_net([vendeuse, acheteuse], +0.080)
    assert r["B"] == pytest.approx(0.080)
    assert r["S"] == 0.0


def test_la_repartition_suit_la_convention_fifo():
    """Ce qui a été racheté a fermé les positions les plus anciennes : le
    résiduel appartient donc aux plus récentes."""
    ouvertes = [{"order_id": "A", "volume": 0.098, "pushed_at": "17:50"},
                {"order_id": "B", "volume": 0.089, "pushed_at": "17:56"},
                {"order_id": "C", "volume": 0.054, "pushed_at": "17:59"}]
    r = ks.repartir_volume_net(ouvertes, -0.10)
    assert r["C"] == pytest.approx(0.054)
    assert r["B"] == pytest.approx(0.046)
    assert r["A"] == 0.0


def test_la_somme_repartie_egale_toujours_le_net():
    """C'est la propriété qui définit la fonction."""
    ouvertes = [{"order_id": c, "volume": v, "pushed_at": str(i)}
                for i, (c, v) in enumerate([("A", 0.1), ("B", 0.2), ("C", 0.05)])]
    for net in (-0.35, -0.2, -0.05, 0.0, -0.34999):
        assert sum(ks.repartir_volume_net(ouvertes, net).values()) == pytest.approx(
            min(abs(net), 0.35), abs=1e-9)


def test_un_net_superieur_a_nos_lignes_ne_les_gonfle_pas():
    """Une position ouverte à la main chez Kraken ne doit pas être absorbée
    dans nos lignes."""
    ouvertes = [{"order_id": "A", "volume": 0.1, "pushed_at": "t"}]
    assert ks.repartir_volume_net(ouvertes, -5.0) == {"A": 0.1}


def test_un_net_nul_vide_toutes_les_lignes():
    ouvertes = [{"order_id": "A", "volume": 0.1, "pushed_at": "1"},
                {"order_id": "B", "volume": 0.2, "pushed_at": "2"}]
    assert ks.repartir_volume_net(ouvertes, 0.0) == {"A": 0.0, "B": 0.0}


def test_le_volume_est_corrige_en_base(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.215,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    assert ks.ajuster_volumes_ouverts(pushes, {"PF_ETHUSD": -0.107}) == 1
    assert _lignes(base)[0]["size_lot"] == pytest.approx(0.107)


def test_une_position_absorbee_est_fermee(base):
    """La laisser ouverte à volume nul en ferait une position fantôme, encore
    comptée par le cap par paire et le garde-fou de corrélation."""
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.215,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    ks.ajuster_volumes_ouverts(pushes, {"PF_ETHUSD": 0.0})
    ligne = _lignes(base)[0]
    assert ligne["status"] == "CLOSED"
    assert ligne["size_lot"] == 0
    assert ligne["close_reason"] == ks.CAUSE_NET
    assert ligne["pnl"] is None or ligne["pnl"] == 0


def test_sans_positions_connues_aucun_volume_n_est_touche(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.215,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    assert ks.ajuster_volumes_ouverts(pushes, None) == 0
    assert _lignes(base)[0]["size_lot"] == pytest.approx(0.215)


def test_un_volume_deja_juste_n_est_pas_reecrit(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.107,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    assert ks.ajuster_volumes_ouverts(pushes, {"PF_ETHUSD": -0.107}) == 0


def test_l_ajustement_intervient_apres_les_clotures():
    """Ajuster avant toucherait des lignes qui vont fermer."""
    import inspect
    src = inspect.getsource(ks.reconcile)
    assert src.index("enregistrer_cloture") < src.index("ajuster_volumes_ouverts")


@pytest.mark.asyncio
async def test_une_position_vendeuse_est_lue_comme_negative(monkeypatch):
    """Le sens était jeté à la lecture. Sans lui, une vente de 0,107 ne se
    distingue pas d'un achat, et le résiduel serait attribué à la mauvaise
    ligne."""
    import httpx

    async def _get(self, url, headers=None):
        return httpx.Response(200, json={"ok": True, "count": 2, "positions": [
            {"symbol": "PF_ETHUSD", "side": "short", "size": 0.107},
            {"symbol": "PF_XBTUSD", "side": "long", "size": 0.0023},
        ]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    pos = await ks.fetch_positions(NS(bridge_url="http://b.test",
                                      bridge_api_key="k"))
    assert pos["PF_ETHUSD"] == pytest.approx(-0.107), "vente lue comme achat"
    assert pos["PF_XBTUSD"] == pytest.approx(0.0023)


@pytest.mark.asyncio
async def test_un_bridge_injoignable_ne_renvoie_aucune_position(monkeypatch):
    """`{}` fait que rien n'est conclu — ni clôture, ni ajustement."""
    import httpx

    async def _get(self, url, headers=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    assert await ks.fetch_positions(NS(bridge_url="http://b.test",
                                       bridge_api_key="k")) is None


def test_un_stop_sur_position_reduite_est_une_cloture_complete(base):
    """Le cas du 2026-08-04 19:38 : un short de 0,215 réduit à 0,107 puis
    stoppé. Comparer la taille fermée au volume D'ORIGINE jugeait la clôture
    incomplète — la position restait ouverte chez nous alors que Kraken
    l'avait fermée."""
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    fills = [{"order_id": "sl-D", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.107, "price": 1879.6,
              "fill_time": "2026-08-04T19:38:52Z", "realized_pnl": -0.799}]

    sans = ks.attribuer_clotures(pushes, fills)[0]
    assert sans["complete"] is False, "sans volume courant, jugee partielle"

    avec = ks.attribuer_clotures(pushes, fills, {"D": 0.107})[0]
    assert avec["complete"] is True
    assert avec["pnl_usd"] == pytest.approx(-0.799)


@pytest.mark.asyncio
async def test_un_bridge_injoignable_se_distingue_d_un_compte_a_plat(monkeypatch):
    """Les deux renvoyaient `{}` : un compte soldé ne fermait donc jamais nos
    lignes, par prudence contre une panne qui n'avait pas eu lieu."""
    import httpx

    async def _plat(self, url, headers=None):
        return httpx.Response(200, json={"ok": True, "count": 0, "positions": []},
                              request=httpx.Request("GET", url))

    async def _panne(self, url, headers=None):
        raise httpx.ConnectError("refused")

    d = NS(bridge_url="http://b.test", bridge_api_key="k")
    monkeypatch.setattr(httpx.AsyncClient, "get", _plat)
    assert await ks.fetch_positions(d) == {}
    monkeypatch.setattr(httpx.AsyncClient, "get", _panne)
    assert await ks.fetch_positions(d) is None


def test_un_compte_a_plat_ferme_nos_lignes(base):
    """`{}` signifie zero exposition : nos lignes doivent suivre."""
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.215,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    assert ks.ajuster_volumes_ouverts(pushes, {}) == 1
    assert _lignes(base)[0]["status"] == "CLOSED"


def test_une_exposition_inconnue_ne_ferme_rien(base):
    with sqlite3.connect(base) as c:
        c.execute("INSERT INTO personal_trades (user,pair,direction,entry_price,"
                  "stop_loss,take_profit,size_lot,status,created_at,mt5_ticket,"
                  "is_auto) VALUES ('auto','ETH/USD','sell',1874.6,1884.0,1857.0,"
                  "0.215,'OPEN','2026-08-04T18:17:37','D',1)")
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    assert ks.ajuster_volumes_ouverts(pushes, None) == 0
    assert _lignes(base)[0]["status"] == "OPEN"


def test_un_stop_est_complet_des_lors_que_le_symbole_est_a_plat():
    """La complétude ne doit pas dépendre d'un volume ajusté plus tard dans
    le même cycle : c'est circulaire, et ce cercle a fait perdre le P&L d'un
    stop réel le 2026-08-04. Un SL est `reduceOnly` et dimensionné sur la
    position — son exécution EST la clôture."""
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    fills = [{"order_id": "sl-D", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.107, "price": 1879.6,
              "fill_time": "2026-08-04T19:38:52Z", "realized_pnl": -0.799}]

    sans = ks.attribuer_clotures(pushes, fills)[0]
    assert sans["complete"] is False

    avec = ks.attribuer_clotures(pushes, fills, None, {})[0]
    assert avec["complete"] is True, "symbole a plat : la cloture est complete"
    assert avec["cause"] == ks.CAUSE_SL
    assert avec["pnl_usd"] == pytest.approx(-0.799)


def test_une_exposition_restante_n_autorise_pas_la_completude():
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    fills = [{"order_id": "sl-D", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.05, "price": 1879.6,
              "fill_time": "2026-08-04T19:38:52Z", "realized_pnl": -0.3}]
    c = ks.attribuer_clotures(pushes, fills, None, {"PF_ETHUSD": -0.157})[0]
    assert c["complete"] is False


def test_le_stop_prime_sur_le_nettage_quand_le_symbole_est_a_plat():
    """Sinon la cause devient NET et le P&L realise est perdu."""
    pushes = [_push(1, "ETH/USD", "sell", "D", "sl-D", 0.215, 1874.6)]
    fills = [{"order_id": "sl-D", "symbol": "PF_ETHUSD", "side": "buy",
              "size": 0.107, "price": 1879.6,
              "fill_time": "2026-08-04T19:38:52Z", "realized_pnl": -0.799}]
    cl = [c for c in ks.attribuer_clotures(pushes, fills, None, {}) if c["complete"]]
    vus = {c["push"]["push_id"] for c in cl}
    assert ks.clotures_par_nettage(pushes, fills, {}, vus) == []
