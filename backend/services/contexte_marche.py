"""Contexte de marche par instrument — de la lecture, jamais une position.

## Ce que c'est

Une fois par jour, un agent lit l'actualite macro et rend, pour chacun des
instruments de `WATCHED_PAIRS`, un paragraphe de contexte et la liste des
echeances datees qui les concernent. La sortie est destinee a un HUMAIN qui
arbitre les passages de phase, pas au moteur de scoring.

## Ce qu'il ne rend jamais

⛔ Ni direction, ni score, ni niveau d'entree, ni recommandation. Ce n'est pas
une consigne de redaction : `_valider()` **retire** ces clefs si le modele en
produit, et un test le verrouille. Un contexte qui se met a suggerer un sens
redevient un facteur de decision — et un facteur de decision doit etre valide
statistiquement, ce que `promotion_criteria` a chiffre a environ 700 clotures.

⛔ Il ne comble pas ses lacunes. Un instrument sur lequel l'agent n'a rien
trouve ressort dans `donnees_manquantes`. Un contexte incomplet et signale
vaut mieux qu'un contexte inventé.

## Pourquoi HTTP et pas le SDK agent

`claude-agent-sdk` lance le CLI Claude Code en sous-processus : il exige Node
et le binaire `claude` DANS l'image Docker (verifie le 2026-09-04 — le SDK
expose `CLINotFoundError`). L'appel HTTP direct ne demande que `httpx`, deja
dans `requirements.txt`. Pour un conteneur sur EC2, le second gagne.

## Reglages

    CONTEXTE_MARCHE_ENABLED=true
    CONTEXTE_MARCHE_API_KEY=...        (ou ANTHROPIC_API_KEY)

Desactive par defaut : l'appel est facture.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONTEXTE_MARCHE_ENABLED = os.getenv(
    "CONTEXTE_MARCHE_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
CONTEXTE_MARCHE_API_KEY = os.getenv("CONTEXTE_MARCHE_API_KEY", "") or os.getenv(
    "ANTHROPIC_API_KEY", ""
)
CONTEXTE_MARCHE_MODEL = os.getenv("CONTEXTE_MARCHE_MODEL", "claude-sonnet-4-5")
CONTEXTE_MARCHE_TIMEOUT = float(os.getenv("CONTEXTE_MARCHE_TIMEOUT", "180"))

# Clefs qui feraient de ce module un facteur de decision. Retirees a l'arrivee,
# quoi que reponde le modele — la consigne ne suffit pas, le code tranche.
CLEFS_INTERDITES = frozenset({
    "direction", "sens", "signal", "score", "confidence", "confiance",
    "action", "recommandation", "recommendation", "position", "entry",
    "entree", "stop", "stop_loss", "target", "take_profit", "biais", "bias",
})

_CHAMPS_INSTRUMENT = ("pair", "resume", "echeances")


def _instruments() -> list[str]:
    """Les instruments suivis, lus au moment de l'appel (jamais figes)."""
    try:
        from config.settings import WATCHED_PAIRS

        return list(WATCHED_PAIRS)
    except Exception as e:
        logger.warning(f"contexte_marche: WATCHED_PAIRS illisible: {e}")
        return []


def _extraire_json(texte: str) -> Optional[dict]:
    """Recupere l'objet JSON d'une reponse, meme entouree de prose ou de balises."""
    if not texte:
        return None
    for essai in (texte, *re.findall(r"```(?:json)?\s*(.*?)```", texte, re.S)):
        essai = essai.strip()
        debut, fin = essai.find("{"), essai.rfind("}")
        if debut == -1 or fin <= debut:
            continue
        try:
            charge = json.loads(essai[debut : fin + 1])
            if isinstance(charge, dict):
                return charge
        except json.JSONDecodeError:
            continue
    return None


def _valider(charge: Any, attendus: list[str]) -> dict:
    """Ne garde que la forme autorisee, et retire toute clef de decision.

    Un instrument absent de la reponse n'est pas invente : il tombe dans
    `donnees_manquantes`.
    """
    sortie: dict[str, Any] = {"instruments": [], "donnees_manquantes": [], "sources": []}
    if not isinstance(charge, dict):
        return {**sortie, "donnees_manquantes": list(attendus)}

    vus: set[str] = set()
    for brut in charge.get("instruments") or []:
        if not isinstance(brut, dict):
            continue
        pair = str(brut.get("pair") or "").strip()
        if pair not in attendus or pair in vus:
            continue
        vus.add(pair)
        propre = {
            "pair": pair,
            "resume": str(brut.get("resume") or "").strip(),
            "echeances": [
                str(x).strip()
                for x in (brut.get("echeances") or [])
                if str(x).strip()
            ],
        }
        # Filet : tout ce qui ressemble a une decision degage.
        retirees = sorted(k for k in brut if k.lower() in CLEFS_INTERDITES)
        if retirees:
            logger.warning(
                f"contexte_marche: clefs de decision retirees sur {pair}: {retirees}"
            )
        if propre["resume"]:
            sortie["instruments"].append(propre)
        else:
            vus.discard(pair)

    sortie["donnees_manquantes"] = [p for p in attendus if p not in vus]
    sortie["sources"] = [
        str(s).strip() for s in (charge.get("sources") or []) if str(s).strip()
    ]
    return sortie


_CONSIGNE = """Tu prepares un contexte de marche pour l'operateur d'un systeme de
trading en demo. Il arbitre des passages de phase, il ne prend pas de position
d'apres toi.

Cherche l'actualite macro du jour et rends UNIQUEMENT un objet JSON :

{"instruments":[{"pair":"EUR/USD","resume":"<3 phrases maximum, faits dates>",
"echeances":["<date> — <evenement>"]}],"sources":["<url>"]}

Regles :
- Aucune direction, aucun score, aucun niveau d'entree, aucune recommandation.
  Tu decris ce qui s'est passe et ce qui est programme, rien d'autre.
- Un chiffre que tu n'as pas trouve dans une source ne s'ecrit pas. Omets
  simplement l'instrument : son absence sera signalee comme une lacune.
- Cite tes sources par leur URL."""


async def contexte(instruments: Optional[list[str]] = None) -> Optional[dict]:
    """Le contexte du jour. None si desactive, sans cle, ou en echec."""
    if not CONTEXTE_MARCHE_ENABLED:
        return None
    if not CONTEXTE_MARCHE_API_KEY:
        logger.info("contexte_marche: active mais aucune cle API")
        return None

    attendus = instruments if instruments is not None else _instruments()
    if not attendus:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=CONTEXTE_MARCHE_TIMEOUT) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": CONTEXTE_MARCHE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CONTEXTE_MARCHE_MODEL,
                    "max_tokens": 4000,
                    "system": _CONSIGNE,
                    "tools": [{"type": "web_search_20250305", "name": "web_search",
                               "max_uses": 8}],
                    "messages": [{
                        "role": "user",
                        "content": "Contexte du jour pour : " + ", ".join(attendus),
                    }],
                },
            )
            r.raise_for_status()
            blocs = r.json().get("content") or []
            texte = "".join(
                b.get("text", "") for b in blocs if b.get("type") == "text"
            )
    except Exception as e:
        logger.warning(f"contexte_marche: appel en echec: {e}")
        return None

    valide = _valider(_extraire_json(texte), attendus)
    return {
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "modele": CONTEXTE_MARCHE_MODEL,
        **valide,
    }
