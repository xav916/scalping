"""Pair Admission Controller — état des pairs dans le pipeline auto-exec.

Généralisation du pair_pnl_regulator. Au lieu d'une simple liste hardcodée
de "stars" + un mécanisme de pause, on a une vraie state machine par pair :

  OBSERVED ──(score promotion OK)──► TELEGRAM ──(admin valide)──► AUTO_EXEC
  AUTO_EXEC ──(sum_pnl < -3% sur 30 trades)──► PAUSED
  PAUSED ──(cool-off 14j + re-eval)──► AUTO_EXEC ou OBSERVED
  PAUSED ──(2× re-pause sur 60j)──► DEMOTED
  DEMOTED ──(manuel)──► OBSERVED

## États

- **OBSERVED** : pair scannée par V1, signaux générés en interne, AUCUN
  push Telegram, AUCUN auto-exec. Source de scoring = shadow_setups
  (backtest live Track A V2) + historique personal_trades / ea_closed_trades
  pour pairs qui ont été AUTO_EXEC dans le passé.
- **TELEGRAM** : niveau intermédiaire, le user reçoit les signaux sur
  Telegram avec verdict TAKE/SKIP/WAIT mais l'auto-exec bridge MT5 NE
  s'enclenche PAS. Permet à l'humain de valider avant d'accorder l'auto-
  exec — passage à AUTO_EXEC = manuel par défaut.
- **AUTO_EXEC** : signaux Telegram + envoi auto au bridge MT5 pour tous
  les users Premium éligibles.
- **PAUSED** : équivalent au pair_pnl_regulator actuel. Push Telegram en
  mode "info" (verdict forcé SKIP), bridge bloqué. Auto-revue après 14j.
- **DEMOTED** : pair sortie de la plateforme après 2 pauses répétées.
  Plus de push Telegram, plus d'exec. Seul un admin manuel peut la
  remettre en OBSERVED.

## Auto-promote vs manuel

Promotion auto : OBSERVED → TELEGRAM (humain peut voir et valider)
Promotion manuelle : TELEGRAM → AUTO_EXEC (entrée d'argent réel = humain
dans la boucle, philosophie loss-averse asymétrique)

Demotion auto : tout le reste (AUTO_EXEC → PAUSED, PAUSED → DEMOTED).

## Source de vérité

Table `pair_admission_state` (historique des transitions, l'état courant
= la row la plus récente pour chaque pair). Permet l'audit du chemin de
chaque pair dans la plateforme.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# États valides (cohérent avec le CHECK contrainte SQL)
STATE_OBSERVED = "OBSERVED"
STATE_TELEGRAM = "TELEGRAM"
STATE_AUTO_EXEC = "AUTO_EXEC"
STATE_PAUSED = "PAUSED"
STATE_DEMOTED = "DEMOTED"

VALID_STATES = frozenset([
    STATE_OBSERVED, STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED, STATE_DEMOTED
])

# Default si pair n'a jamais été vue par le controller : on observe par défaut
# (= ne pas envoyer Telegram ni auto-exec sans décision explicite)
DEFAULT_STATE = STATE_OBSERVED

_SCHEMA_ENSURED = False


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def _ensure_schema() -> None:
    """Crée pair_admission_state si pas déjà là. Idempotent.

    Évolution 2026-05-13 : ajout colonne ``direction`` (NULL pour les rows
    pair-level legacy, 'buy' ou 'sell' pour les rows direction-specific).
    Migration douce : les rows existantes restent direction IS NULL et
    s'appliquent à toutes les directions. Les nouvelles rows
    (pair × direction) overrident les rows pair-level pour le sens donné.
    """
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    with sqlite3.connect(_db_path()) as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS pair_admission_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('OBSERVED', 'TELEGRAM', 'AUTO_EXEC', 'PAUSED', 'DEMOTED')),
                state_since TEXT NOT NULL,
                reason TEXT,
                score_snapshot TEXT,
                transitioned_by TEXT NOT NULL DEFAULT 'auto'
            )
            """
        )
        # Migration : ajoute la colonne direction si absente (idempotent via try)
        try:
            c.execute("ALTER TABLE pair_admission_state ADD COLUMN direction TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_since ON pair_admission_state(pair, state_since DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_dir_since ON pair_admission_state(pair, direction, state_since DESC)"
        )
    _SCHEMA_ENSURED = True


