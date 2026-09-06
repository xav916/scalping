"""Ce que chaque sonde a fait à son dernier passage — but, verdict, quand.

## Le constat

Demande du 06/09 : « chaque passage de sonde doit faire l'objet d'un message
Telegram expliquant le but de la sonde et si le résultat est OK ou KO ».

⛔ Mesuré le jour même : **8 507 passages de cron par jour**. Un message par
passage, c'est un message toutes les dix secondes. Ce dépôt documente
précisément ce que ça produit — l'alerte de sauvegarde S3 a crié **cinq nuits**
sans que personne ne la voie, noyée dans le bruit, et
`fermer_metaux_avant_weekend.py` porte la même leçon en commentaire.

🔑 L'intention, elle, est juste : savoir qu'une sonde est **passée** et si elle
va bien. On sépare donc les deux :

  - **enregistrer** chaque passage, ici, avec son but et son verdict ;
  - **dire** l'ensemble en UN récap, que le healthcheck poste à chaque passage.

Une sonde qui trouve quelque chose parle toujours d'elle-même, tout de suite,
comme avant. Ce journal ne remplace aucune alerte : il répond à la question
« est-ce que ça tourne ? », que le silence ne distinguait pas de « tout va
bien ».

## ⛔ Le but vit AVEC la sonde

Le but est lu dans une ligne `# BUT:` en tête du script, et réenregistré à
chaque passage. Une table de correspondance nom → but serait une deuxième
table, donc une table qui dérive — la leçon des trois tables de canaux du
même jour.

## ⚠️ Un passage MANQUANT est un verdict

`bilan()` distingue trois états, jamais deux : `ok`, `ko`, et **`muet`** —
la sonde n'est pas passée depuis plus longtemps que sa période. Confondre
« muet » avec « ok » est exactement ce qui a laissé la sonde des activations
mentir treize jours.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")

OK = "ok"
KO = "ko"
MUET = "muet"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB), isolation_level=None, timeout=15.0)
    c.row_factory = sqlite3.Row
    return c


def init_schema() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS passages_sondes (
                nom TEXT PRIMARY KEY,
                but TEXT,
                dernier_passage TEXT NOT NULL,
                verdict TEXT NOT NULL,
                code_sortie INTEGER,
                duree_ms INTEGER,
                detail TEXT,
                periode_min INTEGER,
                passages INTEGER NOT NULL DEFAULT 0,
                echecs INTEGER NOT NULL DEFAULT 0
            );
        """)


def enregistrer(nom: str, but: str | None, code_sortie: int,
                duree_ms: int | None = None, detail: str | None = None,
                periode_min: int | None = None) -> str:
    """Note un passage. Rend le verdict retenu.

    ⛔ Le verdict vient du CODE DE SORTIE, pas d'une analyse du texte. Un
    script qui échoue sans rien écrire doit compter comme un échec — c'est
    même le cas le plus dangereux, celui qui ressemble au silence d'une
    situation saine.
    """
    init_schema()
    verdict = OK if code_sortie == 0 else KO
    maintenant = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            """INSERT INTO passages_sondes
                 (nom, but, dernier_passage, verdict, code_sortie, duree_ms,
                  detail, periode_min, passages, echecs)
               VALUES (?,?,?,?,?,?,?,?,1,?)
               ON CONFLICT(nom) DO UPDATE SET
                 but = COALESCE(excluded.but, passages_sondes.but),
                 dernier_passage = excluded.dernier_passage,
                 verdict = excluded.verdict,
                 code_sortie = excluded.code_sortie,
                 duree_ms = excluded.duree_ms,
                 detail = excluded.detail,
                 periode_min = COALESCE(excluded.periode_min,
                                        passages_sondes.periode_min),
                 passages = passages_sondes.passages + 1,
                 echecs = passages_sondes.echecs + ?""",
            (nom, but, maintenant, verdict, code_sortie, duree_ms, detail,
             periode_min, 0 if verdict == OK else 1,
             0 if verdict == OK else 1))
    return verdict


