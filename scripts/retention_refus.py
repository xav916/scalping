#!/usr/bin/env python3
"""Rétention de `signal_rejections` : AGREGER avant de supprimer.

    python scripts/retention_refus.py --essai        # ne touche RIEN, dit tout
    python scripts/retention_refus.py                # applique (30 jours)
    python scripts/retention_refus.py --jours 60

## 🔑 LA MESURE QUI MOTIVE CE SCRIPT (2026-10-09)

    trades.db                    1 115 Mo
    signal_rejections        2 837 523 lignes   ~517 Mo   (46 % de la base)
                             du 2026-05-18 au 2026-10-09
    par jour                   ~100 000 lignes
    plus vieux que 30 jours      395 201 lignes (13,9 %)

Et le cycle rapide sur l'or multiplie les refus d'or par ~36 : une simple purge
a 30 jours stabiliserait la table autour de 1,4 Go, soit PIRE qu'aujourd'hui.

## ⛔ POURQUOI ON N'EFFACE PAS, ON ROULE

La purge du calendrier economique a deja coute cher : elle tombait a chaque
redemarrage, et LE PASSE D'AVANT LE 27/09 RESTE PERDU. Une purge qui supprime
sans conserver detruit de l'information de facon irreversible.

🔑 Or TOUTES les analyses de ce depot lisent des COMPTES PAR MOTIF, jamais les
lignes individuelles : << 224 refus bridge_perte_journaliere >>, << 4 565 refus
XAU/USD >>, << 456 refus execution_globale_fermee en une heure >>.

⇒ On agrege par (jour, paire, sens, destination, motif) PUIS on supprime les
lignes brutes. L'histoire est conservee pour toujours, a ~1/1000 du volume, et
la croissance s'arrete.

## ⚠️ AUCUN VACUUM, ET C'EST ASSUME

Sur une base de 1,1 Go, `VACUUM` exige autant d'espace libre et verrouille
longtemps — or le disque de cet EC2 est deja passe a 97 % une fois. Les pages
liberees sont REUTILISEES par SQLite : la croissance s'arrete meme si le
fichier ne retrecit pas. Si un jour il faut vraiment rendre l'espace, c'est une
operation a part, decidee et surveillee.

## ⚠️ ET LA SUPPRESSION SE FAIT JOUR PAR JOUR

Un seul `DELETE` de 400 000 lignes verrouillerait la base pendant que la
production ecrit dedans. Chaque journee est agregee ET supprimee dans SA
transaction : si le script est interrompu, les jours deja traites le restent,
et les autres seront repris au prochain passage.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "/app")

JOURS_DEFAUT = int(os.environ.get("RETENTION_REFUS_JOURS", "30"))


def _db_path() -> str:
    from backend.services.mt5_sync import _db_path as p
    return p()


def _assurer_table(c: sqlite3.Connection) -> None:
    """L'agregat. La cle PRIMAIRE porte les cinq dimensions : c'est elle qui
    rend l'accumulation sure."""
    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_rejections_jour (
            jour           TEXT NOT NULL,
            pair           TEXT,
            direction      TEXT,
            reason_code    TEXT,
            destination_id TEXT,
            n              INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (jour, pair, direction, reason_code, destination_id)
        )
    """)


def appliquer(jours: int = JOURS_DEFAUT, aujourdhui: str | None = None,
              a_blanc: bool = False) -> dict:
    """Roule puis supprime les refus plus vieux que `jours`. Rend un bilan.

    ⛔ `jours <= 0` est REFUSE : une retention qui mange le jour meme n'est pas
    une retention. On refuse plutot que d'obeir.
    """
    if jours <= 0:
        raise ValueError(
            f"retention de {jours} jour(s) refusee : elle effacerait le jour "
            "meme. Une retention qui mange le present n'est pas une retention.")

    if aujourdhui is None:
        aujourdhui = datetime.now(timezone.utc).date().isoformat()
    limite = (date.fromisoformat(aujourdhui) - timedelta(days=jours)).isoformat()

    chemin = _db_path()
    with sqlite3.connect(chemin) as c:
        # Les journees concernees, pour les traiter UNE PAR UNE.
        jours_vises = [r[0] for r in c.execute(
            "SELECT DISTINCT substr(created_at,1,10) j FROM signal_rejections "
            "WHERE substr(created_at,1,10) < ? ORDER BY j", (limite,))]
        a_rouler = c.execute(
            "SELECT COUNT(*) FROM signal_rejections "
            "WHERE substr(created_at,1,10) < ?", (limite,)).fetchone()[0]

    bilan = {
        "limite": limite, "jours": len(jours_vises),
        "lignes_a_rouler": a_rouler, "lignes_roulees": 0,
        "lignes_restantes": None, "a_blanc": a_blanc,
    }

    if a_blanc or not jours_vises:
        with sqlite3.connect(chemin) as c:
            bilan["lignes_restantes"] = c.execute(
                "SELECT COUNT(*) FROM signal_rejections").fetchone()[0]
        return bilan

    for j in jours_vises:
        # 🔑 UNE TRANSACTION PAR JOUR, et l'agregation et la suppression sont
        # DEDANS ensemble. C'est ce qui rend le script idempotent : au second
        # passage il ne reste aucune ligne brute pour ce jour, donc rien a
        # accumuler. Les separer ferait doubler les comptes.
        with sqlite3.connect(chemin) as c:
            _assurer_table(c)
            c.execute("""
                INSERT INTO signal_rejections_jour
                       (jour, pair, direction, reason_code, destination_id, n)
                SELECT substr(created_at,1,10), pair, direction, reason_code,
                       destination_id, COUNT(*)
                  FROM signal_rejections
                 WHERE substr(created_at,1,10) = ?
                 GROUP BY pair, direction, reason_code, destination_id
                ON CONFLICT (jour, pair, direction, reason_code, destination_id)
                DO UPDATE SET n = n + excluded.n
            """, (j,))
            supprimees = c.execute(
                "DELETE FROM signal_rejections WHERE substr(created_at,1,10) = ?",
                (j,)).rowcount
            c.commit()
        bilan["lignes_roulees"] += max(supprimees, 0)

    with sqlite3.connect(chemin) as c:
        bilan["lignes_restantes"] = c.execute(
            "SELECT COUNT(*) FROM signal_rejections").fetchone()[0]
    return bilan


def main() -> int:
    a_blanc = "--essai" in sys.argv
    jours = JOURS_DEFAUT
    if "--jours" in sys.argv:
        jours = int(sys.argv[sys.argv.index("--jours") + 1])

    taille_avant = os.path.getsize(_db_path()) / 1e6
    try:
        b = appliquer(jours=jours, a_blanc=a_blanc)
    except ValueError as e:
        print(f"retention refus : REFUSE — {e}")
        return 1

    print(f"retention refus : fenetre {jours} j (avant {b['limite']})"
          f"{' [ESSAI]' if a_blanc else ''}")
    print(f"   {b['jours']} journee(s) concernee(s), "
          f"{b['lignes_a_rouler']:,} ligne(s) a rouler")
    if not a_blanc:
        print(f"   {b['lignes_roulees']:,} roulee(s) puis supprimee(s)")
    print(f"   {b['lignes_restantes']:,} ligne(s) brutes restantes")
    print(f"   base : {taille_avant:.0f} Mo "
          f"-> {os.path.getsize(_db_path())/1e6:.0f} Mo")
    # ⚠️ Le fichier ne retrecit PAS sans VACUUM, et c'est voulu : les pages
    # liberees sont reutilisees, donc la croissance s'arrete. Le dire plutot
    # que de laisser croire a un echec.
    if not a_blanc and b["lignes_roulees"]:
        print("   (le fichier ne retrecit pas : les pages liberees sont "
              "REUTILISEES, la croissance s'arrete. Aucun VACUUM, voir l'entete.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
