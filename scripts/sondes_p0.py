#!/usr/bin/env python3
"""Sondes P0 : detecter, ouvrir un ticket, REPARER, prouver, dire.

    python scripts/sondes_p0.py --essai    # detecte et DIT, ne repare rien
    python scripts/sondes_p0.py            # detecte, repare, prouve, previent
    python scripts/sondes_p0.py --bilan    # etat des tickets

Demande de Xavier le 2026-10-09 : des sondes sur trois priorites P0 -- les deux
regles de gestion des SL et l'ouverture de trades -- avec analyse complete
automatique, resolution sans intervention humaine, et un message Telegram a
l'ouverture du ticket d'anomalie puis a sa resolution.

## 🔑 CE QUI EST TENABLE, ET CE QUI NE L'EST PAS

TENABLE : reparer une ACTION QUI N'A PAS ABOUTI. C'est le cas de toutes les
pannes mesurees le 2026-10-09 -- un stop qui n'a pas bouge malgre son palier,
un ordre qui n'est pas parti, une sonde arretee, un script absent du conteneur,
une regle desarmee. La reparation consiste a REEMETTRE L'ACTION DECIDEE, puis a
PROUVER qu'elle a pris effet.

PAS TENABLE : reparer un DEFAUT DE CODE. Le defaut du 2026-10-09 -- une
validation qui se contredisait, `sl_dist = 0` puis refus de ce zero --
demandait d'ecrire du code, et le deployer DESARME REM-002 par conception. Ces
anomalies ESCALADENT avec leur diagnostic complet.

⛔ Pretendre le contraire serait la pire des promesses : une sonde qui dit
<< resolu >> sans l'etre laisse le defaut vivant ET endort la surveillance.

## ⛔ L'INVARIANT QUI NE SE NEGOCIE PAS

AUCUNE REMEDIATION NE DESSERRE UNE PORTE. Jamais. Reparer en elargissant un
plafond fabriquerait le resultat -- c'est la consigne la plus ancienne de ce
depot. Un test lit le catalogue entier pour l'epingler.

## 🔑 Et la reparation REEMET, elle ne DECIDE pas

Deplacer un stop ou relancer un cycle, ce n'est pas prendre une decision
nouvelle : c'est achever une decision deja prise sous la configuration que
Xavier a armee. Une sonde ne rearme jamais l'interrupteur, ne touche aucun
plafond, et ne place aucun ordre que les portes n'auraient pas autorise.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

logger = logging.getLogger("sondes_p0")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# Au-dela de deux echecs on passe la main : une reparation qui boucle est un
# harcelement, et elle peut AGGRAVER.
MAX_TENTATIVES = 2
# Fenetre d'observation de l'ouverture de trades.
FENETRE_OUVERTURE_MIN = int(os.environ.get("SONDES_P0_FENETRE_MIN", "20"))
COOLDOWN_SEC = int(os.environ.get("SONDES_P0_COOLDOWN_SEC", "900"))

# ⚠️ SEUIL D'ABSENCE DE RESULTAT. Les setups QUALIFIES arrivent ~33/jour, soit
# un toutes les ~25 min : un creux de 40 min est NORMAL. Le seuil est donc
# franchement au-dessus, sinon la sonde crierait a chaque respiration.
SEUIL_SANS_ORDRE_MIN = int(os.environ.get("SONDES_P0_SEUIL_MIN", "90"))

# 🔑 Les blocages dont la cause est CHEZ XAVIER. On ne les << repare >> pas :
# fermer ses positions a sa place serait inacceptable. On les lui REND, nommes.
_BLOCAGES_DE_XAVIER = {
    "bridge_marge_insuffisante", "bridge_plafond_risque",
    "max_positions_per_pair", "bridge_doublon", "bridge_position_sans_stop",
    "bridge_perte_journaliere",
}


def _db_path() -> str:
    from backend.services.mt5_sync import _db_path as p
    return p()


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _borne(minutes: float) -> str:
    """Borne basse d'une fenetre, en ISO AVEC fuseau — comme `created_at`.

    ⛔ PIEGE DEJA PAYE DANS CE DEPOT, et que j'ai rejoue ici. Comparer la
    colonne a une borne construite par la fonction `datetime` de SQLite NE
    FILTRE RIEN : la colonne vaut `2026-10-09T15:00:00+00:00` (avec `T` et
    fuseau) alors que cette fonction rend `2026-10-09 15:00:00`. La comparaison
    est LEXICOGRAPHIQUE, et `T` (0x54) > ` ` (0x20) : toutes les lignes passent.

    ⚠️ La formule fautive n'est PAS reproduite ici : le garde
    `test_fenetres_sqlite` scanne les lignes, et une docstring qui la cite le
    fait tomber. Mieux vaut reformuler que d'affaiblir un garde pour y loger
    ma prose.

    🔑 Je l'avais meme CONSTATE une heure plus tot sur un script jetable (des
    comptes << 15 min >> qui valaient la journee entiere) sans en tirer la
    lecon. C'est le garde `test_fenetres_sqlite` du depot qui l'a attrape.

    ⇒ On calcule la borne en Python, dans la MEME forme que la colonne, et on
    la passe en parametre.
    """
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ─── Le COMPTE des trades en live, en permanence ─────────────────────────
#
# Reproche de Xavier le 2026-10-09 : << il faut que tu aies constamment le
# nombre de trades en live >>. Il avait raison, et il visait juste : mes sondes
# verifiaient que les MECANISMES marchent, pas que le RESULTAT arrive.

def compter_live(positions: list[dict]) -> dict:
    """``{total, radar, main}`` des positions d'or ouvertes.

    🔑 LA SEPARATION EST LE POINT. Confondre les deux cacherait l'arret de
    l'automatique derriere l'activite de Xavier -- exactement la situation du
    2026-10-09 a 18h21 : DEUX positions live, et ZERO du radar.
    """
    from backend.services import echelle_stop_or as E

    total = radar = 0
    for p in positions or []:
        sym = str(p.get("symbol") or "").upper()
        if "XAU" not in sym and "GOLD" not in sym:
            continue
        total += 1
        if E.MARQUE_RADAR in str(p.get("comment") or ""):
            radar += 1
    return {"total": total, "radar": radar, "main": total - radar}


def inscrire_live(live: dict, ordres_60min: int) -> None:
    """Une TRACE, pas un instantane perdu : << constamment >> veut dire qu'on
    peut relire l'historique du compte."""
    try:
        with sqlite3.connect(_db_path()) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS trades_live_compte (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    vu_le        TEXT NOT NULL,
                    total        INTEGER NOT NULL,
                    radar        INTEGER NOT NULL,
                    main         INTEGER NOT NULL,
                    ordres_60min INTEGER
                )
            """)
            c.execute("INSERT INTO trades_live_compte (vu_le, total, radar, "
                      "main, ordres_60min) VALUES (?,?,?,?,?)",
                      (_maintenant(), int(live["total"]), int(live["radar"]),
                       int(live["main"]), int(ordres_60min)))
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : compte live non inscrit (%s)", e)


def minutes_depuis_dernier_ordre() -> float | None:
    """Depuis combien de minutes aucun ordre AUTO d'or n'est parti.

    ⛔ ``None`` si la base ne porte aucun ordre : on ne transforme pas une
    absence d'historique en alarme.
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            r = c.execute(
                "SELECT MAX(created_at) FROM personal_trades WHERE is_auto=1 "
                "AND pair='XAU/USD'").fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : dernier ordre illisible (%s)", e)
        return None
    if not r or not r[0]:
        return None
    age = _age(r[0])
    return (age / 60.0) if age is not None else None


