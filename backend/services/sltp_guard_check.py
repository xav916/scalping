"""Garde-fou SL/TP : détecte les positions LIVE ouvertes sans stop-loss sur
les bridges MT5 (legacy Demo + live IC Markets) et, si explicitement activé,
demande au bridge de leur poser un stop via ``/position/sltp``.

Contexte : incident 2026-08-05, position XAU/USD ouverte sans SL ni TP à
02:09 UTC, découverte 7h plus tard à -51€. La cause (échec de pose SL/TP
avalé silencieusement côté bridge) est corrigée dans mt5-bridge/bridge.py
(``_apply_sltp_from_fill`` retourne désormais un résultat exploitable, et
``/order`` l'expose via ``protected``/``sl_applied``/``sl_error``). Ce
module est le second filet — au cas où un mode d'échec similaire
réapparaisse malgré tout, ou pour rattraper une position ouverte hors du
flux normal (manuel, ancien EA, etc.).

Deux drapeaux INDÉPENDANTS doivent être vrais pour qu'un stop soit posé
automatiquement :
  1. ``SLTP_GUARD_AUTO_PROTECT_ENABLED`` ici (côté orchestrateur/EC2)
  2. ``SLTP_GUARD_ENABLED`` sur le bridge lui-même (Windows/VPS)
Si l'un des deux est faux, ce module se contente de DÉTECTER et de
signaler — jamais d'agir. C'est le comportement historique du garde-fou
("alerte sans agir") et il reste le défaut tant que personne n'a activé les
deux drapeaux sciemment.

Le bridge applique en plus SA PROPRE exclusion (horodatage d'activation +
tickets gelés, cf. ``_sltp_guard_eligible`` dans mt5-bridge/bridge.py) —
même si ce module est buggé ou mal configuré, le bridge refuse seul de
toucher une position déjà ouverte au moment de sa mise en service.

Appelé par ``scripts/check-live-positions-sltp.sh`` via
``python -m backend.services.sltp_guard_check``, qui imprime un JSON sur
stdout (les scripts shell savent parser du JSON, pas des logs Python).
"""
import asyncio
import json
import logging

import httpx

from config.settings import (
    MT5_BRIDGE_URL,
    MT5_BRIDGE_API_KEY,
    MT5_BRIDGE_LIVE_URL,
    MT5_BRIDGE_LIVE_API_KEY,
    SLTP_GUARD_AUTO_PROTECT_ENABLED,
    SLTP_GUARD_EMERGENCY_SL_PCT,
)

logger = logging.getLogger(__name__)

# (label, bridge_url, api_key) — mêmes deux bridges que /api/admin/mt5-bridges-health.
_BRIDGES = (
    ("legacy", MT5_BRIDGE_URL, MT5_BRIDGE_API_KEY),
    ("live", MT5_BRIDGE_LIVE_URL, MT5_BRIDGE_LIVE_API_KEY),
)


async def _fetch_positions(bridge_url: str, api_key: str) -> list[dict] | None:
    """Positions ouvertes sur un bridge. None si non configuré ou
    injoignable (best-effort — un bridge down ne doit jamais faire planter
    le scan des autres)."""
    if not bridge_url or not api_key:
        return None
    url = bridge_url.rstrip("/") + "/positions"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={"X-API-Key": api_key})
            if r.status_code != 200:
                logger.warning(f"sltp_guard_check: /positions {bridge_url} → HTTP {r.status_code}")
                return None
            return r.json().get("positions") or []
    except Exception as e:
        logger.warning(f"sltp_guard_check: /positions {bridge_url} failed: {e}")
        return None


def is_naked(position: dict) -> bool:
    """Une position est 'nue' si son SL est absent ou nul.

    L'absence de TP seul n'est pas traitée comme une urgence : l'incident de
    référence est un risque non borné (pas de plafond de perte), pas
    l'absence d'objectif de gain — une position sans TP mais avec SL reste
    une perte bornée, ce que ce garde-fou existe pour garantir.
    """
    sl = position.get("sl")
    try:
        return sl is None or float(sl) == 0.0
    except (TypeError, ValueError):
        # sl illisible : on ne sait pas si elle est protégée → traité comme
        # nue, fail-closed côté détection (mieux vaut une fausse alerte
        # qu'une position réellement nue passée sous silence).
        return True


async def _protect(bridge_url: str, api_key: str, ticket: int, entry: float) -> dict:
    """Demande au bridge de poser un SL d'urgence sur ``ticket``.

    ``entry`` sert de référence de distance : SLTP_GUARD_EMERGENCY_SL_PCT %
    du prix d'entrée. Best-effort : ne raise jamais, retourne
    ``{"ok": False, "error": ...}`` sur tout problème réseau — le bridge
    reste seul juge final (exclusion, flag) via sa propre réponse.
    """
    try:
        entry = float(entry)
    except (TypeError, ValueError):
        entry = 0.0
    sl_dist = abs(entry) * SLTP_GUARD_EMERGENCY_SL_PCT / 100.0
    if sl_dist <= 0:
        return {"ok": False, "error": "sl_dist calculé <= 0 (entry inconnu ou nul)"}
    url = bridge_url.rstrip("/") + "/position/sltp"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                url,
                json={"ticket": ticket, "sl_dist": sl_dist},
                headers={"X-API-Key": api_key},
            )
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:300]}
            return {"ok": r.status_code == 200 and body.get("ok") is True, "status": r.status_code, **body}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def check_all_bridges() -> dict:
    """Scanne tous les bridges configurés.

    Retourne :
        {
          "bridges": {
            "legacy": {"reachable": bool, "naked": [...], "protect_results": [...]},
            "live": {...},
          },
          "naked_total": int,
          "protected_total": int,
          "auto_protect_enabled": bool,  # valeur du drapeau AU MOMENT du scan
        }

    Best-effort de bout en bout : un bridge injoignable donne
    ``reachable: False`` pour lui seul, jamais une exception qui ferait
    échouer tout le scan.
    """
    report = {
        "bridges": {},
        "naked_total": 0,
        "protected_total": 0,
        "auto_protect_enabled": SLTP_GUARD_AUTO_PROTECT_ENABLED,
    }
    for label, url, key in _BRIDGES:
        sub = {"reachable": False, "naked": [], "protect_results": []}
        positions = await _fetch_positions(url, key)
        if positions is None:
            report["bridges"][label] = sub
            continue
        sub["reachable"] = True
        naked = [p for p in positions if is_naked(p)]
        sub["naked"] = naked
        report["naked_total"] += len(naked)
        if naked and SLTP_GUARD_AUTO_PROTECT_ENABLED:
            for p in naked:
                res = await _protect(url, key, p.get("ticket"), p.get("price_open") or 0)
                sub["protect_results"].append({"ticket": p.get("ticket"), **res})
                if res.get("ok"):
                    report["protected_total"] += 1
        report["bridges"][label] = sub
    return report


def run() -> dict:
    """Point d'entrée synchrone pour ``python -m backend.services.sltp_guard_check``."""
    return asyncio.run(check_all_bridges())


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
