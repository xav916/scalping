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

🔑 **La tranche.** Répondre « continue » à −32 € n'autorise pas −300 €. Une
autorisation est **ancrée sur la perte à laquelle elle a été donnée** et couvre
un plafond de plus : accordée à −32,27 € avec un plafond de −21,54 €, elle
tient jusqu'à −53,81 €, puis la question est reposée.

⛔ Elle n'est PAS un `int(cumul / plafond)`. Cette première version a été
sondée en production le 04/09 et montrait son défaut : au redémarrage le
capital retombe sur `TRADING_CAPITAL` (650 €) le temps que le solde réel
(717,93 €) revienne, et le plafond glisse de −21,54 à −19,50 €. Un
dénominateur qui bouge déplace la tranche, donc peut faire **ressurgir une
autorisation périmée**. L'ancrage supprime la question.

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


def franchi(cumul: float, limite: float) -> bool:
    """Le plafond est-il franchi ? ``limite`` est négative (−21,54 €)."""
    if not limite or limite >= 0:
        return False
    return cumul <= limite


def couvre(ligne: dict[str, Any], cumul: float) -> bool:
    """Une autorisation couvre-t-elle encore la perte actuelle ?

    🔑 **Ancrée sur le moment où elle a été donnée**, jamais recalculée. Un
    `CONTINUER` accordé à −32,27 € avec un plafond de −21,54 € couvre jusqu'à
    −53,81 € : une tranche de plus, et pas un euro au-delà.

    ⛔ La première version divisait la perte courante par le plafond courant.
    Sondée en production le 04/09, elle a montré son défaut : au redémarrage le
    capital retombe sur `TRADING_CAPITAL` (650 €) avant que le solde réel
    (717,93 €) ne soit rechargé, et le plafond passe de −21,54 à −19,50 €. Un
    dénominateur qui bouge déplace la tranche — donc peut faire **ressurgir une
    autorisation périmée** sur une perte qu'elle n'a jamais couverte. Ancrer la
    borne dans la ligne supprime la question.
    """
    depart = ligne.get("pnl_au_moment")
    seuil = ligne.get("seuil")
    if depart is None or seuil is None:
        return False
    return cumul > float(depart) + float(seuil)


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


def lignes_du_jour(destination_id: str) -> list[dict[str, Any]]:
    try:
        _init_schema()
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM plafond_arbitrage WHERE destination_id=? "
                "AND jour=? ORDER BY palier",
                (destination_id, _aujourdhui())).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"arbitrage: lignes illisibles ({e})")
        return []


