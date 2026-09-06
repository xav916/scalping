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
MOTIF_EQUILIBRE = "SORTIE_EQUILIBRE"


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
        # Le journal que la soupape d'equilibre n'avait pas (2026-09-06).
        #
        # ⛔ Sa trace EXISTAIT — le bridge ecrit `status="equilibre"` a chaque
        # deplacement reussi — mais elle vivait dans l'audit du bridge, jamais
        # persistee. La sonde ecrite le 24/08 pour la lire n'avait AUCUN cron :
        # elle n'a jamais tourne. Un mecanisme qu'on ne peut pas compter est un
        # mecanisme auquel on ne peut que croire.
        #
        # ⚠️ L'audit du bridge n'est pas un journal : il est borne et se relit
        # en entier (4 000 lignes) a chaque fois. On garde donc un CURSEUR.
        c.executescript("""
            CREATE TABLE IF NOT EXISTS activations_equilibre (
                destination_id TEXT NOT NULL,
                audit_id INTEGER NOT NULL,
                ticket TEXT,
                pair TEXT,
                sl REAL,
                active_le TEXT,
                PRIMARY KEY (destination_id, audit_id)
            );
            CREATE TABLE IF NOT EXISTS curseur_audit_equilibre (
                destination_id TEXT PRIMARY KEY,
                dernier_id INTEGER NOT NULL
            );
        """)


def curseur(destination_id: str) -> int:
    init_schema()
    with _conn() as c:
        r = c.execute("SELECT dernier_id FROM curseur_audit_equilibre "
                      "WHERE destination_id=?", (destination_id,)).fetchone()
    return int(r["dernier_id"]) if r else 0


def enregistrer_activations(destination_id: str, lignes, dernier_id=None) -> int:
    """Persiste les lignes d'audit `status='equilibre'`.

    ⛔ Le curseur n'avance QUE si des lignes ont ete lues. Une lecture qui
    echoue laisserait sinon un trou definitif — le meme defaut que le `DRY_RUN`
    qui avancait le curseur de la sonde de capture des niveaux.
    """
    init_schema()
    n = 0
    with _conn() as c:
        for l in lignes or []:
            if str(l.get("status")) != "equilibre":
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO activations_equilibre "
                "(destination_id, audit_id, ticket, pair, sl, active_le) "
                "VALUES (?,?,?,?,?,?)",
                (destination_id, l.get("id"),
                 str(l.get("ticket")) if l.get("ticket") is not None else None,
                 l.get("pair"), l.get("sl"), l.get("created_at")))
            n += cur.rowcount
        if dernier_id is not None and lignes:
            c.execute("INSERT INTO curseur_audit_equilibre VALUES (?,?) "
                      "ON CONFLICT(destination_id) DO UPDATE SET dernier_id=?",
                      (destination_id, int(dernier_id), int(dernier_id)))
    return n


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
    # La soupape : toute cloture dont le ticket a connu une activation.
    #
    # ⚠️ On n'affirme PAS que la soupape a cause la sortie — seulement que le
    # stop avait ete remonte a l'equilibre avant. C'est ce qu'on sait ; dire
    # plus serait inventer. Le detail porte la date d'activation pour qu'on
    # puisse remonter.
    with _conn() as c:
        try:
            acts = list(c.execute(
                "SELECT ticket, active_le, sl FROM activations_equilibre "
                "WHERE ticket IS NOT NULL"))
        except sqlite3.OperationalError:
            acts = []
        for a in acts:
            formes = {str(a["ticket"])}
            try:
                formes.add(int(a["ticket"]))
            except (TypeError, ValueError):
                pass
            for forme in formes:
                cur = c.execute(
                    "UPDATE personal_trades SET motif_interne=?, motif_interne_detail=? "
                    "WHERE mt5_ticket=? AND (motif_interne IS NULL OR motif_interne='')",
                    (MOTIF_EQUILIBRE,
                     f"stop remonté à l'équilibre le {str(a['active_le'])[:19]}",
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
        "activations_equilibre": _compter_activations(),
        "note": ("⚠️ Une clôture attribuée à la soupape signifie seulement que "
                 "son stop avait été remonté à l'équilibre AVANT — pas que la "
                 "soupape a causé la sortie. Dire plus serait inventer."),
    }


def _compter_activations() -> dict:
    init_schema()
    with _conn() as c:
        return {r["destination_id"]: r["n"] for r in c.execute(
            "SELECT destination_id, COUNT(*) n FROM activations_equilibre "
            "GROUP BY destination_id")}


if __name__ == "__main__":
    import json
    print(json.dumps({"enrichissement": enrichir(), "bilan": bilan()},
                     ensure_ascii=False, indent=1))
