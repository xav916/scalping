"""Le JOURNAL des envois Telegram : qui a ecrit, sur quel fil, et ce qui est
reellement arrive.

> Xavier, 2026-10-11 : « faire 1 et 2 » — le point ① de ce que j'avais laisse
> ouvert apres la rationalisation du fil IC Markets.

## ⛔ LE TROU QU'IL BOUCHE, et je l'ai rencontre en voulant compter

En faisant l'inventaire du fil, j'ai pu dire **qui tente** d'ecrire et **a
quelle cadence**. Je n'ai **pas** pu dire combien de messages arrivent
vraiment : il n'existait ni table, ni log, ni trace d'aucune sorte.

🔑 Consequences, toutes les deux reelles :
  - **les huit copies du meme message du 2026-10-07** ont pu passer sans que
    rien ne les compte ;
  - et la rationalisation en trois etages, armee le soir meme, etait
    **invérifiable** : on ne pouvait pas savoir si elle avait reduit le bruit,
    ni de combien.

⇒ On ne rationalise pas ce qu'on ne compte pas.

## 🔑 ON TRACE TOUTES LES ISSUES, PAS SEULEMENT LES ENVOIS

    envoye      parti, et Telegram a rendu 200
    differe     range dans le bilan du jour (etage DIGEST)
    cooldown    ecarte comme doublon par le cooldown de la route
    reroute     parti sur un AUTRE fil que celui demande (etage INFRA)
    echec       Telegram a refuse, ou le reseau a lache

⛔ Ne tracer que les succes serait exactement l'erreur a ne pas faire : un
emetteur qui echoue mille fois par jour se lirait comme un emetteur muet, et
un cooldown qui etouffe une alerte se lirait comme une absence d'alerte.

## ⛔ IL NE DOIT JAMAIS FAIRE TOMBER UN ENVOI

Chaque ecriture est enveloppee. Un journal indisponible est un desagrement ;
un message de trade perdu parce que son journal etait plein serait une faute.
`tracer()` ne leve donc jamais, et rend `False` quand il n'a pas pu ecrire.

## ⚠️ CE QU'IL NE COUVRE PAS ENCORE

`telegram_service` porte **huit** points d'envoi. Sont traces les deux qui
concernent le fil de Xavier — la route de notification (les 17 emetteurs) et
les ouvertures/fermetures de trade. Les six autres servent les signaux
clients et le test de liaison ; les ajouter multiplierait la surface sans rien
dire de son fil. C'est un choix, pas un oubli.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TABLE = "journal_envois_telegram"

# Les issues possibles. ⛔ Une issue hors de cette liste est ecrite quand meme
# (on ne perd pas une trace pour une faute de frappe) mais elle est criee.
ISSUES = ("envoye", "differe", "cooldown", "reroute", "echec")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc         TEXT NOT NULL,
    canal_demande  TEXT,
    canal_effectif TEXT,
    dedup_key      TEXT,
    etage          TEXT,
    issue          TEXT NOT NULL,
    titre          TEXT,
    detail         TEXT,
    octets         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_{TABLE}_jour ON {TABLE} (ts_utc);
CREATE INDEX IF NOT EXISTS idx_{TABLE}_cle  ON {TABLE} (dedup_key);
"""


