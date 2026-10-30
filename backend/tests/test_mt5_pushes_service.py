"""Tests pour ``mt5_pushes_service`` — Phase B du multi-tenant bridge routing.

Vérifie la dedup atomique en DB (UNIQUE constraint), le cycle complet
(register → update → discard) et la purge.
"""
import logging
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import mt5_pushes_service, trade_log_service


@pytest.fixture
def db(tmp_path: Path):
    """DB SQLite isolée par test, schema initialisé."""
    db_file = tmp_path / "trades.db"
    with patch.object(trade_log_service, "_DB_PATH", db_file):
        mt5_pushes_service._ensure_schema()
        yield db_file


# ─── try_register_push ────────────────────────────────────────────────


def test_try_register_push_returns_true_for_new_key(db):
    ok = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert ok is True


def test_try_register_push_returns_false_on_duplicate(db):
    """Même clé (date, pair, direction, entry, dest) → False au 2e essai."""
    first = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    second = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert first is True
    assert second is False


def test_try_register_push_different_destination_returns_true(db):
    """Même pair/direction/entry mais destination différente → autorisé."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "user:42", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert a is True
    assert b is True


def test_try_register_push_different_entry_returns_true(db):
    """Même destination/pair/direction mais entry différent → autorisé."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10005"
    )
    assert a is True
    assert b is True


def test_try_register_push_different_date_returns_true(db):
    """Même clé mais date différente → autorisé (purge journalière implicite)."""
    a = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    b = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-29", "EUR/USD", "buy", "1.10000"
    )
    assert a is True
    assert b is True


# ─── update_push_result ───────────────────────────────────────────────


def test_update_push_result_marks_ok_true(db):
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.update_push_result(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000",
        ok=True, response={"ticket": 12345, "mode": "live"},
    )
    import sqlite3
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT ok, bridge_response FROM mt5_pushes WHERE pair='EUR/USD'"
        ).fetchone()
    assert row[0] == 1
    assert "12345" in row[1]


def test_update_push_result_truncates_long_response(db):
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    long_resp = {"data": "x" * 1000}
    mt5_pushes_service.update_push_result(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000",
        ok=False, response=long_resp,
    )
    import sqlite3
    with sqlite3.connect(db) as c:
        row = c.execute(
            "SELECT bridge_response FROM mt5_pushes WHERE pair='EUR/USD'"
        ).fetchone()
    assert len(row[0]) <= 500


# ─── discard_push ─────────────────────────────────────────────────────


def test_discard_push_allows_retry(db):
    """Après discard, le même setup peut être re-registré (retry)."""
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.discard_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    retry = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert retry is True


# ─── purge_old_pushes ─────────────────────────────────────────────────


def test_purge_old_pushes_removes_old_entries(db):
    """Pushes de plus de retention_days jours sont supprimés."""
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-01", "EUR/USD", "buy", "1.10000"
    )
    mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    deleted = mt5_pushes_service.purge_old_pushes(retention_days=10)
    # Le test tourne à une date arbitraire — on vérifie juste qu'au moins
    # la ligne du 2026-04-01 (très ancienne) a été supprimée.
    import sqlite3
    with sqlite3.connect(db) as c:
        remaining = c.execute(
            "SELECT date FROM mt5_pushes ORDER BY date"
        ).fetchall()
    dates = [r[0] for r in remaining]
    assert "2026-04-01" not in dates  # purgée
    assert deleted >= 1


# ─── _ensure_schema idempotent ────────────────────────────────────────


def test_ensure_schema_is_idempotent(db):
    """Appeler _ensure_schema 2 fois ne plante pas."""
    mt5_pushes_service._ensure_schema()
    mt5_pushes_service._ensure_schema()  # ne doit pas raise


# ─── best-effort fallback ─────────────────────────────────────────────


def test_try_register_push_returns_true_on_db_error(monkeypatch):
    """Si la DB est inaccessible, fallback safe = retourne True (autorise push)."""
    monkeypatch.setattr(
        trade_log_service, "_DB_PATH", "/nonexistent/path/trades.db"
    )
    ok = mt5_pushes_service.try_register_push(
        "admin_legacy", "2026-04-28", "EUR/USD", "buy", "1.10000"
    )
    assert ok is True


# ─── ⛔ Un ordre CONFIRME ne se libere pas ────────────────────────────────

