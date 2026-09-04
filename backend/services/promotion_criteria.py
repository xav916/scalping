"""Critère de promotion démo → réel, déclaré AVANT la mesure (2026-09-04).

Répond à une demande précise : ouvrir un instrument sur la démo, le mesurer,
et ne le passer sur le compte réel que si ça tient la route.

⛔ **« Ça tient la route » ne veut PAS dire « c'est rentable ».** La rentabilité
d'une paire n'est pas mesurable ici, et ce module refuse de faire semblant.

Mesuré le 2026-09-04 sur 90 jours de démo :

    XAU/USD  16 trades/mois        USD/JPY   2/mois
    WTI/USD  12 trades/mois        XAG/USD   1/mois

Distinguer un edge de +0,15 R du pur hasard demande ~700 trades (95 % de
confiance, 80 % de puissance, sigma 1 R). Soit **44 mois sur la meilleure
paire**, 29 ans sur la moins active. Le système a déjà payé pour l'apprendre :
DSR 0,35, PBO 0,579, une « gagnante » qui tenait à 3 trades sur 233.

🔑 **Ce que trois semaines de démo peuvent trancher, et c'est beaucoup :**

    1. MÉCANIQUE  l'ordre part, le symbole est mappé, le stop est réellement
                  posé chez le courtier            (~20 poussées, 3-5 jours)
    2. COÛT       le spread et le slippage laissent-ils quelque chose
                                                    (~40 clôtures, 2-4 sem.)
    3. INCIDENTS  aucune position nue, aucun stop non appliqué

Ces trois portes DÉCIDENT. La rentabilité est calculée et rapportée, avec le N
qu'il faudrait pour en dire quoi que ce soit — pour que personne ne la lise
comme un verdict.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

# ─── Seuils, tous DÉCLARÉS ICI et justifiés ──────────────────────────────

# Poussées minimales avant de juger la mécanique. En dessous, un seul refus
# ferait basculer le taux d'acceptation ; au-dessus, 3-5 jours suffisent.
MIN_POUSSEES = 20

# Clôtures minimales avant de juger le coût. Le coût se lit sur une MÉDIANE :
# 40 valeurs la rendent stable sans attendre des mois.
MIN_CLOTURES = 40

# Un ordre sur vingt refusé par le courtier reste du bruit d'exécution ; au-delà
# c'est un problème de symbole, de volume ou de spécification.
TAUX_ACCEPTATION_MIN = 0.95

# ⛔ ZÉRO toléré. Une position nue sur le réel a coûté −230 € le 2026-08-24, et
# c'est le seul défaut de cette liste qui peut vider un compte.
STOPS_NON_APPLIQUES_MAX = 0

# Coût aller-retour du modèle MT5, calibré le 2026-08-06 sur 1 361 trades :
# 0,005 % par jambe reproduit les 0,022 R observés à la distance au stop
# médiane (0,380 % du prix).
TAUX_COUT_PAR_JAMBE = 0.00005

# L'espérance absolue mesurée de la route MT5 depuis juin. Le coût d'un
# candidat se juge PAR RAPPORT à elle : un instrument dont les frais mangent
# une trop grosse part n'a plus de quoi payer son propre bruit.
EDGE_ROUTE_R = 0.1056

# 30 % : la route existante tourne à 20,8 % et fonctionne ; à 124 % elle était
# bloquée. La ligne est posée entre les deux, du côté prudent.
PART_MAX_DU_COUT = 0.30

# Paramètres du calcul de puissance qui dit combien de trades il FAUDRAIT.
EDGE_A_DETECTER_R = 0.15
SIGMA_R = 1.0
_Z = 1.96 + 0.84  # 95 % de confiance, 80 % de puissance

EN_ATTENTE, OK, ECHEC = "EN_ATTENTE", "OK", "ECHEC"


def _conn() -> sqlite3.Connection:
    from backend.services.trade_log_service import _DB_PATH
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def trades_requis(edge_R: float = EDGE_A_DETECTER_R) -> int:
    """Combien de clôtures pour distinguer ``edge_R`` du hasard.

    Rendu public parce que c'est le chiffre qui désamorce la tentation : tant
    qu'on ne l'affiche pas à côté du PnL, quelqu'un finira par lire « +8 € sur
    25 trades » comme une preuve.
    """
    if edge_R <= 0:
        return 0
    return math.ceil(2 * SIGMA_R ** 2 * _Z ** 2 / edge_R ** 2)


def _porte_mecanique(poussees: list[sqlite3.Row]) -> dict[str, Any]:
    """L'ordre part-il, et le stop est-il réellement posé CHEZ LE COURTIER ?

    ⚠️ On lit `sl_applied` dans la réponse du bridge, pas `stop_loss` dans nos
    tables : notre base dit ce qu'on a DEMANDÉ, la réponse dit ce qui a été
    OBTENU. Les deux ont déjà divergé — 44 % des SL/TP stockés ne
    correspondaient pas à ceux du courtier (2026-08-25).
    """
    n = len(poussees)
    if n < MIN_POUSSEES:
        return {"verdict": EN_ATTENTE, "n": n, "requis": MIN_POUSSEES}

    acceptes = sum(1 for p in poussees if p["ok"])
    sans_stop, instrumentees, erreurs = 0, 0, []
    for p in poussees:
        if not p["ok"]:
            continue
        try:
            corps = json.loads(p["bridge_response"] or "{}")
        except (ValueError, TypeError):
            erreurs.append("reponse illisible")
            continue
        # ⛔ L'ABSENCE DE TRACE N'EST PAS L'ABSENCE DU STOP.
        #
        # `sl_applied` n'existe dans les reponses du bridge que depuis le
        # 2026-08-06. Une premiere version lisait « champ absent » comme
        # « stop non pose » et condamnait ainsi WTI/USD (0 poussee
        # instrumentee sur 54) et XAU/USD (12 sur 63) — deux paires saines,
        # dont une qui trade sur le compte reel.
        #
        # Seul un `false` EXPLICITE compte comme un manquement. Le reste est
        # non mesurable, et se dit.
        if "sl_applied" in corps:
            instrumentees += 1
            if corps["sl_applied"] is False:
                sans_stop += 1
        for cle in ("sl_error", "tp_error"):
            if corps.get(cle):
                erreurs.append(f"{cle}={corps[cle]}")

    taux = acceptes / n
    details = {"n": n, "taux_acceptation": round(taux, 3),
               "poussees_instrumentees": instrumentees,
               "stops_non_appliques": sans_stop, "erreurs": erreurs[:5]}

    # ⛔ L'ORDRE COMPTE. Le taux d'acceptation se lit sur `ok`, colonne qui a
    # toujours existe : il est mesurable meme quand la trace du stop manque.
    # L'evaluer APRES la porte d'instrumentation laissait passer un symbole
    # mal mappe (40 % de refus) sous l'etiquette « non mesurable ».
    #
    # 🔑 Un echec sur une dimension MESURABLE prime sur un « pas encore
    # mesurable » ailleurs.
    motifs = []
    if taux < TAUX_ACCEPTATION_MIN:
        motifs.append(f"acceptation {taux:.0%} < {TAUX_ACCEPTATION_MIN:.0%}")
    if erreurs:
        motifs.append(f"{len(erreurs)} erreur(s) SL/TP")
    if sans_stop > STOPS_NON_APPLIQUES_MAX:
        motifs.append(f"{sans_stop} ordre(s) sans stop chez le courtier")
    if motifs:
        details["verdict"] = ECHEC
        details["motifs"] = motifs
        return details

    # Rien de fautif dans ce qui est mesurable. Reste a savoir si le stop a pu
    # etre verifie : trop peu de poussees instrumentees, on ne conclut pas.
    # Le temps reglera ce cas seul, chaque nouvelle poussee portant la trace.
    if instrumentees < MIN_POUSSEES:
        details["verdict"] = EN_ATTENTE
        details["requis"] = MIN_POUSSEES
        details["motifs"] = [
            f"seulement {instrumentees}/{n} poussee(s) portent la trace du "
            f"stop (champ pose le 2026-08-06) — non mesurable"]
        return details

    details["verdict"] = OK
    details["motifs"] = []
    return details


def _porte_cout(trades: list[sqlite3.Row]) -> dict[str, Any]:
    """Le spread et le slippage laissent-ils de quoi travailler ?

    Le coût se mesure **en R**, donc relativement à la distance au stop — pas
    en pourcentage du prix. C'est ce rapport qui a tué le 5 min et les frais
    Kraken à 2,6× l'edge : le même spread est indolore sur un stop large et
    prohibitif sur un stop serré.
    """
    couts = []
    for t in trades:
        entree, stop = t["entry_price"], t["stop_loss"]
        if not entree or not stop:
            continue
        distance = abs(float(entree) - float(stop))
        if distance <= 0:
            continue
        couts.append(2 * TAUX_COUT_PAR_JAMBE * float(entree) / distance)

    n = len(couts)
    if n < MIN_CLOTURES:
        return {"verdict": EN_ATTENTE, "n": n, "requis": MIN_CLOTURES}

    couts.sort()
    median = couts[n // 2]
    part = median / EDGE_ROUTE_R if EDGE_ROUTE_R else float("inf")
    verdict = ECHEC if part > PART_MAX_DU_COUT else OK
    return {"verdict": verdict, "n": n,
            "cout_median_R": round(median, 4),
            "part_de_l_edge": round(part, 3),
            "plafond": PART_MAX_DU_COUT,
            "motifs": ([f"les frais mangent {part:.0%} de l'edge de la route "
                        f"(plafond {PART_MAX_DU_COUT:.0%})"] if verdict == ECHEC else [])}


def _porte_incidents(trades: list[sqlite3.Row]) -> dict[str, Any]:
    """Aucune position nue, aucun stop manquant à l'ouverture."""
    n = len(trades)
    if n < MIN_CLOTURES:
        return {"verdict": EN_ATTENTE, "n": n, "requis": MIN_CLOTURES}
    nues = sum(1 for t in trades if not t["stop_loss"])
    verdict = ECHEC if nues > 0 else OK
    return {"verdict": verdict, "n": n, "positions_sans_stop": nues,
            "motifs": ([f"{nues} position(s) ouverte(s) sans stop"] if nues else [])}


