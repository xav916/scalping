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
import re
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

# Cible de la promotion automatique quand tous les critères statistiques sont validés.
# Défaut TELEGRAM = conservateur (admin valide ensuite AUTO_EXEC manuellement).
# Surcharge env AUTO_PROMOTE_TARGET=AUTO_EXEC pour activer le full-auto (saut TELEGRAM).
# ⚠️ AUTO_EXEC engage de l'argent réel sans validation humaine — accepter le risque
# d'oscillation OBSERVED→AUTO_EXEC→PAUSED (cap downside ≈ -3% capital par pair via
# pair_pnl_regulator).
import os as _os
_raw_target = _os.getenv("AUTO_PROMOTE_TARGET", STATE_TELEGRAM).upper()
AUTO_PROMOTE_TARGET = _raw_target if _raw_target in (STATE_TELEGRAM, STATE_AUTO_EXEC) else STATE_TELEGRAM

_SCHEMA_ENSURED = False


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


# ─── Circuit breaker auto-demotes ─────────────────────────────────────
# Anti-cascade : si > THRESHOLD demotions auto sur fenêtre glissante,
# bloque les nouvelles demotions auto. Le PAUSED reste, l'humain peut
# intervenir. Cf. 2026-06-07/08 : 17 demotions en 48h.


def _breaker_window() -> int:
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_WINDOW_DAYS
        return int(PAC_CIRCUIT_BREAKER_WINDOW_DAYS)
    except Exception:
        return 7


def _breaker_threshold() -> int:
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_THRESHOLD
        return int(PAC_CIRCUIT_BREAKER_THRESHOLD)
    except Exception:
        return 5


def _count_recent_auto_demotions(window_days: int = 7) -> int:
    """Compte les DEMOTED auto sur fenêtre glissante."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        with sqlite3.connect(_db_path()) as c:
            row = c.execute(
                """SELECT COUNT(*) FROM pair_admission_state
                   WHERE state = ? AND state_since >= ?
                     AND transitioned_by LIKE 'auto%'""",
                ("DEMOTED", cutoff),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def is_demotion_blocked() -> bool:
    """True si le circuit breaker bloque les auto-demotes (anti-cascade)."""
    try:
        from config.settings import PAC_CIRCUIT_BREAKER_ENABLED
    except ImportError:
        return False
    if not PAC_CIRCUIT_BREAKER_ENABLED:
        return False
    return _count_recent_auto_demotions(_breaker_window()) >= _breaker_threshold()


_breaker_notified_window: set[str] = set()  # dedup notif par jour


def _notify_circuit_breaker_block(pair: str, direction: str | None, n_recent: int) -> None:
    """Push Telegram (user+infra) à chaque blocage. Dedup 1× par (date, pair, direction)
    pour éviter le spam si le breaker déclenche sur plusieurs paires en cascade.
    """
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        key = f"{today}|{pair}|{direction or ''}"
        if key in _breaker_notified_window:
            return
        _breaker_notified_window.add(key)
        # Reset si jour change
        if len(_breaker_notified_window) > 50:
            _breaker_notified_window.clear()
            _breaker_notified_window.add(key)

        import asyncio
        from backend.services.telegram_service import send_text
        # Mapping FR vulgarisé 2026-06-14 (cohérent avec autres msg ScalpingRadar)
        _PAIR_FR_LOCAL = {
            "XAU/USD": "Or",
            "XAG/USD": "Argent",
            "WTI/USD": "Pétrole",
            "BTC/USD": "Bitcoin",
            "ETH/USD": "Ethereum",
            "SOL/USD": "Solana",
            "ADA/USD": "Cardano",
            "XRP/USD": "XRP",
            "LTC/USD": "Litecoin",
            "BCH/USD": "Bitcoin Cash",
            "DOT/USD": "Polkadot",
            "SPX": "S&P 500",
            "NDX": "Nasdaq",
        }
        pair_fr = _PAIR_FR_LOCAL.get(pair, pair)
        dir_label = ""
        if direction == "buy":
            dir_label = " (sens achat)"
        elif direction == "sell":
            dir_label = " (sens vente)"
        msg = (
            f"🚨 *Sécurité activée — paire à problème*\n"
            f"\n"
            f"⚠️ La paire *{pair_fr}* ({pair}){dir_label} a déjà été rétrogradée "
            f"*{n_recent} fois* par le système sur les {_breaker_window()} derniers jours.\n"
            f"\n"
            f"ℹ️ *Pourquoi ce message ?*\n"
            f"Quand une paire se fait rétrograder à répétition, le radar arrête "
            f"de la faire passer d'un mode à l'autre automatiquement et te "
            f"demande de vérifier manuellement. C'est un garde-fou anti-yoyo "
            f"pour éviter d'enchaîner les ajustements pendant que tu dors.\n"
            f"\n"
            f"🛠️ *À faire de ton côté*\n"
            f"Décide si tu veux désactiver complètement la paire (mode pause) "
            f"ou si tu acceptes qu'elle reste dans son état actuel. Va sur "
            f"`/v2/cockpit` → section Admission paires pour agir."
        )
        coro = send_text(msg)
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception as e:
        logger.debug(f"_notify_circuit_breaker_block error: {e}")


def _ensure_schema() -> None:
    """Crée pair_admission_state si pas déjà là. Idempotent.

    Évolution 2026-05-13 : ajout colonne ``direction`` (NULL pour les rows
    pair-level legacy, 'buy' ou 'sell' pour les rows direction-specific).
    Migration douce : les rows existantes restent direction IS NULL et
    s'appliquent à toutes les directions.

    Évolution 2026-07-29 : ajout colonne ``destination`` (NULL = s'applique
    à toutes les destinations, 'admin_legacy' / 'admin_live' = specific).
    Permet le workflow test-then-promote Demo → Live : une pair peut être
    AUTO_EXEC sur admin_legacy tout en restant TELEGRAM sur admin_live.
    Résolution en cascade : destination-specific first, fallback destination
    IS NULL, fallback direction IS NULL.
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
        # Migration 2026-07-29 : ajoute la colonne destination (idempotent)
        try:
            c.execute("ALTER TABLE pair_admission_state ADD COLUMN destination TEXT")
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_since ON pair_admission_state(pair, state_since DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_dir_since ON pair_admission_state(pair, direction, state_since DESC)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pas_pair_dir_dest_since ON pair_admission_state(pair, direction, destination, state_since DESC)"
        )
    _SCHEMA_ENSURED = True