def test_discard_ne_supprime_PAS_une_ligne_confirmee(db):
    """⛔ Constate le 2026-08-28 : `mt5_pushes` etait tombe de 139 lignes le
    20/08 a ZERO les 27 et 28, pendant que des ordres partaient. La date est
    celle du plafond de risque, qui a fait exploser les refus — et chaque
    refus efface sa ligne.

    Une ligne `ok=1` avec un ticket atteste d'un ordre REELLEMENT passe chez
    le courtier. L'effacer autoriserait un retry d'un ordre deja execute, et
    surtout effacerait la seule trace reliant cet ordre a son horizon, son
    motif et sa source. Aucun rattrapage n'existe.

    > **Une ligne qui atteste d'un ordre passe n'est pas une reservation a
    > liberer.**
    """
    cle = ("admin_live", "2026-08-28", "XAU/USD", "sell", "4475.20000")
    assert mt5_pushes_service.try_register_push(*cle, horizon="4h")
    mt5_pushes_service.update_push_result(*cle, ok=True,
                                          response={"ticket": 1357145568})

    mt5_pushes_service.discard_push(*cle)

    ligne = mt5_pushes_service.get_push(*cle)
    assert ligne is not None, "la ligne d'un ordre PASSE a ete effacee"
    assert ligne["mt5_ticket"] == 1357145568
    assert ligne["horizon"] == "4h"


def test_discard_libere_toujours_une_reservation_NON_confirmee(db):
    """Le garde-fou ne doit pas empecher le retry qu'il sert a autoriser."""
    cle = ("admin_live", "2026-08-28", "EUR/USD", "buy", "1.10000")
    assert mt5_pushes_service.try_register_push(*cle)
    mt5_pushes_service.discard_push(*cle)
    assert mt5_pushes_service.get_push(*cle) is None
    # ... et la cle redevient reservable, ce qui est tout l'objet du discard.
    assert mt5_pushes_service.try_register_push(*cle)


def test_discard_libere_une_ligne_marquee_EN_ECHEC(db):
    """`ok=0` explicite : le bridge a refuse, la reservation doit se liberer."""
    cle = ("admin_live", "2026-08-28", "GBP/USD", "sell", "1.30000")
    assert mt5_pushes_service.try_register_push(*cle)
    mt5_pushes_service.update_push_result(*cle, ok=False, response={"error": "429"})
    mt5_pushes_service.discard_push(*cle)
    assert mt5_pushes_service.get_push(*cle) is None


# ─── Le silence du 2026-08-26 ─────────────────────────────────────────


def test_try_register_push_crie_quand_l_ecriture_echoue(db, caplog):
    """⛔ Une erreur d'ecriture ne doit JAMAIS etre muette.

    Constate le 2026-08-31 : `mt5_pushes` etait a ZERO ligne depuis le 26/08
    pendant que des ordres partaient sur le compte reel. L'exception partait
    en DEBUG, sous le niveau du serveur, et `try_register_push` renvoyait
    `True` — le push partait donc sans qu'aucune ligne ne soit ecrite.

    `discard_push` annoncait alors « 0 ligne(s) supprimee(s) », ce qui se lit
    comme « deja liberee » ou « ligne confirmee protegee », jamais comme
    « la ligne n'a jamais existe ».

    ⛔ Le `True` est CONSERVE : le basculer en fail-closed bloquerait un ordre
    reel des que la base tousse. C'est le silence qu'on corrige, pas le
    compromis.
    """
    boom = sqlite3.OperationalError("database is locked")
    with patch.object(mt5_pushes_service.sqlite3, "connect", side_effect=boom):
        with caplog.at_level(
            logging.DEBUG, logger="backend.services.mt5_pushes_service"
        ):
            ok = mt5_pushes_service.try_register_push(
                "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000"
            )

    assert ok is True, "fail-open conserve : ne jamais bloquer un ordre reel"
    cris = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert cris, "l'echec d'ecriture doit etre journalise au moins en WARNING"
    assert any("try_register_push" in r.getMessage() for r in cris)
    assert any("database is locked" in r.getMessage() for r in cris)


def test_update_et_discard_crient_aussi(db, caplog):
    """Les deux autres ecritures de la table d'audit, meme regle."""
    boom = sqlite3.OperationalError("database is locked")
    with patch.object(mt5_pushes_service.sqlite3, "connect", side_effect=boom):
        with caplog.at_level(
            logging.DEBUG, logger="backend.services.mt5_pushes_service"
        ):
            mt5_pushes_service.update_push_result(
                "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000",
                ok=True, response={"ticket": 1},
            )
            mt5_pushes_service.discard_push(
                "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000"
            )

    cris = {r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING}
    assert any("update_push_result" in m for m in cris)
    assert any("discard_push" in m for m in cris)


# ─── Le DDL sort du chemin chaud ──────────────────────────────────────


