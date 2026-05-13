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
    """Crée pair_admission_state si pas déjà là. Idempotent."""
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
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_since ON pair_admission_state(pair, state_since DESC)"
        )
    _SCHEMA_ENSURED = True


# ─── Read API ───────────────────────────────────────────────────────────


def get_current_state(pair: str) -> str:
    """Retourne l'état courant d'un pair (= dernière row, sinon DEFAULT_STATE)."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            """
            SELECT state FROM pair_admission_state
             WHERE pair = ? ORDER BY state_since DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    return row[0] if row else DEFAULT_STATE


def get_full_state(pair: str) -> dict[str, Any]:
    """Retourne l'état + métadonnées (state_since, reason, score)."""
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            """
            SELECT * FROM pair_admission_state
             WHERE pair = ? ORDER BY state_since DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    if not row:
        return {"pair": pair, "state": DEFAULT_STATE, "state_since": None, "reason": None, "score_snapshot": None, "transitioned_by": None}
    d = dict(row)
    if d.get("score_snapshot"):
        try:
            d["score_snapshot"] = json.loads(d["score_snapshot"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def list_all_states() -> list[dict[str, Any]]:
    """Retourne l'état courant de tous les pairs qui ont une row.

    Pour avoir l'univers complet, le caller doit aussi inclure les pairs de
    WATCHED_PAIRS (default state = OBSERVED si pas de row).
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """
            SELECT pas.* FROM pair_admission_state pas
             INNER JOIN (
                SELECT pair, MAX(state_since) AS max_since
                  FROM pair_admission_state GROUP BY pair
             ) latest ON pas.pair = latest.pair AND pas.state_since = latest.max_since
             ORDER BY pas.pair
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


def _has_explicit_state(pair: str) -> bool:
    """True si pair a au moins une row dans pair_admission_state.

    Permet aux helpers de distinguer "pair vraiment OBSERVED par décision"
    vs "pair jamais vue par le controller" (= migration douce, fallback
    sur legacy _STAR_PAIRS_SET tant que backfill n'a pas tourné).
    """
    _ensure_schema()
    with sqlite3.connect(_db_path()) as c:
        row = c.execute(
            "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1", (pair,)
        ).fetchone()
    return bool(row)


def is_auto_exec_eligible(pair: str) -> bool:
    """True si la pair peut être pushée vers le bridge MT5 (auto-exec).

    Migration douce : si la pair n'a JAMAIS été enregistrée dans le
    controller (= row absente), on délègue au callsite (qui peut faire
    un fallback _STAR_PAIRS_SET legacy). Cela évite de casser les
    déploiements pré-backfill.
    """
    if not _has_explicit_state(pair):
        return False  # callsite doit faire son fallback
    return get_current_state(pair) == STATE_AUTO_EXEC


def is_telegram_eligible(pair: str) -> bool:
    """True si la pair peut générer un push Telegram user-facing.

    PAUSED inclus : on continue à informer le user mais avec verdict SKIP
    forcé côté setup (= signal info, pas trade reco).

    Migration douce : si la pair n'a pas de row, retourne False et le
    callsite fait son fallback _STAR_PAIRS_SET legacy.
    """
    if not _has_explicit_state(pair):
        return False  # callsite doit faire son fallback
    return get_current_state(pair) in (STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED)


def has_explicit_state(pair: str) -> bool:
    """API publique de _has_explicit_state pour les callers qui veulent
    décider eux-mêmes du fallback legacy."""
    return _has_explicit_state(pair)


# ─── Write API ──────────────────────────────────────────────────────────


def set_state(
    pair: str,
    new_state: str,
    reason: str,
    score_snapshot: Optional[dict] = None,
    transitioned_by: str = "auto",
) -> int:
    """Transitionne un pair vers un nouvel état. Idempotent si déjà dans l'état."""
    if new_state not in VALID_STATES:
        raise ValueError(f"État invalide : {new_state}. Doit être dans {VALID_STATES}")
    _ensure_schema()

    current = get_current_state(pair)
    if current == new_state:
        logger.debug(f"pair_admission: {pair} déjà {new_state}, no-op")
        return -1

    now = datetime.now(timezone.utc).isoformat()
    score_json = json.dumps(score_snapshot) if score_snapshot else None
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO pair_admission_state
                (pair, state, state_since, reason, score_snapshot, transitioned_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pair, new_state, now, reason, score_json, transitioned_by),
        )
        new_id = cur.lastrowid
    logger.warning(
        f"pair_admission: {pair} {current} → {new_state} by={transitioned_by} reason={reason}"
    )
    return new_id


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