# Destinations valides (miroir de bridge_destinations.BridgeConfig.destination_id)
# Destinations admin connues. ⚠️ Doit rester alignée sur
# `bridge_destinations` : une destination absente d'ici est traitée comme
# inconnue, avec les conséquences décrites dans `_normalize_destination`.
VALID_DESTINATIONS = frozenset({
    "admin_legacy",
    "admin_live",
    "admin_kraken",
    "admin_kraken_spot",
    "admin_kraken_stocks",
    "admin_binance",
})

# Destinations multi-tenant : `user:<id>`, cf. bridge_destinations._user_destinations
_USER_DESTINATION_RE = re.compile(r"^user:\d+$")


def is_valid_destination(destination: str) -> bool:
    """True si la chaîne désigne une destination connue (admin ou user:N)."""
    d = str(destination).strip().lower()
    return d in VALID_DESTINATIONS or bool(_USER_DESTINATION_RE.match(d))


def _normalize_destination(
    destination: Optional[str], *, strict: bool = False
) -> Optional[str]:
    """Normalise une destination, ou None pour « toutes les destinations ».

    ⚠️ **Corrigé le 2026-08-04.** ``VALID_DESTINATIONS`` ne listait que
    ``admin_legacy`` et ``admin_live`` — soit 2 destinations sur 7 — et toute
    valeur non listée était repliée en ``None``. Or ``None`` signifie *« toutes
    les destinations »* : le repli **élargissait** donc les permissions au lieu
    de les restreindre, silencieusement et sans erreur.

    Constaté : ``set_state(..., destination='admin_kraken')`` rendait le couple
    éligible à l'auto-exec sur **toutes** les destinations, y compris ``user:2``
    dont les classes autorisées incluent la crypto.

    Effet miroir en lecture : une row stockée avec une destination non listée
    devenait inatteignable, la cascade retombant sur la row globale. La
    promotion ``BTC/USD buy @admin_kraken_spot`` du 2026-08-03 n'a ainsi jamais
    rien fait.

    ``strict=True`` (chemins d'écriture) : lève sur destination inconnue plutôt
    que d'élargir la portée. En cas de doute, restreindre.
    """
    if destination is None:
        return None
    d = str(destination).strip().lower()
    if is_valid_destination(d):
        return d
    if strict:
        raise ValueError(
            f"Destination inconnue : {destination!r}. "
            f"Attendu : {sorted(VALID_DESTINATIONS)} ou 'user:<id>'. "
            "Refusé plutôt que replié en portée globale."
        )
    logger.warning(
        f"pair_admission: destination inconnue en lecture {destination!r} — "
        "repli sur la cascade globale. Vérifier VALID_DESTINATIONS."
    )
    return None


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