def test_le_schema_n_est_pas_paye_a_chaque_poussee(db):
    """⛔ `CREATE TABLE`/`CREATE INDEX` sont du DDL.

    En `journal_mode=delete` ils reclament un verrou EXCLUSIF qui doit
    attendre TOUS les lecteurs, la ou un INSERT simple passe. Les payer a
    chaque ordre mettait ce DDL sur le chemin chaud du dispatch, et c'est le
    meilleur candidat pour l'exception avalee du 26/08.
    """
    appels = []
    vrai = mt5_pushes_service._ensure_schema

    def compte():
        appels.append(1)
        vrai()

    with patch.object(mt5_pushes_service, "_ensure_schema", side_effect=compte):
        for i in range(5):
            mt5_pushes_service.try_register_push(
                "admin_live", "2026-08-31", "XAU/USD", "sell", f"{3400 + i}.00000"
            )

    assert len(appels) == 1, f"DDL paye {len(appels)} fois pour 5 poussees"


def test_le_schema_est_verifie_pour_CHAQUE_base(tmp_path):
    """⛔ La memoire est indexee par CHEMIN, jamais par un booleen global.

    Les tests — et un futur multi-tenant — basculent `_db_path` d'une base a
    l'autre. Un drapeau unique aurait saute la creation du schema sur la
    deuxieme base : table absente, et AUCUNE erreur au moment du basculement.
    """
    for nom in ("une.db", "deux.db"):
        with patch.object(trade_log_service, "_DB_PATH", tmp_path / nom):
            assert mt5_pushes_service.try_register_push(
                "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000"
            ) is True
            assert mt5_pushes_service.get_push(
                "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000"
            ) is not None, f"schema absent sur {nom}"


# ─── Le motif est un OBJET, pas une chaine ────────────────────────────


def _detection(nom: str = "momentum_down"):
    from datetime import datetime, timezone

    from backend.models.schemas import PatternDetection, PatternType

    return PatternDetection(
        pattern=PatternType(nom),
        confidence=0.7,
        description="diag",
        detected_at=datetime.now(timezone.utc),
    )


def test_le_motif_objet_est_reduit_a_son_nom(db):
    """⛔ `TradeSetup.pattern` est un `PatternDetection`, pas une chaine.

    Les TROIS appelants de `try_register_push` passent `getattr(setup,
    "pattern", None)` — donc l'objet brut. SQLite refuse de le lier :

        ProgrammingError: Error binding parameter 8:
        type 'PatternDetection' is not supported

    L'exception partait dans le `except` qui renvoie `True`, et le push
    partait sans qu'aucune ligne ne soit ecrite. C'est la cause du zero
    absolu de `mt5_pushes` entre le 26/08 et le 31/08.

    ⛔ La reduction se fait ICI, au point d'entree, jamais chez les
    appelants : les recopier trois fois garantit qu'un des trois l'oublie —
    la lecon deja tiree pour `source_du_setup`.
    """
    ok = mt5_pushes_service.try_register_push(
        "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000",
        horizon="5min", pattern=_detection("momentum_down"), source="interne",
    )
    assert ok is True

    ligne = mt5_pushes_service.get_push(
        "admin_live", "2026-08-31", "XAU/USD", "sell", "3421.50000"
    )
    assert ligne is not None, "la ligne d'audit doit exister"
    assert ligne["pattern"] == "momentum_down"


def test_le_motif_deja_en_chaine_passe_inchange(db):
    """Une chaine reste une chaine — pas de regression sur l'appelant sain."""
    mt5_pushes_service.try_register_push(
        "admin_live", "2026-08-31", "XAG/USD", "buy", "39.50000",
        horizon="4h", pattern="range_bounce_up", source="interne",
    )
    ligne = mt5_pushes_service.get_push(
        "admin_live", "2026-08-31", "XAG/USD", "buy", "39.50000"
    )
    assert ligne["pattern"] == "range_bounce_up"


def test_un_horizon_enumere_ne_tue_pas_la_ligne(db):
    """Defense en profondeur : le motif n'est pas le seul champ a risque.

    Un seul parametre non-texte suffit a faire disparaitre la ligne entiere,
    en silence avant le 31/08. Les champs texte sont normalises au meme
    endroit.
    """
    import enum

    class Horizon(str, enum.Enum):
        QUATRE_H = "4h"

    mt5_pushes_service.try_register_push(
        "admin_live", "2026-08-31", "EUR/USD", "buy", "1.10000",
        horizon=Horizon.QUATRE_H, pattern=_detection("breakout_up"),
        source="interne",
    )
    ligne = mt5_pushes_service.get_push(
        "admin_live", "2026-08-31", "EUR/USD", "buy", "1.10000"
    )
    assert ligne is not None
    assert ligne["horizon"] == "4h"
    assert ligne["pattern"] == "breakout_up"


