"""Circuit breaker drawdown sur le wallet Binance.

Chantier #15 (2026-06-18) — protège du black swan en pausant les
pushes admin_binance si la balance baisse de plus de
BINANCE_DD_BREAKER_PCT (default 5%) sur BINANCE_DD_BREAKER_WINDOW_MIN
(default 60 min).

Mécanique :
- Fetch GET /account du binance-bridge (cache TTL court pour ne pas
  spammer à chaque push).
- Maintenir une fenêtre roulante de snapshots (timestamp, wallet_balance).
- Calculer drawdown = (current - max_in_window) / max_in_window.
- Si drawdown ≤ -threshold → set_global_rafale_pause sur kill_switch,
  rejet du push appelant.

Toggle via BINANCE_DD_BREAKER_ENABLED.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ENABLED = os.getenv("BINANCE_DD_BREAKER_ENABLED", "true").strip().lower() in ("true", "1", "yes")
THRESHOLD_PCT = float(os.getenv("BINANCE_DD_BREAKER_PCT", "5.0"))  # 5% default
WINDOW_MIN = float(os.getenv("BINANCE_DD_BREAKER_WINDOW_MIN", "60.0"))
COOLDOWN_MIN = float(os.getenv("BINANCE_DD_BREAKER_COOLDOWN_MIN", "120.0"))
FETCH_CACHE_SEC = float(os.getenv("BINANCE_DD_BREAKER_FETCH_TTL_SEC", "30.0"))

_snapshots: list[tuple[float, float]] = []  # (epoch_sec, wallet_balance)
_last_fetch_at: float = 0.0
_last_fetch_value: float | None = None
_lock = threading.Lock()


def _fetch_wallet(dest) -> float | None:
    """GET /account du bridge Binance et extrait totalWalletBalance."""
    if not getattr(dest, "bridge_url", None):
        return None
    url = dest.bridge_url + "/account"
    headers: dict[str, str] = {}
    if getattr(dest, "bridge_api_key", None):
        headers["X-Bridge-Key"] = dest.bridge_api_key
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(url, headers=headers)
            if r.status_code != 200:
                logger.debug(f"dd_breaker /account → {r.status_code}: {r.text[:120]}")
                return None
            data = r.json()
            return float(data.get("totalWalletBalance", 0) or 0)
    except Exception as e:
        logger.debug(f"dd_breaker /account fetch error: {e}")
        return None


def _purge_window(now: float) -> None:
    """Drop snapshots older than WINDOW_MIN."""
    cutoff = now - WINDOW_MIN * 60.0
    while _snapshots and _snapshots[0][0] < cutoff:
        _snapshots.pop(0)


def _record_snapshot(now: float, balance: float) -> None:
    _snapshots.append((now, balance))
    _purge_window(now)


def _current_drawdown_pct() -> float | None:
    """Retourne le DD% sur la fenêtre roulante. None si <2 snapshots."""
    if len(_snapshots) < 2:
        return None
    max_in_window = max(b for _, b in _snapshots)
    if max_in_window <= 0:
        return None
    current = _snapshots[-1][1]
    return ((current - max_in_window) / max_in_window) * 100.0


def check_and_maybe_trip(dest) -> tuple[bool, str | None]:
    """À appeler avant chaque push admin_binance.

    Returns (allowed, reason_if_blocked).
    - allowed=True : push autorisé
    - allowed=False : circuit tripped, reason explique pourquoi
    """
    if not ENABLED:
        return True, None
    with _lock:
        # Si le kill_switch global est déjà ON, propage le block (mais ne
        # touche pas le kill_switch — c'est le rôle du caller mt5_bridge).
        try:
            from backend.services import kill_switch
            if kill_switch.is_active():
                return False, "global kill_switch active"
        except Exception:
            pass

        now = time.time()
        # Cache fetch pour ne pas hammer /account
        global _last_fetch_at, _last_fetch_value
        if (now - _last_fetch_at) > FETCH_CACHE_SEC or _last_fetch_value is None:
            wallet = _fetch_wallet(dest)
            if wallet is not None:
                _last_fetch_value = wallet
                _last_fetch_at = now
                _record_snapshot(now, wallet)
        else:
            wallet = _last_fetch_value

        if wallet is None:
            # Data indispo — best-effort allow (ne bloque pas faute de signal)
            return True, None

        dd_pct = _current_drawdown_pct()
        if dd_pct is None:
            return True, None  # pas assez d'historique pour conclure

        if dd_pct <= -THRESHOLD_PCT:
            reason = (
                f"Binance wallet drawdown {dd_pct:.2f}% sur {WINDOW_MIN:.0f}min "
                f"(seuil {THRESHOLD_PCT:.1f}%)"
            )
            logger.warning(f"binance_dd_breaker TRIPPED: {reason}")
            try:
                from backend.services import kill_switch
                kill_switch.set_global_rafale_pause(
                    reason=f"binance_drawdown_breaker: {reason}",
                    duration_min=int(COOLDOWN_MIN),
                )
            except Exception as e:
                logger.warning(f"dd_breaker kill_switch set failed: {e}")
            return False, reason

        return True, None


def get_status() -> dict[str, Any]:
    """Snapshot lisible pour debug / cockpit."""
    with _lock:
        dd_pct = _current_drawdown_pct()
        return {
            "enabled": ENABLED,
            "threshold_pct": THRESHOLD_PCT,
            "window_min": WINDOW_MIN,
            "cooldown_min": COOLDOWN_MIN,
            "snapshots_count": len(_snapshots),
            "current_balance": _snapshots[-1][1] if _snapshots else None,
            "max_in_window": max((b for _, b in _snapshots), default=None),
            "drawdown_pct": dd_pct,
            "last_fetch_age_sec": (time.time() - _last_fetch_at) if _last_fetch_at else None,
        }