# ─── Détection P0-1 : l'échelle de gains ─────────────────────────────────

def detecter_echelle(positions: list[dict], suivi: dict, taux: float) -> list[dict]:
    """Un palier a-t-il ete franchi sans que le stop bouge ?

    ⛔ LE DEFAUT EXACT DU 2026-10-09 : trois positions a +1,37 et +1,81 EUR,
    stop inchange, parce que `/position/sltp` rendait 400 a chaque passage.

    ⛔ FAIL-CLOSED SUR L'ABSENCE D'HISTOIRE : sans la sonde 5 s on ne sait pas
    si un palier a ete franchi. Inventer une anomalie serait aussi grave que
    d'en manquer une.
    """
    from backend.services import echelle_stop_or as E

    anos = []
    for p in positions or []:
        try:
            ticket = int(p.get("ticket"))
            if E.MARQUE_RADAR not in str(p.get("comment") or ""):
                continue        # l'echelle l'ignore par conception
            h = suivi.get(ticket)
            if not h:
                continue        # pas d'histoire : on ne conclut pas
            palier = h.get("palier_max_eur")
            if palier is None:
                continue        # aucun palier franchi
            sens = str(p.get("type") or "").lower()
            entree = float(p.get("price_open"))
            sl = float(p.get("sl") or 0)
            if not sl:
                continue
            du_cote_du_profit = (sl > entree) if sens == "buy" else (sl < entree)
            if du_cote_du_profit:
                continue        # la regle a fait son travail
            attendu = E.stop_vise(entree, sens, float(h.get("profit_max_eur") or 0),
                                  taux)
            anos.append({
                "sonde": "P0-1", "code": "stop_non_deplace_malgre_palier",
                "ticket": ticket, "reparable": True,
                "sl_attendu": attendu,
                "detail": (
                    f"palier {palier:+.2f} EUR franchi (max vu "
                    f"{float(h.get('profit_max_eur') or 0):+.2f} EUR sur "
                    f"{h.get('vu_n')} observations) et le stop est reste a "
                    f"{sl} — soit du cote de la PERTE (entree {entree}). "
                    f"Stop attendu : {attendu}"),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("P0-1 : position %s illisible (%s)",
                           p.get("ticket"), e)
    return anos


# ─── Détection P0-2 : la protection des pertes ───────────────────────────

def detecter_protection(positions: list[dict], suivi: dict, taux: float) -> list[dict]:
    """Une position eligible a-t-elle garde son stop large ?

    🔑 Et si la SONDE est muette, la regle est AVEUGLE : elle s'abstient en
    silence, donc la protection est MORTE sans que rien ne le dise. C'est une
    anomalie en soi, et elle est reparable.
    """
    import importlib.util
    chemin = "/app/scripts/protection_perte_or.py"
    if not os.path.exists(chemin):
        chemin = str((os.path.dirname(os.path.abspath(__file__))) +
                     "/protection_perte_or.py")
    spec = importlib.util.spec_from_file_location("_pp", chemin)
    PP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(PP)
    from backend.services import echelle_stop_or as E

    anos = []
    for p in positions or []:
        try:
            ticket = int(p.get("ticket"))
            if E.MARQUE_RADAR not in str(p.get("comment") or ""):
                continue
            sens = str(p.get("type") or "").lower()
            entree = float(p.get("price_open"))
            courant = float(p.get("price_current"))
            signe = 1 if sens == "buy" else -1
            perte = signe * (entree - courant) / taux
            if perte <= 0:
                continue        # domaine de l'echelle de GAINS

            h = suivi.get(ticket)
            if not h:
                # 🔑 La regle lit `negatif_depuis` chez la sonde. Sans sonde,
                # elle s'abstient -- donc la protection ne protege plus.
                anos.append({
                    "sonde": "P0-2", "code": "sonde_muette",
                    "ticket": ticket, "reparable": True,
                    "detail": (
                        f"la position {ticket} est a {-perte:+.2f} EUR et la "
                        "sonde 5 s n'a AUCUNE histoire pour elle : la regle de "
                        "protection s'abstient, donc elle ne protege plus."),
                })
                continue

            ok, _motif = PP.eligible(h.get("ouvert_depuis_sec"), perte,
                                     h.get("negatif_depuis_sec"))
            if not ok:
                continue
            vise = PP.stop_vise_prix(p, taux)
            if vise is None:
                continue        # deja au plancher : la regle s'est arretee
            anos.append({
                "sonde": "P0-2", "code": "stop_non_resserre_malgre_eligibilite",
                "ticket": ticket, "reparable": True, "sl_attendu": vise,
                "detail": (
                    f"perte {-perte:+.2f} EUR depuis "
                    f"{h.get('negatif_depuis_sec'):.0f} s, ouvert depuis "
                    f"{h.get('ouvert_depuis_sec'):.0f} s : le stop devrait "
                    f"etre a {vise} (distance "
                    f"{(signe * (entree - vise) / taux):.1f} EUR) et il est "
                    f"reste a {p.get('sl')}"),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("P0-2 : position %s illisible (%s)",
                           p.get("ticket"), e)
    return anos


# ─── Détection P0-3 : l'ouverture de trades ──────────────────────────────

# Les motifs de refus qui sont le TRI NORMAL des portes, et non une panne.
_REFUS_NORMAUX = {
    "pattern_not_allowed", "horizon_not_allowed", "chaine_non_armee",
    "below_confidence", "heure_spread_defavorable", "bridge_marge_insuffisante",
    "bridge_plafond_risque", "bridge_perte_journaliere", "max_positions_per_pair",
    "bridge_doublon", "price_divergence", "verdict_blocker", "pair_auto_paused",
    "fees_exceed_edge", "max_positions_per_pair_indecidable", "_not_admitted",
}


def detecter_ouverture(etat_interrupteur: dict, refus_recents: dict,
                       ordres_recents: int, setups_recents: int,
                       minutes_sans_ordre: float | None = None) -> list[dict]:
    """Des ordres partent-ils, et sinon : quelle porte refuse ?"""
    anos = []

    if (etat_interrupteur or {}).get("decision") != "ALLOW":
        # ⛔ NON REPARABLE : le rearmement est la DECISION DE XAVIER. Une sonde
        # qui rearmerait toute seule viderait le garde-fou de son sens.
        anos.append({
            "sonde": "P0-3", "code": "execution_desarmee", "ticket": None,
            "reparable": False,
            "detail": (
                f"interrupteur {etat_interrupteur.get('decision')} / "
                f"{etat_interrupteur.get('reason_code')} : AUCUN ordre ne "
                "partira. Le rearmement est ta decision — reponds-moi et je "
                "tape la commande sous ton nom."),
        })

    inconnus = {k: v for k, v in (refus_recents or {}).items()
                if k not in _REFUS_NORMAUX}
    for code, n in inconnus.items():
        # ⛔ NON REPARABLE : un motif qu'on ne sait pas nommer demande du code.
        anos.append({
            "sonde": "P0-3", "code": "refus_non_nomme", "ticket": None,
            "reparable": False,
            "detail": (
                f"{n} refus sous le motif generique {code!r} en "
                f"{FENETRE_OUVERTURE_MIN} min. Un motif range sous une "
                "etiquette generique est un motif qu'on ne verra jamais — "
                "c'est ainsi que 9 refus de marge sont restes invisibles le "
                "09/10. Il faut le NOMMER, donc du code."),
        })

    arme = (etat_interrupteur or {}).get("decision") == "ALLOW"

    if arme and ordres_recents == 0 and setups_recents > 0 and not refus_recents:
        anos.append({
            "sonde": "P0-3", "code": "aucun_ordre_malgre_setups", "ticket": None,
            "reparable": True,
            "detail": (
                f"{setups_recents} setup(s) en {FENETRE_OUVERTURE_MIN} min, "
                "interrupteur ARME, AUCUN refus enregistre et AUCUN ordre "
                "parti. Les setups n'atteignent donc meme pas les portes."),
        })

    # ⛔ L'ABSENCE PROLONGEE DE RESULTAT, ET C'EST LA CORRECTION DE MON DEFAUT
    # DE CONCEPTION (2026-10-09).
    #
    # Mes sondes verifiaient que les MECANISMES marchent, pas que le RESULTAT
    # arrive. L'ancienne condition portait `not refus_recents` : des que les
    # portes parlaient, la sonde se TAISAIT. Deux heures de refus a 100 % ne
    # disaient donc RIEN -- tout << fonctionnait >>, et rien ne sortait.
    #
    # 🔑 Reproche de Xavier, mot pour mot : << tu dois te demander par toi-meme
    # pourquoi je n'ai plus de trades de lances >>. Ce qui compte n'est pas que
    # les portes parlent, c'est COMBIEN DE TRADES SONT VIVANTS.
    #
    # ⚠️ On n'alerte PAS quand l'execution est desarmee : l'absence d'ordre en
    # DECOULE, et deux alertes pour une seule cause noieraient le fil.
    if arme and minutes_sans_ordre is not None \
            and minutes_sans_ordre >= SEUIL_SANS_ORDRE_MIN:
        dominant, n_dominant = (None, 0)
        if refus_recents:
            dominant, n_dominant = max(refus_recents.items(), key=lambda x: x[1])

        # 🔑 Le blocage dominant est NOMME : sans lui, << aucun trade >> n'est
        # pas actionnable. Le 09/10 la reponse etait << tes deux positions a la
        # main consomment la marge >>.
        if dominant is None:
            cause = ("AUCUN refus enregistre : le chemin d'analyse dort, il ne "
                     "produit meme pas de verdict")
            reparable = True
        elif dominant in _BLOCAGES_DE_XAVIER:
            cause = (f"blocage dominant `{dominant}` ({n_dominant} refus) — "
                     "la cause est de TON cote (positions ouvertes, marge, "
                     "risque engage, plafond). Je ne ferme pas tes positions a "
                     "ta place : c'est ton arbitrage")
            reparable = False
        else:
            cause = (f"blocage dominant `{dominant}` ({n_dominant} refus) — "
                     "le tri normal des portes. Si cela dure, c'est le reglage "
                     "qu'il faut revoir, pas une panne a reparer")
            reparable = False

        anos.append({
            "sonde": "P0-3", "code": "aucun_resultat_prolonge", "ticket": None,
            "reparable": reparable,
            "detail": (
                f"AUCUN ordre automatique d'or depuis {minutes_sans_ordre:.0f} "
                f"min (seuil {SEUIL_SANS_ORDRE_MIN} min), interrupteur ARME. "
                f"{cause}."),
        })
    return anos


# ─── Les remédiations, en catalogue DÉCLARÉ ──────────────────────────────
#
# ⛔ Chaque entree porte son action ET sa verification. Une reparation sans
# preuve ne vaut rien : c'est exactement ce qui endormirait la surveillance.
#
# ⛔ ET AUCUNE NE TOUCHE UN GARDE-FOU. Un test lit ce catalogue pour l'epingler.

def _reemettre_stop(ano: dict) -> dict:
    """Reemet le deplacement de stop que la regle avait decide."""
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    prix = ano.get("sl_attendu")
    if not prix:
        return {"ok": False, "error": "aucun stop attendu calcule"}
    r = httpx.post(f"{base}/position/sltp", headers={"X-API-Key": cle},
                   json={"ticket": int(ano["ticket"]), "sl_absolu": float(prix),
                         "deplacer": True}, timeout=12)
    try:
        return {"status": r.status_code, **r.json()}
    except Exception:  # noqa: BLE001
        return {"status": r.status_code, "brut": r.text[:200]}


def _verifier_stop(ano: dict) -> tuple[bool, str]:
    """Le stop a-t-il REELLEMENT bouge CHEZ LE COURTIER ?"""
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    r = httpx.get(base + "/positions", headers={"X-API-Key": cle}, timeout=8)
    for p in (r.json() or {}).get("positions") or []:
        if int(p.get("ticket") or 0) == int(ano["ticket"]):
            attendu = float(ano.get("sl_attendu") or 0)
            reel = float(p.get("sl") or 0)
            if abs(reel - attendu) < 0.5:
                return (True, f"sl verifie CHEZ LE COURTIER a {reel} "
                              f"(attendu {attendu})")
            return (False, f"sl toujours a {reel}, attendu {attendu}")
    return (True, "position fermee entre-temps : plus rien a proteger")


def _relancer_sonde(ano: dict) -> dict:
    import subprocess
    r = subprocess.run(["/opt/scalping/jobs/sonde_echelle_or.sh", "--une-passe"],
                       capture_output=True, text=True, timeout=120)
    return {"ok": r.returncode == 0, "sortie": (r.stdout or r.stderr)[-200:]}


def _verifier_sonde(ano: dict) -> tuple[bool, str]:
    with sqlite3.connect(_db_path()) as c:
        r = c.execute("SELECT vu_n, vu_dernier_a FROM echelle_or_suivi "
                      "WHERE ticket = ?", (int(ano["ticket"]),)).fetchone()
    if r:
        return (True, f"la sonde a repris : {r[0]} observations, derniere {r[1]}")
    return (False, "la sonde n'a toujours aucune histoire pour ce ticket")


def _relancer_cycle(ano: dict) -> dict:
    """Relance un cycle d'analyse RESTREINT a l'or.

    🔑 Cela ne DECIDE rien : le cycle repasse par les 13 portes a l'identique.
    On ne fait que reveiller un chemin qui dormait.
    """
    import asyncio
    from backend.services.scheduler import run_analysis_cycle
    paires = [p.strip() for p in os.getenv(
        "MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "XAU/USD").split(",") if p.strip()]
    asyncio.run(run_analysis_cycle(paires))
    return {"ok": True, "paires": paires}


def _verifier_cycle(ano: dict) -> tuple[bool, str]:
    """Un ordre est-il parti, OU une porte s'est-elle enfin prononcee ?

    🔑 Les deux comptent comme resolution : ce qu'on reparait est le SILENCE,
    pas l'absence d'ordre. Une porte qui refuse explicitement n'est pas une
    panne.
    """
    borne = _borne(3)
    with sqlite3.connect(_db_path()) as c:
        n_refus = c.execute(
            "SELECT COUNT(*) FROM signal_rejections WHERE pair='XAU/USD' "
            "AND created_at >= ?", (borne,)).fetchone()[0]
        n_ordres = c.execute(
            "SELECT COUNT(*) FROM personal_trades WHERE is_auto=1 "
            "AND pair='XAU/USD' AND created_at >= ?", (borne,)).fetchone()[0]
    if n_ordres:
        return (True, f"{n_ordres} ordre(s) parti(s) apres la relance")
    if n_refus:
        return (True, f"{n_refus} refus enregistre(s) : les portes se "
                      "prononcent de nouveau, le silence est leve")
    return (False, "toujours aucun refus ni ordre apres la relance")


def _rearmer_regle(ano: dict) -> dict:
    """Relance la regle de protection avec son drapeau, via le lanceur.

    ⚠️ Ce n'est PAS un desserrement : le drapeau arme une regle qui RESSERRE
    des stops, et il est deja pose dans la crontab par Xavier.
    """
    import subprocess
    env = {**os.environ, "PROTECTION_PERTE_OR": "1"}
    r = subprocess.run(["/opt/scalping/jobs/protection_perte_or.sh"],
                       capture_output=True, text=True, timeout=120, env=env)
    return {"ok": r.returncode == 0, "sortie": (r.stdout or r.stderr)[-200:]}


def _verifier_regle(ano: dict) -> tuple[bool, str]:
    chemin = "/var/log/scalping/protection_perte_or.log"
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            fin = f.read()[-1500:]
    except Exception as e:  # noqa: BLE001
        return (False, f"journal illisible ({e})")
    if "DESARMEE" in fin.split("\n")[-6:][0] if fin else False:
        return (False, "la regle se declare encore DESARMEE")
    return (True, "la regle a tourne armee")


REMEDIATIONS: dict[str, dict] = {
    "stop_non_deplace_malgre_palier": {
        "action_nom": "reemettre le deplacement de stop decide par l'echelle",
        "description": ("on repose le PRIX de stop que l'echelle avait calcule, "
                        "puis on relit la position chez le courtier pour "
                        "verifier que le stop a REELLEMENT bouge"),
        "action": _reemettre_stop, "verification": _verifier_stop,
    },
    "stop_non_resserre_malgre_eligibilite": {
        "action_nom": "reemettre le resserrement decide par la regle de perte",
        "description": ("on repose le PRIX de stop calcule par la regle, puis "
                        "on relit la position chez le courtier"),
        "action": _reemettre_stop, "verification": _verifier_stop,
    },
    "sonde_muette": {
        "action_nom": "relancer la sonde 5 s",
        "description": ("on relance une passe de la sonde, puis on verifie "
                        "qu'une histoire existe de nouveau pour ce ticket"),
        "action": _relancer_sonde, "verification": _verifier_sonde,
    },
    "aucun_ordre_malgre_setups": {
        "action_nom": "relancer un cycle d'analyse restreint",
        "description": ("on reveille le chemin d'analyse sur l'univers du "
                        "compte reel ; il repasse par les 13 portes a "
                        "l'identique, puis on verifie qu'un ordre est parti OU "
                        "qu'une porte s'est enfin prononcee"),
        "action": _relancer_cycle, "verification": _verifier_cycle,
    },
    "regle_desarmee": {
        "action_nom": "relancer la regle de protection avec son drapeau",
        "description": ("on relance le lanceur en lui passant le drapeau que "
                        "la crontab porte deja, puis on relit son journal"),
        "action": _rearmer_regle, "verification": _verifier_regle,
    },
}


# ─── Le cycle de vie du ticket ───────────────────────────────────────────

def _assurer_table(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS anomalies_sonde (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sonde      TEXT NOT NULL,
            code       TEXT NOT NULL,
            ticket     INTEGER,
            detail     TEXT,
            etat       TEXT NOT NULL DEFAULT 'OUVERT',
            ouvert_le  TEXT NOT NULL,
            resolu_le  TEXT,
            preuve     TEXT,
            tentatives INTEGER NOT NULL DEFAULT 0
        )
    """)


def ouvrir_ticket(ano: dict) -> int:
    """Ouvre un ticket, ou rend l'existant s'il est deja OUVERT.

    ⚠️ Sans cette idempotence, une anomalie persistante ouvrirait un ticket
    toutes les 5 min et noierait le fil Telegram — la lecon des 8 doublons du
    07/10. Une anomalie RESOLUE qui revient ouvre en revanche un NOUVEAU
    dossier : une recidive doit se voir.
    """
    with sqlite3.connect(_db_path()) as c:
        _assurer_table(c)
        r = c.execute(
            "SELECT id FROM anomalies_sonde WHERE code = ? "
            "AND COALESCE(ticket,-1) = ? AND etat IN ('OUVERT','ESCALADE') "
            "ORDER BY id DESC LIMIT 1",
            (ano["code"], int(ano.get("ticket") or -1))).fetchone()
        if r:
            return int(r[0])
        cur = c.execute(
            "INSERT INTO anomalies_sonde (sonde, code, ticket, detail, etat, "
            "ouvert_le) VALUES (?,?,?,?,'OUVERT',?)",
            (ano["sonde"], ano["code"], ano.get("ticket"), ano.get("detail"),
             _maintenant()))
        return int(cur.lastrowid)


def resoudre_ticket(tid: int, preuve: str) -> None:
    with sqlite3.connect(_db_path()) as c:
        _assurer_table(c)
        c.execute("UPDATE anomalies_sonde SET etat='RESOLU', resolu_le=?, "
                  "preuve=? WHERE id=?", (_maintenant(), preuve, int(tid)))


def echec_ticket(tid: int, raison: str) -> None:
    with sqlite3.connect(_db_path()) as c:
        _assurer_table(c)
        c.execute("UPDATE anomalies_sonde SET etat='ESCALADE', "
                  "tentatives = tentatives + 1, preuve = ? WHERE id=?",
                  (raison, int(tid)))


def doit_reessayer(tid: int) -> bool:
    """⛔ Au-dela de `MAX_TENTATIVES` on passe la main : une reparation qui
    boucle est un harcelement, et elle peut AGGRAVER."""
    with sqlite3.connect(_db_path()) as c:
        _assurer_table(c)
        r = c.execute("SELECT tentatives FROM anomalies_sonde WHERE id=?",
                      (int(tid),)).fetchone()
    return bool(r) and int(r[0]) < MAX_TENTATIVES


# ─── Telegram ────────────────────────────────────────────────────────────

def _prevenir(titre: str, corps: str, dedup: str) -> bool:
    """Poste sur le fil INFRA. ⚠️ `cooldown_seconds` est TRANSMIS : sans duree,
    la garde du relais est INERTE (lecon du 07/10)."""
    try:
        from backend.services.canaux_telegram import canal_pour, notifier
        return notifier(canal_pour(None), titre, corps, timeout=15,
                        dedup_key=dedup, cooldown_seconds=COOLDOWN_SEC)
    except Exception as e:  # noqa: BLE001 — un envoi rate ne casse pas la sonde
        logger.warning("sondes P0 : Telegram echoue (%s)", e)
        return False


def _corps_ouverture(tid: int, ano: dict) -> str:
    r = REMEDIATIONS.get(ano["code"])
    lignes = [
        f"**Ticket #{tid}** — sonde `{ano['sonde']}`",
        f"• Code : `{ano['code']}`",
    ]
    if ano.get("ticket"):
        lignes.append(f"• Position : `{ano['ticket']}`")
    lignes += ["", "**Ce qui est mesuré**", ano.get("detail") or "—", ""]
    if ano.get("reparable") and r:
        lignes += [
            "🔧 **Réparation automatique en cours**",
            f"• Action : {r['action_nom']}",
            f"• Comment : {r['description']}",
            "",
            "_Je te dis dans un instant si la preuve confirme._",
        ]
    else:
        lignes += [
            "⛔ **Pas de réparation automatique possible**",
            "",
            "Ce n'est pas une action qui a échoué, c'est un défaut qui demande "
            "du code — et le déployer désarmerait REM-002. **C'est ta "
            "décision.**",
        ]
    return "\n".join(lignes)


def _corps_resolution(tid: int, ano: dict, preuve: str) -> str:
    return "\n".join([
        f"**Ticket #{tid} RÉSOLU** — sonde `{ano['sonde']}`",
        f"• Code : `{ano['code']}`",
        f"• Position : `{ano.get('ticket') or '—'}`",
        "",
        "**Preuve**",
        preuve,
        "",
        "_Vérifié après l'action, pas supposé._",
    ])


def _corps_escalade(tid: int, ano: dict, raison: str) -> str:
    return "\n".join([
        f"🛑 **Ticket #{tid} ESCALADÉ** — sonde `{ano['sonde']}`",
        f"• Code : `{ano['code']}`",
        f"• Position : `{ano.get('ticket') or '—'}`",
        "",
        "**Ce qui est mesuré**",
        ano.get("detail") or "—",
        "",
        "**Pourquoi je ne l'ai pas résolu**",
        raison,
        "",
        # 🔑 Une escalade doit TOUJOURS nommer le decideur. Sans cette ligne,
        # le message dit << je n'ai pas pu >> sans dire a qui revient la suite
        # — et un ticket sans proprietaire est un ticket qui dort.
        "👤 **C'est ta décision**, pas la mienne : je ne réarme rien et je ne "
        "desserre aucune porte de moi-même.",
        "",
        "Réponds-moi et je m'en occupe avec toi.",
    ])


# ─── L'orchestration ─────────────────────────────────────────────────────

def traiter(anomalies: list[dict], a_blanc: bool = False) -> dict:
    """Ouvre, previent, repare, prouve, previent. Rend un bilan.

    ⛔ NE LEVE JAMAIS sur une anomalie : une anomalie qui explose ne doit pas
    condamner le traitement des autres — ce serait une panne qui en cache
    d'autres.
    """
    bilan = {"ouverts": 0, "resolus": 0, "escalades": 0, "a_blanc": a_blanc}
    for ano in anomalies or []:
        try:
            tid = ouvrir_ticket(ano)
            bilan["ouverts"] += 1
            if a_blanc:
                logger.info("sondes P0 [ESSAI] : ticket #%s %s — %s",
                            tid, ano["code"], ano.get("detail"))
                continue

            nouveau = _est_nouveau(tid)
            if nouveau:
                _prevenir(f"🔎 Anomalie de sonde — ticket #{tid}",
                          _corps_ouverture(tid, ano), f"sonde_p0_ouv_{tid}")

            r = REMEDIATIONS.get(ano["code"])
            if not ano.get("reparable") or not r:
                echec_ticket(tid, raison=(
                    "aucune reparation automatique : ce n'est pas une action "
                    "qui a echoue, c'est un defaut qui demande du code"))
                bilan["escalades"] += 1
                _prevenir(f"🛑 Ticket #{tid} escaladé",
                          _corps_escalade(tid, ano, (
                              "Pas d'action à réémettre : il faut écrire du "
                              "code, et le déployer désarmerait REM-002.")),
                          f"sonde_p0_esc_{tid}")
                continue

            if not doit_reessayer(tid):
                logger.info("sondes P0 : ticket #%s — %d tentatives atteintes, "
                            "on passe la main", tid, MAX_TENTATIVES)
                continue

            try:
                sortie = r["action"](ano)
            except Exception as e:  # noqa: BLE001
                echec_ticket(tid, raison=f"l'action a leve : {type(e).__name__}: {e}")
                bilan["escalades"] += 1
                _prevenir(f"🛑 Ticket #{tid} escaladé",
                          _corps_escalade(tid, ano, f"L'action a levé : {e}"),
                          f"sonde_p0_esc_{tid}")
                continue

            try:
                ok, preuve = r["verification"](ano)
            except Exception as e:  # noqa: BLE001
                ok, preuve = (False, f"verification impossible : {e}")

            if ok:
                resoudre_ticket(tid, preuve=preuve)
                bilan["resolus"] += 1
                _prevenir(f"✅ Ticket #{tid} résolu",
                          _corps_resolution(tid, ano, preuve),
                          f"sonde_p0_res_{tid}")
            else:
                echec_ticket(tid, raison=preuve)
                bilan["escalades"] += 1
                _prevenir(f"🛑 Ticket #{tid} escaladé",
                          _corps_escalade(tid, ano, preuve),
                          f"sonde_p0_esc_{tid}")
                logger.warning("sondes P0 : ticket #%s NON resolu — %s (sortie "
                               "de l'action : %s)", tid, preuve, str(sortie)[:200])
        except Exception as e:  # noqa: BLE001
            logger.warning("sondes P0 : anomalie %s non traitee (%s: %s)",
                           ano.get("code"), type(e).__name__, e)
    return bilan


def _est_nouveau(tid: int) -> bool:
    """Le ticket vient-il d'etre ouvert (donc jamais annonce) ?

    ⚠️ C'est ce qui empeche une anomalie PERSISTANTE de renvoyer un message
    toutes les 5 min — la lecon des 8 doublons du 07/10.
    """
    with sqlite3.connect(_db_path()) as c:
        _assurer_table(c)
        r = c.execute("SELECT tentatives, etat FROM anomalies_sonde WHERE id=?",
                      (int(tid),)).fetchone()
    return bool(r) and int(r[0]) == 0 and r[1] == "OUVERT"


# ─── La collecte, et le programme ────────────────────────────────────────

def _collecter() -> tuple[list[dict], dict, float, dict, dict, int, int]:
    """Tout ce que les sondes lisent. Rien n'est devine."""
    import httpx
    from backend.services import echelle_stop_boucle as B
    from backend.services import global_execution_switch as sw

    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    positions: list[dict] = []
    try:
        r = httpx.get(base + "/positions", headers={"X-API-Key": cle}, timeout=8)
        if r.status_code == 200:
            positions = (r.json() or {}).get("positions") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : /positions illisible (%s)", e)

    taux = 0.0
    try:
        taux = float(B._taux() or 0)
    except Exception:  # noqa: BLE001
        pass

    suivi: dict = {}
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            for x in c.execute(
                    "SELECT ticket, palier_max_eur, profit_max_eur, sl_au_max, "
                    "vu_n, negatif_depuis, ouvert_depuis FROM echelle_or_suivi"):
                d = dict(x)
                d["negatif_depuis_sec"] = _age(d.pop("negatif_depuis"))
                d["ouvert_depuis_sec"] = _age(d.pop("ouvert_depuis"))
                suivi[int(d["ticket"])] = d
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : suivi illisible (%s)", e)

    etat = {}
    try:
        etat = sw.status() or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : interrupteur illisible (%s)", e)

    refus, ordres, setups = {}, 0, 0
    try:
        borne = _borne(FENETRE_OUVERTURE_MIN)
        with sqlite3.connect(_db_path()) as c:
            for code, n in c.execute(
                    "SELECT reason_code, COUNT(*) FROM signal_rejections "
                    "WHERE pair='XAU/USD' AND destination_id='admin_live' "
                    "AND created_at >= ? GROUP BY reason_code", (borne,)):
                refus[code] = n
            ordres = c.execute(
                "SELECT COUNT(*) FROM personal_trades WHERE is_auto=1 "
                "AND pair='XAU/USD' AND created_at >= ?",
                (borne,)).fetchone()[0]
            setups = sum(refus.values()) + ordres
    except Exception as e:  # noqa: BLE001
        logger.warning("sondes P0 : journal des refus illisible (%s)", e)

    return (positions, suivi, taux, etat, refus, ordres, setups)


def _age(iso) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def _bilan_tickets() -> None:
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            _assurer_table(c)
            lignes = list(c.execute(
                "SELECT * FROM anomalies_sonde ORDER BY id DESC LIMIT 12"))
    except Exception as e:  # noqa: BLE001
        print(f"bilan illisible : {e}")
        return
    if not lignes:
        print("aucun ticket d'anomalie — les trois sondes P0 sont au vert")
        return
    for r in lignes:
        print(f"#{r['id']} [{r['etat']}] {r['sonde']} {r['code']} "
              f"ticket={r['ticket']}  ouvert {str(r['ouvert_le'])[11:19]}"
              f"{'  resolu ' + str(r['resolu_le'])[11:19] if r['resolu_le'] else ''}")
        if r["detail"]:
            print(f"    {r['detail'][:160]}")
        if r["preuve"]:
            print(f"    preuve : {r['preuve'][:160]}")


def main() -> int:
    if "--bilan" in sys.argv:
        _bilan_tickets()
        return 0
    a_blanc = "--essai" in sys.argv

    positions, suivi, taux, etat, refus, ordres, setups = _collecter()

    # 🔑 LE COMPTE, A CHAQUE PASSAGE ET QUOI QU'IL ARRIVE. C'est la demande
    # explicite de Xavier, et c'est aussi ce qui rend l'absence de resultat
    # relisible APRES coup plutot que devinee.
    live = compter_live(positions)
    sans_ordre = minutes_depuis_dernier_ordre()
    inscrire_live(live, ordres_60min=ordres)
    print(f"   trades LIVE : {live['total']} (radar {live['radar']}, "
          f"main {live['main']})  |  {ordres} ordre(s) auto en "
          f"{FENETRE_OUVERTURE_MIN} min"
          + (f"  |  dernier ordre il y a {sans_ordre:.0f} min"
             if sans_ordre is not None else "  |  aucun ordre en base"))
    if not taux:
        # ⛔ Sans le taux, les deux sondes de SL sont inconvertibles. On ne
        # devine pas, et on le DIT.
        logger.warning("sondes P0 : taux EUR/USD illisible — sondes de SL "
                       "suspendues ce passage")
        anos = detecter_ouverture(etat, refus, ordres, setups, sans_ordre)
    else:
        anos = (detecter_echelle(positions, suivi, taux)
                + detecter_protection(positions, suivi, taux)
                + detecter_ouverture(etat, refus, ordres, setups, sans_ordre))

    b = traiter(anos, a_blanc=a_blanc)
    print(f"sondes P0{' [ESSAI]' if a_blanc else ''} : {len(anos)} anomalie(s) "
          f"— {b['ouverts']} ticket(s), {b['resolus']} resolu(s), "
          f"{b['escalades']} escalade(s)")
    for a in anos:
        print(f"   [{a['sonde']}] {a['code']} ticket={a.get('ticket')} "
              f"reparable={a.get('reparable')}")
        print(f"      {a.get('detail')}")
    if not anos:
        print("   les trois sondes P0 sont au vert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
