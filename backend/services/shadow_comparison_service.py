"""Shadow comparison MT5 (Demo + Live) vs Binance.

Chantier #25 Tier 5 (2026-06-18) — outille la décision Phase 3 en
exposant côté API la comparaison des fills par signal entre les
destinations admin_legacy, admin_live et admin_binance.

Source : table ``mt5_pushes`` (déjà alimentée pour les 3 destinations).
Identifiant naturel d'un signal = (date, pair, direction, entry_price_5dp).
Pour chaque signal, on dérive :
- destinations qui ont push (et ok)
- avg_price extrait de ``bridge_response`` JSON (Binance) ou ``price`` (MT5)
- slippage_bps = (fill - entry) / entry × 10000, signed selon direction

Pas de calcul PnL ici — c'est le rôle de trade_log_service. Cet
endpoint est pour la VISUALISATION de la qualité d'exécution comparée.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = (
    Path("/app/data/mt5_pushes.db")
    if Path("/app/data").exists()
    else Path("mt5_pushes.db")
)

# Destinations attendues (les 3 actives + futurs Premium éventuels).
_KNOWN_DESTINATIONS = ("admin_legacy", "admin_live", "admin_binance")


def _extract_fill(bridge_response_json: str | None) -> float | None:
    """Extrait avg_price (Binance) ou price (MT5) depuis le JSON bridge.

    Retourne None si parsing fail.
    """
    if not bridge_response_json:
        return None
    try:
        data = json.loads(bridge_response_json)
        # Binance bridge → avg_price ; MT5 bridge → price ; fallback fill
        for key in ("avg_price", "price", "fill", "fillPrice"):
            v = data.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def _slippage_bps(entry: float, fill: float | None, direction: str) -> float | None:
    """Slippage en bps signed. Positif = défavorable pour le trader.

    BUY défavorable = fill > entry (on paie plus).
    SELL défavorable = fill < entry (on encaisse moins).
    """
    if fill is None or entry <= 0:
        return None
    raw = (fill - entry) / entry
    if direction.lower() == "sell":
        raw = -raw  # défavorable SELL = fill < entry
    return round(raw * 10000, 2)


def get_shadow_comparison(
    days: int = 7,
    pair: str | None = None,
    direction: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Retourne la comparaison des fills par signal sur les N derniers jours.

    Args:
        days: fenêtre de recherche (défaut 7j).
        pair: filtre optionnel sur une pair (ex: "BTC/USD").
        direction: filtre optionnel sur direction (buy/sell).
        limit: max signals retournés (défaut 200, le plus récent en premier).

    Returns:
        dict avec :
        - signals: list de dict, un par signal unique avec sous-dict par destination
        - summary: agrégats par destination (count, ok_rate, avg_slippage_bps)
        - meta: filtre appliqué + horodatage
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).date().isoformat()

    where: list[str] = ["date >= ?"]
    params: list[Any] = [cutoff]
    if pair:
        where.append("pair = ?")
        params.append(pair)
    if direction:
        where.append("direction = ?")
        params.append(direction.lower())

    sql = f"""
        SELECT date, pair, direction, entry_price_5dp, destination_id,
               ok, pushed_at, bridge_response
        FROM mt5_pushes
        WHERE {" AND ".join(where)}
        ORDER BY pushed_at DESC
    """

    try:
        with sqlite3.connect(_DB_PATH) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
    except Exception as e:
        logger.warning(f"shadow_comparison db query failed: {e}")
        return {
            "signals": [], "summary": {}, "meta": {"error": str(e)[:200]},
        }

    # Regroupement par signal (date, pair, direction, entry_price_5dp)
    signals_map: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (r["date"], r["pair"], r["direction"], r["entry_price_5dp"])
        if key not in signals_map:
            try:
                entry_float = float(r["entry_price_5dp"])
            except (TypeError, ValueError):
                entry_float = 0.0
            signals_map[key] = {
                "date": r["date"],
                "pair": r["pair"],
                "direction": r["direction"],
                "entry_price": entry_float,
                "destinations": {},
            }
        fill = _extract_fill(r["bridge_response"])
        signals_map[key]["destinations"][r["destination_id"]] = {
            "ok": bool(r["ok"]),
            "pushed_at": r["pushed_at"],
            "fill_price": fill,
            "slippage_bps": _slippage_bps(
                signals_map[key]["entry_price"], fill, r["direction"],
            ),
        }

    # Tri par pushed_at desc (la plus récente destination push gouverne)
    signals_list = sorted(
        signals_map.values(),
        key=lambda s: max(
            (d["pushed_at"] for d in s["destinations"].values() if d.get("pushed_at")),
            default="",
        ),
        reverse=True,
    )[:limit]

    # Summary agrégats par destination
    summary: dict[str, dict[str, Any]] = {}
    for dest in _KNOWN_DESTINATIONS:
        slips = []
        oks = 0
        total = 0
        for s in signals_map.values():
            if dest not in s["destinations"]:
                continue
            total += 1
            d = s["destinations"][dest]
            if d["ok"]:
                oks += 1
            if d["slippage_bps"] is not None:
                slips.append(d["slippage_bps"])
        if total == 0:
            continue
        summary[dest] = {
            "total_pushes": total,
            "ok_rate": round(oks / total, 4) if total else 0.0,
            "avg_slippage_bps": round(sum(slips) / len(slips), 2) if slips else None,
            "median_slippage_bps": (
                round(sorted(slips)[len(slips) // 2], 2) if slips else None
            ),
            "slippage_samples": len(slips),
        }

    return {
        "signals": signals_list,
        "summary": summary,
        "meta": {
            "days": days,
            "pair_filter": pair,
            "direction_filter": direction,
            "limit": limit,
            "cutoff_date": cutoff,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }
