"""Runtime bridge vers les skills .claude/skills/trader-*/*.py.

## Pourquoi

Les 11 skills ``trader-*`` sont des CLI standalone (stdlib-only) qui lisent
et écrivent des fichiers JSON dans ``trader/``. auto_trader.py a sa propre
logique interne pour screener / risk / budget → les décisions ne passent
PAS par les skills, ce qui a frustré l'utilisateur ("je veux m'assurer
que les trades IBKR passent par les trader-skills").

Ce module importe les skills comme bibliothèques Python et expose des
fonctions runtime que auto_trader peut appeler à chaque cycle, avant
de poster sur le bridge IBKR.

## API exposée

Toutes les fonctions sont **sync** (les skills sont stdlib-only, pas de
networking), retournent ``dict`` avec au minimum ``ok: bool`` et ``reason: str``.

- ``risk_check(order, portfolio, prices, cfg)`` → délègue à trader-risk
- ``nyse_clock()`` → délègue à trader-alerts (ouvert ? next_open ?)
- ``market_quote(ticker)`` → délègue à trader-alerts

## Chargement des skills

Les skills vivent dans ``.claude/skills/`` qui n'est pas dans PYTHONPATH
par défaut. On les importe via ``importlib.util.spec_from_file_location``.
Si l'import échoue (skill déplacée, fichier manquant), fail-open : le
wrapper retourne ``{"ok": True, "reason": "skill_unavailable_fail_open"}``
pour ne pas bloquer le trading.

## Trace

Chaque invocation logge ``trader_skills_bridge: <skill>.<fn>() → ok=<bool> reason=<str>``
pour audit : on peut relire les logs et prouver que les skills ont bien
été consultées à chaque trade.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


SKILLS_ROOT = Path(__file__).parent.parent.parent / ".claude" / "skills"


# Cache des modules déjà importés (évite reload à chaque appel).
_SKILL_CACHE: dict[str, Any] = {}


def _load_skill(skill_name: str, module_filename: str):
    """Importe ``.claude/skills/<skill_name>/<module_filename>.py`` comme module.

    Returns le module ou ``None`` si impossible.
    """
    cache_key = f"{skill_name}/{module_filename}"
    if cache_key in _SKILL_CACHE:
        return _SKILL_CACHE[cache_key]
    try:
        path = SKILLS_ROOT / skill_name / module_filename
        if not path.exists():
            logger.warning("trader_skills_bridge: skill %s non trouvee (%s)",
                           skill_name, path)
            _SKILL_CACHE[cache_key] = None
            return None
        spec = importlib.util.spec_from_file_location(
            f"skill_{skill_name}", str(path),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SKILL_CACHE[cache_key] = mod
        logger.info("trader_skills_bridge: skill %s chargee (%s)",
                    skill_name, path)
        return mod
    except Exception as e:  # noqa: BLE001
        logger.error("trader_skills_bridge: chargement %s echoue — %s",
                     skill_name, e)
        _SKILL_CACHE[cache_key] = None
        return None


# ─── trader-risk / check.py ────────────────────────────────────────────

def risk_check(
    order: dict,
    cfg: dict | None = None,
    portfolio: dict | None = None,
    prices: dict | None = None,
) -> dict:
    """Délègue à trader-risk.check() pour valider un ordre.

    Args:
        order: dict {"symbol": "AAPL", "side": "buy", "qty": 10, ...}
        cfg: config trader-risk (défaut = DEFAULTS du skill)
        portfolio: {"cash_usd": ..., "positions": {...}}
        prices: {"AAPL": 180.5, ...}

    Returns:
        ``{"ok": bool, "reason": str, "result": dict_detail}``
    """
    mod = _load_skill("trader-risk", "check.py")
    if mod is None:
        return {"ok": True, "reason": "skill_unavailable_fail_open"}
    try:
        res = mod.check(
            orders=[order],
            cfg=cfg or {},
            portfolio=portfolio,
            prices=prices,
        )
        # res = {"results": [...], "pass": N, "block": N, "warnings": [...]}
        passed = int(res.get("pass", 0))
        blocked = int(res.get("block", 0))
        ok = (blocked == 0 and passed >= 1)
        reason = (
            "skill_risk_pass" if ok
            else f"skill_risk_block ({blocked}/{passed+blocked})"
        )
        logger.info(
            "trader_skills_bridge: trader-risk.check() → ok=%s reason=%s",
            ok, reason,
        )
        return {"ok": ok, "reason": reason, "result": res}
    except Exception as e:  # noqa: BLE001
        logger.error("trader_skills_bridge: risk_check exception — %s", e)
        return {"ok": True, "reason": f"skill_risk_exception_fail_open: {e}"}


# ─── trader-alerts / alerts.py — NYSE clock ────────────────────────────

def nyse_market_status() -> dict:
    """Retourne l'état courant du NYSE via trader-alerts.

    Returns:
        ``{"ok": bool, "status": "open"|"closed"|"pre"|..., "detail": str}``
    """
    mod = _load_skill("trader-alerts", "alerts.py")
    if mod is None:
        return {"ok": True, "status": "unknown", "detail": "skill_unavailable"}
    try:
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        session = mod.market_status(now_utc)
        # session typiquement {"status": "open", "next_open": "...", "next_close": "..."}
        status = (session or {}).get("status", "unknown")
        logger.info(
            "trader_skills_bridge: trader-alerts.market_status() → %s",
            status,
        )
        return {"ok": True, "status": status, "detail": str(session)}
    except Exception as e:  # noqa: BLE001
        logger.error("trader_skills_bridge: nyse_market_status exception — %s", e)
        return {"ok": True, "status": "unknown", "detail": f"exception: {e}"}


# ─── trader-budget / size.py ───────────────────────────────────────────

def budget_allocate(
    rows: list[dict], investable: float, cap: float = 0.25,
) -> dict:
    """Délègue à trader-budget.allocate() pour le sizing.

    Args:
        rows: [{"symbol": "AAPL", "weight": 0.2, "price": 180.5}, ...]
        investable: montant total disponible en USD
        cap: part max par ticker (0.25 = 25%)

    Returns:
        ``{"ok": bool, "allocations": [...], "reason": str}``
    """
    mod = _load_skill("trader-budget", "size.py")
    if mod is None:
        return {"ok": True, "allocations": [], "reason": "skill_unavailable_fail_open"}
    try:
        allocations = mod.allocate(rows, investable, cap)
        logger.info(
            "trader_skills_bridge: trader-budget.allocate() → %d allocations",
            len(allocations),
        )
        return {"ok": True, "allocations": allocations, "reason": "skill_budget_pass"}
    except Exception as e:  # noqa: BLE001
        logger.error("trader_skills_bridge: budget_allocate exception — %s", e)
        return {
            "ok": True, "allocations": [],
            "reason": f"skill_budget_exception_fail_open: {e}",
        }