def _fetch_trades_for_pair(pair: str, window: int) -> list[float]:
    """Union admin (personal_trades) + Premium (ea_closed_trades) + shadow.

    Pour scoring promotion d'une pair OBSERVED qui n'a pas de live trades :
    on tombera sur shadow_setups (Track A V2 backtest live, table
    `shadow_setups`) comme source secondaire.
    """
    _ensure_schema()
    # ea_closed_trades schema doit aussi être garanti (UNION le requiert)
    from backend.services import ea_closed_trades_service as _eact
    _eact._ensure_schema()
    pnls: list[float] = []
    with sqlite3.connect(_db_path()) as c:
        # 1. Live trades (admin + Premium)
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

        # 2. Si pas assez de live, compléter avec shadow_setups (backtest live)
        if len(pnls) < window:
            need = window - len(pnls)
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


def compute_promotion_score(pair: str, window: int = 30) -> dict[str, Any]:
    """Calcule le score composite pour décider si un pair peut transiter.

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
    pnls = _fetch_trades_for_pair(pair, window)
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


def evaluate_pair(pair: str) -> dict[str, Any]:
    """Décide la transition d'un pair selon son état actuel + score.

    Retourne {action: 'transition'|'keep', from_state, to_state?, score, reason}.
    Si action='transition', set_state est appelé automatiquement.
    """
    current = get_current_state(pair)
    score = compute_promotion_score(pair)

    # Transitions selon l'état actuel
    if current == STATE_OBSERVED:
        # Peut auto-promote vers TELEGRAM si tous critères OK
        if score["eligible_for"] == STATE_TELEGRAM:
            set_state(pair, STATE_TELEGRAM, f"auto-promote: {score['reason']}", score)
            return {"action": "transition", "from_state": current, "to_state": STATE_TELEGRAM, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": score["reason"]}

    elif current == STATE_TELEGRAM:
        # Auto-demote si critères ne sont plus tenus (ex: PnL retombe sous seuil)
        if score["eligible_for"] == STATE_OBSERVED and score["sample"] >= PROMOTE_MIN_SAMPLE:
            # Demotion seulement si suffisamment de sample pour conclure
            set_state(pair, STATE_OBSERVED, f"auto-demote: {score['reason']}", score)
            return {"action": "transition", "from_state": current, "to_state": STATE_OBSERVED, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": "telegram healthy or sample insufficient"}

    elif current == STATE_AUTO_EXEC:
        # Demotion vers PAUSED si saignement (= pair_pnl_regulator logique)
        if score["sample"] >= PROMOTE_MIN_SAMPLE and score["pnl_pct"] < -3.0:
            set_state(pair, STATE_PAUSED, f"auto-pause: pnl_pct {score['pnl_pct']}% < -3%", score)
            return {"action": "transition", "from_state": current, "to_state": STATE_PAUSED, "score": score, "reason": "saignement détecté"}
        return {"action": "keep", "from_state": current, "score": score, "reason": "auto_exec healthy"}

    elif current == STATE_PAUSED:
        # Auto-resume après cool-off 14j IF PnL re-évalué et OK
        from datetime import timedelta
        full = get_full_state(pair)
        try:
            since = datetime.fromisoformat(full["state_since"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - since
        except (ValueError, AttributeError, TypeError):
            elapsed = timedelta(days=0)
        if elapsed >= timedelta(days=14):
            # Check demotion DEMOTED : 2× pauses récentes = trop instable
            recent_pauses = _count_recent_pauses(pair, days=60)
            if recent_pauses >= DEMOTE_MAX_RE_PAUSES_60D:
                set_state(pair, STATE_DEMOTED, f"auto-demote: {recent_pauses} pauses on 60d (max {DEMOTE_MAX_RE_PAUSES_60D})", score)
                return {"action": "transition", "from_state": current, "to_state": STATE_DEMOTED, "score": score, "reason": "trop instable"}
            # Sinon resume vers AUTO_EXEC (ré-évaluation au prochain cycle)
            set_state(pair, STATE_AUTO_EXEC, "cool-off 14j expired, re-evaluating live", score)
            return {"action": "transition", "from_state": current, "to_state": STATE_AUTO_EXEC, "score": score, "reason": "cool-off expired"}
        return {"action": "keep", "from_state": current, "score": score, "reason": f"cool-off encore {(timedelta(days=14) - elapsed).days}j"}

    elif current == STATE_DEMOTED:
        # Pas de transition auto depuis DEMOTED — admin manuel uniquement
        return {"action": "keep", "from_state": current, "score": score, "reason": "DEMOTED requires manual admin transition"}

    return {"action": "keep", "from_state": current, "score": score, "reason": "unknown state"}


def check_and_regulate() -> dict[str, Any]:
    """Job scheduler : évalue tous les pairs de l'univers, applique transitions."""
    from config.settings import WATCHED_PAIRS
    # Univers = WATCHED_PAIRS + tout pair qui a déjà une row (PAUSED/DEMOTED histo)
    universe = set(WATCHED_PAIRS)
    for s in list_all_states():
        universe.add(s["pair"])

    decisions = []
    for pair in sorted(universe):
        try:
            d = evaluate_pair(pair)
            d["pair"] = pair
            decisions.append(d)
        except Exception:
            logger.exception(f"pair_admission: evaluate {pair} failed")

    transitions = sum(1 for d in decisions if d["action"] == "transition")
    logger.info(f"pair_admission: check n_pairs={len(decisions)} transitions={transitions}")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "n_pairs": len(decisions),
        "n_transitions": transitions,
        "decisions": decisions,
    }


