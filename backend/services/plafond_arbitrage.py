"""Le plafond journalier devient un ARBITRAGE, plus un gel automatique.

Demande de Xavier le 2026-09-04 : quand le plafond de perte du jour est
franchi, ne plus geler tout seul — **poser la question sur Telegram**, et
**bloquer le compte pendant tout le temps de la réponse**.

Le sens exact, et il compte :

    dépassement  →  compte BLOQUÉ immédiatement  →  question posée
                 →  « gele »     : reste bloqué jusqu'à minuit UTC
                 →  « continue » : débloqué, pour CE palier seulement

⛔ **Fermé par défaut, à chaque étage.** L'absence de ligne d'arbitrage bloque.
Une ligne en attente bloque. Une base illisible bloque. Seul un `CONTINUER`
explicitement enregistré débloque. L'inverse ferait d'une panne — scheduler
mort, Telegram muet, disque plein — une autorisation de trader, et c'est de
l'argent réel.

🔑 **Le palier.** Répondre « continue » à −32 € n'autorise pas −300 €. Le
palier vaut ``int(cumul / limite)`` : il passe à 2 au deuxième plafond
consommé, aucune ligne d'arbitrage n'existe pour ce palier, et la question est
reposée. Une autorisation vaut pour la tranche où elle a été donnée, jamais
pour la journée.

⛔ **La ligne naît AVANT le message.** `doit_bloquer()` l'insère au moment
exact du dépassement, sans réseau ; le job scheduler ne fait que livrer la
question. Si le job meurt, on garde quand même la trace horodatée qu'un
arbitrage était dû — et le compte reste bloqué. Sans ça, un scheduler en panne
aurait produit un blocage muet et sans mémoire.

⛔ **`demande_le` n'avance que sur un envoi CONFIRMÉ.** C'est la règle déjà
posée sur les sondes : marquer avant confirmation ferait disparaître la
question à jamais, et le compte resterait bloqué sur un message que personne
n'a reçu. Le 20/08, le moniteur est resté muet trois mois sans que rien ne le
dise.

⚠️ La question part sur le fil **sales** et non sur le fil des trades : c'est
le seul bot dont l'entrée est branchée (`/api/telegram/sales-webhook`, filtré
sur le `chat_id` de Xavier). Poser la question là où la réponse ne peut pas
revenir en ferait un dispositif décoratif.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

EN_ATTENTE = "EN_ATTENTE"
GELER = "GELER"
CONTINUER = "CONTINUER"


def _conn() -> sqlite3.Connection:
    from backend.services.trade_log_service import _DB_PATH
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _init_schema() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS plafond_arbitrage (
            destination_id TEXT NOT NULL,
            jour           TEXT NOT NULL,
            palier         INTEGER NOT NULL,
            etat           TEXT NOT NULL,
            pnl_au_moment  REAL,
            seuil          REAL,
            cree_le        TEXT,
            demande_le     TEXT,
            repondu_le     TEXT,
            PRIMARY KEY (destination_id, jour, palier))""")


def _aujourdhui() -> str:
    """Le jour du plafond, en UTC — le fuseau du serveur.

    Le même « jour » que `_pnl_du_jour_par_destination`, qui compare à
    `date('now')` en SQLite. Deux notions du jour qui divergeraient rendraient
    l'arbitrage valide pour une journée que le cumul ne connaît pas.
    """
    return datetime.now(timezone.utc).date().isoformat()


def palier_de(cumul: float, limite: float) -> int:
    """Combien de fois le plafond est consommé. 0 = pas encore franchi.

    ``limite`` est négative (−21,54 €). À −32,27 € le palier vaut 1 ; il
    passera à 2 à −43,08 €, et la question sera reposée.
    """
    if not limite or limite >= 0:
        return 0
    if cumul > limite:
        return 0
    return max(1, int(cumul / limite))


# ── Lecture / écriture d'état ─────────────────────────────────────────────

def etat_courant(destination_id: str, palier: int,
                 jour: str | None = None) -> dict[str, Any] | None:
    try:
        with _conn() as c:
            r = c.execute(
                "SELECT * FROM plafond_arbitrage WHERE destination_id=? "
                "AND jour=? AND palier=?",
                (destination_id, jour or _aujourdhui(), palier)).fetchone()
        return dict(r) if r else None
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"arbitrage: état illisible ({e})")
        return None


def ouvrir_demande(destination_id: str, palier: int, cumul: float,
                   seuil: float) -> bool:
    """Crée la ligne d'arbitrage si elle n'existe pas. True si elle est neuve.

    Idempotent par clé primaire : `doit_bloquer` est appelé des centaines de
    fois par jour (570 le 04/09), et ré-ouvrir la demande à chaque appel
    rejouerait la question sans fin.
    """
    try:
        _init_schema()
        with _conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO plafond_arbitrage "
                "(destination_id, jour, palier, etat, pnl_au_moment, seuil, "
                " cree_le) VALUES (?,?,?,?,?,?,?)",
                (destination_id, _aujourdhui(), palier, EN_ATTENTE,
                 round(float(cumul), 2), round(float(seuil), 2),
                 datetime.now(timezone.utc).isoformat()))
            return cur.rowcount > 0
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"arbitrage: ouverture impossible ({e})")
        return False


def marquer_question_posee(destination_id: str, palier: int) -> None:
    """N'est appelé QUE sur un envoi Telegram confirmé."""
    with _conn() as c:
        c.execute(
            "UPDATE plafond_arbitrage SET demande_le=? WHERE destination_id=? "
            "AND jour=? AND palier=? AND demande_le IS NULL",
            (datetime.now(timezone.utc).isoformat(), destination_id,
             _aujourdhui(), palier))


