"""Promotion Engine — évalue les gates de promotion et applique les démotions.

Sprint 2 du chantier promotion criteria (mémo project_promotion_criteria_2026_07_29).

Workflow test-then-promote 5 états × destination :

  WATCH_ONLY ─(Gate 1)─► DEMO_OBSERVATION ─(Gate 2)─► DEMO_TRADABLE
    (OBSERVED)              (TELEGRAM,legacy)          (AUTO_EXEC,legacy)
                                                            │
                                                            │ (Gate 3, additive)
                                                            ▼
                                                     LIVE_OBSERVATION
                                                     (TELEGRAM,live)
                                                            │
                                                            │ (Gate 4)
                                                            ▼
                                                      LIVE_TRADABLE
                                                     (AUTO_EXEC,live)

## Sprint 2 scope

- Évaluation des 4 gates de promotion (chaque gate = critères validés Xavier 2026-07-29)
- Démotions automatiques (safety-first, appliquées sans confirmation humaine)
- Notif Telegram infra info-only pour les promotions proposées (Sprint 3 = bouton 1-clic)

## Vetos transverses (bloquent promotion)

- Kill switch actif
- Sharpe rolling 7j < 0
- Macro/geopolitical veto : skip Sprint 2 (à ajouter en 2.5)
"""
from __future__ import annotations

import logging
import os
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.services import pair_admission_controller as pac

logger = logging.getLogger(__name__)


# ─── Seuils validés Xavier 2026-07-29 ──────────────────────────────────

# Gate 1 : Watch → Demo observation
GATE_1_MIN_SIGNALS_14D = 15
GATE_1_MAX_DIRECTION_IMBALANCE_PCT = 40.0
GATE_1_MIN_AGE_DAYS = 5

# Gate 2 : Demo observation → Demo tradable
GATE_2_MIN_SETUPS_10D = 30
GATE_2_MIN_WR_PCT = 45.0
GATE_2_MIN_AGE_DAYS = 10

# Gate 3 : Demo tradable → Live observation
GATE_3_MIN_TRADES_14D = 40
GATE_3_MAX_DD_PCT = 15.0
GATE_3_MIN_SHARPE = 0.3
GATE_3_MIN_AGE_DAYS = 14

# Gate 4 : Live observation → Live tradable
GATE_4_MIN_SIGNALS_5D = 20
GATE_4_MIN_AGE_DAYS = 5

# Démotions
#
# ⛔ Le critère « N pertes consécutives » est DÉSACTIVÉ depuis le 2026-08-06
#    (`None` = inactif). Il ne mesurait rien.
#
#    Mesuré sur les 1581 trades réels : **73,4 % des fenêtres de 7 trades**
#    contiennent déjà une série de 3 pertes d'affilée. La plus longue série
#    observée par couple va de 6 à 35, médiane 12 — et le couple le plus
#    performant (EUR/USD vente, 50 % de réussite) atteint 6. Avec un taux de
#    réussite global de 23,9 %, ces séries sont la norme, pas un signal.
#
#    Conséquence : le seuil à 3 se déclenchait sur TOUS les couples, TOUJOURS.
#    Ce n'était pas un filtre de performance mais un minuteur — toute paire
#    laissée assez longtemps en auto-exécution finissait rétrogradée. Combiné
#    au plancher de 30 trades RÉELS exigé pour promouvoir (`PAC_MIN_REAL_TRADES`),
#    qu'une paire non exécutante ne peut jamais atteindre, cela formait un
#    cliquet : l'univers tradable ne pouvait que rétrécir. Constaté en
#    production — 11 couples le 04/08, 8 le 05/08, et 62 % du volume perdu.
#
#    ⚠️ Aucun seuil ne répare ce critère : les bons couples produisent des
#    séries aussi longues que les mauvais. Le remonter ne ferait que retarder
#    le minuteur. Il est laissé configurable pour pouvoir le réactiver
#    sciemment, jamais par défaut.
#
#    Le drawdown, lui, reste ACTIF : c'est une limite de perte sur une grandeur
#    mesurée (de l'argent effectivement perdu), pas une inférence statistique
#    sur trois observations. Les deux ne méritent pas le même traitement.
DEMOTION_DEMO_TRAD_MAX_CONSEC_SL = None
DEMOTION_DEMO_TRAD_MAX_DD_7D = 15.0
DEMOTION_LIVE_TRAD_MAX_CONSEC_SL = None
DEMOTION_LIVE_TRAD_MAX_DD_7D = 10.0