# ─── Read API ───────────────────────────────────────────────────────────


def _normalize_direction(direction: Optional[str]) -> Optional[str]:
    """Normalise direction en 'buy'/'sell' ou None. Valide les entrées."""
    if direction is None:
        return None
    d = str(direction).strip().lower()
    if d in ("buy", "long", "b"):
        return "buy"
    if d in ("sell", "short", "s"):
        return "sell"
    return None  # entrée invalide → fallback pair-level


def get_current_state(pair: str, direction: Optional[str] = None) -> str:
    """Retourne l'état courant pour (pair, direction).

    Résolution :
    1. Si direction fournie : cherche row direction-specific (= row où la
       colonne direction = direction) la plus récente.
    2. Sinon ou si pas de row spécifique : cherche row pair-level (= row
       où direction IS NULL) la plus récente.
    3. Sinon : retourne DEFAULT_STATE.

    Cette résolution permet la migration douce : les rows existantes
    (direction IS NULL = pair-level legacy) restent honorées tant qu'on
    n'a pas posé de row direction-specific qui override.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    with sqlite3.connect(_db_path()) as c:
        if direction is not None:
            # 1. Row direction-specific
            row = c.execute(
                """
                SELECT state FROM pair_admission_state
                 WHERE pair = ? AND direction = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
            if row:
                return row[0]
        # 2. Row pair-level legacy (direction IS NULL)
        row = c.execute(
            """
            SELECT state FROM pair_admission_state
             WHERE pair = ? AND direction IS NULL
             ORDER BY state_since DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    return row[0] if row else DEFAULT_STATE


def get_full_state(pair: str, direction: Optional[str] = None) -> dict[str, Any]:
    """Retourne l'état + métadonnées (state_since, reason, score).

    Même résolution que get_current_state : direction-specific d'abord,
    fallback pair-level.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = None
        if direction is not None:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
        if not row:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair,),
            ).fetchone()
    if not row:
        return {"pair": pair, "direction": direction, "state": DEFAULT_STATE,
                "state_since": None, "reason": None, "score_snapshot": None,
                "transitioned_by": None}
    d = dict(row)
    if d.get("score_snapshot"):
        try:
            d["score_snapshot"] = json.loads(d["score_snapshot"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_all_states() -> list[dict[str, Any]]:
    """Retourne l'état courant de tous les (pair × direction) qui ont une row.

    Une row par bucket (pair, direction) — ex: 3 rows possibles par pair
    (pair-level NULL + buy + sell). Le caller peut filtrer/grouper selon ses
    besoins. Pour l'univers complet, inclure WATCHED_PAIRS (default OBSERVED).
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        # On groupe par (pair, direction) avec IS NULL bien traité via COALESCE
        rows = c.execute(
            """
            SELECT pas.* FROM pair_admission_state pas
             INNER JOIN (
                SELECT pair, COALESCE(direction, '__null__') AS dir_key,
                       MAX(state_since) AS max_since
                  FROM pair_admission_state
                 GROUP BY pair, dir_key
             ) latest
               ON pas.pair = latest.pair
              AND COALESCE(pas.direction, '__null__') = latest.dir_key
              AND pas.state_since = latest.max_since
             ORDER BY pas.pair, pas.direction
            """
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("score_snapshot"):
            try:
                d["score_snapshot"] = json.loads(d["score_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


# ─── Eligibility helpers (utilisés par mt5_bridge + telegram_service) ───


def _has_explicit_state(pair: str, direction: Optional[str] = None) -> bool:
    """True si (pair, direction) a au moins une row dans pair_admission_state.

    Si direction fournie : True si row direction-specific OU row pair-level.
    Si direction None : True si au moins une row existe pour pair.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    with sqlite3.connect(_db_path()) as c:
        if direction is not None:
            row = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? AND (direction = ? OR direction IS NULL) LIMIT 1",
                (pair, direction),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1",
                (pair,),
            ).fetchone()
    return bool(row)


def is_auto_exec_eligible(pair: str, direction: Optional[str] = None) -> bool:
    """True si (pair, direction) peut être pushée vers le bridge MT5.

    Migration douce : si pas de row pour (pair, direction) ni pair-level,
    retourne False et le callsite fait son fallback _STAR_PAIRS_SET legacy.
    """
    if not _has_explicit_state(pair, direction):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction) == STATE_AUTO_EXEC


