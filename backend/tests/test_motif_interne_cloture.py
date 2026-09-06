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


def test_une_cloture_TRAILING_SL_sans_activation_reste_generique(base):
    """⚠️ `TRAILING_SL` est le motif natif de MT5 : il ne prouve PAS que la
    soupape a agi. Sans activation journalisee, la cloture reste inexpliquee —
    et le bilan la compte comme telle plutot que de l'attribuer par ressemblance."""
    c, _ = base
    _trade(c, "1", reason="TRAILING_SL")
    mi.enrichir()
    assert c.execute("SELECT motif_interne FROM personal_trades").fetchone()[0] is None
    assert mi.bilan()["clotures_generiques_non_attribuees"] == 1


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


# ── Le journal de la soupape d'équilibre ─────────────────────────────
#
# ⛔ Sa trace EXISTAIT — le bridge écrit `status="equilibre"` — mais elle vivait
# dans l'audit du bridge, jamais persistée, et la sonde écrite le 24/08 pour la
# lire n'avait AUCUN cron. Une activation en 14 jours sur le réel, zéro sur le
# démo : sans journal, on ne pouvait même pas le savoir.

def _audit(id_, status="equilibre", ticket="1357145568"):
    return {"id": id_, "status": status, "ticket": ticket, "pair": "XAU/USD",
            "sl": 4475.2, "created_at": "2026-08-31T02:48:35+00:00"}


def test_seules_les_lignes_EQUILIBRE_sont_journalisees(base):
    c, _ = base
    n = mi.enregistrer_activations("admin_live",
                                   [_audit(1), _audit(2, status="filled"),
                                    _audit(3, status="closed")], dernier_id=3)
    assert n == 1


def test_le_journal_est_IDEMPOTENT(base):
    mi.enregistrer_activations("admin_live", [_audit(1)], dernier_id=1)
    assert mi.enregistrer_activations("admin_live", [_audit(1)], dernier_id=1) == 0


def test_le_curseur_n_avance_QUE_si_on_a_lu(base):
    """⛔ Une lecture qui échoue laisserait un trou définitif — le défaut du
    `DRY_RUN` qui avançait le curseur de la sonde de capture des niveaux."""
    mi.enregistrer_activations("admin_live", [_audit(7)], dernier_id=7)
    assert mi.curseur("admin_live") == 7
    mi.enregistrer_activations("admin_live", [], dernier_id=99)
    assert mi.curseur("admin_live") == 7, "aucune ligne lue ⇒ curseur inchangé"


def test_la_cloture_qui_SUIT_une_activation_est_attribuee(base):
    c, _ = base
    _trade(c, "1357145568", reason="TRAILING_SL", pnl=5.0, dest="admin_live")
    mi.enregistrer_activations("admin_live", [_audit(1)], dernier_id=1)
    mi.enrichir()
    r = c.execute("SELECT motif_interne, motif_interne_detail FROM personal_trades").fetchone()
    assert r[0] == mi.MOTIF_EQUILIBRE
    assert "2026-08-31" in r[1]


def test_le_tiers_PRIME_sur_la_soupape_si_les_deux(base):
    """Une clôture déjà attribuée n'est pas réécrite : le premier motif tient."""
    c, _ = base
    _trade(c, "42")
    _journal(c, "42")
    mi.enrichir()
    mi.enregistrer_activations("admin_legacy", [_audit(1, ticket="42")], dernier_id=1)
    mi.enrichir()
    assert c.execute("SELECT motif_interne FROM personal_trades"
                     ).fetchone()[0] == mi.MOTIF_TIERS


def test_le_bilan_expose_le_COMPTE_d_activations(base):
    mi.enregistrer_activations("admin_live", [_audit(1), _audit(2, ticket="X")],
                               dernier_id=2)
    assert mi.bilan()["activations_equilibre"] == {"admin_live": 2}


def test_le_bilan_ne_pretend_PAS_a_une_causalite(base):
    """⚠️ Une clôture attribuée dit que le stop avait été remonté AVANT — pas
    que la soupape a causé la sortie."""
    n = mi.bilan()["note"].lower()
    assert "pas que la soupape a causé" in n or "inventer" in n
