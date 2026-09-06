"""Pourquoi NOUS avons fermé, à côté de ce que le courtier a vu (2026-09-06).

La règle du tiers a fermé deux positions le 04/09 (+10,24 € et +2,37 €), et
`close_reason` les enregistre en **`EXPERT`** — le motif que MT5 attribue à
toute fermeture par API. ⛔ `pre_weekend` n'apparaît dans aucune clôture : le
mécanisme agit et sa trace se perd.

🔑 L'information existait pourtant dans `fermetures_weekend`. Elle n'était
jamais jointe.

Ce que ces tests verrouillent :
  - `close_reason` n'est JAMAIS écrasé — c'est la parole du courtier, vérifiée
    à 345 accords contre 0 désaccord ;
  - la jointure porte sur `mt5_ticket` et tolère texte comme entier ;
  - le bilan dit combien de clôtures restent INEXPLIQUÉES.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import motif_interne_cloture as mi


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "t.db"
    monkeypatch.setattr(mi, "_DB", chemin)
    c = sqlite3.connect(str(chemin), isolation_level=None)
    c.executescript("""
        CREATE TABLE personal_trades (
            mt5_ticket TEXT, pair TEXT, close_reason TEXT,
            destination_id TEXT, pnl REAL, closed_at TEXT, entry_price REAL);
        CREATE TABLE fermetures_weekend (
            jour TEXT, destination_id TEXT, ticket TEXT, symbole TEXT,
            sens TEXT, volume REAL, part REAL, profit REAL, ferme_le TEXT);
    """)
    return c, chemin


def _trade(c, ticket, reason="EXPERT", pnl=10.24, dest="admin_legacy"):
    c.execute("INSERT INTO personal_trades VALUES (?,?,?,?,?,?,?)",
              (ticket, "XAU/USD", reason, dest, pnl, "2026-09-04T18:05:05+00:00", 100.0))


def _journal(c, ticket, part=0.3788):
    c.execute("INSERT INTO fermetures_weekend VALUES (?,?,?,?,?,?,?,?,?)",
              ("2026-09-04", "admin_legacy", ticket, "XAUUSD", "sell", 0.01,
               part, 10.24, "2026-09-04T18:05:03+00:00"))


# ── L'enrichissement ─────────────────────────────────────────────────

def test_la_cloture_du_tiers_est_ATTRIBUEE(base):
    c, chemin = base
    _trade(c, "87814920")
    _journal(c, "87814920")
    assert mi.enrichir()["enrichies"] == 1
    r = c.execute("SELECT motif_interne, motif_interne_detail, close_reason "
                  "FROM personal_trades").fetchone()
    assert r[0] == mi.MOTIF_TIERS
    assert "0.379" in r[1]


def test_close_reason_n_est_JAMAIS_ecrase(base):
    """⛔ C'est la parole du courtier, verifiee a 345 accords / 0 desaccord.
    Deux faits distincts, tous deux vrais : il dit EXPERT, nous disons
    pourquoi."""
    c, _ = base
    _trade(c, "1", reason="EXPERT")
    _journal(c, "1")
    mi.enrichir()
    assert c.execute("SELECT close_reason FROM personal_trades").fetchone()[0] == "EXPERT"


def test_le_ticket_TEXTE_ou_ENTIER_joint_pareil(base):
    """⚠️ Le journal stocke du texte, les clotures parfois de l'entier. Une
    jointure qui echoue sur un TYPE ne dit rien, elle rend zero."""
    c, _ = base
    c.execute("INSERT INTO personal_trades VALUES (?,?,?,?,?,?,?)",
              (99, "XAU/USD", "EXPERT", "admin_legacy", 1.0,
               "2026-09-04T18:00:00+00:00", 100.0))
    _journal(c, "99")
    assert mi.enrichir()["enrichies"] == 1


def test_une_cloture_deja_attribuee_n_est_pas_retouchee(base):
    c, _ = base
    _trade(c, "1")
    _journal(c, "1")
    mi.enrichir()
    assert mi.enrichir()["enrichies"] == 0, "l'enrichissement est idempotent"


def test_un_ticket_ABSENT_du_journal_reste_sans_motif(base):
    c, _ = base
    _trade(c, "555")
    _journal(c, "111")
    mi.enrichir()
    assert c.execute("SELECT motif_interne FROM personal_trades").fetchone()[0] is None


def test_sans_journal_ce_n_est_PAS_une_anomalie(tmp_path, monkeypatch):
    chemin = tmp_path / "vide.db"
    monkeypatch.setattr(mi, "_DB", chemin)
    c = sqlite3.connect(str(chemin), isolation_level=None)
    c.execute("""CREATE TABLE personal_trades (mt5_ticket TEXT, pair TEXT,
                 close_reason TEXT, destination_id TEXT, pnl REAL,
                 closed_at TEXT, entry_price REAL)""")
    c.close()
    r = mi.enrichir()
    assert r["sans_journal"] is True and r["enrichies"] == 0


# ── Le bilan ─────────────────────────────────────────────────────────

def test_le_bilan_compte_les_INEXPLIQUEES(base):
    """⛔ Taire ce qui n'est pas attribue donnerait l'illusion que tout est
    trace."""
    c, _ = base
    _trade(c, "1")                 # sera attribuee
    _journal(c, "1")
    _trade(c, "2", reason="MANUAL", pnl=3.0)        # generique, non attribuee
    _trade(c, "3", reason="TRAILING_SL", pnl=2.31)  # la soupape, non tracee
    _trade(c, "4", reason="SL", pnl=-13.0)          # motif propre : pas generique
    mi.enrichir()
    b = mi.bilan()
    assert b["clotures_generiques_non_attribuees"] == 2
    assert any(mi.MOTIF_TIERS in k for k in b["par_motif"])


def test_le_bilan_DIT_que_la_soupape_n_est_pas_tracee(base):
    c, _ = base
    _trade(c, "1", reason="TRAILING_SL")
    b = mi.bilan()
    assert "soupape" in b["note"].lower()
    assert "aucun journal" in b["note"].lower()


def test_le_bilan_ne_compte_pas_DEUX_FOIS_la_meme_cloture(base):
    """⛔ `personal_trades` porte deux lignes par clôture : une au nom radar
    (`XAU/USD`) et une au nom courtier (`XAUUSD`, `entry_price = 0`). Compter
    les lignes doublait le P&L — 25,22 € annoncés pour 12,61 réels le 06/09."""
    c, _ = base
    c.execute("INSERT INTO personal_trades (mt5_ticket,pair,close_reason,"
              "destination_id,pnl,closed_at,entry_price) VALUES (?,?,?,?,?,?,?)",
              ("42", "XAU/USD", "EXPERT", "admin_legacy", 10.24,
               "2026-09-04T18:05:05+00:00", 4400.0))
    c.execute("INSERT INTO personal_trades (mt5_ticket,pair,close_reason,"
              "destination_id,pnl,closed_at,entry_price) VALUES (?,?,?,?,?,?,?)",
              ("42", "XAUUSD", "EXPERT", "admin_legacy", 10.24,
               "2026-09-04T18:05:05+00:00", 0.0))
    _journal(c, "42")
    mi.enrichir()
    b = mi.bilan()
    ligne = next(v for k, v in b["par_motif"].items() if mi.MOTIF_TIERS in k)
    assert ligne["n"] == 1, "une clôture, pas deux"
    assert ligne["pnl"] == pytest.approx(10.24), "le P&L ne doit pas doubler"
