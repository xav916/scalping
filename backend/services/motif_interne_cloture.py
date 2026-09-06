"""Pourquoi NOUS avons fermé — à côté de ce que le courtier en a vu.

Point ② du plan du 2026-09-06 : tracer ce que les mécanismes de sortie
déclenchent réellement.

## Le constat

La règle du tiers a bien fermé deux positions le 04/09 :

```
18:05  XAU/USD  sell  admin_legacy  +10,24 €   part de l'objectif 0,379
18:40  USD/CHF  buy   admin_legacy   +2,37 €   part de l'objectif 0,340
```

⛔ Mais `personal_trades.close_reason` les enregistre en **`EXPERT`** — le motif
que MT5 attribue à *toute* fermeture par API. Elles sont indistinguables d'une
action quelconque de l'EA, et **`pre_weekend` n'apparaît dans aucune clôture**.

🔑 L'information n'est pas perdue : la table `fermetures_weekend` porte le
ticket, le profit et la part atteinte. **Elle n'était simplement jamais jointe.**

## Pourquoi une COLONNE À PART, et pas un `close_reason` corrigé

⛔ `close_reason` est vérifié contre le courtier — 345 accords, 0 désaccord
depuis le 25/08. L'écraser détruirait la valeur de cette vérification.

Ce sont **deux faits distincts, tous deux vrais** :

  - le courtier dit `EXPERT` : la position a bien été fermée par API ;
  - nous disons `PRE_WEEKEND_TIERS` : voilà *pourquoi* on l'a fait.

Les confondre ferait perdre l'un des deux. `motif_interne` porte le nôtre, et
`close_reason` reste la parole du courtier.

⚠️ La soupape d'équilibre, elle, n'a **aucun journal** : rien ne la trace, donc
rien à joindre. Les 4 clôtures `TRAILING_SL` sont le motif natif de MT5, et une
seule est postérieure à son armement du 23/08. Ce module ne peut pas la
documenter — il le dit plutôt que de l'inventer.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

MOTIF_TIERS = "PRE_WEEKEND_TIERS"


def _conn():
    c = sqlite3.connect(str(_DB), isolation_level=None)
    c.row_factory = sqlite3.Row
    return c


def init_schema() -> None:
    """Ajoute `motif_interne` si absente. ⛔ Jamais de recréation de table :
    `personal_trades` porte l'historique de l'argent réel."""
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(personal_trades)")]
        if "motif_interne" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN motif_interne TEXT")
        if "motif_interne_detail" not in cols:
            c.execute("ALTER TABLE personal_trades ADD COLUMN motif_interne_detail TEXT")


def enrichir() -> dict:
    """Joint `fermetures_weekend` à `personal_trades` par le TICKET.

    ⛔ La jointure porte sur `mt5_ticket`, pas `ticket` — la colonne s'appelle
    ainsi, et le mauvais nom rendrait une jointure vide qui ressemble à
    « rien à enrichir ». Déjà rencontré le même jour.

    ⚠️ Le ticket est stocké en TEXTE dans `fermetures_weekend` et en entier
    ailleurs : on compare les deux formes. Une jointure qui échoue sur un type
    ne dit rien, elle rend zéro.
    """
    init_schema()
    n = 0
    with _conn() as c:
        try:
            journal = list(c.execute(
                "SELECT ticket, part, profit, jour FROM fermetures_weekend"))
        except sqlite3.OperationalError:
            # Pas de journal : rien à joindre, et ce n'est pas une anomalie.
            return {"enrichies": 0, "sans_journal": True}
        for r in journal:
            t = r["ticket"]
            formes = {str(t)}
            try:
                formes.add(int(t))
            except (TypeError, ValueError):
                pass
            for forme in formes:
                cur = c.execute(
                    "UPDATE personal_trades SET motif_interne=?, motif_interne_detail=? "
                    "WHERE mt5_ticket=? AND (motif_interne IS NULL OR motif_interne='')",
                    (MOTIF_TIERS,
                     f"part de l'objectif {float(r['part']):.3f}" if r["part"] is not None else None,
                     forme))
                n += cur.rowcount
    return {"enrichies": n, "sans_journal": False}


def bilan() -> dict:
    """Ce que chaque mécanisme a produit, par compte.

    ⛔ Rend aussi les clôtures **génériques non attribuées** : c'est le chiffre
    qui dit combien de fermetures restent inexplicables. Le taire donnerait
    l'illusion que tout est tracé.
    """
    init_schema()
    par_motif: dict = {}
    generiques = 0
    # ⛔ `personal_trades` porte DEUX lignes par cloture : une au nom radar
    # (`XAU/USD`) et une au nom courtier (`XAUUSD`), cette derniere avec
    # `entry_price = 0`. Compter les lignes DOUBLAIT le P&L — mesure du 06/09 :
    # 25,22 EUR annonces pour 12,61 reels. On compte donc par TICKET.
    vus: set = set()
    with _conn() as c:
        for r in c.execute(
                "SELECT mt5_ticket, destination_id, close_reason, motif_interne, pnl "
                "FROM personal_trades WHERE closed_at >= '2026-08-25' "
                "ORDER BY (entry_price IS NULL), entry_price DESC"):
            cle_ticket = str(r["mt5_ticket"]) if r["mt5_ticket"] else None
            if cle_ticket and cle_ticket in vus:
                continue
            if cle_ticket:
                vus.add(cle_ticket)
            mi = r["motif_interne"]
            if mi:
                cle = (r["destination_id"], mi)
                e = par_motif.setdefault(cle, {"n": 0, "pnl": 0.0})
                e["n"] += 1
                try:
                    e["pnl"] += float(r["pnl"])
                except (TypeError, ValueError):
                    pass
            elif (r["close_reason"] or "") in ("EXPERT", "MANUAL", "TRAILING_SL"):
                generiques += 1
    return {
        "par_motif": {f"{d} · {m}": v for (d, m), v in sorted(par_motif.items())},
        "clotures_generiques_non_attribuees": generiques,
        "note": ("⚠️ La soupape d'équilibre n'a AUCUN journal : ses clôtures "
                 "restent dans le compte générique ci-dessus, et rien ne permet "
                 "de les distinguer."),
    }


if __name__ == "__main__":
    import json
    print(json.dumps({"enrichissement": enrichir(), "bilan": bilan()},
                     ensure_ascii=False, indent=1))
