"""Le réajustement automatique de l'or : ce que le laboratoire peut décider seul.

Demandé par Xavier le 2026-09-08, en suite du [[laboratoire_or]].

## ⛔ Les trois choses qu'il ne peut PAS faire

1. **Ouvrir un motif qu'un humain n'a pas ouvert.** Le mécanisme ne sait que
   RESSERRER. « Ne jamais desserrer les portes » n'est pas négociable, et un
   automate qui peut s'accorder des permissions n'a plus de garde-fou.
2. **Rouvrir ce qu'il n'a pas fermé lui-même.** Il défait ses propres décisions,
   jamais celles d'un humain.
3. **Décider sur une seule nuit.** Un `t` qui oscille autour du seuil ferait
   battre la porte tous les soirs. Il faut `NUITS_CONSECUTIVES` verdicts
   identiques.

## Ce qu'il fait

Chaque nuit, il enregistre les cellules mesurées, puis :

- une cellule **RÉFUTÉE** `NUITS_CONSECUTIVES` nuits d'affilée est **fermée** ;
- une cellule **RETENUE** `NUITS_CONSECUTIVES` nuits d'affilée, et fermée PAR
  LUI, est **rouverte**.

Une cellule est réfutée quand elle perd de l'argent avec un `|t|` **au-dessus du
plafond du hasard** calculé pour le nombre de combinaisons examinées — et
qu'elle fait moins bien que des entrées au hasard. Cf. `laboratoire_or`.

## ⚠️ Le garde-fou qui compte

Il ne fermera jamais au point de laisser un horizon sans motif. Un mécanisme
qui éteint tout en silence, c'est l'incident du kill-switch oublié — celui que
ce projet cite depuis le 2026-07-13. Quand il refuse de fermer pour cette
raison, **il le dit**.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from backend.services import laboratoire_or as labo

logger = logging.getLogger(__name__)

PAIRE = "XAU/USD"

# Combien de nuits de suite un verdict doit tenir avant d'agir.
NUITS_CONSECUTIVES = int(os.getenv("REGLAGE_OR_NUITS", "3"))

# ⛔ Il restera toujours au moins ce nombre de motifs par horizon. Un mécanisme
# qui éteint tout en silence est le mode de défaillance du kill-switch oublié.
MOTIFS_MINIMUM_PAR_HORIZON = int(os.getenv("REGLAGE_OR_MOTIFS_MINIMUM", "3"))

# Interrupteur. ⚠️ À `0`, il mesure et propose mais n'applique RIEN.
ARME = os.getenv("REGLAGE_OR_ARME", "1") not in ("0", "false", "False")

FERMER = "fermer"
ROUVRIR = "rouvrir"
REFUSE_PLANCHER = "refuse_plancher"


def _db() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _maintenant() -> str:
    # ⛔ Avec un ESPACE, jamais le `T` de l'ISO : les fenêtres SQLite comparent
    # des chaînes, et `T` (0x54) > espace (0x20) fait qu'un `>= datetime(...)`
    # ne filtre plus rien. Ce piège a coûté six fenêtres dans ce dépôt.
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _schema(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS labo_or_cellules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mesure_le TEXT NOT NULL, pair TEXT NOT NULL, horizon TEXT NOT NULL,
        motif TEXT NOT NULL, sens TEXT NOT NULL, n INTEGER NOT NULL,
        r_moyen REAL, t REAL, delta_hasard REAL, plafond REAL,
        verdict TEXT NOT NULL)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_labo_or_cellules
        ON labo_or_cellules(pair, horizon, motif, mesure_le)""")
    c.execute("""CREATE TABLE IF NOT EXISTS labo_or_fermetures (
        pair TEXT NOT NULL, horizon TEXT NOT NULL, motif TEXT NOT NULL,
        sens TEXT, ferme_le TEXT NOT NULL, preuve TEXT,
        PRIMARY KEY (pair, horizon, motif))""")
    c.execute("""CREATE TABLE IF NOT EXISTS labo_or_journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decide_le TEXT NOT NULL, action TEXT NOT NULL, pair TEXT NOT NULL,
        horizon TEXT NOT NULL, motif TEXT NOT NULL, motif_decision TEXT)""")


# ─────────────────────────────────────────────────────────────────────
# Enregistrer
# ─────────────────────────────────────────────────────────────────────