def get_current_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> str:
    """Retourne l'état courant pour (pair, direction, destination).

    Résolution en cascade (spécifique → legacy) :
    1. (pair, direction, destination) — most specific
    2. (pair, direction, destination IS NULL) — direction-specific, all destinations
    3. (pair, direction IS NULL, destination IS NULL) — pair-level legacy
    4. DEFAULT_STATE

    Migration douce : les rows existantes (direction IS NULL, destination IS NULL)
    restent honorées tant qu'aucune row plus spécifique n'override.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        # 1. Row (pair, direction, destination) — most specific
        if direction is not None and destination is not None:
            row = c.execute(
                """
                SELECT state FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction, destination),
            ).fetchone()
            if row:
                return row[0]
        # 2. Row (pair, direction, destination IS NULL) — direction-specific legacy
        if direction is not None:
            row = c.execute(
                """
                SELECT state FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
            if row:
                return row[0]
        # 3. Row (pair, direction IS NULL, destination IS NULL) — pair-level legacy
        row = c.execute(
            """
            SELECT state FROM pair_admission_state
             WHERE pair = ? AND direction IS NULL AND destination IS NULL
             ORDER BY state_since DESC LIMIT 1
            """,
            (pair,),
        ).fetchone()
    return row[0] if row else DEFAULT_STATE


def get_full_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> dict[str, Any]:
    """Retourne l'état + métadonnées (state_since, reason, score, destination).

    Même cascade que get_current_state : (pair, dir, dest) → (pair, dir, dest NULL)
    → (pair, dir NULL, dest NULL) → default.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        row = None
        # 1. (pair, direction, destination)
        if direction is not None and destination is not None:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination = ?
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction, destination),
            ).fetchone()
        # 2. (pair, direction, destination IS NULL)
        if not row and direction is not None:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction = ? AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair, direction),
            ).fetchone()
        # 3. (pair, direction IS NULL, destination IS NULL)
        if not row:
            row = c.execute(
                """
                SELECT * FROM pair_admission_state
                 WHERE pair = ? AND direction IS NULL AND destination IS NULL
                 ORDER BY state_since DESC LIMIT 1
                """,
                (pair,),
            ).fetchone()
    if not row:
        return {"pair": pair, "direction": direction, "destination": destination,
                "state": DEFAULT_STATE, "state_since": None, "reason": None,
                "score_snapshot": None, "transitioned_by": None}
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


def _has_explicit_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si une row matche (pair, direction, destination) avec cascade.

    Match si au moins l'un des 3 niveaux existe : (dir, dest) spec, (dir, dest NULL),
    (dir NULL, dest NULL). Retour True = get_current_state renverra une valeur
    de la DB (pas DEFAULT_STATE), donc le callsite doit honorer l'état.
    """
    _ensure_schema()
    direction = _normalize_direction(direction)
    destination = _normalize_destination(destination)
    with sqlite3.connect(_db_path()) as c:
        # Le OR ci-dessous couvre les 3 niveaux de cascade en une seule query.
        # destination IS NULL matche toujours (destination-agnostic legacy row).
        if direction is not None:
            if destination is not None:
                row = c.execute(
                    """
                    SELECT 1 FROM pair_admission_state
                     WHERE pair = ?
                       AND (direction = ? OR direction IS NULL)
                       AND (destination = ? OR destination IS NULL)
                     LIMIT 1
                    """,
                    (pair, direction, destination),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT 1 FROM pair_admission_state
                     WHERE pair = ?
                       AND (direction = ? OR direction IS NULL)
                       AND destination IS NULL
                     LIMIT 1
                    """,
                    (pair, direction),
                ).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM pair_admission_state WHERE pair = ? LIMIT 1",
                (pair,),
            ).fetchone()
    return bool(row)


