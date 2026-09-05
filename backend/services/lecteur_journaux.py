"""Lecteur de journaux — il lit ce que le systeme a deja ecrit, et ne decide rien.

## Pourquoi

Le projet produit plus de traces qu'il n'en relit : `signal_rejections`,
les contrefactuels `geopolitical_features_json`, les shadows en attente de
resolution, les clotures par paire. Ces tables savent des choses que personne
ne va chercher — qu'une regle de veto n'a plus tire depuis deux mois, qu'une
paire n'accumule plus rien, qu'un shadow ouvert depuis trois semaines ne sera
jamais resolu.

## Ce que ce module refuse de faire

⛔ **Il ne decide rien.** Aucune sortie de ce module n'entre dans le scoring,
le dispatch ou l'admission. Il n'a pas de gate, pas de veto, pas de score. La
raison n'est pas la prudence : c'est qu'un module qui deciderait devrait etre
valide statistiquement, et le banc d'essai (`research_bench`) a deja etabli ce
que coute une hypothese de plus.

⛔ **Le modele de langage ne calcule aucun chiffre.** La couche `releve()` est
du SQL et de l'arithmetique, integralement testee. La couche `narration()` ne
recoit que ce releve **deja calcule** et le met en francais. Elle ne voit
jamais une ligne brute et n'a rien a additionner. Un chiffre faux dans le
bulletin est donc un bug de `releve()`, jamais une hallucination.

Cette separation est la seule raison pour laquelle un LLM a sa place ici.

## Ce qu'il mesure

1. **Rejets** par `reason_code`, fenetre courante contre fenetre precedente.
2. **Regles inertes** — les regles de `geopolitical_veto` qui n'ont pas tire.
   Une regle qui ne tire jamais n'est pas prudente, elle est indecidable.
3. **Contrefactuel du veto** — combien de shadows portent `would_veto=true`.
   C'est la mesure conservee volontairement le 2026-08-08 en passant le veto
   en consultatif : elle dit si la regle sera jugeable un jour.
4. **Shadows en suspens** — un shadow non resolu est de la mesure morte.
5. **Cadence par paire** — clotures/mois, et le temps qu'il faudrait pour
   atteindre le N de `promotion_criteria`.

⚠️ La cadence est une mesure de **debit**, pas de rentabilite. Elle dit quand
une paire aura assez d'observations pour qu'on puisse en parler. Elle ne dit
rien de ce qu'on y lira.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Reglages ────────────────────────────────────────────────────────────

# Narration desactivee par defaut : elle appelle une API payante. Le releve,
# lui, tourne toujours — c'est la partie qui porte l'information.
LECTEUR_NARRATION_ENABLED = os.getenv(
    "LECTEUR_NARRATION_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
LECTEUR_NARRATION_API_KEY = os.getenv("LECTEUR_NARRATION_API_KEY", "") or os.getenv(
    "ANTHROPIC_API_KEY", ""
)
LECTEUR_NARRATION_MODEL = os.getenv("LECTEUR_NARRATION_MODEL", "claude-sonnet-4-5")
LECTEUR_NARRATION_TIMEOUT = float(os.getenv("LECTEUR_NARRATION_TIMEOUT", "45"))

# N de clotures necessaire pour distinguer un edge de +0,15 R du hasard
# (95 % de confiance, 80 % de puissance, sigma 1 R). Chiffre etabli dans
# `promotion_criteria` le 2026-09-04 — repris ici tel quel, pas recalcule.
N_REQUIS_EDGE = 700

# Au-dela, un shadow ouvert n'a plus de raison de se resoudre.
JOURS_SHADOW_ABANDONNE = 14


def _connexion() -> Optional[sqlite3.Connection]:
    """Ouvre trades.db en lecture. None si la base n'existe pas encore.

    Import dans la fonction : `_DB_PATH` est monkeypatche par les tests, et
    une liaison au chargement du module figerait le chemin de production.
    """
    try:
        from backend.services.trade_log_service import _DB_PATH

        chemin = str(_DB_PATH)
        if not os.path.exists(chemin):
            return None
        c = sqlite3.connect(chemin)
        c.row_factory = sqlite3.Row
        return c
    except Exception as e:
        logger.warning(f"lecteur_journaux: ouverture base impossible: {e}")
        return None


def _colonnes(c: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def _jour(valeur: Any) -> str:
    """Les 10 premiers caracteres d'un horodatage, quel que soit son format.

    `signal_rejections.created_at` est de l'ISO-8601 avec fuseau, tandis que
    `shadow_setups.detected_at` prend le format SQLite 'YYYY-MM-DD HH:MM:SS'
    quand il vient du DEFAULT. Les deux commencent par la date : on compare
    la date, jamais l'horodatage entier.
    """
    return str(valeur or "")[:10]


# ─── 1. Rejets ───────────────────────────────────────────────────────────
def _rejets(c: sqlite3.Connection, debut: str, milieu: str, fin: str) -> dict:
    """Compte par `reason_code` sur la fenetre courante et la precedente."""
    def compter(a: str, b: str) -> dict[str, int]:
        rows = c.execute(
            "SELECT reason_code, COUNT(*) n FROM signal_rejections "
            "WHERE substr(created_at,1,10) >= ? AND substr(created_at,1,10) < ? "
            "GROUP BY 1",
            (a, b),
        ).fetchall()
        return {r["reason_code"]: r["n"] for r in rows}

    courant = compter(milieu, fin)
    precedent = compter(debut, milieu)
    codes = sorted(set(courant) | set(precedent))
    return {
        "total_courant": sum(courant.values()),
        "total_precedent": sum(precedent.values()),
        "par_code": [
            {
                "code": k,
                "courant": courant.get(k, 0),
                "precedent": precedent.get(k, 0),
                "delta": courant.get(k, 0) - precedent.get(k, 0),
            }
            for k in codes
        ],
    }


# ─── 2. Regles inertes ───────────────────────────────────────────────────
def _regles_inertes(c: sqlite3.Connection) -> list[dict]:
    """Pour chaque regle de `geopolitical_veto` : date du dernier tir.

    Une regle sans tir depuis toujours est signalee `jamais_tiree`. Le module
    ne conclut pas a sa place — il donne la date, la lecture reste humaine.
    """
    try:
        from backend.services.geopolitical_veto import KNOWN_RULES, _RULE_TAG_RE
    except Exception as e:
        logger.debug(f"lecteur_journaux: regles indisponibles: {e}")
        return []

    dernier: dict[str, str] = {}
    try:
        rows = c.execute(
            "SELECT created_at, details FROM signal_rejections "
            "WHERE reason_code = 'geopolitical_veto' ORDER BY created_at"
        ).fetchall()
    except Exception:
        rows = []

    for row in rows:
        try:
            details = json.loads(row["details"]) if row["details"] else {}
        except (json.JSONDecodeError, TypeError):
            continue
        blockers = details.get("blockers") or []
        if not blockers:
            continue
        m = _RULE_TAG_RE.search(blockers[0])
        if m and m.group(1) in KNOWN_RULES:
            dernier[m.group(1)] = _jour(row["created_at"])

    aujourdhui = datetime.now(timezone.utc).date()
    sortie = []
    for regle in KNOWN_RULES:
        d = dernier.get(regle)
        jours = None
        if d:
            try:
                jours = (aujourdhui - datetime.fromisoformat(d).date()).days
            except ValueError:
                jours = None
        sortie.append(
            {
                "regle": regle,
                "dernier_tir": d,
                "jours_depuis": jours,
                "jamais_tiree": d is None,
            }
        )
    return sortie


# ─── 3. Contrefactuel du veto ────────────────────────────────────────────
def _veto_contrefactuel(c: sqlite3.Connection, debut: str, fin: str) -> dict:
    """Ce que le veto AURAIT fait, lu dans `shadow_setups`.

    C'est la donnee que le passage en consultatif du 2026-08-08 a
    explicitement preservee. Si le taux est nul sur la fenetre, la regle
    n'est pas seulement inactive : elle est hors de portee d'une mesure.
    """
    if "geopolitical_features_json" not in _colonnes(c, "shadow_setups"):
        return {"disponible": False}

    try:
        rows = c.execute(
            "SELECT geopolitical_features_json g FROM shadow_setups "
            "WHERE g IS NOT NULL "
            "AND substr(detected_at,1,10) >= ? AND substr(detected_at,1,10) < ?",
            (debut, fin),
        ).fetchall()
    except Exception as e:
        logger.debug(f"lecteur_journaux: contrefactuel indisponible: {e}")
        return {"disponible": False}

    avec_snapshot = 0
    would_veto = 0
    par_regle: dict[str, int] = {}
    for row in rows:
        try:
            snap = json.loads(row["g"])
        except (json.JSONDecodeError, TypeError):
            continue
        evalue = snap.get("veto_evaluated") or {}
        if "would_veto" not in evalue:
            continue
        avec_snapshot += 1
        if evalue.get("would_veto"):
            would_veto += 1
            for r in evalue.get("rules_matched") or []:
                par_regle[r] = par_regle.get(r, 0) + 1

    taux = (would_veto / avec_snapshot) if avec_snapshot else None
    return {
        "disponible": True,
        "shadows_evalues": avec_snapshot,
        "would_veto": would_veto,
        "taux": taux,
        "par_regle": par_regle,
    }


# ─── 4. Shadows en suspens ───────────────────────────────────────────────
def _shadows_en_suspens(c: sqlite3.Connection) -> dict:
    """Shadows sans `outcome`, ventiles par age."""
    try:
        rows = c.execute(
            "SELECT pair, detected_at FROM shadow_setups WHERE outcome IS NULL"
        ).fetchall()
    except Exception:
        return {"total": 0, "abandonnes": 0, "par_paire": []}

    aujourdhui = datetime.now(timezone.utc).date()
    abandonnes = 0
    par_paire: dict[str, int] = {}
    for row in rows:
        par_paire[row["pair"]] = par_paire.get(row["pair"], 0) + 1
        try:
            d = datetime.fromisoformat(_jour(row["detected_at"])).date()
            if (aujourdhui - d).days > JOURS_SHADOW_ABANDONNE:
                abandonnes += 1
        except ValueError:
            continue

    return {
        "total": len(rows),
        "abandonnes": abandonnes,
        "seuil_abandon_jours": JOURS_SHADOW_ABANDONNE,
        "par_paire": sorted(
            ({"pair": k, "n": v} for k, v in par_paire.items()),
            key=lambda x: -x["n"],
        )[:10],
    }


# ─── 5. Cadence par paire ────────────────────────────────────────────────
def _cadence(c: sqlite3.Connection, debut: str, fin: str, jours: int) -> list[dict]:
    """Clotures par mois et par paire, et le temps restant jusqu'a N_REQUIS_EDGE.

    ⚠️ Debit uniquement. Le nombre de mois annonce est le temps avant de
    POUVOIR conclure, jamais une promesse sur ce qu'on conclura.
    """
    cols = _colonnes(c, "personal_trades")
    if not {"pair", "status"} <= cols:
        return []
    horodatage = "closed_at" if "closed_at" in cols else "created_at"

    try:
        rows = c.execute(
            f"SELECT pair, COUNT(*) n FROM personal_trades "
            f"WHERE status = 'CLOSED' AND {horodatage} IS NOT NULL "
            f"AND substr({horodatage},1,10) >= ? AND substr({horodatage},1,10) < ? "
            f"GROUP BY 1 ORDER BY 2 DESC",
            (debut, fin),
        ).fetchall()
        totaux = {
            r["pair"]: r["n"]
            for r in c.execute(
                "SELECT pair, COUNT(*) n FROM personal_trades "
                "WHERE status = 'CLOSED' GROUP BY 1"
            )
        }
    except Exception as e:
        logger.debug(f"lecteur_journaux: cadence indisponible: {e}")
        return []

    sortie = []
    for row in rows:
        par_mois = row["n"] * 30.4 / max(1, jours)
        acquis = totaux.get(row["pair"], 0)
        restant = max(0, N_REQUIS_EDGE - acquis)
        mois = (restant / par_mois) if par_mois > 0 else None
        sortie.append(
            {
                "pair": row["pair"],
                "clotures_fenetre": row["n"],
                "par_mois": round(par_mois, 1),
                "clotures_totales": acquis,
                "n_requis": N_REQUIS_EDGE,
                "mois_restants": round(mois, 1) if mois is not None else None,
            }
        )
    return sortie


# ─── Releve ──────────────────────────────────────────────────────────────
def releve(jours: int = 7) -> dict:
    """Les faits, calcules ici et nulle part ailleurs.

    Best-effort de bout en bout : une section qui echoue vaut vide, jamais
    une exception — ce module ne doit pouvoir casser aucun appelant.
    """
    jours = max(1, min(90, int(jours)))
    maintenant = datetime.now(timezone.utc)
    fin = (maintenant.date() + timedelta(days=1)).isoformat()
    milieu = (maintenant.date() - timedelta(days=jours - 1)).isoformat()
    debut = (maintenant.date() - timedelta(days=2 * jours - 1)).isoformat()

    base = {
        "genere_le": maintenant.isoformat(),
        "jours": jours,
        "fenetre_courante": [milieu, fin],
        "fenetre_precedente": [debut, milieu],
        "rejets": {"total_courant": 0, "total_precedent": 0, "par_code": []},
        "regles_inertes": [],
        "veto_contrefactuel": {"disponible": False},
        "shadows_en_suspens": {"total": 0, "abandonnes": 0, "par_paire": []},
        "cadence": [],
    }

    c = _connexion()
    if c is None:
        return base
    try:
        for cle, fn in (
            ("rejets", lambda: _rejets(c, debut, milieu, fin)),
            ("regles_inertes", lambda: _regles_inertes(c)),
            ("veto_contrefactuel", lambda: _veto_contrefactuel(c, milieu, fin)),
            ("shadows_en_suspens", lambda: _shadows_en_suspens(c)),
            ("cadence", lambda: _cadence(c, milieu, fin, jours)),
        ):
            try:
                base[cle] = fn()
            except Exception as e:
                logger.warning(f"lecteur_journaux: section {cle} en echec: {e}")
    finally:
        c.close()
    return base


# ─── Narration ───────────────────────────────────────────────────────────
_CONSIGNE = """Tu lis le releve d'un systeme de trading automatise en demo.