# Sharpe veto
SHARPE_VETO_WINDOW_DAYS = 7
SHARPE_VETO_THRESHOLD = 0.0


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _iso_since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ─── Query helpers ─────────────────────────────────────────────────────

def _query_signals_count(pair: str, direction: str, since_utc: str, min_conf: float = 60.0) -> int:
    """Count signaux ≥ min_conf depuis signal_rejections + mt5_pushes.

    Compte agrégé : chaque timestamp compté 1x même si multiples destinations rejettent.
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            n_rej = c.execute(
                """SELECT COUNT(DISTINCT created_at) FROM signal_rejections
                   WHERE pair = ? AND direction = ? AND confidence >= ?
                     AND created_at >= ?""",
                (pair, direction, min_conf, since_utc),
            ).fetchone()[0]
            n_push = c.execute(
                """SELECT COUNT(*) FROM mt5_pushes
                   WHERE pair = ? AND direction = ? AND pushed_at >= ?""",
                (pair, direction, since_utc),
            ).fetchone()[0]
        return int(n_rej) + int(n_push)
    except Exception as e:
        logger.debug(f"_query_signals_count error: {e}")
        return 0


def _query_direction_distribution(pair: str, since_utc: str) -> tuple[int, int]:
    """(n_buy, n_sell) depuis signal_rejections sur la fenêtre."""
    try:
        with sqlite3.connect(_db_path()) as c:
            buy = c.execute(
                """SELECT COUNT(*) FROM signal_rejections
                   WHERE pair = ? AND direction = 'buy' AND created_at >= ?""",
                (pair, since_utc),
            ).fetchone()[0]
            sell = c.execute(
                """SELECT COUNT(*) FROM signal_rejections
                   WHERE pair = ? AND direction = 'sell' AND created_at >= ?""",
                (pair, since_utc),
            ).fetchone()[0]
        return int(buy), int(sell)
    except Exception:
        return 0, 0


def _tickets_exclus() -> frozenset[int]:
    """Délègue à `tickets_exclus` — cf. ce module pour la raison d'être."""
    from backend.services.tickets_exclus import tickets_exclus
    return tickets_exclus()


def _query_trades_pnl(pair: str, direction: str, since_utc: str) -> list[dict]:
    """Trades fermés PnL depuis since (personal_trades admin + ea_closed_trades users).

    Query splittée pour être robuste si l'une des tables est absente (tests isolated
    ou schema pas encore migré). Chaque source contribue best-effort.

    ⚠️ La fenêtre est **temporelle** (`closed_at >= since`), pas un « N derniers
    trades » : écarter un ticket réduit l'échantillon de 1, aucun trade plus
    ancien ne remonte. C'est correct ici — il n'y a pas de compte à tenir plein,
    contrairement aux deux autres juges qui bornent par `LIMIT`.
    """
    from backend.services.tickets_exclus import filtre_sql
    exclus = _tickets_exclus()
    filtre = filtre_sql(exclus)
    ex = tuple(exclus)
    rows: list[dict] = []
    # 1. personal_trades (admin Xavier + admin_legacy/live si sync)
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            r = c.execute(
                f"""
                SELECT pnl, closed_at, close_reason FROM personal_trades
                 WHERE pair = ? AND direction = ? AND status = 'CLOSED'
                   AND is_auto = 1 AND pnl IS NOT NULL AND closed_at >= ?{filtre}
                ORDER BY closed_at DESC
                """,
                (pair, direction, since_utc) + ex,
            ).fetchall()
            rows.extend(dict(x) for x in r)
    except Exception as e:
        logger.debug(f"_query_trades_pnl personal_trades error: {e}")

    # 2. ea_closed_trades (users Premium via EA MQL5)
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            r = c.execute(
                f"""
                SELECT pnl, closed_at, close_reason FROM ea_closed_trades
                 WHERE pair = ? AND direction = ? AND closed_at >= ?{filtre}
                ORDER BY closed_at DESC
                """,
                (pair, direction, since_utc) + ex,
            ).fetchall()
            rows.extend(dict(x) for x in r)
    except Exception as e:
        logger.debug(f"_query_trades_pnl ea_closed_trades error: {e}")

    # Tri final unifié newest-first
    rows.sort(key=lambda r: r.get("closed_at") or "", reverse=True)
    return rows


