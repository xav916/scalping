"""Rétention de `signal_rejections` : AGRÉGER avant de supprimer.

## 🔑 LA MESURE QUI MOTIVE CE TRAVAIL (2026-10-09)

```
trades.db                    1 115 Mo
signal_rejections        2 837 523 lignes   ~517 Mo   (46 % de la base)
                         du 2026-05-18 au 2026-10-09
par jour                   ~100 000 lignes
plus vieux que 30 jours      395 201 lignes (13,9 %)
```

Et le cycle rapide sur l'or multiplie les refus d'or par ~36 : une simple
purge à 30 jours stabiliserait la table autour de **1,4 Go**, soit **pire**
qu'aujourd'hui.

## ⛔ POURQUOI ON N'EFFACE PAS, ON ROULE

La purge du calendrier économique a déjà coûté cher : elle tombait à chaque
redémarrage, et **le passé d'avant le 27/09 reste perdu**. Une purge qui
supprime sans conserver détruit de l'information de façon irréversible.

🔑 Or **toutes** les analyses de ce dépôt lisent des *comptes par motif*, jamais
les lignes individuelles : « 224 refus `bridge_perte_journaliere` », « 4 565
refus `XAU/USD` », « 456 refus `execution_globale_fermee` en une heure ».

⇒ On agrège par `(jour, paire, sens, destination, motif)` **puis** on supprime
les lignes brutes. L'histoire est conservée pour toujours, à ~1/1000 du volume,
et la croissance s'arrête.

## Ce que ces tests épinglent

1. l'agrégat porte le **détail** par paire / destination / motif — un simple
   total par jour ne répondrait à aucune des questions qu'on pose ;
2. les lignes brutes agrégées sont **supprimées** ;
3. les lignes **dans** la fenêtre de rétention sont **intactes** ;
4. ⛔ **idempotence** : relancer ne double pas les comptes. L'agrégat accumule,
   donc cette garantie repose sur le fait que l'agrégation et la suppression
   d'un jour sont dans la **même transaction** ;
5. le mode à blanc ne touche **rien** ;
6. ⚠️ aucun `VACUUM` : sur une base de 1,1 Go il exige autant d'espace libre et
   verrouille longtemps, et le disque de cet EC2 est déjà passé à 97 % une
   fois. Les pages libérées sont **réutilisées**, donc la croissance s'arrête
   même si le fichier ne rétrécit pas. C'est le compromis assumé, et il est dit.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "retention_refus.py")


@pytest.fixture()
def r():
    spec = importlib.util.spec_from_file_location("retention_refus", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def base(tmp_path, monkeypatch, r):
    """Une base au schéma de `signal_rejections`, peuplée de deux époques."""
    f = tmp_path / "trades.db"
    c = sqlite3.connect(f)
    c.execute("""
        CREATE TABLE signal_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            pair TEXT, direction TEXT, confidence REAL,
            reason_code TEXT, details TEXT,
            user_id INTEGER, destination_id TEXT
        )
    """)
    lignes = [
        # VIEUX (hors fenêtre) — trois motifs, deux destinations
        ("2026-08-01T10:00:00+00:00", "XAU/USD", "buy", "pattern_not_allowed", "admin_live"),
        ("2026-08-01T10:00:05+00:00", "XAU/USD", "buy", "pattern_not_allowed", "admin_live"),
        ("2026-08-01T10:00:10+00:00", "XAU/USD", "sell", "pattern_not_allowed", "admin_live"),
        ("2026-08-01T11:00:00+00:00", "XAU/USD", "buy", "bridge_marge_insuffisante", "admin_live"),
        ("2026-08-01T11:00:01+00:00", "EUR/USD", "buy", "pattern_not_allowed", "admin_legacy"),
        ("2026-08-02T09:00:00+00:00", "XAU/USD", "buy", "pattern_not_allowed", "admin_live"),
        # RÉCENT (dans la fenêtre) — ne doit pas bouger
        ("2026-10-08T09:00:00+00:00", "XAU/USD", "buy", "pattern_not_allowed", "admin_live"),
        ("2026-10-09T09:00:00+00:00", "XAU/USD", "sell", "bridge_plafond_risque", "admin_live"),
    ]
    c.executemany(
        "INSERT INTO signal_rejections (created_at, pair, direction, "
        "reason_code, destination_id) VALUES (?,?,?,?,?)", lignes)
    c.commit()
    c.close()
    monkeypatch.setattr(r, "_db_path", lambda: str(f))
    return str(f)


def _agregat(base_path) -> list[dict]:
    with sqlite3.connect(base_path) as c:
        c.row_factory = sqlite3.Row
        try:
            return [dict(x) for x in c.execute(
                "SELECT * FROM signal_rejections_jour ORDER BY jour, pair, "
                "direction, reason_code")]
        except sqlite3.OperationalError:
            return []


def _brutes(base_path) -> int:
    with sqlite3.connect(base_path) as c:
        return c.execute("SELECT COUNT(*) FROM signal_rejections").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────
# L'agrégat porte le DÉTAIL
# ─────────────────────────────────────────────────────────────────────────

def test_l_agregat_garde_le_detail_par_motif_et_destination(base, r):
    """🔑 Un total par jour ne repondrait a AUCUNE des questions qu'on pose.
    C'est le detail qui porte l'information."""
    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)

    ag = _agregat(base)
    cles = {(x["jour"], x["pair"], x["direction"], x["reason_code"],
             x["destination_id"]): x["n"] for x in ag}

    assert cles[("2026-08-01", "XAU/USD", "buy", "pattern_not_allowed", "admin_live")] == 2
    assert cles[("2026-08-01", "XAU/USD", "sell", "pattern_not_allowed", "admin_live")] == 1
    assert cles[("2026-08-01", "XAU/USD", "buy", "bridge_marge_insuffisante", "admin_live")] == 1
    assert cles[("2026-08-01", "EUR/USD", "buy", "pattern_not_allowed", "admin_legacy")] == 1
    assert cles[("2026-08-02", "XAU/USD", "buy", "pattern_not_allowed", "admin_live")] == 1


def test_les_lignes_BRUTES_agregees_sont_supprimees(base, r):
    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)

    # Il ne reste que les deux lignes RECENTES.
    assert _brutes(base) == 2


def test_les_lignes_DANS_la_fenetre_sont_INTACTES(base, r):
    """⛔ Le garde le plus important : on ne touche pas au present."""
    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)

    with sqlite3.connect(base) as c:
        restantes = [x[0] for x in c.execute(
            "SELECT created_at FROM signal_rejections ORDER BY created_at")]
    assert restantes == ["2026-10-08T09:00:00+00:00", "2026-10-09T09:00:00+00:00"]
    # …et aucune d'elles n'a ete agregee.
    assert all(not x["jour"].startswith("2026-10") for x in _agregat(base))


# ─────────────────────────────────────────────────────────────────────────
# ⛔ Idempotence et mode à blanc
# ─────────────────────────────────────────────────────────────────────────

def test_relancer_ne_DOUBLE_pas_les_comptes(base, r):
    """⛔ L'agregat ACCUMULE : cette garantie repose sur le fait que
    l'agregation et la suppression d'un jour sont dans la MEME transaction.
    Sans cela, un second passage recompterait les memes lignes brutes."""
    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)
    avant = _agregat(base)

    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)
    r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)

    assert _agregat(base) == avant
    assert _brutes(base) == 2


def test_le_mode_A_BLANC_ne_touche_RIEN(base, r):
    bilan = r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=True)

    assert _brutes(base) == 8
    assert _agregat(base) == []
    # …mais il DIT ce qu'il aurait fait.
    assert bilan["lignes_a_rouler"] == 6
    assert bilan["jours"] == 2


def test_le_bilan_chiffre_ce_qui_a_ete_fait(base, r):
    bilan = r.appliquer(jours=30, aujourdhui="2026-10-09", a_blanc=False)

    assert bilan["lignes_roulees"] == 6
    assert bilan["jours"] == 2
    assert bilan["lignes_restantes"] == 2


def test_une_base_SANS_rien_a_purger_ne_fait_rien(base, r):
    """Une fenêtre large : aucun jour ne sort, et ça ne doit pas lever."""
    bilan = r.appliquer(jours=3650, aujourdhui="2026-10-09", a_blanc=False)

    assert bilan["lignes_roulees"] == 0
    assert _brutes(base) == 8


def test_une_fenetre_ABSURDE_est_refusee(base, r):
    """⛔ `jours=0` effacerait le jour meme. On refuse plutot que d'obeir : une
    retention qui mange le present n'est pas une retention."""
    with pytest.raises(ValueError):
        r.appliquer(jours=0, aujourdhui="2026-10-09", a_blanc=False)
    with pytest.raises(ValueError):
        r.appliquer(jours=-5, aujourdhui="2026-10-09", a_blanc=False)

    assert _brutes(base) == 8


def test_AUCUN_vacuum_n_est_lance(r):
    """⚠️ Sur une base de 1,1 Go, `VACUUM` exige autant d'espace libre et
    verrouille longtemps — et le disque de cet EC2 est deja passe a 97 % une
    fois. Les pages liberees sont REUTILISEES : la croissance s'arrete meme si
    le fichier ne retrecit pas."""
    src = _SCRIPT.read_text(encoding="utf-8")

    # ⚠️ ASSERTION PRECISE, et ma premiere version ne l'etait pas : elle
    # cherchait le MOT `VACUUM` n'importe ou, et tombait sur mes propres
    # commentaires qui expliquent POURQUOI il n'y en a pas. Un test qui
    # confond une mention et une instruction est un test qui mentira dans
    # l'autre sens le jour ou le commentaire disparait.
    #
    # Ce qui compte est qu'aucune ligne ne FASSE executer un VACUUM.
    coupables = [l.strip() for l in src.splitlines()
                 if "VACUUM" in l.upper() and "execute" in l]

    assert coupables == [], f"un VACUUM est execute : {coupables}"