def _db(chemin: str | None = None) -> sqlite3.Connection:
    if chemin is None:
        from backend.services.mt5_sync import _db_path
        chemin = _db_path()
    c = sqlite3.connect(chemin, timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def tracer(issue: str, canal_demande: str | None = None,
           canal_effectif: str | None = None, dedup_key: str | None = None,
           etage: str | None = None, titre: str | None = None,
           detail: str | None = None, octets: int | None = None,
           chemin: str | None = None,
           maintenant: datetime | None = None) -> bool:
    """Ecrit une ligne. Rend ``False`` s'il n'a pas pu — et ne leve JAMAIS.

    ⚠️ `titre` est tronque a 200 caracteres : le journal sert a COMPTER, pas a
    archiver. Garder 4 000 caracteres par ligne ferait une base de plusieurs
    gigaoctets en quelques mois, comme la `backtest.db` de 7,2 Go deja
    presente sur ce disque.
    """
    if issue not in ISSUES:
        logger.error("journal_envois_telegram: issue %r hors de %s — tracee "
                     "quand meme", issue, ISSUES)
    try:
        t = (maintenant or datetime.now(timezone.utc)).isoformat()
        with _db(chemin) as c:
            c.execute(
                f"INSERT INTO {TABLE} (ts_utc, canal_demande, canal_effectif,"
                f" dedup_key, etage, issue, titre, detail, octets)"
                f" VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t, canal_demande, canal_effectif, dedup_key, etage, issue,
                 (titre or "")[:200], (detail or "")[:200], octets))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("journal_envois_telegram: trace impossible (%s) — "
                       "l'envoi lui-meme n'est PAS affecte", e)
        return False


def bilan(jours: int = 1, canal: str | None = None,
          chemin: str | None = None,
          maintenant: datetime | None = None) -> list[dict]:
    """Par emetteur et par issue : combien, sur les `jours` derniers jours.

    🔑 Groupe par **prefixe** de `dedup_key`, comme la table des etages : c'est
    la seule partie stable d'une cle qui porte une identite variable.
    """
    depuis = ((maintenant or datetime.now(timezone.utc))
              - timedelta(days=jours)).isoformat()
    try:
        with _db(chemin) as c:
            sql = (f"SELECT dedup_key, issue, canal_effectif, COUNT(*) AS n"
                   f" FROM {TABLE} WHERE ts_utc >= ?")
            args: list = [depuis]
            if canal:
                sql += " AND canal_demande = ?"
                args.append(canal)
            sql += " GROUP BY dedup_key, issue, canal_effectif"
            lignes = list(c.execute(sql, args))
    except Exception as e:  # noqa: BLE001
        logger.warning("journal_envois_telegram: bilan illisible (%s)", e)
        return []

    groupes: dict[tuple[str, str, str], int] = {}
    for l in lignes:
        prefixe = (l["dedup_key"] or "sans cle").split(":")[0]
        cle = (prefixe, l["issue"], l["canal_effectif"] or "?")
        groupes[cle] = groupes.get(cle, 0) + int(l["n"])
    return [{"emetteur": a, "issue": b, "canal": c, "n": n}
            for (a, b, c), n in sorted(groupes.items(), key=lambda x: -x[1])]


def purger(garder_jours: int = 90, chemin: str | None = None,
           maintenant: datetime | None = None) -> int:
    """Retire les lignes plus vieilles que `garder_jours`. Rend le compte.

    ⛔ POURQUOI UNE PURGE, ET POURQUOI 90 JOURS. Ce disque porte deja une
    `backtest.db` de **7,2 Go** : une table qui grossit sans fin finit par
    couter plus cher que ce qu'elle apprend. Trois mois suffisent a comparer
    un avant et un apres.
    ⚠️ Et la purge AGREGE-T-ELLE avant de supprimer ? Non — ici on perd le
    detail ancien volontairement. Le `bilan()` est a lancer AVANT si on veut
    garder la trace d'une periode. C'est l'inverse du choix fait pour les
    refus d'admission (ou l'agregation valait 44x), parce qu'ici le volume
    attendu est de quelques centaines de lignes par jour, pas 395 201.
    """
    avant = ((maintenant or datetime.now(timezone.utc))
             - timedelta(days=garder_jours)).isoformat()
    try:
        with _db(chemin) as c:
            cur = c.execute(f"DELETE FROM {TABLE} WHERE ts_utc < ?", (avant,))
            return int(cur.rowcount or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("journal_envois_telegram: purge impossible (%s)", e)
        return 0