def evaluer_candidat(pair: str, destination: str = "admin_legacy",
                     fenetre_jours: int = 90) -> dict[str, Any]:
    """Verdict de promotion pour ``pair`` sur ``destination``.

    ``PROMOUVOIR`` / ``REFUSER`` / ``EN_ATTENTE``. Le verdict ne dépend QUE des
    trois portes ; la rentabilité l'accompagne sans jamais le décider.
    """
    with _conn() as c:
        poussees = c.execute(
            "SELECT ok, bridge_response FROM mt5_pushes "
            "WHERE pair = ? AND destination_id = ? "
            "AND pushed_at >= date('now', ?)",
            (pair, destination, f"-{fenetre_jours} days"),
        ).fetchall()
        trades = c.execute(
            "SELECT pnl, entry_price, stop_loss, slippage_pips FROM personal_trades "
            "WHERE pair = ? AND destination_id = ? AND status = 'CLOSED' "
            "AND created_at >= date('now', ?)",
            (pair, destination, f"-{fenetre_jours} days"),
        ).fetchall()

    portes = {
        "mecanique": _porte_mecanique(poussees),
        "cout": _porte_cout(trades),
        "incidents": _porte_incidents(trades),
    }

    verdicts = [p["verdict"] for p in portes.values()]
    if ECHEC in verdicts:
        verdict = "REFUSER"
    elif EN_ATTENTE in verdicts:
        verdict = "EN_ATTENTE"
    else:
        verdict = "PROMOUVOIR"

    # ⛔ Calculée, rapportée, JAMAIS déterminante — et toujours accompagnée du
    # N qu'il faudrait. Sans ce chiffre à côté, « +8 € sur 25 trades » finit
    # par se lire comme une preuve.
    pnls = [float(t["pnl"] or 0) for t in trades]
    requis = trades_requis()
    rentabilite = {
        "pnl_total": round(sum(pnls), 2),
        "n": len(pnls),
        "n_requis": requis,
        "edge_teste_R": EDGE_A_DETECTER_R,
        "decidable": len(pnls) >= requis,
        "note": ("Indécidable à ce N — la rentabilité n'entre PAS dans le "
                 "verdict, par construction."),
    }

    return {
        "pair": pair,
        "destination": destination,
        "fenetre_jours": fenetre_jours,
        "n_poussees": len(poussees),
        "n_clotures": len(trades),
        "portes": portes,
        "verdict": verdict,
        "rentabilite": rentabilite,
    }


