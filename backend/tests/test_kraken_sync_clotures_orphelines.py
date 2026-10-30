"""Une clôture ne doit pas être perdue parce que son push a été purgé.

## L'incident, mesuré le 2026-10-30

`attribuer_clotures` ne reconnaît une fermeture qu'à travers l'`order_id` du
SL ou du TP **de son push**. Un fill sans push est écarté par un `continue`
muet, et `purge_old_pushes` supprime les pushes au bout de 30 jours.

Confronté aux fills du courtier : **7 clôtures sur 49 manquaient aux livres**
(14 %), pour **+4,20 $** net jamais porté. Les trois vérifiées une par une :

| position | ouverte | fermée | sortie | gain perdu |
|---|---|---|---|---|
| `AVAX` | 07/09 | 19/09 | **9,862 = son objectif PILE** | +3,27 $ |
| `XLM`  | 15/09 | 22/09 | 0,21533 | +1,40 $ |
| `DOT`  | 22/08 | 27/09 | 1,235 | +0,63 $ |

`DOT` a vécu **36 jours**, au-delà de la rétention. `XLM` a manqué la fenêtre
conservée de **20 heures** (poussé le 15/09 à 01h17, fenêtre ouvrant à 21h58).

Les données de ces tests sont **celles de l'incident**, prix et P&L compris.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import kraken_sync as ks


# --- les fills réels, côté clôture ---------------------------------------

F_AVAX = {"order_id": "inconnu-avax", "symbol": "PF_AVAXUSD", "side": "sell",
          "size": 1.82, "price": 9.862, "realized_pnl": 3.2669,
          "fill_time": "2026-09-19T23:16:32.000Z"}
F_XLM = {"order_id": "inconnu-xlm", "symbol": "PF_XLMUSD", "side": "sell",
         "size": 63.0, "price": 0.21533, "realized_pnl": 1.3999,
         "fill_time": "2026-09-22T21:39:58.000Z"}
F_DOT = {"order_id": "inconnu-dot", "symbol": "PF_DOTUSD", "side": "sell",
         "size": 2.2, "price": 1.235, "realized_pnl": 0.6255,
         "fill_time": "2026-09-27T13:55:33.000Z"}


@pytest.fixture()
def base(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT DEFAULT 'auto',
            pair TEXT, direction TEXT, entry_price REAL, stop_loss REAL,
            take_profit REAL, size_lot REAL, status TEXT DEFAULT 'OPEN',
            exit_price REAL, pnl REAL DEFAULT 0, created_at TEXT,
            closed_at TEXT, close_reason TEXT, mt5_ticket TEXT,
            is_auto INTEGER DEFAULT 1, destination_id TEXT)""")
    monkeypatch.setattr(ks, "_db_path", lambda: str(db))
    return str(db)