def test_les_trois_appelants_passent_bien_un_objet(db):
    """Verrouille la forme reelle : `setup.pattern` EST un `PatternDetection`.

    Si un jour le modele change et expose deja une chaine, ce test le dit —
    et la normalisation devient inutile plutot que silencieusement fausse.
    """
    from backend.models.schemas import PatternDetection

    assert isinstance(_detection(), PatternDetection)
    assert not isinstance(_detection(), str)


# ─── La garde : jamais purger le push d'un trade encore OUVERT ─────────
#
# Mesure du 2026-10-30 : le push est le seul lien entre un ordre broker et sa
# cloture (`kraken_sync` n'apparie que par l'`order_id` du SL/TP du push). En
# le supprimant on rend la cloture irreconciliable A JAMAIS. Confronte aux
# fills du courtier : 7 clotures sur 49 manquaient aux livres, dont une
# position DOT tenue 36 JOURS -- au-dela de la retention de 30.

def _table_trades(db_file, lignes):
    """Cree `personal_trades` et y pose des lignes (ticket, statut)."""
    import sqlite3 as s
    with s.connect(db_file) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS personal_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT,
            mt5_ticket TEXT)""")
        c.executemany("INSERT INTO personal_trades (status, mt5_ticket) "
                      "VALUES (?,?)", lignes)


def _poser_push_ancien(db_file, ticket=None, reponse=None, date="2026-04-01"):
    import sqlite3 as s
    with s.connect(db_file) as c:
        c.execute("INSERT INTO mt5_pushes (destination_id, date, pair, "
                  "direction, entry_price_5dp, pushed_at, ok, mt5_ticket, "
                  "bridge_response) VALUES "
                  "('admin_kraken',?, 'DOT/USD','buy','0.95070',?,1,?,?)",
                  (date, date + "T00:41:14+00:00", ticket, reponse))


def test_un_push_dont_le_trade_est_OUVERT_n_est_PAS_purge(db):
    """⛔ LE test qui compte. Le cas DOT : ouverte 36 jours, donc son push
    tombait sous la retention alors que la position vivait encore."""
    _table_trades(db, [("OPEN", "a28f3377")])
    _poser_push_ancien(db, ticket="a28f3377")
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 0
    import sqlite3 as s
    with s.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM mt5_pushes").fetchone()[0] == 1


def test_un_push_dont_le_trade_est_FERME_est_bien_purge(db):
    """La garde ne doit pas tout garder : une fois la cloture ecrite, le
    push n'a plus de role."""
    _table_trades(db, [("CLOSED", "a28f3377")])
    _poser_push_ancien(db, ticket="a28f3377")
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 1


def test_la_reference_est_reconnue_DANS_la_reponse_du_pont(db):
    """Sur Kraken l'identifiant d'ordre vit dans `bridge_response`, pas dans
    la colonne `mt5_ticket` : la garde doit le voir la aussi."""
    _table_trades(db, [("OPEN", "a2b09006-c88e-4169-be10-ebf8a9fa51bd")])
    _poser_push_ancien(db, ticket=None, reponse=(
        '{"market_order_id": "a2b09006-c88e-4169-be10-ebf8a9fa51bd",'
        ' "symbol": "PF_AVAXUSD"}'))
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 0


def test_sans_table_personal_trades_la_purge_fonctionne_NORMALEMENT(db):
    """« Pas de table » = aucun trade a proteger. La premiere version avalait
    l'exception et rendait 0 : la purge se neutralisait en SILENCE."""
    _poser_push_ancien(db, ticket="peu-importe")
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 1


def test_si_les_trades_ouverts_sont_ILLISIBLES_on_ne_purge_RIEN(db, monkeypatch):
    """Fail-closed : une purge sautee coute une table un peu plus grosse,
    une purge aveugle coute une cloture definitivement perdue."""
    _table_trades(db, [("OPEN", "a28f3377")])
    _poser_push_ancien(db, ticket="a28f3377")
    monkeypatch.setattr(mt5_pushes_service, "_tickets_de_trades_ouverts",
                        lambda c: None)
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 0
    import sqlite3 as s
    with s.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM mt5_pushes").fetchone()[0] == 1


def test_un_ticket_VIDE_ne_protege_pas_tous_les_pushes(db):
    """Un `mt5_ticket` vide ou NULL ne doit pas se comporter comme un joker :
    `'' in n_importe_quoi` est VRAI en Python, ce qui garderait TOUT."""
    _table_trades(db, [("OPEN", ""), ("OPEN", None)])
    _poser_push_ancien(db, ticket="sans-rapport")
    assert mt5_pushes_service.purge_old_pushes(retention_days=10) == 1
