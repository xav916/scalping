"""Importe dans `economic_events` l'historique calendrier exporte du terminal MT5.

## Pourquoi

`refresh_calendar()` purgeait tout evenement de plus de 7 jours. La purge est
retiree (2026-10-04), donc l'historique s'accumule DESORMAIS — mais au moment
du correctif le plus ancien evenement en base datait du 27/09. Le passe
d'avant est perdu pour ForexFactory, qui ne sert que la semaine en cours.

Le terminal MT5 embarque la base calendrier de MetaQuotes, avec `actual`,
`forecast` et `previous` sur plusieurs annees. C'est la seule source de
rattrapage disponible. ⛔ Le binding Python n'expose AUCUNE fonction
calendrier — verifie sur le binding 5.0.5735 installe, pas suppose :

    [n for n in dir(MetaTrader5) if 'calendar' in n.lower()]  ->  []

D'ou le detour par `mt5-bridge/CalendrierExport.mq5`, et d'ou ce module qui
lit ce qu'il produit.

## ⚠️ LE PIEGE CENTRAL : ON MESURE UN FUSEAU, PAS UN DECALAGE

`MqlCalendarValue.time` n'est pas garanti en UTC. Un serveur MT5 typique
tourne en EET/EEST : **UTC+2 en hiver, UTC+3 en ete**. Un decalage FIXE
applique a cinq ans d'historique se trompe donc d'une heure la moitie de
l'annee — c'est exactement l'erreur deja commise trois fois dans ce projet :

- le spread mesure a un INSTANT, puis applique a un banc entier ;
- la derive du pont lue sur un tick perime, qui decalait chaque bougie ;
- le taux EUR/USD FIGE a 1,155 quand le courtier cotait 1,1250.

D'ou `choisir_fuseau()` : on compare l'export aux lignes ForexFactory deja en
base, fuseau par fuseau, et `zoneinfo` applique ensuite les vraies regles
d'heure d'ete a chaque instant.

## ⛔ ET LA FENETRE ACTUELLE NE SUFFIT PAS A TRANCHER

La fenetre de recouvrement (27/09 -> aujourd'hui) ne traverse PAS le
changement d'heure du 25 octobre. Sur cette fenetre, `Europe/Helsinki`
(+3 l'ete) et `Etc/GMT-3` (+3 toute l'annee) apparient EXACTEMENT les memes
lignes — et pourtant ils divergent d'une heure sur tout janvier.

🔑 Le module refuse alors d'ecrire, et dit sur quelle ligne les candidats se
contredisent. Deux sorties honnetes :

1. attendre que la couverture ForexFactory passe le **25 octobre** : la
   mesure tranchera seule, un test le prouve ;
2. imposer le fuseau explicitement, en sachant ce qu'on tranche.

⚠️ Une egalite n'est PAS toujours un probleme : `Europe/Helsinki` et
`Europe/Athens` ont les memes regles et convertissent tout a l'identique.
L'egalite ne leve que si les candidats a egalite DIVERGENT sur une ligne.

## 🔑 L'import n'ecrit que le passe ANTERIEUR a ForexFactory

ForexFactory possede sa fenetre et tout ce qui suit. Ecrire par-dessus
creerait le meme evenement sous deux identifiants differents — un doublon
invisible, puisque `mql5_<value_id>` et `<ts>_<devise>_<titre>` ne se
ressemblent pas. La frontiere est la plus ancienne ligne non-MQL5 en base, et
elle est STRICTE.

## ⚠️ La colonne `source` et ses NULL

`_assurer_colonne_source()` cree la colonne et etiquette l'existant en
`forexfactory` a chaque import. Mais `refresh_calendar()` ne la renseigne pas :
les lignes ForexFactory ecrites APRES un import restent donc a NULL jusqu'au
suivant.

⛔ Ne pas lire cette colonne comme « NULL = inconnu ». Par construction,
NULL ne peut venir que de `refresh_calendar()` — l'import MQL5 ecrit toujours
`mql5`. Donc **NULL vaut `forexfactory`**, et toute requete doit faire
`COALESCE(source, 'forexfactory')`. La seule facon de supprimer cette
convention serait de renseigner `source` dans `refresh_calendar()` — ce qui
coute un redeploiement, et donc un rearmement de REM-002, pour une colonne
que rien ne lit encore.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SOURCE = "mql5"
SOURCE_FF = "forexfactory"

# Les instants de l'export sont au format `TimeToString(..., TIME_DATE|TIME_SECONDS)`.
_FORMAT_MQL5 = "%Y.%m.%d %H:%M:%S"

# MQL5 : CALENDAR_IMPORTANCE_NONE=0, LOW=1, MODERATE=2, HIGH=3.
_IMPORTANCE = {"3": "High", "2": "Medium", "1": "Low", "0": "Low"}

# Fuseaux plausibles pour un serveur MT5. ⚠️ Les `Etc/GMT-n` sont la EXPRES :
# ce sont des decalages FIXES, sans heure d'ete. S'ils gagnent, c'est que les
# instants du calendrier ne suivent pas l'heure d'ete — et il faut le savoir.
# (Dans `Etc/GMT-3`, le signe est inverse par convention POSIX : c'est UTC+3.)
FUSEAUX_CANDIDATS: tuple[str, ...] = (
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Helsinki",
    "Europe/Athens",
    "Europe/Moscow",
    "Etc/GMT-1",
    "Etc/GMT-2",
    "Etc/GMT-3",
    "America/New_York",
)


class ExportInvalide(ValueError):
    """Le fichier n'a pas la forme attendue, ou il est tronque."""