Ces chiffres sont deja calcules et exacts. Tu ne dois en produire aucun autre :
recopie-les, ne les additionne pas, n'en derive pas de nouveaux, n'extrapole pas.

Ecris en francais, 200 mots maximum, en prose continue, sans titres ni listes.
Dis ce qui a change et ce qui n'avance pas. Une regle qui n'a jamais tire et un
contrefactuel a zero veulent dire qu'elle est indecidable : dis-le. Une paire
dont les mois restants depassent la duree de vie du projet, dis-le aussi.

Tu ne recommandes aucun trade et ne juges aucune rentabilite : le releve ne
contient pas de quoi le faire. Si rien de notable n'a bouge, ecris-le en une
phrase plutot que de meubler."""


async def narration(donnees: dict) -> Optional[str]:
    """Met le releve en francais. None si desactive, sans cle, ou en echec.

    Ne recoit que `donnees` — un releve deja calcule. Aucun acces a la base.
    """
    if not LECTEUR_NARRATION_ENABLED:
        return None
    if not LECTEUR_NARRATION_API_KEY:
        logger.info("lecteur_journaux: narration active mais aucune cle API")
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=LECTEUR_NARRATION_TIMEOUT) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": LECTEUR_NARRATION_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": LECTEUR_NARRATION_MODEL,
                    "max_tokens": 700,
                    "system": _CONSIGNE,
                    "messages": [
                        {
                            "role": "user",
                            "content": json.dumps(donnees, ensure_ascii=False, default=str),
                        }
                    ],
                },
            )
            r.raise_for_status()
            blocs = r.json().get("content") or []
            texte = "".join(b.get("text", "") for b in blocs if b.get("type") == "text")
            return texte.strip() or None
    except Exception as e:
        logger.warning(f"lecteur_journaux: narration en echec: {e}")
        return None


async def bulletin(jours: int = 7) -> dict:
    """Releve + narration. La narration vaut None si elle n'a pas pu se faire ;
    les faits, eux, sont toujours la."""
    donnees = releve(jours=jours)
    return {**donnees, "narration": await narration(donnees)}


# ─── Bulletin ────────────────────────────────────────────────────────────
def texte_bulletin(donnees: dict) -> str:
    """Met le releve en texte brut pour Telegram. Pur, donc testable.

    La narration, si elle existe, est placee EN TETE et clairement separee des
    faits : c'est le seul passage que le modele a ecrit, et le lecteur doit
    savoir ou il commence et ou il s'arrete.
    """
    lignes: list[str] = [f"Lecteur de journaux — {donnees.get('jours', 0)} jours"]

    narration = donnees.get("narration")
    if narration:
        lignes += ["", narration, "", "— faits —"]

    r = donnees.get("rejets") or {}
    if r.get("total_courant") or r.get("total_precedent"):
        lignes.append(
            f"Rejets : {r.get('total_courant', 0)} "
            f"(periode precedente {r.get('total_precedent', 0)})"
        )
        for c in (r.get("par_code") or [])[:5]:
            signe = "+" if c["delta"] > 0 else ""
            lignes.append(f"  {c['code']} : {c['courant']} ({signe}{c['delta']})")

    inertes = [x for x in (donnees.get("regles_inertes") or []) if x.get("jamais_tiree")]
    if inertes:
        lignes.append(
            "Regles jamais declenchees : " + ", ".join(x["regle"] for x in inertes)
        )

    v = donnees.get("veto_contrefactuel") or {}
    if v.get("disponible") and v.get("shadows_evalues"):
        taux = v.get("taux")
        lignes.append(
            f"Veto contrefactuel : {v['would_veto']}/{v['shadows_evalues']} shadows"
            + (f" ({taux * 100:.2f} %)" if taux is not None else "")
        )

    s = donnees.get("shadows_en_suspens") or {}
    if s.get("total"):
        lignes.append(
            f"Shadows non resolus : {s['total']}, dont {s.get('abandonnes', 0)} "
            f"au-dela de {s.get('seuil_abandon_jours', JOURS_SHADOW_ABANDONNE)} jours"
        )

    cadence = donnees.get("cadence") or []
    if cadence:
        lignes.append("Cadence (clotures/mois, mois avant de pouvoir conclure) :")
        for c in cadence[:6]:
            mois = c.get("mois_restants")
            lignes.append(
                f"  {c['pair']} : {c['par_mois']}/mois, "
                + (f"{mois} mois" if mois is not None else "jamais a ce rythme")
            )

    if len(lignes) == 1:
        lignes.append("Rien a signaler : aucune trace sur la periode.")
    return "\n".join(lignes)


async def envoyer_bulletin_hebdomadaire(jours: int = 7) -> bool:
    """Job scheduler : lit, met en forme, envoie sur le fil infra.

    ⚠️ Le retour de l'envoi est JOURNALISE. Un bulletin qui part n'est pas un
    bulletin qui arrive — meme lecon que la sauvegarde S3 tombee cinq nuits.

    Fil infra et non sales : ce bulletin parle de la SANTE DE LA MESURE, pas
    d'un verdict sur une paire. Changer `send_infra_text` suffit a le deplacer.
    """
    from backend.services import telegram_service

    try:
        donnees = await bulletin(jours=jours)
        texte = texte_bulletin(donnees)
    except Exception:
        logger.exception("lecteur_journaux: construction du bulletin impossible")
        return False

    envoye = await telegram_service.send_infra_text(texte, parse_mode=None)
    logger.info(
        "lecteur_journaux: bulletin %d j, narration=%s, envoye=%s",
        jours, bool(donnees.get("narration")), envoye,
    )
    return bool(envoye)