def _est_muette(ligne, maintenant: datetime) -> bool:
    """Une sonde est muette si elle a manqué plus de DEUX fois sa période.

    ⚠️ Deux et pas une : un décalage de cron, une machine chargée, un passage
    qui traîne — crier au premier retard ferait du bruit là où on veut du
    signal. Sans période déclarée, on tolère six heures.
    """
    periode = ligne["periode_min"] or 360
    try:
        vu = datetime.fromisoformat(str(ligne["dernier_passage"]))
    except (TypeError, ValueError):
        return True
    if vu.tzinfo is None:
        vu = vu.replace(tzinfo=timezone.utc)
    return (maintenant - vu) > timedelta(minutes=2 * periode)


def bilan(maintenant: datetime | None = None) -> dict:
    """L'état de toutes les sondes connues.

    ⛔ Trois états, jamais deux : `ok`, `ko`, et `muet` — la sonde n'est pas
    passée. Confondre « muet » et « ok » est ce qui a laissé la sonde des
    activations mentir treize jours.
    """
    init_schema()
    maintenant = maintenant or datetime.now(timezone.utc)
    lignes = []
    with _conn() as c:
        for r in c.execute("SELECT * FROM passages_sondes ORDER BY nom"):
            verdict = MUET if _est_muette(r, maintenant) else r["verdict"]
            lignes.append({
                "nom": r["nom"],
                "but": r["but"] or "(but non déclaré)",
                "verdict": verdict,
                "dernier_passage": r["dernier_passage"],
                "code_sortie": r["code_sortie"],
                "duree_ms": r["duree_ms"],
                "detail": r["detail"],
                "passages": r["passages"],
                "echecs": r["echecs"],
            })
    compte = {OK: 0, KO: 0, MUET: 0}
    for l in lignes:
        compte[l["verdict"]] = compte.get(l["verdict"], 0) + 1
    return {"sondes": lignes, "compte": compte, "total": len(lignes)}


def message(bilan_: dict) -> tuple[str, str]:
    """Le récap, en texte simple.

    ⚠️ Texte SANS balise : l'endpoint passe le corps dans `html.escape`, une
    balise s'y afficherait telle quelle.

    ⛔ Le message part MÊME quand tout va bien. Une santé qui ne parle qu'en
    cas de problème rend un cron cassé indiscernable d'une situation saine —
    c'est la règle que porte déjà `notify-daily-health.sh`.
    """
    c = bilan_["compte"]
    if not bilan_["total"]:
        return ("Sondes : aucun passage enregistré",
                "Aucune sonde n'a encore enregistré de passage.\n\n"
                "Ce n'est pas « tout va bien » : c'est « on ne sait pas ». "
                "Les sondes s'enregistrent en passant par scripts/sonde.sh.")

    sain = c.get(KO, 0) == 0 and c.get(MUET, 0) == 0
    titre = (f"{'✅' if sain else '⛔'} Sondes — {c.get(OK, 0)} OK, "
             f"{c.get(KO, 0)} KO, {c.get(MUET, 0)} muette(s)")

    lignes = []
    # Ce qui ne va pas d'abord : c'est ce qu'on doit lire même en diagonale.
    for etat, marque in ((KO, "⛔"), (MUET, "⚠️"), (OK, "✅")):
        groupe = [s for s in bilan_["sondes"] if s["verdict"] == etat]
        if not groupe:
            continue
        if etat == MUET:
            lignes.append("")
            lignes.append("MUETTES — pas passées depuis plus de deux fois "
                          "leur période. Ce n'est PAS « rien à signaler ».")
        elif etat == KO:
            lignes.append("EN ECHEC")
        else:
            lignes.append("")
            lignes.append("OK")
        for s in groupe:
            quand = str(s["dernier_passage"])[11:16]
            lignes.append(f"{marque} {s['nom']} — {s['but']}")
            if etat != OK:
                lignes.append(f"    dernier passage {quand} UTC, "
                              f"code {s['code_sortie']}")
                if s["detail"]:
                    lignes.append(f"    {str(s['detail'])[:160]}")
    return titre, "\n".join(lignes)


if __name__ == "__main__":
    import json
    print(json.dumps(bilan(), ensure_ascii=False, indent=1))