def is_auto_exec_eligible(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si (pair, direction, destination) peut être pushée vers son bridge.

    Migration douce : si pas de row matchant la cascade, retourne False et
    le callsite fait son fallback _STAR_PAIRS_SET legacy.
    """
    if not _has_explicit_state(pair, direction, destination):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction, destination) == STATE_AUTO_EXEC


def is_telegram_eligible(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """True si (pair, direction, destination) peut générer un push Telegram.

    PAUSED inclus : on continue à informer le user mais avec verdict SKIP
    forcé côté setup (= signal info, pas trade reco).
    """
    if not _has_explicit_state(pair, direction, destination):
        return False  # callsite doit faire son fallback
    return get_current_state(pair, direction, destination) in (
        STATE_TELEGRAM, STATE_AUTO_EXEC, STATE_PAUSED
    )


def has_explicit_state(
    pair: str,
    direction: Optional[str] = None,
    destination: Optional[str] = None,
) -> bool:
    """API publique de _has_explicit_state pour les callers qui veulent
    décider eux-mêmes du fallback legacy."""
    return _has_explicit_state(pair, direction, destination)


# ─── Write API ──────────────────────────────────────────────────────────


def set_state(
    pair: str,
    new_state: str,
    reason: str,
    direction: Optional[str] = None,
    score_snapshot: Optional[dict] = None,
    transitioned_by: str = "auto",
    destination: Optional[str] = None,
) -> int:
    """Transitionne (pair, direction, destination) vers un nouvel état. Idempotent.

    Si destination=None : row destination-agnostic (s'applique aux 2 bridges).
    Si destination='admin_legacy'/'admin_live' : override pour cette destination.

    Si direction=None : row pair-level (tous les sens).
    Si direction='buy'/'sell' : row direction-specific.
    """
    if new_state not in VALID_STATES:
        raise ValueError(f"État invalide : {new_state}. Doit être dans {VALID_STATES}")
    _ensure_schema()
    direction = _normalize_direction(direction)
    # strict : une destination inconnue doit échouer, jamais devenir globale.
    destination = _normalize_destination(destination, strict=True)

    current = get_current_state(pair, direction, destination)
    if current == new_state:
        logger.debug(
            f"pair_admission: {pair}/{direction}/{destination} déjà {new_state}, no-op"
        )
        return -1

    now = datetime.now(timezone.utc).isoformat()
    score_json = json.dumps(score_snapshot) if score_snapshot else None
    with sqlite3.connect(_db_path()) as c:
        cur = c.execute(
            """
            INSERT INTO pair_admission_state
                (pair, direction, destination, state, state_since, reason, score_snapshot, transitioned_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pair, direction, destination, new_state, now, reason, score_json, transitioned_by),
        )
        new_id = cur.lastrowid
    dir_label = f"/{direction}" if direction else ""
    dest_label = f"@{destination}" if destination else ""
    logger.warning(
        f"pair_admission: {pair}{dir_label}{dest_label} {current} → {new_state} "
        f"by={transitioned_by} reason={reason}"
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

    # Notif user-facing en plus de l'infra (refonte 2026-06-10).
    # Best-effort, fire-and-forget. Évite spam : déjà filtré côté caller
    # par `transitioned_by != "auto:backfill"`.
    try:
        from backend.services.telegram_service import send_pac_transition_user
        coro_user = send_pac_transition_user(pair, direction, from_state, to_state, reason or "")
        if loop and loop.is_running():
            asyncio.ensure_future(coro_user)
        else:
            asyncio.run(coro_user)
    except Exception as e:
        logger.debug(f"pair_admission: telegram user notify failed: {e}")


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


def _r_unit_eur() -> float:
    """Valeur en euros d'une unité de risque (1 R), selon la politique de sizing.

    Un signal résolu vaut `rr_realized` R ; on le convertit ici en euros pour
    l'homogénéiser avec les PnL réels de `personal_trades` / `ea_closed_trades`.

    Utiliser `TRADING_CAPITAL × RISK_PER_TRADE_PCT` — et non une constante —
    rend `pnl_pct` égal à `somme(R) × RISK_PER_TRADE_PCT`, donc **indépendant
    du capital configuré**. L'ancien chemin shadow figeait 1 R = 100 € contre
    un capital réel de 3 000 €, ce qui gonflait mécaniquement `pnl_pct` d'un
    facteur 3,3 et produisait les « −103 % » relevés dans l'historique des
    rétrogradations.
    """
    from config.settings import TRADING_CAPITAL, RISK_PER_TRADE_PCT
    return TRADING_CAPITAL * (RISK_PER_TRADE_PCT / 100.0)


def _fetch_signal_pnls(pair: str, direction: Optional[str], need: int) -> list[float]:
    """PnL en euros des N derniers signaux résolus, depuis `backtest.db.trades`.

    ⚠️ Cette fonction lisait `shadow_setups` jusqu'au 2026-08-04. Cette table
    répliquait une même idée de trade jusqu'à 960 fois (déduplication
    inopérante, cf. `shadow_v1._bar_timestamp`), et les décisions automatiques
    d'admission en dépendaient : trois paires equity ont été rétrogradées le
    2026-08-04 sur un `wr 0.0` qui n'était qu'un unique trade perdant compté
    457 fois. `backtest.db.trades` est saine (duplication ×1,00 vérifiée).
    """
    if need <= 0:
        return []
    try:
        from backend.services.backtest_service import fetch_recent_rr
        rr = fetch_recent_rr(pair, direction, need)
    except Exception as e:  # backtest.db indispo (tests isolés) : pas de fallback
        logger.debug(f"admission: backtest.db indisponible pour {pair}: {e}")
        return []
    unit = _r_unit_eur()
    return [r * unit for r in rr]


def _fetch_trades_for_pair(pair: str, window: int, direction: Optional[str] = None) -> list[float]:
    """Trades réels, complétés par des signaux si la fenêtre n'est pas pleine.

    Voir `_fetch_real_trades_for_pair` et `_fetch_signal_pnls`. Le scoring
    passe par ces deux-là directement, afin de savoir d'où vient chaque PnL.
    """
    pnls = _fetch_real_trades_for_pair(pair, window, direction)
    if len(pnls) < window:
        pnls.extend(_fetch_signal_pnls(pair, _normalize_direction(direction),
                                       window - len(pnls)))
    return pnls


def _fetch_real_trades_for_pair(pair: str, window: int, direction: Optional[str] = None) -> list[float]:
    """Union admin (personal_trades) + Premium (ea_closed_trades). Argent réel.

    Filtre optionnel par direction ('buy' ou 'sell'). Si direction None,
    agrège toutes directions confondues (= comportement pair-level).
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
    pnls = _fetch_real_trades_for_pair(pair, window, direction=direction)
    n_real = len(pnls)
    # Complément signaux : les trades réels sont rares (une pair en OBSERVED
    # n'en a aucun), donc on remplit la fenêtre avec les signaux résolus du
    # radar. C'est ce qui permet la promotion auto from scratch — sans quoi
    # une pair non tradée ne pourrait jamais accumuler d'historique.
    if n_real < window:
        pnls.extend(_fetch_signal_pnls(pair, _normalize_direction(direction),
                                       window - n_real))
    sample = len(pnls)

    # Étiquette honnête : jusqu'au 2026-08-04 `pnl_source` annonçait
    # 'personal_trades' même quand 100 % de l'échantillon venait du shadow.
    if sample == 0 or n_real == sample:
        pnl_source = "personal_trades"
    elif n_real == 0:
        pnl_source = "backtest_trades"
    else:
        pnl_source = f"mixed({n_real}/{sample} réels)"
    if sample == 0:
        return {
            "sample": 0, "sum_pnl": 0.0, "pnl_pct": 0.0,
            "wr": 0.0, "pf": 0.0, "max_dd_pct": 0.0,
            "eligible_for": STATE_OBSERVED,
            "reason": "no data",
            "pnl_source": pnl_source,
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
        # Tous critères OK : cible déterminée par env AUTO_PROMOTE_TARGET.
        # Défaut TELEGRAM (admin valide AUTO_EXEC ensuite) ; AUTO_EXEC = full-auto.
        eligible = AUTO_PROMOTE_TARGET
        reason = f"all promote criteria met → eligible for {AUTO_PROMOTE_TARGET}"
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
        "pnl_source": pnl_source,
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
        # Accepte TELEGRAM ou AUTO_EXEC comme cible selon AUTO_PROMOTE_TARGET env.
        target = score["eligible_for"]
        if target in (STATE_TELEGRAM, STATE_AUTO_EXEC):
            set_state(pair, target, f"auto-promote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": target, "score": score, "reason": score["reason"]}
        return {"action": "keep", "from_state": current, "score": score, "reason": score["reason"]}

    elif current == STATE_TELEGRAM:
        if score["eligible_for"] == STATE_OBSERVED and score["sample"] >= PROMOTE_MIN_SAMPLE:
            set_state(pair, STATE_OBSERVED, f"auto-demote: {score['reason']}", direction=direction, score_snapshot=score)
            return {"action": "transition", "from_state": current, "to_state": STATE_OBSERVED, "score": score, "reason": score["reason"]}
        # Palier loss-averse asymétrique : promote TELEGRAM → AUTO_EXEC après
        # PAC_TELEGRAM_TO_AUTOEXEC_DAYS stables (default 7j) sans demote.
        # Évite les promotes auto trop rapides vers l'argent réel (cas XAU buy
        # 2026-06-08 cool-off → AUTO_EXEC → -125% PnL en 24h).
        from datetime import timedelta
        try:
            from config.settings import PAC_TELEGRAM_TO_AUTOEXEC_DAYS as _tg_days
        except ImportError:
            _tg_days = 7
        full = get_full_state(pair, direction)
        try:
            since = datetime.fromisoformat(full["state_since"].replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - since
        except (ValueError, AttributeError, TypeError):
            elapsed = timedelta(days=0)
        if (
            elapsed >= timedelta(days=_tg_days)
            and score["sample"] >= PROMOTE_MIN_SAMPLE
            and score["eligible_for"] in (STATE_TELEGRAM, STATE_AUTO_EXEC)
        ):
            set_state(
                pair, STATE_AUTO_EXEC,
                f"auto-promote TELEGRAM stable {elapsed.days}j ≥ {_tg_days}j",
                direction=direction, score_snapshot=score,
            )
            return {"action": "transition", "from_state": current, "to_state": STATE_AUTO_EXEC, "score": score, "reason": "stable in TELEGRAM"}
        days_left = max(0, _tg_days - elapsed.days)
        return {"action": "keep", "from_state": current, "score": score, "reason": f"telegram stable {elapsed.days}j (encore {days_left}j avant AUTO_EXEC)"}

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
                # Circuit breaker : si trop de demotions auto récentes, on bloque
                # l'éjection définitive (anti-cascade cf. 2026-06-07/08 — 17
                # demotions en 48h). Le PAUSED reste, l'humain peut intervenir.
                if is_demotion_blocked():
                    n_recent = _count_recent_auto_demotions(_breaker_window())
                    logger.warning(
                        f"pac_circuit_breaker: blocking DEMOTED for {pair}/{direction} "
                        f"({n_recent} auto-demotes / {_breaker_window()}d)"
                    )
                    _notify_circuit_breaker_block(pair, direction, n_recent)
                    return {
                        "action": "keep",
                        "from_state": current,
                        "score": score,
                        "reason": f"DEMOTE bloquée par circuit breaker ({n_recent} demotes/{_breaker_window()}d)",
                    }
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