def is_telegram_eligible(pair: str, direction: Optional[str] = None) -> bool:
    """True si (pair, direction) peut générer un push Telegram user-facing.

    PAUSED inclus : on continue à informer le user mais avec verdict SKIP
    forcé côté setup (= signal info, pas trade reco).
    """
    if not _has_explicit_state(pair, direction):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction) in (STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED)


def has_explicit_state(pair: str, direction: Optional[str] = None) -> bool:
    """API publique de _has_explicit_state pour les callers qui veulent
    décider eux-mêmes du fallback legacy."""
    return _has_explicit_state(pair, direction)


# ─── Write API ──────────────────────────────────────────────────────────


def set_state(
    pair: str,
    new_state: str,
    reason: str,
    direction: Optional[str] = None,
    score_snapshot: Optional[dict] = None,
    transitioned_by: str = "auto",
) -> int:
    """Transitionne (pair, direction) vers un nouvel état. Idempotent.

    Si direction=None : insère une row pair-level (= s'applique à tous
    les sens en l'absence de row direction-specific).
    Si direction='buy'/'sell' : insère une row direction-specific qui
    override le pair-level pour ce sens.
    """
    if new_state not in VALID_STATES:
        raise ValueError(f"État invalide : {new_state}. Doit être dans {VALID_STATES}")
    _ensure_schema()
    direction = _normalize_direction(direction)

    current = get_current_state(pair, direction)
    if current == new_state:
        logger.debug(f"pair_admission: {pair}/{direction} déjà {new_state}, no-op")
        return -1

    now = datetime.now(timezone.utc).isoformat()
    score_json = json.dumps(score_snapshot) if score_snapshot else None
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO pair_admission_state
                (pair, direction, state, state_since, reason, score_snapshot, transitioned_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pair, direction, new_state, now, reason, score_json, transitioned_by),
        )
        new_id = cur.lastrowid
    dir_label = f"/{direction}" if direction else ""
    logger.warning(
        f"pair_admission: {pair}{dir_label} {current} → {new_state} by={transitioned_by} reason={reason}"
    )

    # Notification Telegram infra des transitions, sauf le backfill initial
    # (= silencieux pour ne pas spammer ~30 messages au déploiement). Best-effort :
    # toute erreur Telegram est swallowée pour ne jamais bloquer l'écriture DB.
    if not transitioned_by.startswith("auto:backfill"):
        try:
            _notify_transition(pair, direction, current, new_state, reason, score_snapshot, transitioned_by)
        except Exception as e:
            logger.debug(f"pair_admission: telegram notify failed: {e}")

    return new_id


def _notify_transition(
    pair: str,
    direction: Optional[str],
    from_state: str,
    to_state: str,
    reason: str,
    score: Optional[dict],
    transitioned_by: str,
) -> None:
    """Pousse une alerte HTML sur le canal Telegram infra @xav_scalping_infra_bot.

    Format compact : pair/direction, transition, raison + métriques score si dispo.
    Best-effort fire-and-forget. Si l'event loop n'a pas de session async dispo,
    on lance la coroutine dans un thread isolé pour ne pas bloquer le caller.
    """
    import asyncio
    import html
    from backend.services.telegram_service import send_infra_text

    dir_label = direction.upper() if direction else "pair-level"
    safe_reason = html.escape((reason or "").strip())[:200]

    # Emoji selon transition pour scanability
    arrow = {
        ("OBSERVED", "TELEGRAM"): "📈",
        ("TELEGRAM", "OBSERVED"): "📉",
        ("AUTO_EXEC", "PAUSED"): "⏸",
        ("PAUSED", "AUTO_EXEC"): "▶️",
        ("PAUSED", "DEMOTED"): "❌",
        ("OBSERVED", "AUTO_EXEC"): "📈",
    }.get((from_state, to_state), "🔄")

    lines = [
        f"{arrow} <b>Pair admission</b> · <code>{html.escape(pair)}</code> · {dir_label}",
        f"<b>{from_state}</b> → <b>{to_state}</b>",
        f"Raison : {safe_reason}",
    ]
    if score and isinstance(score, dict) and score.get("sample"):
        lines.append(
            f"Score : n={score.get('sample')} pnl%={score.get('pnl_pct')} "
            f"WR%={score.get('wr')} PF={score.get('pf')} maxDD%={score.get('max_dd_pct')}"
        )
    if transitioned_by and transitioned_by != "auto":
        lines.append(f"By : {html.escape(transitioned_by)}")
    text = "\n".join(lines)

    # Run la coroutine send_infra_text dans le contexte approprié
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = send_infra_text(text, parse_mode="HTML")
    if loop and loop.is_running():
        # Schedule sans bloquer (fire-and-forget)
        asyncio.ensure_future(coro)
    else:
        # Pas de loop actif (test ou contexte sync) → run sync
        asyncio.run(coro)