# ─── Bulletin hebdomadaire ───────────────────────────────────────────────

def _ce_qui_manque(r: dict[str, Any]) -> str:
    """Le compte a rebours, pas juste l'etiquette.

    « EN_ATTENTE » seul n'apprend rien et devient un bruit hebdomadaire de
    plus. Ce qui rend le bulletin utile, c'est de savoir COMBIEN il reste —
    et donc quand la reponse tombera.
    """
    # ⚠️ Regroupe PAR UNITE, jamais par porte. Les portes « cout » et
    # « incidents » reclament toutes deux des CLOTURES : les lister
    # separement produisait « manque 37 cloturees et 37 cloturees », vu dans
    # le premier bulletin envoye en vrai. Le manque est le MEME.
    restes: dict[str, int] = {}
    for nom, porte in r["portes"].items():
        if porte["verdict"] != EN_ATTENTE:
            continue
        requis = porte.get("requis")
        if requis is None:
            continue
        # La mecanique compte des POUSSEES instrumentees, les deux autres des
        # CLOTURES : annoncer le mauvais reste serait pire que se taire.
        if nom == "mecanique":
            acquis = porte.get("poussees_instrumentees", porte.get("n", 0))
            unite = "poussees tracees"
        else:
            acquis, unite = porte.get("n", 0), "cloturees"
        if acquis < requis:
            # Le plus exigeant l'emporte : sinon on annoncerait une echeance
            # plus proche que la realite.
            restes[unite] = max(restes.get(unite, 0), requis - acquis)
    if not restes:
        return "en cours"
    return " et ".join(f"{n} {u}" for u, n in restes.items())