def _ouvrir(db, pair, direction="buy", entree=8.067, lot=1.82,
            cree="2026-09-07T14:42:22+00:00", ticket="a2b09006",
            dest="admin_kraken", status="OPEN"):
    with sqlite3.connect(db) as c:
        c.execute("""INSERT INTO personal_trades
            (pair, direction, entry_price, stop_loss, take_profit, size_lot,
             status, created_at, mt5_ticket, destination_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (pair, direction, entree, entree * 0.9, entree * 1.2, lot,
                   status, cree, ticket, dest))


# --- le cas nominal : ce que l'incident aurait dû produire ----------------

def test_AVAX_est_rattrapee_avec_son_prix_et_son_pnl(base):
    _ouvrir(base, "AVAX/USD")
    out = ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.0}, set())
    assert len(out) == 1
    c = out[0]
    assert c["cause"] == ks.CAUSE_EXTERNE
    assert c["exit_price"] == pytest.approx(9.862)
    assert c["pnl_usd"] == pytest.approx(3.2669)
    assert c["closed_at"].startswith("2026-09-19")
    assert c["complete"] is True


def test_la_cloture_rattrapee_s_ECRIT_bien(base):
    """Bout en bout : le « push » synthétique doit satisfaire
    `enregistrer_cloture`, sinon le rattrapage ne sert à rien."""
    _ouvrir(base, "AVAX/USD")
    c = ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.0}, set())[0]
    trade = ks.enregistrer_cloture(c, eur_usd=1.155)
    assert trade is not None
    with sqlite3.connect(base) as cx:
        cx.row_factory = sqlite3.Row
        r = dict(cx.execute("SELECT * FROM personal_trades").fetchone())
    assert r["status"] == "CLOSED"
    assert r["close_reason"] == "EXTERNE"
    assert r["pnl"] == pytest.approx(3.2669 / 1.155, abs=0.01)
    assert r["exit_price"] == pytest.approx(9.862)


@pytest.mark.parametrize("pair,fill,ticket,entree,lot,cree", [
    ("XLM/USD", F_XLM, "a2bf881e", 0.19311, 63.0, "2026-09-15T01:17:41+00:00"),
    ("DOT/USD", F_DOT, "a28f3377", 0.9507, 2.2, "2026-08-22T00:41:14+00:00"),
])
def test_les_trois_de_l_incident_sont_toutes_rattrapees(
        base, pair, fill, ticket, entree, lot, cree):
    _ouvrir(base, pair, entree=entree, lot=lot, cree=cree, ticket=ticket)
    out = ks.clotures_orphelines([fill], {fill["symbol"]: 0.0}, set())
    assert len(out) == 1, "%s n'a pas ete rattrapee" % pair
    assert out[0]["pnl_usd"] == pytest.approx(fill["realized_pnl"])


# --- LES QUATRE REFUS, qui font la sûreté --------------------------------

def test_une_exposition_ILLISIBLE_ne_ferme_RIEN(base):
    """⛔ LE refus qui compte. `positions is None` = panne réseau. La traiter
    comme « position fermée » clôturerait des lignes vivantes à chaque
    incident de liaison."""
    _ouvrir(base, "AVAX/USD")
    assert ks.clotures_orphelines([F_AVAX], None, set()) == []


def test_une_exposition_NON_NULLE_ne_ferme_rien(base):
    """Une réduction partielle n'est pas une clôture."""
    _ouvrir(base, "AVAX/USD")
    assert ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.9}, set()) == []


def test_DEUX_lignes_ouvertes_sur_le_meme_symbole_ne_ferment_RIEN(base, caplog):
    """⛔ Choisir laquelle fermer serait une attribution inventée. On
    s'abstient, et surtout on le DIT — c'est le silence qui a coûté cher."""
    _ouvrir(base, "AVAX/USD", ticket="t1")
    _ouvrir(base, "AVAX/USD", ticket="t2", cree="2026-09-08T10:00:00+00:00")
    with caplog.at_level("WARNING"):
        out = ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.0}, set())
    assert out == []
    assert any("AVAX" in r.message or "AVAX" in str(r.args)
               for r in caplog.records), "l'abstention doit etre journalisee"


def test_un_fill_DEJA_attribue_n_est_pas_redouble(base):
    """Les voies qui connaissent la cause passent d'abord ; le rattrapage ne
    doit pas réécrire ce qu'elles ont déjà pris."""
    _ouvrir(base, "AVAX/USD", ticket="a2b09006")
    assert ks.clotures_orphelines(
        [F_AVAX], {"PF_AVAXUSD": 0.0}, {"a2b09006"}) == []


# --- les filtres sur les fills -------------------------------------------

def test_un_fill_du_MAUVAIS_SENS_est_ignore(base):
    """Sur une ligne acheteuse, seul un `sell` ferme."""
    _ouvrir(base, "AVAX/USD", direction="buy")
    achat = dict(F_AVAX, side="buy")
    assert ks.clotures_orphelines([achat], {"PF_AVAXUSD": 0.0}, set()) == []


def test_un_fill_ANTERIEUR_a_l_ouverture_est_ignore(base):
    """Sinon on rattacherait la clôture d'un trade précédent sur le même
    symbole — exactement l'erreur que le nettage Kraken rend facile."""
    _ouvrir(base, "AVAX/USD", cree="2026-09-25T00:00:00+00:00")
    assert ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.0}, set()) == []