# ─── Score composite + transitions auto ─────────────────────────────────

# Seuils par défaut (overridables via env). On garde des seuils prudents
# côté promotion (asymétrique avec demotion) — philosophie loss-averse.
PROMOTE_MIN_SAMPLE = 30           # nb minimum de setups pour évaluer une pair
PROMOTE_MIN_PNL_PCT = 2.0         # +2% sur le capital sur la fenêtre
PROMOTE_MIN_WR_PCT = 45.0         # WR (Win Rate) ≥ 45% pour promote
PROMOTE_MIN_PF = 1.3              # PF (Profit Factor) ≥ 1.3
PROMOTE_MAX_DD_PCT = 10.0         # Drawdown max < 10% du capital

DEMOTE_MAX_RE_PAUSES_60D = 2      # 2× re-pause auto en 60j → DEMOTED


def _compute_pf(trades_pnl: list[float]) -> float:
    """Profit Factor = sum(gains) / sum(losses en absolu). Inf si pas de loss."""
    gains = sum(p for p in trades_pnl if p > 0)
    losses = abs(sum(p for p in trades_pnl if p < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return round(gains / losses, 2)


def _compute_max_dd(trades_pnl: list[float], capital: float) -> float:
    """Drawdown max en % du capital sur la séquence chronologique des trades.

    On prend l'equity curve = cumul des PnL, et on calcule le plus grand
    écart entre un pic et le creux suivant. Le résultat est exprimé en %
    négatif (ex: -7.5 = -7.5% du capital).
    """
    if not trades_pnl or capital <= 0:
        return 0.0
    # On reverse car nos sources retournent DESC par date — on veut chrono ASC
    chrono = list(reversed(trades_pnl))
    equity = 0.0
    peak = 0.0
    max_dd_eur = 0.0
    for p in chrono:
        equity += p
        peak = max(peak, equity)
        dd = equity - peak
        max_dd_eur = min(max_dd_eur, dd)
    return round(100.0 * max_dd_eur / capital, 2)


def _fetch_trades_for_pair(pair: str, window: int, direction: Optional[str] = None) -> list[float]:
    """Union admin (personal_trades) + Premium (ea_closed_trades) + shadow.

    Filtre optionnel par direction ('buy' ou 'sell'). Si direction None,
    agrège toutes directions confondues (= comportement pair-level).
    Pour scoring d'une pair OBSERVED sans live trades, fallback sur
    shadow_setups (Track A V2 backtest live).
    """
    _ensure_schema()
    from backend.services import ea_closed_trades_service as _eact
    _eact._ensure_schema()
    direction = _normalize_direction(direction)
    pnls: list[float] = []

    with sqlite3.connect(_db_path()) as c:
        if direction is not None:
            # Filtre par direction sur toutes les sources
            rows = c.execute(
                """
                SELECT pnl, closed_at FROM personal_trades
                 WHERE pair = ? AND status = 'CLOSED'
                   AND is_auto = 1 AND pnl IS NOT NULL
                   AND LOWER(direction) = ?
                UNION ALL
                SELECT pnl, closed_at FROM ea_closed_trades
                 WHERE pair = ? AND LOWER(direction) = ?
                ORDER BY closed_at DESC LIMIT ?
                """,
                (pair, direction, pair, direction, window),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT pnl, closed_at FROM personal_trades
                 WHERE pair = ? AND status = 'CLOSED'
                   AND is_auto = 1 AND pnl IS NOT NULL
                UNION ALL
                SELECT pnl, closed_at FROM ea_closed_trades WHERE pair = ?
                ORDER BY closed_at DESC LIMIT ?
                """,
                (pair, pair, window),
            ).fetchall()
        for r in rows:
            pnls.append(float(r[0]))

        # Fallback shadow_setups si pas assez de live
        if len(pnls) < window:
            need = window - len(pnls)
            if direction is not None:
                shadow_rows = c.execute(
                    """
                    SELECT pnl_eur FROM shadow_setups
                     WHERE pair = ? AND outcome IS NOT NULL
                       AND outcome != 'OPEN' AND pnl_eur IS NOT NULL
                       AND LOWER(direction) = ?
                     ORDER BY exit_at DESC LIMIT ?
                    """,
                    (pair, direction, need),
                ).fetchall()
            else:
                shadow_rows = c.execute(
                    """
                    SELECT pnl_eur FROM shadow_setups
                     WHERE pair = ? AND outcome IS NOT NULL
                       AND outcome != 'OPEN' AND pnl_eur IS NOT NULL
                     ORDER BY exit_at DESC LIMIT ?
                    """,
                    (pair, need),
                ).fetchall()
            for r in shadow_rows:
                pnls.append(float(r[0]))
    return pnls


def compute_promotion_score(pair: str, window: int = 30, direction: Optional[str] = None) -> dict[str, Any]:
    """Calcule le score composite pour décider si (pair, direction) peut transiter.

    Si direction None : agrège toutes directions (= scoring pair-level legacy).
    Si direction 'buy'/'sell' : scoring restreint à ce sens.

    Retourne :
    - sample : nb total de trades évalués
    - sum_pnl : PnL cumulé en euros
    - pnl_pct : PnL en % du capital (cf TRADING_CAPITAL config)
    - wr : Win Rate en %
    - pf : Profit Factor
    - max_dd_pct : Max Drawdown en % du capital (négatif)
    - eligible_for : 'AUTO_EXEC' | 'TELEGRAM' | 'OBSERVED' (la cible naturelle)
    """
    from config.settings import TRADING_CAPITAL
    pnls = _fetch_trades_for_pair(pair, window, direction=direction)
    sample = len(pnls)
    if sample == 0:
        return {
            "sample": 0, "sum_pnl": 0.0, "pnl_pct": 0.0,
            "wr": 0.0, "pf": 0.0, "max_dd_pct": 0.0,
            "eligible_for": STATE_OBSERVED,
            "reason": "no data",
        }
    sum_pnl = round(sum(pnls), 2)
    wins = sum(1 for p in pnls if p > 0)
    wr = round(100.0 * wins / sample, 2)
    pf = _compute_pf(pnls)
    pnl_pct = round(100.0 * sum_pnl / TRADING_CAPITAL, 2)
    max_dd_pct = _compute_max_dd(pnls, TRADING_CAPITAL)

    # Décision : tous les critères doivent passer pour promotion AUTO_EXEC
    eligible = STATE_OBSERVED
    reason_parts = []
    if sample < PROMOTE_MIN_SAMPLE:
        reason_parts.append(f"sample {sample} < {PROMOTE_MIN_SAMPLE}")
    if pnl_pct < PROMOTE_MIN_PNL_PCT:
        reason_parts.append(f"pnl_pct {pnl_pct} < {PROMOTE_MIN_PNL_PCT}")
    if wr < PROMOTE_MIN_WR_PCT:
        reason_parts.append(f"wr {wr} < {PROMOTE_MIN_WR_PCT}")
    if pf < PROMOTE_MIN_PF:
        reason_parts.append(f"pf {pf} < {PROMOTE_MIN_PF}")
    if max_dd_pct < -PROMOTE_MAX_DD_PCT:
        reason_parts.append(f"max_dd {max_dd_pct} < -{PROMOTE_MAX_DD_PCT}")

    if not reason_parts:
        # Tous critères OK : éligible AUTO_EXEC. Mais transition auto = TELEGRAM seul,
        # AUTO_EXEC reste manuel par défaut (admin valide l'entrée d'argent).
        eligible = STATE_TELEGRAM
        reason = "all promote criteria met → eligible for TELEGRAM (admin must validate AUTO_EXEC)"
    else:
        reason = "; ".join(reason_parts)

    return {
        "sample": sample,
        "sum_pnl": sum_pnl,
        "pnl_pct": pnl_pct,
        "wr": wr,
        "pf": pf,
        "max_dd_pct": max_dd_pct,
        "eligible_for": eligible,
        "reason": reason,
    }


def _count_recent_pauses(pair: str, days: int = 60) -> int:
    """Compte le nombre de transitions vers PAUSED dans les N derniers jours."""
    _ensure_schema()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            """
            SELECT COUNT(*) FROM pair_admission_state
             WHERE pair = ? AND state = 'PAUSED' AND state_since >= ?
            """,
            (pair, cutoff),
        ).fetchone()
    return int(row[0]) if row else 0


def evaluate_pair(pair: str, direction: Optional[str] = None) -> dict[str, Any]:
    """Décide la transition d'un (pair, direction) selon son état + score.

    Si direction None : scoring + transition agrégés (= pair-level legacy).
    Si direction 'buy'/'sell' : scoring + transition restreint à ce sens.

    Retourne {action, from_state, to_state?, score, reason}.
    """
    direction = _normalize_direction(direction)
    current = get_current_state(pair, direction)
    score = compute_promotion_score(pair, direction=direction)

    if current == STATE_OBSERVED:
        if score["eligible_for"] == STATE_TELEGRAM:
            set_state(pair, STATE_TELEGRAM, f"auto-promote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_TELEGRAM, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": score["reason"]}

    elif current == STATE_TELEGRAM:
        if score["eligible_for"] == STATE_OBSERVED and score["sample"] >= PROMOTE_MIN_SAMPLE:
            set_state(pair, STATE_OBSERVED, f"auto-demote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_OBSERVED, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": "telegram healthy or sample insufficient"}

    elif current == STATE_AUTO_EXEC:
        if score["sample"] >= PROMOTE_MIN_SAMPLE and score["pnl_pct"] < -3.0:
            set_state(pair, STATE_PAUSED, f"auto-pause: pnl_pct {score['pnl_pct']}% < -3%", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_PAUSED, "score": score, "reason": "saignement détecté"}
        return {"action": "keep", "from_state": current, "score": score, "reason": "auto_exec healthy"}

    elif current == STATE_PAUSED:
        from datetime import timedelta
        full = get_full_state(pair, direction)
        try:
            since = datetime.fromisoformat(full["state_since"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - since
        except (ValueError, AttributeError, TypeError):
            elapsed = timedelta(days=0)
        if elapsed >= timedelta(days=14):
            recent_pauses = _count_recent_pauses(pair, days=60)
            if recent_pauses >= DEMOTE_MAX_RE_PAUSES_60D:
                set_state(pair, STATE_DEMOTED, f"auto-demote: {recent_pauses} pauses on 60d (max {DEMOTE_MAX_RE_PAUSES_60D})", direction=direction, score_snapshot=score)
                return {"action": "transition", "from_state": current, "to_state": STATE_DEMOTED, "score": score, "reason": "trop instable"}
            set_state(pair, STATE_AUTO_EXEC, "cool-off 14j expired, re-evaluating live", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_AUTO_EXEC, "score": score, "reason": "cool-off expired"}
        return {"action": "keep", "from_state": current, "score": score, "reason": f"cool-off encore {(timedelta(days=14) - elapsed).days}j"}

    elif current == STATE_DEMOTED:
        return {"action": "keep", "from_state": current, "score": score, "reason": "DEMOTED requires manual admin transition"}

    return {"action": "keep", "from_state": current, "score": score, "reason": "unknown state"}


def check_and_regulate() -> dict[str, Any]:
    """Job scheduler : évalue tous les (pair × direction) de l'univers."""
    from config.settings import WATCHED_PAIRS
    universe = set(WATCHED_PAIRS)
    for s in list_all_states():
        universe.add(s["pair"])

    decisions = []
    for pair in sorted(universe):
        for direction in ("buy", "sell"):
            try:
                d = evaluate_pair(pair, direction=direction)
                d["pair"] = pair
                d["direction"] = direction
                decisions.append(d)
            except Exception:
                logger.exception(f"pair_admission: evaluate {pair}/{direction} failed")

    transitions = sum(1 for d in decisions if d["action"] == "transition")
    logger.info(f"pair_admission: check n_buckets={len(decisions)} transitions={transitions}")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "n_buckets": len(decisions),
        "n_pairs": len({d["pair"] for d in decisions}),
        "n_transitions": transitions,
        "decisions": decisions,
    }


def backfill_initial_states() -> dict[str, Any]:
    """Au premier deploy, donne un état initial à chaque pair de WATCHED_PAIRS.

    Évolution 2026-05-13 : backfill (pair × direction) au lieu de pair-level
    seul. Matérialise explicitement le filtre `*:buy` historique en posant
    (pair, 'buy') = OBSERVED pour toutes les pairs, et (pair, 'sell') hérite
    du comportement legacy pair-level (AUTO_EXEC pour les stars sauf XAG
    SELL paused, OBSERVED pour les autres).

    Stratégie :
    - Phase 1 (rétrocompat) : si pair n'a AUCUNE row, applique la logique
      pair-level legacy (= comportement v1 contrôleur).
    - Phase 2 (direction granularité) : pour chaque (pair, direction) qui
      n'a pas de row direction-specific, déclare l'état initial selon les
      règles ci-dessus.

    Idempotent : ré-appel = 0 changement si état déjà posé.
    """
    from config.settings import WATCHED_PAIRS
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
    from backend.services import pair_pnl_regulator

    _ensure_schema()

    star_set = frozenset(_STAR_PAIRS)
    transitions: list[dict[str, Any]] = []
    universe = set(WATCHED_PAIRS) | star_set

    for pair in sorted(universe):
        # Phase 1 : Backfill pair-level legacy si jamais aucune row
        with sqlite3.connect(_db_path()) as c:
            has_any = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1", (pair,)
            ).fetchone()
            has_pair_level = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? AND direction IS NULL LIMIT 1", (pair,)
            ).fetchone()

        if not has_any:
            if pair in star_set:
                if pair_pnl_regulator.is_paused(pair):
                    pair_level_target = STATE_PAUSED
                    pair_level_reason = "backfill: pair was in _STAR_PAIRS_SET and paused by pair_pnl_regulator"
                else:
                    pair_level_target = STATE_AUTO_EXEC
                    pair_level_reason = "backfill: pair was in _STAR_PAIRS_SET (legacy star) and active"
            else:
                pair_level_target = STATE_OBSERVED
                pair_level_reason = "backfill: pair not in legacy _STAR_PAIRS, default OBSERVED"

            inserted = set_state(pair, pair_level_target, pair_level_reason, transitioned_by="auto:backfill")
            if inserted and inserted > 0:
                transitions.append({"pair": pair, "direction": None, "to_state": pair_level_target, "reason": pair_level_reason})

        # Phase 2 : Backfill direction-specific (buy / sell)
        # Récupère le state pair-level effectif (post phase 1)
        pair_level_state = get_current_state(pair)  # direction=None → pair-level lookup

        for direction in ("buy", "sell"):
            # Skip si déjà une row direction-specific pour ce sens
            with sqlite3.connect(_db_path()) as c:
                has_dir = c.execute(
                    "SELECT 1 FROM pair_admission_state WHERE pair = ? AND direction = ? LIMIT 1",
                    (pair, direction),
                ).fetchone()
            if has_dir:
                continue

            if direction == "buy":
                # Reproduit le filtre *:buy historique : tout buy = OBSERVED
                # (= pas d'auto-exec). Sera promu manuellement ou par
                # check_and_regulate quand un edge buy émerge (V2 long).
                dir_target = STATE_OBSERVED
                dir_reason = "backfill: direction=buy default OBSERVED (= remplace filtre statique *:buy)"
            else:  # sell
                # Hérite du comportement pair-level : si pair était AUTO_EXEC,
                # le SELL hérite (= seul sens autorisé sous *:buy historique).
                # Si pair était PAUSED, on propage à SELL (= la direction qui
                # saignait, cas XAG).
                dir_target = pair_level_state
                dir_reason = f"backfill: direction=sell inherits pair-level state ({pair_level_state})"

            inserted = set_state(pair, dir_target, dir_reason, direction=direction, transitioned_by="auto:backfill")
            if inserted and inserted > 0:
                transitions.append({"pair": pair, "direction": direction, "to_state": dir_target, "reason": dir_reason})

    logger.info(
        f"pair_admission: backfill_initial_states applied {len(transitions)} transitions"
    )
    return {"applied": len(transitions), "transitions": transitions}


def get_recent_transitions(pair: str, limit: int = 10) -> list[dict[str, Any]]:
    """Historique des N dernières transitions d'un pair (pour audit/dashboard)."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT * FROM pair_admission_state
             WHERE pair = ? ORDER BY state_since DESC LIMIT ?
            """,
            (pair, limit),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("score_snapshot"):
            try:
                d["score_snapshot"] = json.loads(d["score_snapshot"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result