class RecouvrementInsuffisant(RuntimeError):
    """Aucune ligne ForexFactory ne recouvre la periode exportee : on ne peut
    pas mesurer le fuseau, et on ne le devine pas."""


class MesureAmbigue(RuntimeError):
    """Plusieurs fuseaux apparient autant de lignes ET se contredisent sur
    l'historique : la mesure ne tranche pas."""


# ─── Lecture du fichier ─────────────────────────────────────────────────────

def lire_entete(texte: str) -> dict[str, str]:
    """Rend les metadonnees de la ligne `#export` (gmt, serveur, build).

    ⚠️ Ces deux instants ne donnent le decalage que d'UN instant. Ils servent
    a constater, pas a convertir : c'est `choisir_fuseau()` qui tranche.
    """
    for ligne in texte.splitlines():
        if ligne.startswith("#export"):
            champs = ligne.split("\t")[1:]
            return {k: v for k, _, v in (c.partition("=") for c in champs) if k}
    return {}


def lire_export(texte: str) -> list[dict[str, str | None]]:
    """Lit les lignes de valeurs. Leve `ExportInvalide` si la forme ne tient pas.

    ⚠️ Le nombre de champs est verifie ligne par ligne. Un export coupe au
    milieu d'une ligne passerait sinon pour complet — c'est exactement le
    defaut du `/rates` du pont, qui tronquait en silence en gardant les
    bougies les plus ANCIENNES.
    """
    colonnes: list[str] | None = None
    lignes: list[dict[str, str | None]] = []

    for num, ligne in enumerate(texte.splitlines(), start=1):
        if not ligne.strip():
            continue
        if ligne.startswith("#colonnes"):
            colonnes = ligne.split("\t")[1:]
            continue
        if ligne.startswith("#"):
            continue
        if colonnes is None:
            raise ExportInvalide(
                f"ligne {num} : des donnees avant l'en-tete `#colonnes`")
        champs = ligne.split("\t")
        if len(champs) != len(colonnes):
            raise ExportInvalide(
                f"ligne {num} : {len(champs)} champs pour {len(colonnes)} "
                f"colonnes — export probablement TRONQUE")
        # ⛔ Un champ vide reste None. Le convertir en 0 confondrait « pas de
        # chiffre publie » et « zero », et fabriquerait des surprises nulles
        # la ou il n'y a aucune donnee.
        lignes.append({c: (v if v != "" else None)
                       for c, v in zip(colonnes, champs)})

    if colonnes is None:
        raise ExportInvalide("aucune ligne `#colonnes` : ce n'est pas un export")
    return lignes


def impact_depuis_importance(importance: str | None) -> str:
    """Traduit l'importance MQL5 dans le vocabulaire maison High/Medium/Low.

    NONE devient Low, comme le fait deja `_normalize_impact` pour tout ce
    qu'il ne reconnait pas cote ForexFactory : rester coherent importe plus
    qu'inventer un 4e niveau que personne ne lit.
    """
    return _IMPORTANCE.get((importance or "").strip(), "Low")