def enregistrer(mesure: dict) -> int:
    """Range les cellules de la nuit. Rend le nombre de lignes écrites."""
    cellules = mesure.get("cellules") or []
    if not cellules:
        return 0
    quand = _maintenant()
    pair = mesure.get("pair") or PAIRE
    with sqlite3.connect(_db()) as c:
        _schema(c)
        c.executemany(
            """INSERT INTO labo_or_cellules
               (mesure_le, pair, horizon, motif, sens, n, r_moyen, t,
                delta_hasard, plafond, verdict)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(quand, pair, x["horizon"], x["motif"], x["sens"], x["n"],
              x["r_moyen"], x["t"], x.get("delta_hasard"), x.get("plafond"),
              x["verdict"]) for x in cellules])
    return len(cellules)


def _dernieres_nuits(pair: str, combien: int) -> dict[tuple[str, str], list[str]]:
    """Les `combien` derniers verdicts QUOTIDIENS de chaque (horizon, motif),
    du plus récent au plus ancien.

    ⛔ Une nuit = un JOUR, pas un horodatage. Ma première version comptait les
    valeurs distinctes de `mesure_le` : trois lancements dans la même soirée
    auraient alors valu « trois nuits de suite », et une seule séance de mesure
    aurait suffi à fermer un motif. C'est tout le garde-fou qui sautait.

    ⚠️ Quand un jour porte plusieurs passages, on retient le DERNIER — le plus
    informé. C'est aussi pour ça que `_maintenant()` sépare par un espace :
    `date()` de SQLite ne sait pas lire un `T`.
    """
    with sqlite3.connect(_db()) as c:
        _schema(c)
        jours = [r[0] for r in c.execute(
            "SELECT DISTINCT date(mesure_le) FROM labo_or_cellules "
            "WHERE pair = ? ORDER BY 1 DESC LIMIT ?", (pair, combien))]
        if not jours:
            return {}
        marques = ",".join("?" * len(jours))
        lignes = c.execute(
            f"""SELECT horizon, motif, verdict FROM labo_or_cellules c
                WHERE c.pair = ? AND date(c.mesure_le) IN ({marques})
                  AND c.mesure_le = (SELECT MAX(c2.mesure_le)
                                     FROM labo_or_cellules c2
                                     WHERE c2.pair = c.pair
                                       AND c2.horizon = c.horizon
                                       AND c2.motif = c.motif
                                       AND date(c2.mesure_le) = date(c.mesure_le))
                ORDER BY c.mesure_le DESC""", (pair, *jours)).fetchall()
    out: dict[tuple[str, str], list[str]] = {}
    for horizon, motif, verdict in lignes:
        out.setdefault((horizon, motif), []).append(verdict)
    return out


# ─────────────────────────────────────────────────────────────────────
# Décider
# ─────────────────────────────────────────────────────────────────────

# ⚠️ Cette lecture est sur le chemin de CHAQUE décision de push. Un aller-retour
# SQLite par setup serait absurde ; un cache figé rendrait la décision nocturne
# invisible jusqu'au redémarrage. 60 s tranche les deux.
_CACHE_S = float(os.getenv("REGLAGE_OR_CACHE_S", "60"))
_cache: dict[str, tuple[float, set]] = {}


def fermetures(pair: str = PAIRE, frais: bool = False) -> set[tuple[str, str]]:
    """Les (horizon, motif) que le laboratoire a fermés. Lu à CHAUD.

    ⛔ En base, pas dans le `.env` : une décision nocturne qui exigerait un
    redéploiement pour s'appliquer ne s'appliquerait pas.
    """
    import time as _time
    entree = _cache.get(pair)
    if entree and not frais and _time.monotonic() - entree[0] < _CACHE_S:
        return entree[1]
    try:
        with sqlite3.connect(_db()) as c:
            _schema(c)
            trouve = {(h, m) for h, m in c.execute(
                "SELECT horizon, motif FROM labo_or_fermetures WHERE pair = ?",
                (pair,))}
        _cache[pair] = (_time.monotonic(), trouve)
        return trouve
    except Exception as e:  # noqa: BLE001
        # ⛔ fail-OUVERT assumé : une base illisible ne doit pas fermer des
        # motifs par accident. L'inverse fermerait tout sur une erreur d'I/O.
        logger.warning("reglage_or: fermetures illisibles (%s) — aucune appliquée", e)
        return set()


def _motifs_ouverts_a(horizon: str, mesure: dict, fermes: set) -> int:
    """Combien de motifs restent servis sur cet horizon, fermetures déduites."""
    tous = {c["motif"] for c in (mesure.get("cellules") or [])
            if c["horizon"] == horizon}
    return len(tous - {m for h, m in fermes if h == horizon})


def decider(mesure: dict, pair: str = PAIRE) -> list[dict]:
    """Applique ce que les dernières nuits autorisent. Rend les actions.

    ⚠️ À appeler APRÈS `enregistrer(mesure)` : la nuit du jour compte.
    """
    historique = _dernieres_nuits(pair, NUITS_CONSECUTIVES)
    fermes = fermetures(pair)
    par_cle = {(c["horizon"], c["motif"]): c
               for c in (mesure.get("cellules") or [])}
    actions: list[dict] = []

    for cle, verdicts in sorted(historique.items()):
        horizon, motif = cle
        if len(verdicts) < NUITS_CONSECUTIVES:
            continue                      # pas encore assez de nuits
        cellule = par_cle.get(cle)
        constant = len(set(verdicts)) == 1
        if not constant:
            continue

        if verdicts[0] == labo.REFUTE and cle not in fermes:
            restants = _motifs_ouverts_a(horizon, mesure, fermes)
            if restants - 1 < MOTIFS_MINIMUM_PAR_HORIZON:
                # ⛔ On le DIT plutôt que de fermer en silence — ou de ne rien
                # dire du tout, ce qui reviendrait au kill-switch oublié.
                actions.append({"action": REFUSE_PLANCHER, "horizon": horizon,
                                "motif": motif, "pair": pair,
                                "detail": f"{restants} motifs ouverts, plancher "
                                          f"{MOTIFS_MINIMUM_PAR_HORIZON}"})
                continue
            actions.append({"action": FERMER, "horizon": horizon, "motif": motif,
                            "pair": pair, "sens": (cellule or {}).get("sens"),
                            "cellule": cellule,
                            "detail": _preuve(cellule, verdicts)})

        elif verdicts[0] == labo.RETENU and cle in fermes:
            # 🔑 Il ne rouvre QUE ce qu'il a fermé — `fermes` ne contient que
            # ses propres décisions.
            actions.append({"action": ROUVRIR, "horizon": horizon, "motif": motif,
                            "pair": pair, "sens": (cellule or {}).get("sens"),
                            "cellule": cellule,
                            "detail": _preuve(cellule, verdicts)})

    if ARME:
        _appliquer(actions)
    else:
        logger.warning("reglage_or: DÉSARMÉ — %d action(s) proposée(s), aucune "
                       "appliquée", len(actions))
    return actions


def _preuve(cellule: dict | None, verdicts: list[str]) -> str:
    if not cellule:
        return f"{len(verdicts)} nuits {verdicts[0]}"
    return (f"{cellule['r_moyen']:+.2f} R sur {cellule['n']} trades, "
            f"t={cellule['t']:+.2f} contre un plafond de "
            f"{cellule.get('plafond', 0):.2f} · {len(verdicts)} nuits de suite")


def _appliquer(actions: list[dict]) -> None:
    if not actions:
        return
    quand = _maintenant()
    with sqlite3.connect(_db()) as c:
        _schema(c)
        for a in actions:
            if a["action"] == FERMER:
                c.execute(
                    """INSERT OR REPLACE INTO labo_or_fermetures
                       (pair, horizon, motif, sens, ferme_le, preuve)
                       VALUES (?,?,?,?,?,?)""",
                    (a["pair"], a["horizon"], a["motif"], a.get("sens"), quand,
                     json.dumps(a.get("cellule") or {}, ensure_ascii=False)))
            elif a["action"] == ROUVRIR:
                c.execute("DELETE FROM labo_or_fermetures WHERE pair = ? "
                          "AND horizon = ? AND motif = ?",
                          (a["pair"], a["horizon"], a["motif"]))
            if a["action"] in (FERMER, ROUVRIR, REFUSE_PLANCHER):
                c.execute(
                    """INSERT INTO labo_or_journal
                       (decide_le, action, pair, horizon, motif, motif_decision)
                       VALUES (?,?,?,?,?,?)""",
                    (quand, a["action"], a["pair"], a["horizon"], a["motif"],
                     a.get("detail")))
    for a in actions:
        logger.warning("reglage_or: %s %s %s — %s", a["action"], a["horizon"],
                       a["motif"], a.get("detail"))


# ─────────────────────────────────────────────────────────────────────
# Le cycle de la nuit
# ─────────────────────────────────────────────────────────────────────

JOURS_ETUDIES = int(os.getenv("LABO_OR_JOURS", "90"))


def _bougies_et_spread(jours: int) -> tuple[list, float]:
    """Va chercher les bougies de 5 min et le spread vivant chez le courtier.

    ⚠️ Le pont MT5 sert l'historique gratuitement — contrairement à Twelve Data,
    dont le quota a déjà saturé (954 refus 429). C'est la bonne porte pour
    17 000 bougies.
    """
    import json
    import urllib.parse
    import urllib.request
    from datetime import datetime, timedelta, timezone

    from backend.services.destinations_registry import DESTINATIONS

    d = DESTINATIONS["admin_live"]
    base = os.environ[d.url_env].rstrip("/")
    entetes = {getattr(d, "key_header", None) or "X-API-Key": os.environ[d.key_env]}
    symbole = PAIRE.replace("/", "")

    tick = json.load(urllib.request.urlopen(urllib.request.Request(
        base + "/tick/" + symbole, headers=entetes), timeout=30))
    spread = float(tick["ask"]) - float(tick["bid"])

    fin = datetime.now(timezone.utc)
    debut = fin - timedelta(days=jours)
    brut: list = []
    while debut < fin:
        borne = min(debut + timedelta(days=10), fin)
        q = urllib.parse.urlencode({
            "pair": symbole, "timeframe": "M5",
            "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": borne.strftime("%Y-%m-%dT%H:%M:%SZ")})
        try:
            o = json.load(urllib.request.urlopen(urllib.request.Request(
                base + "/rates?" + q, headers=entetes), timeout=180))
            brut += o.get("bougies") or []
        except Exception as e:  # noqa: BLE001
            # ⚠️ Une fenêtre manquante ne doit pas annuler la nuit — mais elle
            # doit se voir, sinon on mesurerait 60 jours en croyant en faire 90.
            logger.warning("labo_or: fenêtre %s ignorée (%s)", debut.date(), e)
        debut = borne

    vus, propre = set(), []
    for x in brut:
        if x["t"] not in vus:
            vus.add(x["t"])
            propre.append(x)
    propre.sort(key=lambda x: x["t"])
    return propre, spread


def cycle_nocturne() -> dict:
    """Mesurer, enregistrer, décider, dire. Best-effort de bout en bout.

    ⛔ Tourne DANS le conteneur, pas en cron sur l'hôte : `/opt/scalping/scripts`
    a déjà divergé du dépôt, et huit correctifs y sont restés morts une journée
    entière. Ce qui est déployé est alors forcément ce qui s'exécute.
    """
    try:
        bougies, spread = _bougies_et_spread(JOURS_ETUDIES)
    except Exception as e:  # noqa: BLE001
        logger.warning("labo_or: bougies indisponibles (%s) — nuit sautée", e)
        return {"erreur": str(e)[:200]}
    if len(bougies) < 500:
        logger.warning("labo_or: %d bougies seulement — nuit sautée", len(bougies))
        return {"erreur": f"{len(bougies)} bougies"}

    mesure = labo.mesurer(bougies, spread, pair=PAIRE)
    enregistrer(mesure)
    actions = decider(mesure)
    _notifier(mesure, actions)
    return {"cellules": len(mesure.get("cellules") or []),
            "actions": actions, "plafond": mesure.get("plafond")}


def en_observation(mesure: dict, pair: str = PAIRE) -> list[dict]:
    """Les cellules réfutées qui n'ont pas encore assez de nuits pour agir.

    🔑 Sans ça, le mécanisme resterait muet jusqu'au soir où il ferme quelque
    chose — une décision surgie de nulle part. Là, on voit venir : « 1 nuit sur
    3 ». C'est la différence entre un automate et une boîte noire.
    """
    historique = _dernieres_nuits(pair, NUITS_CONSECUTIVES)
    dejas = fermetures(pair)
    out = []
    for c in (mesure.get("cellules") or []):
        if c["verdict"] != labo.REFUTE:
            continue
        cle = (c["horizon"], c["motif"])
        if cle in dejas:
            continue                    # déjà fermé, plus rien à guetter
        verdicts = historique.get(cle) or []
        suite = 0
        for v in verdicts:              # du plus récent au plus ancien
            if v != labo.REFUTE:
                break
            suite += 1
        if suite < NUITS_CONSECUTIVES:
            out.append({**c, "nuits": suite})
    return out


def _lignes_observation(guettees: list[dict]) -> list[str]:
    if not guettees:
        return []
    out = ["👁️ <b>En observation</b> — perd de façon nette, pas encore fermé :"]
    for c in sorted(guettees, key=lambda x: x["t"]):
        out.append(f"• {c['horizon']} {c['motif']} {c['sens']} — "
                   f"{c['r_moyen']:+.2f} R sur {c['n']} trades "
                   f"(t={c['t']:+.2f}) · {c['nuits']}/{NUITS_CONSECUTIVES} nuits")
    out.append("")
    return out


def _notifier(mesure: dict, actions: list[dict]) -> None:
    """Un message par nuit, sur le fil du compte concerné.

    ⚠️ La couche soustractive s'applique à TOUTES les destinations : une
    fermeture vaut aussi pour l'argent réel. Le message doit le dire — c'est
    une décision de trading, pas une note de laboratoire.
    """
    interessant = [a for a in actions
                   if a["action"] in (FERMER, ROUVRIR, REFUSE_PLANCHER)]
    retenues = [c for c in (mesure.get("cellules") or [])
                if c["verdict"] == labo.RETENU]
    guettees = en_observation(mesure)
    if not interessant and not retenues and not guettees:
        # ⛔ Pas de message quand il n'y a rien à dire. Le bruit quotidien est
        # ce qui a noyé l'alerte de sauvegarde S3 pendant cinq nuits.
        logger.info("labo_or: rien à signaler (%d cellules, plafond %.2f)",
                    len(mesure.get("cellules") or []), mesure.get("plafond", 0))
        return
    try:
        import httpx

        from backend.services.canaux_telegram import (canal_pour,
                                                      libelle_avec_picto)

        jeton = os.getenv("INFRA_TELEGRAM_TOKEN", "").strip()
        if not jeton:
            return
        base = os.getenv("INTERNAL_API_BASE_URL",
                         "http://127.0.0.1:8000").rstrip("/")
        corps = "\n".join(labo.lignes(mesure) + [""]
                          + _lignes_observation(guettees) + lignes(actions))
        if any(a["action"] in (FERMER, ROUVRIR) for a in interessant):
            corps += ("\n\n⚠️ Cette décision vaut pour TOUS les comptes qui "
                      "servent cet horizon, argent réel compris. Elle ne ferme "
                      "aucune position ouverte.")
        # ⚠️ Le nom CANONIQUE, dérivé de la destination — pas l'alias `sales`,
        # qui est accepté à l'entrée de l'endpoint mais absent de la table des
        # libellés. Ma première version levait `KeyError: 'sales'`, et le
        # `except` large l'avalait : aucune notification, aucun bruit.
        canal = canal_pour("admin_live")     # le fil IC MARKETS — l'or y trade
        httpx.post(f"{base}/api/admin/notify-infra-telegram",
                   json={"title": f"{libelle_avec_picto(canal)} — laboratoire "
                                  "de l'or", "body": corps, "channel": canal},
                   headers={"X-Admin-Token": jeton}, timeout=15).raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning("labo_or: notification échouée : %s", e)


# ─────────────────────────────────────────────────────────────────────
# Le rendu
# ─────────────────────────────────────────────────────────────────────

def lignes(actions: list[dict], pair: str = PAIRE) -> list[str]:
    """Le bloc lisible. Fonction PURE — elle ne relit pas la base."""
    actives = fermetures(pair)
    out: list[str] = []
    fermees = [a for a in actions if a["action"] == FERMER]
    rouvertes = [a for a in actions if a["action"] == ROUVRIR]
    refusees = [a for a in actions if a["action"] == REFUSE_PLANCHER]

    if fermees:
        out.append("🔒 <b>Fermé cette nuit</b> (perd de l'argent de façon nette) :")
        for a in fermees:
            out.append(f"• {a['horizon']} {a['motif']} — {a['detail']}")
    if rouvertes:
        out.append("🔓 <b>Rouvert</b> (redevenu meilleur que le hasard) :")
        for a in rouvertes:
            out.append(f"• {a['horizon']} {a['motif']} — {a['detail']}")
    if refusees:
        out.append("⚠️ <b>Fermeture refusée</b> — il resterait trop peu de "
                   "motifs sur cet horizon :")
        for a in refusees:
            out.append(f"• {a['horizon']} {a['motif']} ({a['detail']})")

    if not out:
        out.append("🔁 Réajustement de l'or : rien à changer cette nuit.")
    if actives:
        out.append(f"  (motifs actuellement fermés par le labo : "
                   f"{', '.join(sorted(f'{h} {m}' for h, m in actives))})")
    if not ARME:
        out.append("⚠️ Mécanisme DÉSARMÉ (`REGLAGE_OR_ARME=0`) — ce qui précède "
                   "est une proposition, rien n'a été appliqué.")
    return out
