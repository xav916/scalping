"""Sonde de déploiement de l'horizon 1 jour (2026-09-04).

Les 12 paires de la whitelist démo servent désormais 4h **et** 1 jour. Le
chemin est vérifié mécaniquement — 60 bougies récupérées par paire — mais au
rythme du 1 jour (~0,4 setup par paire et par jour), le premier signal réel
n'était pas attendu avant ~5 heures. Rester devant l'écran n'aurait rien
prouvé de plus.

Cette sonde répond à la seule question qui reste : **est-ce que ça produit ?**

🔑 **Elle a une FIN.** Une sonde qui répète indéfiniment devient du bruit, et
on a vu le 04/09 ce que devient une alerte qu'on cesse de lire : la sauvegarde
S3 signalait son échec depuis cinq nuits, les messages partaient, arrivaient,
et personne ne les voyait plus. Celle-ci annonce le premier setup 1 jour, puis
se tait définitivement.

⚠️ Elle vit dans le SCHEDULER, pas dans un script cron. Les scripts hors dépôt
de ce projet ont tous fini par diverger de ce qui tourne — `backup-s3.sh` en
deux copies, les configs nginx périmées d'avril. Ici elle est versionnée et
testée.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Les 12 paires ouvertes au 1 jour le 2026-09-04.
PAIRES = (
    "XAU/USD", "XAG/USD", "WTI/USD", "EUR/USD", "GBP/USD", "USD/JPY",
    "EUR/JPY", "GBP/JPY", "EUR/GBP", "USD/CHF", "AUD/USD", "USD/CAD",
)

_CLE = "horizon_1d_premier_setup"


def _conn() -> sqlite3.Connection:
    from backend.services.trade_log_service import _DB_PATH
    return sqlite3.connect(str(_DB_PATH))


def _init_schema() -> None:
    """Table d'état minimale, idempotente.

    ⚠️ Créée ici plutôt que réutilisée : le projet n'a pas de magasin
    clé/valeur générique, et en détourner un (`pair_admission_state`) mêlerait
    l'observation à la décision — exactement ce qu'on a passé la journée à
    séparer.
    """
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sonde_etat (
            cle TEXT PRIMARY KEY, valeur TEXT NOT NULL, maj_le TEXT)""")


def _lire(cle: str) -> str | None:
    try:
        with _conn() as c:
            r = c.execute("SELECT valeur FROM sonde_etat WHERE cle = ?",
                          (cle,)).fetchone()
        return r[0] if r else None
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"sonde 1d: état illisible ({e})")
        return None


def _ecrire(cle: str, valeur: str) -> None:
    from datetime import datetime, timezone
    with _conn() as c:
        c.execute(
            "INSERT INTO sonde_etat (cle, valeur, maj_le) VALUES (?,?,?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur, "
            "maj_le=excluded.maj_le",
            (cle, valeur, datetime.now(timezone.utc).isoformat()))


def _compter_setups_1d() -> list[tuple[str, str, str]]:
    trous = ",".join("?" * len(PAIRES))
    with _conn() as c:
        return c.execute(
            f"SELECT pair, pattern, detected_at FROM shadow_setups "
            f"WHERE timeframe = '1d' AND pair IN ({trous}) "
            f"ORDER BY id DESC LIMIT 5", PAIRES).fetchall()


def marquer_etat_initial() -> None:
    """Pose l'état de départ SANS rien annoncer.

    ⛔ Sans ce marquage, un redémarrage rejouerait l'annonce d'un setup vieux
    de plusieurs jours : la sonde crierait une nouvelle qui n'en est plus une.
    """
    if _lire(_CLE) is None:
        deja = bool(_compter_setups_1d())
        _ecrire(_CLE, "repondu" if deja else "en_attente")


def marquer_annonce() -> None:
    _ecrire(_CLE, "repondu")


def construire_message() -> str | None:
    """Le texte à envoyer, ou ``None`` s'il n'y a rien à dire.

    ⚠️ Texte simple, sans `<` ni `>` : le canal poste en HTML et Telegram
    refuse le message ENTIER sur une balise mal formée — échec silencieux.
    """
    if _lire(_CLE) == "repondu":
        return None
    lignes = _compter_setups_1d()
    if not lignes:
        return None

    pair, motif, quand = lignes[0]
    return "\n".join([
        "HORIZON 1 JOUR : premier setup produit",
        "",
        f"  {pair} — {motif} — {str(quand)[:16]}",
        "",
        f"{len(lignes)} setup(s) 1 jour vus sur les 12 paires ouvertes le 04/09.",
        "La chaine produit donc bien a cet horizon, sur le compte DEMO seul.",
        "",
        "Cette sonde ne parlera plus : sa question a une reponse.",
    ])


async def executer() -> bool:
    """Job scheduler : annonce le premier setup 1 jour, puis se tait.

    ⛔ L'état n'avance QUE sur un envoi confirmé. Le marquer avant ferait
    disparaitre l'annonce a jamais — la sonde se tairait sur une reponse que
    personne n'a recue. C'est la regle deja posee sur les sondes existantes.
    """
    _init_schema()
    marquer_etat_initial()

    texte = construire_message()
    if texte is None:
        return False

    from backend.services import telegram_service
    envoye = await telegram_service.send_sales_text(texte, parse_mode=None)
    if envoye:
        marquer_annonce()
        logger.info("sonde 1d: premier setup annonce, sonde eteinte")
    else:
        logger.warning(
            "sonde 1d: envoi non confirme — etat NON avance, nouvelle tentative "
            "au prochain passage")
    return bool(envoye)
