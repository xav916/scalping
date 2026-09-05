"""Garde-fou SL/TP côté Kraken : détecte une position nue, et la répare.

Le bridge Kraken savait DÉTECTER une position sans stop (`/openorders` →
``positions_non_protegees``, posé le 2026-08-19) et, depuis le 2026-09-06, la
RÉPARER (``POST /position/sltp``). Rien ne reliait les deux : il fallait un
humain entre la détection et le geste. Ce module est ce lien, et il reprend
telle quelle la politique des bridges MT5, armés le 2026-08-28.

⚠️ **Deux drapeaux INDÉPENDANTS** doivent être vrais pour qu'un stop parte :

  1. ``KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED`` ici, côté orchestrateur ;
  2. ``KRAKEN_SLTP_GUARD_ENABLED`` sur le bridge lui-même.

Si l'un des deux est faux, ce module se contente de DÉTECTER et de signaler —
jamais d'agir. Poser un stop automatique sur de l'argent réel est un changement
de comportement qui doit s'allumer sciemment.

⛔ Le bridge applique EN PLUS sa propre exclusion (``garde_fou_eligible`` :
horodatage d'armement, symboles gelés, ouverture indatable). Même si ce module
est bogué ou mal configuré, **le bridge refuse seul** de toucher une position
antérieure à sa mise en service. C'est pour ça que l'appel se DÉCLARE
automatique (``garde_fou: true``) : un déplacement demandé explicitement — une
sortie à l'équilibre, une réparation à la main — n'a pas à passer cette porte.

🔑 Le stop d'urgence vaut ``SLTP_GUARD_EMERGENCY_SL_PCT`` % du prix d'entrée
(1 % par défaut, même réglage que MT5 — une seule source de vérité pour une
seule décision). **Ce n'est pas un stop de trading** : il borne un risque
*infini*, il ne cherche pas le bon niveau.

⚠️ L'enjeu dépasse la position elle-même : une position nue **bloque TOUTE
nouvelle ouverture** sur Kraken, ``_controle_risque_engage_kraken`` refusant
tant qu'un risque n'est pas bornable. Un garde-fou désarmé se manifeste donc
par un compte qui cesse de trader, sans que personne sache pourquoi.

Appelé par ``scripts/check-kraken-positions-sltp.sh`` via
``python -m backend.services.kraken_sltp_guard``, qui imprime un JSON sur
stdout — même patron que le garde-fou MT5.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from config.settings import (
    KRAKEN_BRIDGE_URL,
    KRAKEN_BRIDGE_API_KEY,
    KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED,
    SLTP_GUARD_EMERGENCY_SL_PCT,
)

logger = logging.getLogger(__name__)

# Recopies au niveau module : c'est ce qui rend le garde-fou testable sans
# environnement, et lisible d'un coup d'oeil dans le rapport qu'il produit.
AUTO_PROTECT_ENABLED = KRAKEN_SLTP_GUARD_AUTO_PROTECT_ENABLED
EMERGENCY_SL_PCT = SLTP_GUARD_EMERGENCY_SL_PCT
BRIDGE_URL = KRAKEN_BRIDGE_URL
BRIDGE_KEY = KRAKEN_BRIDGE_API_KEY
TIMEOUT_SEC = 12.0


async def _lire(url: str, cle: str = "") -> dict:
    """GET sur le bridge. Lève — l'appelant décide quoi faire d'une panne."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
        r = await c.get(url, headers={"X-Bridge-Key": cle} if cle else {})
        r.raise_for_status()
        return r.json()