def _nombre(valeur: str | None) -> str | None:
    """« -41.700000 » -> « -41.7 », « 9.000000 » -> « 9.0 », vide -> None."""
    if valeur is None:
        return None
    s = valeur.strip()
    if not s:
        return None
    if "." in s:
        s = s.rstrip("0")
        if s.endswith("."):
            s += "0"
    return s


def instant_utc(brut: str | None, fuseau: str) -> str | None:
    """Instant brut de l'export, lu DANS `fuseau`, rendu en UTC.

    🔑 C'est `zoneinfo` qui applique l'heure d'ete, instant par instant. Un
    decalage fixe se tromperait d'une heure la moitie de l'annee.

    ⚠️ Pendant l'heure repetee du retour a l'heure d'hiver, `fold` vaut 0 :
    on retient la premiere occurrence. Une publication economique tombe
    rarement dans cette heure-la, et aucun choix n'est meilleur sans
    information supplementaire.
    """
    if not brut:
        return None
    try:
        t = datetime.strptime(brut.strip(), _FORMAT_MQL5)
    except ValueError:
        return None
    return (t.replace(tzinfo=ZoneInfo(fuseau))
            .astimezone(timezone.utc).isoformat())


# ─── Mesure du fuseau ───────────────────────────────────────────────────────

def _reperes_forexfactory(db: Path | str) -> set[tuple[str, str]]:
    """Les couples (instant, devise) des lignes qui ne viennent pas de MQL5.

    ⚠️ L'appariement se fait sur (instant, devise) et PAS sur le nom : deux
    sources nomment le meme evenement differemment (« Employment Change » /
    « Variation de l'emploi »). Exiger le nom ferait echouer la mesure pour
    une raison qui n'a rien a voir avec le fuseau. En echange, le gagnant
    doit etre seul — ou equivalent a ses ex aequo.
    """
    with sqlite3.connect(str(db)) as c:
        return {(ts, dev) for ts, dev in c.execute(
            "SELECT ts_utc, currency FROM economic_events "
            "WHERE id NOT LIKE 'mql5_%'")}


def mesurer_fuseau(
    texte: str,
    db: Path | str,
    candidats: Iterable[str] = FUSEAUX_CANDIDATS,
) -> dict[str, int]:
    """Compte, pour chaque fuseau candidat, les lignes qui tombent sur une
    ligne ForexFactory existante. Ne juge pas : rend le tableau brut.
    """
    lignes = lire_export(texte)
    reperes = _reperes_forexfactory(db)
    return {
        f: sum(1 for l in lignes
               if (instant_utc(l.get("time_brut"), f), l.get("devise")) in reperes)
        for f in candidats
    }


def _conversions(texte: str, fuseau: str) -> tuple[str | None, ...]:
    """La suite des instants UTC produits par un fuseau — sa signature."""
    return tuple(instant_utc(l.get("time_brut"), fuseau)
                 for l in lire_export(texte))


def choisir_fuseau(
    texte: str,
    db: Path | str,
    candidats: Sequence[str] = FUSEAUX_CANDIDATS,
) -> tuple[str, dict[str, int]]:
    """Rend (fuseau retenu, tableau des scores), ou leve.

    ⛔ `RecouvrementInsuffisant` si aucun candidat n'apparie quoi que ce soit.
    ⛔ `MesureAmbigue` si les ex aequo DIVERGENT sur au moins une ligne.

    ⚠️ Des ex aequo qui convertissent tout a l'identique (Helsinki / Athenes,
    memes regles) ne sont pas une ambiguite : on en retient un, et le resultat
    est le meme.
    """
    scores = mesurer_fuseau(texte, db, candidats)
    meilleur = max(scores.values()) if scores else 0
    if meilleur == 0:
        raise RecouvrementInsuffisant(
            "aucune ligne ForexFactory ne recouvre la periode exportee : "
            "le fuseau ne peut pas etre mesure, et il ne sera pas devine")

    gagnants = sorted(f for f, n in scores.items() if n == meilleur)
    signatures = {f: _conversions(texte, f) for f in gagnants}
    reference = signatures[gagnants[0]]
    divergents = [f for f in gagnants if signatures[f] != reference]

    if divergents:
        # Nomme la PREMIERE ligne sur laquelle ils se contredisent : sans
        # elle, « ambigu » n'apprend rien a celui qui doit trancher.
        autre = divergents[0]
        exemple = next(
            (f"{a} vs {b}" for a, b in zip(reference, signatures[autre]) if a != b),
            "(indetermine)")
        raise MesureAmbigue(
            f"{len(gagnants)} fuseaux apparient {meilleur} lignes "
            f"({', '.join(gagnants)}) et se contredisent sur l'historique : "
            f"{exemple}. La fenetre de recouvrement ne traverse probablement "
            f"pas de changement d'heure — attendre le 25 octobre, ou imposer "
            f"le fuseau en connaissance de cause.")

    return gagnants[0], scores