def test_un_fill_sans_PNL_realise_n_est_pas_une_cloture(base):
    """Un `realized_pnl` nul, c'est une OUVERTURE."""
    _ouvrir(base, "AVAX/USD")
    ouverture = dict(F_AVAX, realized_pnl=0.0)
    assert ks.clotures_orphelines([ouverture], {"PF_AVAXUSD": 0.0}, set()) == []


def test_une_ligne_DEJA_fermee_n_est_pas_retouchee(base):
    _ouvrir(base, "AVAX/USD", status="CLOSED")
    assert ks.clotures_orphelines([F_AVAX], {"PF_AVAXUSD": 0.0}, set()) == []


def test_plusieurs_fills_se_SOMMENT_en_une_cloture(base):
    """Une clôture peut arriver en morceaux : taille, notionnel et P&L
    s'additionnent, et la date retenue est la DERNIÈRE."""
    _ouvrir(base, "AVAX/USD", lot=1.82)
    a = dict(F_AVAX, size=1.0, price=9.8, realized_pnl=1.0,
             fill_time="2026-09-19T23:16:00.000Z")
    b = dict(F_AVAX, size=0.82, price=10.0, realized_pnl=2.2669,
             fill_time="2026-09-19T23:16:32.000Z")
    c = ks.clotures_orphelines([a, b], {"PF_AVAXUSD": 0.0}, set())[0]
    assert c["taille"] == pytest.approx(1.82)
    assert c["pnl_usd"] == pytest.approx(3.2669)
    assert c["exit_price"] == pytest.approx((1.0 * 9.8 + 0.82 * 10.0) / 1.82)
    assert c["closed_at"].endswith("23:16:32.000Z")


# --- la traduction des symboles ------------------------------------------

@pytest.mark.parametrize("sym,attendu", [
    ("PF_DOTUSD", "DOT/USD"), ("PF_AVAXUSD", "AVAX/USD"),
    ("PF_XLMUSD", "XLM/USD"), ("PF_XBTUSD", "BTC/USD"),
    ("PF_INJUSD", "INJ/USD"),
])
def test_symbole_vers_paire(sym, attendu):
    assert ks._symbole_vers_paire(sym) == attendu


@pytest.mark.parametrize("sym", [
    "PF_AAPLXUSD", "PF_SPYXUSD", "PF_NVDAXUSD",   # futures d'ACTIONS
    "XBTUSD", "PF_ETHEUR", "", None, "PF_USD",
])
def test_un_symbole_inattendu_rend_None_plutot_que_de_deviner(sym):
    """⛔ Deviner rapprocherait une clôture d'une ligne qui n'est pas la
    sienne. Les futures d'actions (`…XUSD`) sont écartés nommément."""
    assert ks._symbole_vers_paire(sym) is None


# --- le compteur qui aurait crié -----------------------------------------

def test_fills_non_attribues_compte_ce_que_personne_ne_reclame():
    pushes = [{"order_id": "o1", "sl_order_id": "sl1", "tp_order_id": "tp1"}]
    fills = [
        {"order_id": "sl1", "realized_pnl": -1.0},   # connu du push
        {"order_id": "o1", "realized_pnl": 0.0},     # ouverture, sans pnl
        {"order_id": "orphelin", "realized_pnl": 3.27},   # <-- le perdu
    ]
    assert ks.fills_non_attribues(pushes, fills, []) == 1


def test_un_fill_rattrape_ne_compte_plus_comme_orphelin():
    pushes = []
    fills = [{"order_id": "x", "realized_pnl": 3.27}]
    clotures = [{"push": {"order_id": "x"}}]
    assert ks.fills_non_attribues(pushes, fills, clotures) == 0


# ─── Un rattrapage s'ECRIT mais ne se NOTIFIE pas ────────────────────────
#
# Une cloture de septembre decouverte en octobre n'est pas une alerte, c'est
# du bruit -- et le bruit dans un fil de surveillance est la facon dont une
# vraie alerte se perd. La LIGNE est ecrite, le P&L est compte ; seule la
# notification est retenue, et l'omission est journalisee.

def _il_y_a(heures=0, jours=0):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc)
            - timedelta(hours=heures, days=jours)).isoformat()


def test_une_cloture_RECENTE_se_notifie():
    assert ks.notifiable(_il_y_a(heures=2)) is True