def ouvrir_demande(destination_id: str, cumul: float, seuil: float,
                   palier: int | None = None) -> bool:
    """Ouvre une tranche d'arbitrage. True si une ligne a été créée.

    ⚠️ Le `palier` n'est plus DÉDUIT d'un calcul : c'est un simple numéro
    d'ordre dans la journée. Le déduire d'une division par le plafond le
    rendait sensible aux variations de capital — voir `couvre()`.
    """
    try:
        _init_schema()
        if palier is None:
            palier = len(lignes_du_jour(destination_id)) + 1
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

    Tout ce qui n'est pas un `CONTINUER` couvrant bloque — y compris une base
    illisible. C'est de l'argent réel : une panne de lecture ne peut pas valoir
    autorisation.

    L'ordre des quatre lectures n'est pas indifférent :

    1. un `GELER` explicite l'emporte sur tout — Xavier a tranché, on ne le
       redérange pas jusqu'à minuit ;
    2. un `CONTINUER` qui **couvre encore** la perte débloque ;
    3. une question déjà en attente bloque, sans en poser une seconde ;
    4. sinon la perte a franchi une tranche neuve : on ouvre, et on bloque.
    """
    if not franchi(cumul, seuil):  # pragma: no cover - appelant fautif
        return False

    lignes = lignes_du_jour(destination_id)

    if any(l.get("etat") == GELER for l in lignes):
        return True
    if any(l.get("etat") == CONTINUER and couvre(l, cumul) for l in lignes):
        return False
    if any(l.get("etat") == EN_ATTENTE for l in lignes):
        return True

    ouvrir_demande(destination_id, cumul, seuil)
    return True


def autorisation_couvrante(destination_id: str, cumul: float
                           ) -> dict[str, Any] | None:
    """L'autorisation en vigueur pour cette perte, ou ``None``.

    ⛔ Un `GELER` du jour l'emporte et rend ``None`` même si un `CONTINUER`
    plus ancien couvrait encore : Xavier a tranché dans l'autre sens depuis.
    Lire les lignes sans cet ordre laisserait une vieille autorisation
    survivre à un gel explicite.
    """
    lignes = lignes_du_jour(destination_id)
    if any(l.get("etat") == GELER for l in lignes):
        return None
    for l in lignes:
        if l.get("etat") == CONTINUER and couvre(l, cumul):
            return {
                "accorde_a": l.get("pnl_au_moment"),
                "couvre_jusqua": round(
                    float(l["pnl_au_moment"]) + float(l["seuil"]), 2),
                "repondu_le": l.get("repondu_le"),
            }
    return None


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


# ── À QUEL compte s'adresse la décision ───────────────────────────────────
#
# ⛔ Le défaut réparé le 06/09 : `repondre(decision)` était appelé sans
# destination. Un seul « continue » tapé sur Telegram débloquait donc TOUS les
# comptes en attente — y compris ceux dont Xavier n'avait pas lu la ligne.
# L'autorisation est censée être ANCRÉE et ne couvrir qu'une tranche ; elle
# couvrait en réalité tout le monde.
#
# 🔑 On résout le mot tapé contre les seules demandes EN ATTENTE. Pas besoin
# d'une table d'alias — donc pas de table qui dérive — et toute ambiguïté est
# décidable sur place.


def resoudre_cible(cible: str | None, decision: str
                   ) -> tuple[str | None, str | None]:
    """Rend ``(destination_id, refus)``.

    ``destination_id`` à ``None`` signifie « toutes les demandes en attente ».
    ``refus`` non nul signifie qu'on n'écrit RIEN et qu'on redemande.

    ⛔ Un « continue » nu quand PLUSIEURS comptes attendent est refusé : c'est
    la seule décision qui remet de l'argent réel en jeu, et rien ne dit que
    Xavier a vu les autres lignes. Un « gele » nu, lui, s'applique à tous —
    il va dans le sens qui protège.
    """
    comptes = sorted({d["destination_id"] for d in demandes_en_attente()})

    if cible:
        brut = cible.strip().lower().replace("-", "_")
        exacts = [c for c in comptes if c.lower() == brut]
        if exacts:
            return exacts[0], None
        # Tolérance utile : « live », « kraken », « ic_markets »… On ne
        # cherche QUE parmi les comptes en attente, donc jamais au hasard.
        proches = [c for c in comptes
                   if brut in c.lower()
                   or brut in c.lower().removeprefix("admin_")]
        if len(proches) == 1:
            return proches[0], None
        if not proches:
            return None, ("Compte inconnu : " + cible.strip() + "\n"
                          "En attente : " + (", ".join(comptes) or "aucun"))
        return None, ("Plusieurs comptes correspondent a « " + cible.strip()
                      + " » : " + ", ".join(proches) + "\n"
                        "Repondre avec le nom complet.")

    if len(comptes) <= 1 or decision == GELER:
        return None, None

    return None, ("Plusieurs comptes attendent une decision :\n"
                  + "\n".join("  " + c for c in comptes)
                  + "\n\nUn « continue » remet de l'argent reel en jeu : il "
                    "faut nommer le compte.\n"
                    "Exemple : continue " + comptes[0] + "\n\n"
                    "« gele » sans nom les bloque TOUS.")


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
    ]
    # ⛔ Quand PLUSIEURS comptes attendent, un « continue » nu est refuse : il
    # remettrait de l'argent reel en jeu sur des comptes dont la ligne n'a
    # peut-etre pas ete lue. On le dit AVANT, sinon le refus arrive par
    # surprise et se lit comme une panne.
    if len(demandes) > 1:
        lignes += [
            "",
            "PLUSIEURS comptes attendent : « continue » doit nommer lequel.",
            "  continue " + str(demandes[0]["destination_id"]),
            "« gele » sans nom les bloque TOUS.",
        ]
    lignes += [
        "",
        "Sans reponse, il reste bloque. Une nouvelle question sera posee si la",
        "perte franchit un plafond de plus.",
    ]
    return "\n".join(lignes)


def etat_en_vigueur() -> dict[str, dict[str, Any]]:
    """Ce qui est actuellement décidé, par compte réel dont le plafond est franchi.

    Sert uniquement à répondre juste : sans lui, quelqu'un dont la décision EST
    en vigueur s'entend dire « rien n'a été modifié », ce qui se lit comme
    « ça n'a pas marché ».
    """
    sortie: dict[str, dict[str, Any]] = {}
    try:
        from backend.services import trade_log_service as t
        for dest in t._destinations_reelles():
            cumul, limite = t._cumul_et_limite(dest)
            if cumul is None or cumul > limite:
                continue
            if any(l.get("etat") == GELER for l in lignes_du_jour(dest)):
                sortie[dest] = {"etat": GELER}
                continue
            accord = autorisation_couvrante(dest, cumul)
            if accord:
                sortie[dest] = {"etat": CONTINUER, **accord}
    except Exception as e:  # pragma: no cover - défensif
        logger.warning(f"arbitrage: état en vigueur illisible ({e})")
    return sortie


def confirmation(resultat: dict[str, Any]) -> str:
    if not resultat.get("applique"):
        # ⛔ Ne pas confondre « tu ne peux pas pré-autoriser » avec « c'est
        # déjà fait ». Le 04/09, Xavier a renvoyé « continue » après une
        # réponse déjà enregistrée et s'est entendu dire que rien n'avait été
        # modifié et qu'on ne pré-autorise pas : exact, et trompeur — son
        # compte était autorisé depuis 16:35. Un message juste sur le fond qui
        # laisse conclure l'inverse du vrai est un défaut, pas un détail.
        vigueur = etat_en_vigueur()
        if vigueur:
            lignes = ["Aucune demande en attente - ta decision est DEJA en "
                      "vigueur.", ""]
            for dest, v in sorted(vigueur.items()):
                if v.get("etat") == CONTINUER:
                    lignes.append(
                        f"  {dest} : AUTORISE a trader, couvre jusqu'a "
                        f"{v.get('couvre_jusqua')} EUR")
                else:
                    lignes.append(f"  {dest} : GELE jusqu'a minuit UTC")
            lignes += ["", "Rien a changer. La question reviendra au plafond "
                           "suivant."]
            return "\n".join(lignes)
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