# ─── Ecriture ───────────────────────────────────────────────────────────────

def _assurer_colonne_source(conn: sqlite3.Connection) -> None:
    """Ajoute `source` si elle manque, et etiquette l'existant.

    ⛔ Un chiffre dont on ne connait pas la source est un chiffre d'air. Et
    l'ajout doit etre idempotent : SQLite n'a pas de `ADD COLUMN IF NOT
    EXISTS`, donc on lit le schema avant.
    """
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(economic_events)")}
    if "source" not in colonnes:
        conn.execute("ALTER TABLE economic_events ADD COLUMN source TEXT")
    # ⛔ `event_code` AJOUTE le 2026-10-05, et c'est un defaut que j'avais
    # laisse passer : je ne stockais que `event_name`, qui vient du terminal
    # dans SA langue — « Evolution de l'emploi ». Toute regle ecrite sur des
    # codes anglais (`employment-change`) aurait trouve ZERO evenement, en
    # silence. Le code, lui, est independant de la langue.
    if "event_code" not in colonnes:
        conn.execute("ALTER TABLE economic_events ADD COLUMN event_code TEXT")
    conn.execute(
        "UPDATE economic_events SET source = ? "
        "WHERE source IS NULL AND id NOT LIKE 'mql5_%'", (SOURCE_FF,))


def _frontiere(conn: sqlite3.Connection) -> str | None:
    """La plus ancienne ligne non-MQL5. L'import s'arrete STRICTEMENT avant."""
    valeur, = conn.execute(
        "SELECT MIN(ts_utc) FROM economic_events WHERE id NOT LIKE 'mql5_%'"
    ).fetchone()
    return valeur


def importer(texte: str, db: Path | str, fuseau: str) -> int:
    """Ecrit les lignes anterieures a la couverture ForexFactory. Rend le compte.

    `fuseau` doit venir de `choisir_fuseau()`, ou d'une decision assumee.
    """
    lignes = lire_export(texte)
    maintenant = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(str(db)) as conn:
        _assurer_colonne_source(conn)
        frontiere = _frontiere(conn)

        a_ecrire = []
        ignorees = 0
        for l in lignes:
            ts = instant_utc(l.get("time_brut"), fuseau)
            if ts is None:
                ignorees += 1
                continue
            if frontiere is not None and ts >= frontiere:
                ignorees += 1
                continue
            devise = (l.get("devise") or "").strip()
            nom = (l.get("nom") or "").strip()
            if not devise or not nom:
                # Une valeur sans devise ni nom n'est pas exploitable : on ne
                # saurait a quelle paire la rattacher.
                ignorees += 1
                continue
            a_ecrire.append({
                "id": f"{SOURCE}_{l.get('value_id')}",
                "ts_utc": ts,
                "currency": devise,
                "event_name": nom,
                "impact": impact_depuis_importance(l.get("importance")),
                "actual": _nombre(l.get("actual")),
                "forecast": _nombre(l.get("forecast")),
                "previous": _nombre(l.get("previous")),
                "fetched_at": maintenant,
                "source": SOURCE,
                "event_code": (l.get("event_code") or "").strip() or None,
            })

        if a_ecrire:
            conn.executemany(
                "INSERT OR REPLACE INTO economic_events "
                "(id, ts_utc, currency, event_name, impact, actual, forecast, "
                " previous, fetched_at, source, event_code) "
                "VALUES (:id, :ts_utc, :currency, :event_name, :impact, "
                " :actual, :forecast, :previous, :fetched_at, :source, "
                " :event_code)",
                a_ecrire)

    logger.info(
        "import calendrier MQL5 : %d ecrites, %d ignorees (frontiere %s, "
        "fuseau %s)", len(a_ecrire), ignorees, frontiere, fuseau)
    return len(a_ecrire)