def backfill_initial_states() -> dict[str, Any]:
    """Au premier deploy, donne un état initial à chaque pair de WATCHED_PAIRS.

    Pour chaque pair de WATCHED_PAIRS qui n'a aucune row dans
    pair_admission_state :
    - Si pair dans _STAR_PAIRS (set legacy hardcodé Phase 4) :
        - Si pair_pnl_regulator.is_paused(pair) → PAUSED
        - Sinon → AUTO_EXEC
    - Sinon → OBSERVED

    Idempotent : si la pair a déjà une row, on ne touche pas.

    À appeler une fois au startup pour migrer en douceur de la liste
    hardcodée vers le contrôleur dynamique.
    """
    from config.settings import WATCHED_PAIRS
    from backend.services.shadow_v2_core_long import SHADOW_PAIRS as _STAR_PAIRS
    from backend.services import pair_pnl_regulator

    _ensure_schema()

    star_set = frozenset(_STAR_PAIRS)
    transitions: list[dict[str, Any]] = []
    universe = set(WATCHED_PAIRS) | star_set  # garantir que XLI/XLK soient inclus

    for pair in sorted(universe):
        existing = get_current_state(pair)
        # get_current_state retourne DEFAULT_STATE (OBSERVED) si pas de row.
        # On doit distinguer "pas de row" vs "row = OBSERVED explicite" :
        with sqlite3.connect(_db_path()) as c:
            row = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1", (pair,)
            ).fetchone()
        if row:
            continue  # déjà une row, ne touche pas

        # Détermine l'état initial
        if pair in star_set:
            if pair_pnl_regulator.is_paused(pair):
                target = STATE_PAUSED
                reason = "backfill: pair was in _STAR_PAIRS_SET and paused by pair_pnl_regulator"
            else:
                target = STATE_AUTO_EXEC
                reason = "backfill: pair was in _STAR_PAIRS_SET (legacy star) and active"
        else:
            target = STATE_OBSERVED
            reason = "backfill: pair not in legacy _STAR_PAIRS, default OBSERVED"

        inserted = set_state(pair, target, reason, transitioned_by="auto:backfill")
        # set_state retourne -1 si idempotent (target = current = OBSERVED par
        # défaut). On ne compte une "vraie" transition que si l'insert a eu
        # lieu — sinon idempotence second-run garantie.
        if inserted and inserted > 0:
            transitions.append({"pair": pair, "to_state": target, "reason": reason})

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