def bulletin_hebdomadaire(paires: list[str],
                          destination: str = "admin_legacy") -> str:
    """Texte du bulletin, SANS effet de bord — donc testable sans reseau.

    ⚠️ Texte simple, sans `<` ni `>` : `send_sales_text` poste en HTML et
    Telegram refuse le message ENTIER sur une balise mal formee. L'echec
    serait silencieux.
    """
    groupes: dict[str, list[str]] = {"PROMOUVOIR": [], "REFUSER": [], "EN_ATTENTE": []}
    requis_rentabilite = trades_requis()

    for pair in sorted(paires):
        r = evaluer_candidat(pair, destination)
        n = r["n_clotures"]
        if r["verdict"] == "PROMOUVOIR":
            groupes["PROMOUVOIR"].append(f"• {pair} — {n} cloturees, les 3 portes OK")
        elif r["verdict"] == "REFUSER":
            motifs = [m for p in r["portes"].values() for m in p.get("motifs", [])]
            groupes["REFUSER"].append(f"• {pair} — {motifs[0] if motifs else 'porte non franchie'}")
        else:
            groupes["EN_ATTENTE"].append(f"• {pair} — {n} cloturees, manque {_ce_qui_manque(r)}")

    lignes = ["BANC D'ESSAI DEMO — bulletin hebdomadaire", ""]
    if groupes["PROMOUVOIR"]:
        lignes += [f"PRETES POUR LE REEL ({len(groupes['PROMOUVOIR'])})"]
        lignes += groupes["PROMOUVOIR"]
        lignes += ["", "  Pour promouvoir : ajouter la paire a",
                   "  MT5_BRIDGE_LIVE_WHITELIST_PAIRS", ""]
    if groupes["REFUSER"]:
        lignes += [f"REFUSEES ({len(groupes['REFUSER'])})"] + groupes["REFUSER"] + [""]
    if groupes["EN_ATTENTE"]:
        lignes += [f"EN COURS ({len(groupes['EN_ATTENTE'])})"] + groupes["EN_ATTENTE"] + [""]
    if not any(groupes.values()):
        lignes += ["Aucune paire a evaluer.", ""]

    # ⛔ Le garde-fou voyage AVEC le message. Un lecteur qui voit
    # « PRETE POUR LE REEL » et un PnL sur la meme page fera le lien tout seul
    # si rien ne l'en dissuade — et c'est exactement ainsi qu'on promeut du
    # bruit.
    lignes += [
        "Ce verdict porte sur la MECANIQUE et le COUT : l'ordre part, le stop",
        "est pose chez le courtier, les frais laissent de quoi travailler.",
        f"Il ne dit RIEN de la rentabilite : il faudrait {requis_rentabilite} cloturees",
        "par paire pour la mesurer, contre ~12 par mois disponibles.",
    ]
    return "\n".join(lignes)


async def envoyer_bulletin_hebdomadaire() -> bool:
    """Job scheduler : construit le bulletin et l'envoie sur le fil sales.

    ⚠️ Le retour de l'envoi est JOURNALISE. Prouver qu'un message part ne
    prouve pas qu'il arrive — le moniteur muet de juin l'a montre, et la
    sauvegarde cassee cinq nuits l'a confirme dans l'autre sens.
    """
    import os

    from backend.services import telegram_service

    paires = [p.strip() for p in
              os.getenv("MT5_BRIDGE_LEGACY_WHITELIST_PAIRS", "").split(",")
              if p.strip()]
    try:
        texte = bulletin_hebdomadaire(paires)
    except Exception:
        logger.exception("bulletin promotion: construction impossible")
        return False

    envoye = await telegram_service.send_sales_text(texte, parse_mode=None)
    logger.info("bulletin promotion: %d paire(s) evaluee(s), envoye=%s",
                len(paires), envoye)
    return bool(envoye)