def _compute_metrics(trades: list[dict]) -> dict:
    """Retourne dict avec n, WR, EV, DD%, Sharpe, PnL cumulé, N SL consécutifs."""
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0.0, "ev": 0.0, "dd_pct": 0.0, "sharpe": 0.0,
                "pnl_cumul": 0.0, "n_consec_sl": 0}
    pnls = [float(t.get("pnl", 0.0) or 0.0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    wr = 100.0 * wins / n
    pnl_cumul = sum(pnls)
    ev = pnl_cumul / n

    # DD : chronological (oldest → newest), track peak equity
    chrono = list(reversed(pnls))
    cumul = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in chrono:
        cumul += p
        if cumul > peak:
            peak = cumul
        dd = peak - cumul
        if dd > max_dd:
            max_dd = dd

    # DD % relatif au capital théorique
    try:
        from config.settings import TRADING_CAPITAL
        capital = float(TRADING_CAPITAL) if TRADING_CAPITAL else 3000.0
    except Exception:
        capital = 3000.0
    dd_pct = 100.0 * max_dd / capital if capital > 0 else 0.0

    # Sharpe simplifié
    if n > 1:
        mean = statistics.mean(pnls)
        std = statistics.pstdev(pnls)
        sharpe = mean / std if std > 0 else 0.0
    else:
        sharpe = 0.0

    # SL consécutifs depuis le trade le plus récent (trades ordered newest → oldest)
    n_consec_sl = 0
    for p in pnls:
        if p < 0:
            n_consec_sl += 1
        else:
            break

    return {
        "n": n,
        "wr": round(wr, 1),
        "ev": round(ev, 2),
        "dd_pct": round(dd_pct, 2),
        "sharpe": round(sharpe, 3),
        "pnl_cumul": round(pnl_cumul, 2),
        "n_consec_sl": n_consec_sl,
    }


def _sharpe_recent_days(pair: str, direction: str, days: int) -> float:
    trades = _query_trades_pnl(pair, direction, _iso_since(days))
    return _compute_metrics(trades)["sharpe"]


def _state_age_days(pair: str, direction: str, destination: Optional[str]) -> Optional[float]:
    """Nombre de jours depuis que l'état actuel a été set (via state_since)."""
    full = pac.get_full_state(pair, direction=direction, destination=destination)
    since = full.get("state_since")
    if not since:
        return None
    try:
        since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - since_dt).total_seconds() / 86400
    except Exception:
        return None


# ─── Vetos ─────────────────────────────────────────────────────────────

def _check_vetos(pair: str, direction: str) -> list[str]:
    """Liste des veto reasons actifs. Vide = aucun veto → promotion possible."""
    vetos: list[str] = []

    # Kill switch actif dans les 24h précédentes
    try:
        from backend.services import kill_switch
        if kill_switch.is_active(pair=pair):
            vetos.append("kill_switch_active")
    except Exception as e:
        logger.debug(f"kill_switch veto check: {e}")

    # Sharpe rolling 7j < 0
    try:
        sharpe_7d = _sharpe_recent_days(pair, direction, SHARPE_VETO_WINDOW_DAYS)
        if sharpe_7d < SHARPE_VETO_THRESHOLD:
            vetos.append(f"sharpe_7d_below_{SHARPE_VETO_THRESHOLD}:{sharpe_7d:.3f}")
    except Exception as e:
        logger.debug(f"sharpe veto check: {e}")

    # Macro/geopolitical veto : à ajouter en Sprint 2.5 (nécessite lookup macro_daily + geopolitical_snapshots)
    return vetos


# ─── Gate evaluations ──────────────────────────────────────────────────

def evaluate_gate_1_watch_to_demo_obs(pair: str, direction: str) -> dict:
    """Watch → Demo observation. Critères : ≥15 signaux ≥60 sur 14j, imbalance ≤40%, age ≥5j."""
    since = _iso_since(14)
    n_signals = _query_signals_count(pair, direction, since)
    n_buy, n_sell = _query_direction_distribution(pair, since)
    total_dir = n_buy + n_sell
    imbalance = 100.0 * abs(n_buy - n_sell) / total_dir if total_dir else 100.0
    age = _state_age_days(pair, direction, destination=None)

    blockers = []
    if n_signals < GATE_1_MIN_SIGNALS_14D:
        blockers.append(f"signals_below_{GATE_1_MIN_SIGNALS_14D}:{n_signals}")
    if imbalance > GATE_1_MAX_DIRECTION_IMBALANCE_PCT:
        blockers.append(f"direction_imbalance:{imbalance:.1f}%")
    if age is not None and age < GATE_1_MIN_AGE_DAYS:
        blockers.append(f"age_below_{GATE_1_MIN_AGE_DAYS}d:{age:.1f}")

    vetos = _check_vetos(pair, direction)
    return {
        "gate": "1_watch_to_demo_obs",
        "eligible": not blockers and not vetos,
        "blockers": blockers,
        "vetos": vetos,
        "metrics": {
            "signals_14d": n_signals,
            "imbalance_pct": round(imbalance, 1),
            "age_days": round(age, 1) if age is not None else None,
        },
    }


def evaluate_gate_2_demo_obs_to_demo_trad(pair: str, direction: str) -> dict:
    """Demo obs → Demo tradable. Critères : ≥30 trades sur ≥10j, WR≥45%, EV>0, age≥10j."""
    trades = _query_trades_pnl(pair, direction, _iso_since(10))
    m = _compute_metrics(trades)
    age = _state_age_days(pair, direction, destination="admin_legacy")

    blockers = []
    if m["n"] < GATE_2_MIN_SETUPS_10D:
        blockers.append(f"trades_below_{GATE_2_MIN_SETUPS_10D}:{m['n']}")
    if m["wr"] < GATE_2_MIN_WR_PCT:
        blockers.append(f"wr_below_{GATE_2_MIN_WR_PCT}%:{m['wr']}")
    if m["ev"] <= 0:
        blockers.append(f"ev_non_positive:{m['ev']}")
    if age is not None and age < GATE_2_MIN_AGE_DAYS:
        blockers.append(f"age_below_{GATE_2_MIN_AGE_DAYS}d:{age:.1f}")

    vetos = _check_vetos(pair, direction)
    return {
        "gate": "2_demo_obs_to_demo_trad",
        "eligible": not blockers and not vetos,
        "blockers": blockers,
        "vetos": vetos,
        "metrics": {**m, "age_days": round(age, 1) if age is not None else None},
    }


def evaluate_gate_3_demo_trad_to_live_obs(pair: str, direction: str) -> dict:
    """Demo trad → Live observation. Critères : ≥40 trades sur ≥14j, PnL>0, DD≤15%, Sharpe>0.3, age≥14j."""
    trades = _query_trades_pnl(pair, direction, _iso_since(14))
    m = _compute_metrics(trades)
    age = _state_age_days(pair, direction, destination="admin_legacy")

    blockers = []
    if m["n"] < GATE_3_MIN_TRADES_14D:
        blockers.append(f"trades_below_{GATE_3_MIN_TRADES_14D}:{m['n']}")
    if m["pnl_cumul"] <= 0:
        blockers.append(f"pnl_cumul_non_positive:{m['pnl_cumul']}")
    if m["dd_pct"] > GATE_3_MAX_DD_PCT:
        blockers.append(f"dd_above_{GATE_3_MAX_DD_PCT}%:{m['dd_pct']}")
    if m["sharpe"] < GATE_3_MIN_SHARPE:
        blockers.append(f"sharpe_below_{GATE_3_MIN_SHARPE}:{m['sharpe']}")
    if age is not None and age < GATE_3_MIN_AGE_DAYS:
        blockers.append(f"age_below_{GATE_3_MIN_AGE_DAYS}d:{age:.1f}")

    vetos = _check_vetos(pair, direction)
    return {
        "gate": "3_demo_trad_to_live_obs",
        "eligible": not blockers and not vetos,
        "blockers": blockers,
        "vetos": vetos,
        "metrics": {**m, "age_days": round(age, 1) if age is not None else None},
    }


def evaluate_gate_4_live_obs_to_live_trad(pair: str, direction: str) -> dict:
    """Live obs → Live tradable. Critères : ≥20 signaux Live obs sur ≥5j, age≥5j.

    Sprint 2 : critères Live-specific (slippage, coût, delta WR) reportés au Sprint 2.5
    car nécessitent un flow de log Live observation qui n'existe pas encore.
    """
    n_signals = _query_signals_count(pair, direction, _iso_since(5))
    age = _state_age_days(pair, direction, destination="admin_live")

    blockers = []
    if n_signals < GATE_4_MIN_SIGNALS_5D:
        blockers.append(f"signals_below_{GATE_4_MIN_SIGNALS_5D}:{n_signals}")
    if age is not None and age < GATE_4_MIN_AGE_DAYS:
        blockers.append(f"age_below_{GATE_4_MIN_AGE_DAYS}d:{age:.1f}")

    vetos = _check_vetos(pair, direction)
    return {
        "gate": "4_live_obs_to_live_trad",
        "eligible": not blockers and not vetos,
        "blockers": blockers,
        "vetos": vetos,
        "metrics": {
            "signals_5d": n_signals,
            "age_days": round(age, 1) if age is not None else None,
        },
    }


# ─── Démotion ──────────────────────────────────────────────────────────

def check_demotion(pair: str, direction: str, destination: str) -> Optional[dict]:
    """Retourne dict de démotion si conditions remplies, sinon None.

    Règles :
    - Demo tradable  : DD>15% sur 7j → retour Demo obs (TELEGRAM legacy)
    - Live tradable  : DD>10% sur 7j → retour Live obs (TELEGRAM live)

    Le critère « N pertes consécutives » est inactif par défaut — voir le bloc
    de constantes pour la mesure qui l'a disqualifié. Il n'est appliqué que si
    son seuil est explicitement renseigné (non `None`).
    """
    state = pac.get_current_state(pair, direction, destination)
    if state != pac.STATE_AUTO_EXEC:
        return None
    trades = _query_trades_pnl(pair, direction, _iso_since(7))
    m = _compute_metrics(trades)

    if destination == "admin_legacy":
        seuil_sl = DEMOTION_DEMO_TRAD_MAX_CONSEC_SL
        seuil_dd = DEMOTION_DEMO_TRAD_MAX_DD_7D
    elif destination == "admin_live":
        seuil_sl = DEMOTION_LIVE_TRAD_MAX_CONSEC_SL
        seuil_dd = DEMOTION_LIVE_TRAD_MAX_DD_7D
    else:
        return None

    # Inférence statistique — désactivée par défaut, cf. bloc de constantes.
    if seuil_sl is not None and m["n_consec_sl"] >= seuil_sl:
        return {"trigger": f"{seuil_sl}_consec_sl",
                "to_state": pac.STATE_TELEGRAM, "metrics": m}
    # Limite de perte sur une grandeur mesurée — toujours active.
    if m["dd_pct"] > seuil_dd:
        return {"trigger": f"dd_above_{seuil_dd}%_7d:{m['dd_pct']}",
                "to_state": pac.STATE_TELEGRAM, "metrics": m}
    return None


# ─── Cycle runner ──────────────────────────────────────────────────────

def _select_next_gate(state_legacy: str, state_live: str) -> Optional[str]:
    """Retourne le nom du gate applicable en fonction des états courants, ou None."""
    if state_legacy == pac.STATE_OBSERVED:
        return "gate_1"
    if state_legacy == pac.STATE_TELEGRAM and state_live in (pac.STATE_OBSERVED, pac.DEFAULT_STATE):
        return "gate_2"
    if state_legacy == pac.STATE_AUTO_EXEC and state_live in (pac.STATE_OBSERVED, pac.DEFAULT_STATE):
        return "gate_3"
    if state_legacy == pac.STATE_AUTO_EXEC and state_live == pac.STATE_TELEGRAM:
        return "gate_4"
    return None


def run_promotion_cycle() -> dict:
    """Boucle nightly : démotions auto d'abord, puis proposition promotions (Sprint 2 = notif only).

    Retourne un dict summary avec compteurs + détails.
    """
    try:
        from config.settings import WATCHED_PAIRS
    except Exception:
        WATCHED_PAIRS = []

    promotions_proposed: list[dict] = []
    demotions_applied: list[dict] = []
    errors: list[dict] = []

    for pair in WATCHED_PAIRS:
        for direction in ("buy", "sell"):
            try:
                # 1. Safety first : check démotions sur les 2 destinations
                for dest in ("admin_legacy", "admin_live"):
                    dem = check_demotion(pair, direction, dest)
                    if dem:
                        pac.set_state(
                            pair, dem["to_state"],
                            reason=f"auto:demotion:{dem['trigger']}",
                            direction=direction,
                            destination=dest,
                            score_snapshot=dem["metrics"],
                            transitioned_by="auto:promotion_engine",
                        )
                        demotions_applied.append({
                            "pair": pair, "direction": direction,
                            "destination": dest, "trigger": dem["trigger"],
                        })

                # 2. Évalue le gate applicable au nouvel état
                state_legacy = pac.get_current_state(pair, direction, destination="admin_legacy")
                state_live = pac.get_current_state(pair, direction, destination="admin_live")
                gate = _select_next_gate(state_legacy, state_live)
                if not gate:
                    continue

                if gate == "gate_1":
                    result = evaluate_gate_1_watch_to_demo_obs(pair, direction)
                elif gate == "gate_2":
                    result = evaluate_gate_2_demo_obs_to_demo_trad(pair, direction)
                elif gate == "gate_3":
                    result = evaluate_gate_3_demo_trad_to_live_obs(pair, direction)
                elif gate == "gate_4":
                    result = evaluate_gate_4_live_obs_to_live_trad(pair, direction)
                else:
                    continue

                if result["eligible"]:
                    promotions_proposed.append({
                        "pair": pair, "direction": direction,
                        "gate": result["gate"], "metrics": result["metrics"],
                    })
            except PermissionError as refus:
                # ⛔ Un refus du banc d'essai est une DÉCISION, pas une panne — et
                # le cycle en rencontrera à chaque tour dès que la porte sera
                # armée. Le journaliser en `exception` dirait « échec » là où le
                # dispositif fait son travail. Même correction que dans
                # `pair_admission_controller.check_and_regulate` : une parade
                # posée sur un chemin n'est pas posée sur l'autre.
                logger.warning("promotion_engine: %s/%s refusé par le banc — %s",
                               pair, direction, refus)
                errors.append({"pair": pair, "direction": direction,
                               "refused_by_bench": str(refus)})
            except Exception as e:
                logger.exception(f"promotion_engine: error {pair}/{direction}: {e}")
                errors.append({"pair": pair, "direction": direction, "error": str(e)})

    if promotions_proposed or demotions_applied:
        _notify_telegram_infra(promotions_proposed, demotions_applied)

    summary = {
        "promotions_proposed": len(promotions_proposed),
        "demotions_applied": len(demotions_applied),
        "errors": len(errors),
        "details": {
            "promotions": promotions_proposed,
            "demotions": demotions_applied,
        },
    }
    logger.warning(
        f"promotion_engine: cycle done — {len(promotions_proposed)} proposed, "
        f"{len(demotions_applied)} demoted, {len(errors)} errors"
    )
    return summary


def _notify_telegram_infra(promotions: list[dict], demotions: list[dict]) -> None:
    """Post au bot infra Telegram via /api/admin/notify-infra-telegram (best-effort)."""
    try:
        import httpx
        title = "🎯 Promotion Engine — cycle nightly"
        lines: list[str] = []
        if promotions:
            lines.append(f"*{len(promotions)} promotion(s) proposée(s)* :")
            for p in promotions[:10]:
                lines.append(f"  • {p['pair']} {p['direction']} → {p['gate']}")
        if demotions:
            lines.append(f"*{len(demotions)} démotion(s) appliquée(s)* :")
            for d in demotions[:10]:
                lines.append(
                    f"  • {d['pair']} {d['direction']} @{d['destination']} : {d['trigger']}"
                )
        body = "\n".join(lines) if lines else "Rien à signaler."

        token = os.getenv("INFRA_TELEGRAM_TOKEN", "").strip()
        if not token:
            logger.debug("promotion_engine: INFRA_TELEGRAM_TOKEN not set, skip notif")
            return

        base_url = os.getenv("INTERNAL_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        r = httpx.post(
            f"{base_url}/api/admin/notify-infra-telegram",
            json={"title": title, "body": body},
            headers={"X-Admin-Token": token},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"promotion_engine: telegram notif failed: {e}")