def demandes_en_attente() -> list[dict[str, Any]]:
    """Les arbitrages du jour non tranchés, le plus récent d'abord."""
    try:
        _init_schema()
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM plafond_arbitrage WHERE jour=? AND etat=? "
                "ORDER BY palier DESC, destination_id",
                (_aujourdhui(), EN_ATTENTE)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"arbitrage: liste illisible ({e})")
        return []


# ── La décision ───────────────────────────────────────────────────────────

def doit_bloquer(destination_id: str, cumul: float, seuil: float) -> bool:
    """Le compte doit-il rester bloqué, le plafond étant franchi ?

    ⛔ Appelée UNIQUEMENT quand le dépassement est déjà constaté. Elle ne
    rejuge pas le dépassement : elle dit qui, de l'arbitrage ou du défaut,
    l'emporte.

    Tout ce qui n'est pas un `CONTINUER` enregistré bloque — y compris une
    base illisible. C'est de l'argent réel : une panne de lecture ne peut pas
    valoir autorisation.
    """
    palier = palier_de(cumul, seuil)
    if palier <= 0:  # pragma: no cover - appelant fautif
        return False

    ouvrir_demande(destination_id, palier, cumul, seuil)

    etat = etat_courant(destination_id, palier)
    if etat is None:
        logger.warning(
            f"arbitrage[{destination_id}]: état introuvable — blocage par "
            "prudence")
        return True
    return etat.get("etat") != CONTINUER


def repondre(decision: str, destination_id: str | None = None
             ) -> dict[str, Any]:
    """Applique ``GELER`` / ``CONTINUER`` aux demandes en attente.

    ⛔ Sans demande en attente, elle n'écrit RIEN. Autoriser d'avance ouvrirait
    la porte la plus dangereuse du dispositif : un « continue » envoyé le matin
    désarmerait le plafond pour un dépassement du soir, sans que personne ne
    l'ait vu venir.
    """
    if decision not in (GELER, CONTINUER):
        raise ValueError(f"décision inconnue: {decision!r}")

    attente = [d for d in demandes_en_attente()
               if destination_id is None
               or d["destination_id"] == destination_id]
    if not attente:
        return {"applique": 0, "decision": decision, "destinations": []}

    maintenant = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        for d in attente:
            c.execute(
                "UPDATE plafond_arbitrage SET etat=?, repondu_le=? "
                "WHERE destination_id=? AND jour=? AND palier=? AND etat=?",
                (decision, maintenant, d["destination_id"], d["jour"],
                 d["palier"], EN_ATTENTE))
    return {"applique": len(attente), "decision": decision,
            "destinations": sorted({d["destination_id"] for d in attente})}


# ── Le message ────────────────────────────────────────────────────────────

def construire_question(demandes: list[dict[str, Any]]) -> str:
    """Texte simple, sans chevrons : le canal poste en HTML et Telegram refuse
    le message ENTIER sur une balise mal formée — échec silencieux."""
    lignes = ["PLAFOND DE PERTE FRANCHI - ta decision", ""]
    for d in demandes:
        lignes.append(
            f"  {d['destination_id']} : {d.get('pnl_au_moment')} EUR "
            f"(plafond {d.get('seuil')} EUR, palier {d['palier']})")
    lignes += [
        "",
        "Le compte est DEJA bloque - il le reste tant que tu n'as pas repondu.",
        "",
        "  gele     : il reste bloque jusqu'a minuit UTC (02h00 Paris)",
        "  continue : il retrade, pour CETTE tranche de perte seulement",
        "",
        "Sans reponse, il reste bloque. Une nouvelle question sera posee si la",
        "perte franchit un plafond de plus.",
    ]
    return "\n".join(lignes)


def confirmation(resultat: dict[str, Any]) -> str:
    if not resultat.get("applique"):
        return ("Aucun arbitrage en attente - rien n'a ete modifie.\n"
                "Un « continue » ne s'enregistre pas d'avance : il faut un "
                "plafond effectivement franchi.")
    quoi = ("Comptes GELES jusqu'a minuit UTC"
            if resultat["decision"] == GELER
            else "Comptes DEBLOQUES pour cette tranche de perte")
    return (f"{quoi} : {', '.join(resultat['destinations'])}\n\n"
            "Une nouvelle question sera posee au plafond suivant.")


# ── Le job qui pose la question ───────────────────────────────────────────

async def executer() -> int:
    """Livre les questions ouvertes et non encore posées. Rend le nombre envoyé.

    Ne décide de rien : le blocage est déjà en vigueur depuis `doit_bloquer`.
    Son unique rôle est que Xavier SOIT AU COURANT — c'est la partie du
    dispositif qui, si elle tombe en panne, laisse un blocage muet.
    """
    _init_schema()
    a_poser = [d for d in demandes_en_attente() if not d.get("demande_le")]
    if not a_poser:
        return 0

    from backend.services import telegram_service
    texte = construire_question(a_poser)
    envoye = await telegram_service.send_sales_text(texte, parse_mode=None)
    if not envoye:
        logger.warning(
            "arbitrage: question NON transmise — demande laissée ouverte, "
            "nouvelle tentative au prochain passage")
        return 0

    for d in a_poser:
        marquer_question_posee(d["destination_id"], d["palier"])
    logger.info(f"arbitrage: question posée pour {len(a_poser)} compte(s)")
    return len(a_poser)