async def _poser(url: str, corps: dict, cle: str = "") -> dict:
    """POST /position/sltp. Best-effort : rend toujours un dict lisible."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
            r = await c.post(url, json=corps,
                             headers={"X-Bridge-Key": cle} if cle else {})
            try:
                reponse = r.json()
            except Exception:
                reponse = {"raw": r.text[:300]}
            return {"ok": r.status_code == 200 and reponse.get("ok") is True,
                    "status": r.status_code, **reponse}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def stop_d_urgence(entree: float, long: bool, pct: float | None = None) -> float | None:
    """Prix du stop d'urgence : ``pct`` % SOUS l'entrée d'un achat, AU-DESSUS
    d'une vente.

    ⛔ Rend ``None`` si l'entrée est inconnue ou nulle : un stop calculé depuis
    zéro serait à zéro, c'est-à-dire nulle part. Mieux vaut ne rien poser et
    continuer d'alerter que poser un stop qui ne borne rien.
    """
    try:
        entree = float(entree)
    except (TypeError, ValueError):
        return None
    if entree <= 0:
        return None
    part = abs(entree) * float(pct if pct is not None else EMERGENCY_SL_PCT) / 100.0
    if part <= 0:
        return None
    return round(entree - part, 8) if long else round(entree + part, 8)


async def scanner() -> dict:
    """Scanne le bridge Kraken, et protège si les deux drapeaux le permettent.

    Rend ::

        {"joignable": bool, "nues": [...], "nues_total": int,
         "protegees_total": int, "auto_protect_enabled": bool,
         "resultats": [...]}

    Best-effort de bout en bout : un bridge injoignable rend
    ``joignable: False``, jamais une exception — un garde-fou qui plante est un
    garde-fou muet, et le silence se lit comme « tout va bien ».
    """
    rapport: dict = {
        "joignable": False,
        "nues": [],
        "nues_total": 0,
        "protegees_total": 0,
        "auto_protect_enabled": AUTO_PROTECT_ENABLED,
        "resultats": [],
    }
    base = (BRIDGE_URL or "").rstrip("/")
    if not base:
        return rapport

    try:
        ordres = await _lire(base + "/openorders", BRIDGE_KEY)
        positions = await _lire(base + "/positions", BRIDGE_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"kraken_sltp_guard : bridge injoignable : {e}")
        return rapport

    rapport["joignable"] = True
    # ⛔ La liste des non protégées est calculée PAR LE BRIDGE, qui joint
    # positions et ordres `reduceOnly`. La recalculer ici ferait deux vérités
    # pour une seule question — et c'est celle du bridge qui décide.
    sans_stop = set(ordres.get("positions_non_protegees") or [])
    par_symbole = {p.get("symbol"): p for p in (positions.get("positions") or [])}

    for symbole in sorted(sans_stop):
        p = par_symbole.get(symbole) or {}
        ligne = {
            "symbol": symbole,
            "side": p.get("side"),
            "size": p.get("size"),
            "price": p.get("price"),
            "fill_time": p.get("fill_time"),
        }
        rapport["nues"].append(ligne)
        rapport["nues_total"] += 1

        if not AUTO_PROTECT_ENABLED:
            continue

        long = str(p.get("side") or "").lower().startswith("l")
        sl = stop_d_urgence(p.get("price"), long)
        if sl is None:
            rapport["resultats"].append({
                "symbol": symbole, "ok": False,
                "error": "entree inconnue — stop d'urgence incalculable"})
            continue
        res = await _poser(base + "/position/sltp", {
            "symbol": symbole,
            "sl": sl,
            # ⛔ L'appel se DÉCLARE automatique : c'est cette marque qui le
            # soumet à la porte du bridge (armement, symboles gelés, ouverture
            # indatable). Sans elle, le garde-fou passerait pour un appelant
            # humain et contournerait sa propre exclusion.
            "garde_fou": True,
            "raison": "garde_fou_position_nue",
        }, BRIDGE_KEY)
        rapport["resultats"].append({"symbol": symbole, **res})
        if res.get("ok"):
            rapport["protegees_total"] += 1

    return rapport


def run() -> dict:
    """Point d'entrée synchrone pour ``python -m backend.services.kraken_sltp_guard``."""
    return asyncio.run(scanner())


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