def test_une_cloture_de_PLUSIEURS_SEMAINES_ne_se_notifie_pas():
    assert ks.notifiable(_il_y_a(jours=40)) is False


def test_les_trois_de_l_incident_ne_notifieraient_PAS():
    """Les dates reelles : septembre 2026, soit plus d'un mois."""
    for quand in ("2026-09-19T23:16:32.000Z", "2026-09-22T21:39:58.000Z",
                  "2026-09-27T13:55:33.000Z"):
        assert ks.notifiable(quand) is False, quand


def test_la_bordure_est_du_bon_cote():
    assert ks.notifiable(_il_y_a(heures=ks.NOTIF_MAX_AGE_H - 1)) is True
    assert ks.notifiable(_il_y_a(heures=ks.NOTIF_MAX_AGE_H + 1)) is False


@pytest.mark.parametrize("valeur", [None, "", "pas une date", 12345, "2026-13-45"])
def test_une_date_ABSENTE_ou_ILLISIBLE_se_notifie(valeur):
    """⛔ Le silence n'est jamais le repli sur pour une notification : ne pas
    savoir QUAND une position s'est fermee est precisement une chose a dire."""
    assert ks.notifiable(valeur) is True


def test_un_retard_d_une_nuit_notifie_encore():
    """Le seuil doit tolerer un cycle rate, un redemarrage, une nuit — et
    retenir seulement les semaines."""
    assert ks.notifiable(_il_y_a(heures=10)) is True


# ─── LE TEST QUI MANQUAIT, et qui a laisse passer un correctif inerte ────
#
# Le 30/10, premier deploiement : les 3 clotures N'ONT PAS ete rattrapees.
# `clotures_orphelines` cherchait une entree explicite a ZERO dans le
# dictionnaire des positions. Mais `fetch_positions` ne liste que les
# positions OUVERTES : un symbole solde en est ABSENT, pas a zero.
#
# ⛔ Et mon epreuve de lecture seule faisait `positions.setdefault(sym, 0.0)` :
# elle injectait elle-meme les zeros manquants. L'instrument etait d'accord
# avec moi parce que je l'avais construit pour ca. Tous les tests ci-dessus
# passaient le symbole explicitement -- aucun ne testait l'ABSENCE.

def test_un_symbole_ABSENT_des_positions_est_PLAT(base):
    """⛔ LE cas reel de la production : le pont ne rend que PF_INJUSD, et
    AVAX -- solde -- n'apparait nulle part. Il doit quand meme etre
    rattrape."""
    _ouvrir(base, "AVAX/USD")
    reel = {"PF_INJUSD": 0.4}        # exactement ce que le pont renvoyait
    out = ks.clotures_orphelines([F_AVAX], reel, set())
    assert len(out) == 1, (
        "un symbole absent du dictionnaire est PLAT : `fetch_positions` ne "
        "liste que les positions OUVERTES")
    assert out[0]["pnl_usd"] == pytest.approx(3.2669)


def test_un_compte_entierement_a_plat_rattrape_tout(base):
    """`{}` signifie « compte reellement a plat », et non « inconnu » —
    c'est la distinction que `fetch_positions` a ete ecrite pour porter."""
    _ouvrir(base, "AVAX/USD")
    out = ks.clotures_orphelines([F_AVAX], {}, set())
    assert len(out) == 1


def test_le_symbole_ENCORE_OUVERT_n_est_pas_ferme_lui(base):
    """Le revers : INJ est dans la liste avec une taille non nulle, donc on
    n'y touche pas. C'est ce qui distingue un rattrapage d'un degat."""
    _ouvrir(base, "INJ/USD", entree=7.979, lot=0.4, ticket="a2f5e01e",
            cree="2026-10-12T01:38:27+00:00")
    f_inj = {"order_id": "x", "symbol": "PF_INJUSD", "side": "sell",
             "size": 0.4, "price": 8.5, "realized_pnl": 0.2,
             "fill_time": "2026-10-29T12:00:00.000Z"}
    assert ks.clotures_orphelines([f_inj], {"PF_INJUSD": 0.4}, set()) == []
