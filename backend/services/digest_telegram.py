"""Le bilan du jour : ranger les messages differes, puis les envoyer en UN seul.

Deuxieme moitie de la regle des trois etages (`etages_notification`). Sans ce
magasin, << differer >> voudrait dire **perdre**, et rationaliser un fil en
jetant des messages serait le pire des deux.

## 🔑 UNE TABLE, PAS UN FICHIER JSON

Le depot range beaucoup d'etats en JSON, et c'est bien pour un etat de
deduplication — une seule valeur, ecrasee. Ici il faut **ajouter** depuis
plusieurs processus (le conteneur, les crons, les scripts shell) et **lire une
fois par jour**. Un JSON lu-modifie-ecrit par trois ecrivains concurrents perd
des lignes sans le dire ; SQLite non.

## ⛔ CE QU'IL NE FAIT PAS : dedupliquer a la place du cooldown

Le cooldown de la route vit AVANT lui. Si une cle passe le cooldown dix fois
dans la journee, dix lignes sont rangees — et le bilan les **compte** au lieu
de les repeter. Dire << palier franchi x10 >> est une information ; dire dix
fois << palier franchi >> est du bruit.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TABLE = "digest_telegram"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc     TEXT    NOT NULL,
    canal      TEXT    NOT NULL,
    dedup_key  TEXT,
    titre      TEXT,
    corps      TEXT,
    envoye_le  TEXT
);
CREATE INDEX IF NOT EXISTS idx_{TABLE}_attente
    ON {TABLE} (canal, envoye_le);
"""


def _db(chemin: str | None = None) -> sqlite3.Connection:
    if chemin is None:
        from backend.services.mt5_sync import _db_path
        chemin = _db_path()
    c = sqlite3.connect(chemin, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def ranger(canal: str, dedup_key: str | None, titre: str, corps: str,
           chemin: str | None = None, maintenant: datetime | None = None) -> int:
    """Range un message differe. Rend son `id`.

    ⛔ Ne leve jamais vers l'appelant : la route d'envoi ne doit pas tomber
    parce que le bilan est indisponible. Mais elle le DIT, et rend 0 — pour
    que l'appelant puisse decider d'envoyer tout de suite plutot que de
    perdre le message.
    """
    t = (maintenant or datetime.now(timezone.utc)).isoformat()
    try:
        with _db(chemin) as c:
            cur = c.execute(
                f"INSERT INTO {TABLE} (ts_utc, canal, dedup_key, titre, corps)"
                f" VALUES (?, ?, ?, ?, ?)",
                (t, canal, dedup_key, titre, corps))
            return int(cur.lastrowid or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("digest_telegram: impossible de ranger %r (%s) — "
                       "l'appelant doit envoyer tout de suite", dedup_key, e)
        return 0


def en_attente(canal: str, chemin: str | None = None) -> list[sqlite3.Row]:
    try:
        with _db(chemin) as c:
            return list(c.execute(
                f"SELECT * FROM {TABLE} WHERE canal = ? AND envoye_le IS NULL"
                f" ORDER BY id", (canal,)))
    except Exception as e:  # noqa: BLE001
        logger.warning("digest_telegram: lecture impossible (%s)", e)
        return []


def formater(lignes) -> str:
    """Le texte du bilan — groupe par PREFIXE de cle, et COMPTE les repetitions.

    🔑 << palier franchi x10 >> est une information ; dix lignes
    << palier franchi >> sont du bruit. C'est toute la difference entre un
    bilan et une archive.

    ⛔ TEXTE BRUT, aucun Markdown. Les `dedup_key` sont en snake_case et
    Telegram lit un underscore comme une italique OUVERTE : le message part en
    400 et n'est jamais livre. Defaut deja paye le 2026-10-10 sur `/trade`.
    """
    if not lignes:
        return ""
    groupes: dict[str, list] = {}
    for l in lignes:
        cle = (l["dedup_key"] or "sans cle").split(":")[0]
        groupes.setdefault(cle, []).append(l)

    out = ["Bilan du jour — %d message(s) differe(s)" % len(lignes), ""]
    for cle in sorted(groupes, key=lambda k: -len(groupes[k])):
        g = groupes[cle]
        if len(g) == 1:
            titre = (g[0]["titre"] or "").strip()
            corps = (g[0]["corps"] or "").strip()
            out.append("- %s%s" % (titre or cle, (" : " + corps) if corps else ""))
        else:
            out.append("- %s x%d" % (cle, len(g)))
            # Le dernier suffit : les precedents sont le meme fait, plus vieux.
            dernier = (g[-1]["corps"] or g[-1]["titre"] or "").strip()
            if dernier:
                out.append("    dernier : %s" % dernier[:160])
    return "\n".join(out)


def marquer_envoyes(ids, chemin: str | None = None,
                    maintenant: datetime | None = None) -> int:
    """⛔ A n'appeler QU'APRES un envoi reussi. Marquer avant, c'est perdre le
    bilan le jour ou Telegram refuse."""
    if not ids:
        return 0
    t = (maintenant or datetime.now(timezone.utc)).isoformat()
    try:
        with _db(chemin) as c:
            c.executemany(
                f"UPDATE {TABLE} SET envoye_le = ? WHERE id = ?",
                [(t, int(i)) for i in ids])
            return len(ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("digest_telegram: marquage impossible (%s) — le bilan "
                       "sera renvoye demain", e)
        return 0
