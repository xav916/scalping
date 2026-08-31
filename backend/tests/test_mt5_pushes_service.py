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
